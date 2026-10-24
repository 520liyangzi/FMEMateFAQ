import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from fmemate.claude_cli import _parse_output, _prompt, extract_requirements


class ClaudeOutputTests(unittest.TestCase):
    def test_direct_json_and_outer_envelope(self):
        raw = '{"requirements":["接收光功率","GNSS工作模式"]}'
        self.assertEqual(_parse_output(raw), ["接收光功率", "GNSS工作模式"])
        self.assertEqual(_parse_output(json.dumps({"result": raw})), ["接收光功率", "GNSS工作模式"])

    def test_fenced_json_inside_and_outside_envelope(self):
        raw = '```json\n{"requirements":["端口状态"]}\n```'
        self.assertEqual(_parse_output(raw), ["端口状态"])
        self.assertEqual(_parse_output(json.dumps({"result": raw})), ["端口状态"])

    def test_invalid_outputs_are_not_treated_as_requirements(self):
        for output in ['I recommend analyze ticket', '[]', '{}', '{"requirements":[]}', '{"requirements":[2]}', '{"requirements":["a"],"functions":["invented"]}']:
            with self.subTest(output=output), self.assertRaises(ValueError):
                _parse_output(output)

    def test_parser_preserves_positions_for_alignment_validation(self):
        self.assertEqual(_parse_output('{"requirements":[" GNSS ","GNSS"]}'), ["GNSS", "GNSS"])

    def test_model_error_does_not_leak_diagnostic(self):
        with self.assertRaisesRegex(ValueError, "调用失败") as caught:
            _parse_output('{"is_error":true,"result":"secret-test-token"}')
        self.assertNotIn("secret-test-token", str(caught.exception))

    def test_prompt_keeps_unknown_requirements_and_bounds_catalog(self):
        catalog = {"functions": [{"question_zh": "工单分析", "objects": [{"name_zh": "端口", "fields": [{"name_zh": "测试" * 40_000}]}]}]}
        prompt = _prompt("未知需求", catalog)
        self.assertIn("未知需求", prompt)
        self.assertIn('"original_requirements":["未知需求"]', prompt)
        self.assertIn('"catalog_terms_truncated":true', prompt)
        self.assertLessEqual(len(prompt.encode("utf-8")), 60_000)


