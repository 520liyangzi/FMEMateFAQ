"""Exercise the real process boundary with a small controlled CLI surrogate."""

import sys
import unittest

from fmemate.claude_cli import extract_requirements


class CliIntegrationTests(unittest.TestCase):
    def test_real_child_receives_stdin_in_isolated_directory(self):
        program = (
            "import json,sys,os; "
            "prompt=sys.stdin.read(); "
            "assert 'original_requirements' in prompt; "
            "assert 'fmemate-claude-' in os.getcwd(); "
            "assert sys.argv[sys.argv.index('--tools')+1] == ''; "
            "print(json.dumps({'result':json.dumps({'requirements':['RX optical power','battery life']})}))"
        )
        result = extract_requirements("接收光功率和电池寿命", {"functions": []}, {
            "claude_enabled": True, "claude_command": [sys.executable, "-c", program],
            "claude_timeout_seconds": 10})
        self.assertEqual(result, ["RX optical power", "battery life"])

    def test_real_child_error_never_returns_diagnostic_contents(self):
        program = "import sys; sys.stderr.write('Unauthorized surrogate-private-diagnostic'); sys.exit(1)"
        with self.assertRaisesRegex(ValueError, "登录或认证失败") as caught:
            extract_requirements("端口状态", {}, {
                "claude_enabled": True, "claude_command": [sys.executable, "-c", program],
                "claude_timeout_seconds": 10})
        self.assertNotIn("surrogate-private-diagnostic", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