class ClaudeProcessTests(unittest.TestCase):
    settings = {"claude_enabled": True, "claude_command": ["claude"], "claude_timeout_seconds": 45}

    def mock_process(self, communicate=None, returncode=0):
        process = MagicMock()
        process.returncode = returncode
        process.pid = 12345
        process.__enter__.return_value = process
        process.communicate.return_value = communicate or ('{"result":"{\\"requirements\\":[\\"端口状态\\"]}"}', "")
        return process

    @patch("fmemate.claude_cli.subprocess.Popen")
    @patch("fmemate.claude_cli.shutil.which", return_value="/usr/local/bin/claude")
    def test_disabled_does_not_start_process(self, which, popen):
        with self.assertRaisesRegex(ValueError, "尚未启用"):
            extract_requirements("端口状态", {}, {})
        popen.assert_not_called()
        which.assert_not_called()

    @patch("fmemate.claude_cli.shutil.which", return_value=None)
    def test_missing_cli_is_actionable(self, which):
        with self.assertRaisesRegex(ValueError, "未找到 Claude"):
            extract_requirements("端口状态", {}, self.settings)

    @patch("fmemate.claude_cli.subprocess.Popen")
    @patch("fmemate.claude_cli.shutil.which", return_value="/usr/local/bin/claude")
    def test_stdin_query_and_no_tools_with_existing_environment(self, which, popen):
        process = self.mock_process()
        popen.return_value = process
        query = '端口状态 $(evil) --dangerously-skip-permissions'
        self.assertEqual(extract_requirements(query, {}, self.settings), ["端口状态"])
        args, kwargs = popen.call_args
        self.assertNotIn(query, args[0])
        self.assertEqual(args[0][args[0].index("--tools") + 1], "")
        self.assertEqual(args[0][args[0].index("--disallowedTools") + 1], "*")
        self.assertFalse(kwargs["shell"])
        self.assertIn("fmemate-claude-", kwargs["cwd"])
        self.assertIn(query, process.communicate.call_args.args[0])

    @patch("fmemate.claude_cli._stop_process")
    @patch("fmemate.claude_cli.subprocess.Popen")
    @patch("fmemate.claude_cli.shutil.which", return_value="/usr/local/bin/claude")
    def test_timeout_terminates_process_tree(self, which, popen, stop):
        process = self.mock_process()
        process.communicate.side_effect = [subprocess.TimeoutExpired("claude", 45), ("", "")]
        popen.return_value = process
        with self.assertRaisesRegex(ValueError, "响应超时"):
            extract_requirements("端口状态", {}, self.settings)
        stop.assert_called_once_with(process)

    @patch("fmemate.claude_cli.subprocess.Popen")
    @patch("fmemate.claude_cli.shutil.which", return_value="/usr/local/bin/claude")
    def test_authentication_error_is_sanitized(self, which, popen):
        popen.return_value = self.mock_process(("", "Unauthorized: secret-test-token"), 1)
        with self.assertRaisesRegex(ValueError, "登录或认证失败") as caught:
            extract_requirements("端口状态", {}, self.settings)
        self.assertNotIn("secret-test-token", str(caught.exception))

    @patch("fmemate.claude_cli.subprocess.Popen")
    @patch("fmemate.claude_cli.shutil.which", return_value="/usr/local/bin/claude")
    def test_unknown_cli_options_explained(self, which, popen):
        popen.return_value = self.mock_process(("", "error: unknown option --tools"), 1)
        with self.assertRaisesRegex(ValueError, "不支持"):
            extract_requirements("端口状态", {}, self.settings)

    @patch("fmemate.claude_cli.subprocess.Popen")
    @patch("fmemate.claude_cli.shutil.which", return_value="/usr/local/bin/claude")
    def test_dropped_unknown_requirement_rejected(self, which, popen):
        popen.return_value = self.mock_process(('{"requirements":["端口状态"]}', ""))
        with self.assertRaisesRegex(ValueError, "数量与原始需求不一致"):
            extract_requirements("端口状态和火星链路", {}, self.settings)

    @patch("fmemate.claude_cli.subprocess.Popen")
    @patch("fmemate.claude_cli.shutil.which", return_value="/usr/local/bin/claude")
    def test_added_requirement_rejected(self, which, popen):
        popen.return_value = self.mock_process(('{"requirements":["端口状态","GNSS工作模式"]}', ""))
        with self.assertRaisesRegex(ValueError, "数量与原始需求不一致"):
            extract_requirements("端口状态", {}, self.settings)

    @patch("fmemate.claude_cli.subprocess.Popen")
    @patch("fmemate.claude_cli.shutil.which", return_value="/usr/local/bin/claude")
    def test_positional_duplicate_normalization_rejected(self, which, popen):
        popen.return_value = self.mock_process(('{"requirements":["端口状态","端口状态"]}', ""))
        with self.assertRaisesRegex(ValueError, "重复内容"):
            extract_requirements("端口状态和板卡状态", {}, self.settings)

    @patch("fmemate.claude_cli.subprocess.Popen")
    @patch("fmemate.claude_cli.shutil.which", return_value="/usr/local/bin/claude")
    def test_aligned_normalization_keeps_unknown(self, which, popen):
        popen.return_value = self.mock_process(('{"requirements":["接收光功率","发射光功率","GNSS工作模式","火星链路"]}', ""))
        self.assertEqual(extract_requirements("端口收发光功率和GNSS工作模式和火星链路", {}, self.settings), ["接收光功率", "发射光功率", "GNSS工作模式", "火星链路"])

    def test_timeout_and_command_validation(self):
        for value in [0, 121, "45", True]:
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                extract_requirements("端口状态", {}, {**self.settings, "claude_timeout_seconds": value})
        with self.assertRaises(ValueError):
            extract_requirements("端口状态", {}, {**self.settings, "claude_command": "claude"})


if __name__ == "__main__":
    unittest.main()
