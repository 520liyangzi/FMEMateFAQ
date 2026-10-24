import base64
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fmemate.server import AppServer
from fmemate.storage import Store, validate_aliases, validate_settings


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = AppServer(("127.0.0.1", 0), self.directory.name)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        connection.request(method, path, body=payload,
                           headers={"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        raw = response.read()
        result = json.loads(raw) if response.getheader("Content-Type").startswith("application/json") else raw
        connection.close()
        return response.status, result

    def test_demo_query_covers_three_needs_with_one_function(self):
        status, state = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertTrue(state["is_demo"])
        self.assertFalse(state["settings"]["claude_enabled"])
        status, result = self.request("POST", "/api/recommend", {"query": "端口的收发光功率和GNSS工作模式"})
        self.assertEqual(status, 200)
        self.assertEqual(result["plan"]["function_ids"], ["demo_analyze"])
        self.assertEqual(result["plan"]["coverage"], 1)
        self.assertEqual(len(result["requirements"]), 3)
        self.assertTrue(any("演示" in w for w in result["warnings"]))

    def test_preview_does_not_change_catalog_then_confirm_persists(self):
        csv = ("触发问题,英文触发问题,对象中文,对象英文,字段中文,字段英文\n"
               "分析,Analyze,端口,Port,接收光功率,RX optical power\n"
               ",,,,发射光功率,TX optical power\n"
               ",,卫星,Satellite,GNSS工作模式,GNSS Working Mode\n").encode("utf-8")
        status, preview = self.request("POST", "/api/import/preview", {
            "filename": "actual.csv", "content_base64": base64.b64encode(csv).decode("ascii")})
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["summary"]["fields"], 3)
        self.assertTrue(self.request("GET", "/api/state")[1]["is_demo"])
        self.assertFalse(Path(self.directory.name, "state.json").exists())
        status, state = self.request("POST", "/api/import/confirm", {"preview_id": preview["preview_id"]})
        self.assertEqual(status, 200)
        self.assertFalse(state["is_demo"])
        self.assertEqual(state["summary"], {"functions": 1, "objects": 2, "fields": 3})
        reloaded = Store(self.directory.name, {"groups": []}).state()
        self.assertEqual(reloaded["catalog"], state["catalog"])
        status, result = self.request("POST", "/api/recommend", {"query": "端口的收发光功率和GNSS工作模式"})
        self.assertEqual(status, 200)
        self.assertEqual(result["plan"]["coverage"], 1)
        self.assertEqual(len(result["plan"]["function_ids"]), 1)
        self.assertEqual(self.request("POST", "/api/import/confirm", {"preview_id": preview["preview_id"]})[0], 400)

    def test_unknown_need_is_visible(self):
        _, result = self.request("POST", "/api/recommend", {"query": "接收光功率和电池寿命"})
        self.assertLess(result["plan"]["coverage"], 1)
        self.assertTrue(result["unmatched_requirements"])

    def test_ai_cannot_drop_need_or_change_existing_evidence(self):
        self.request("PUT", "/api/settings", {"claude_enabled": True})
        with patch("fmemate.server.extract_requirements", return_value=["接收光功率"]):
            _, result = self.request("POST", "/api/recommend", {"query": "接收光功率和电池寿命", "use_ai": True})
        self.assertEqual(result["mode"], "local")
        self.assertEqual(len(result["requirements"]), 2)
        self.assertEqual(result["plan"]["coverage"], 0.5)
        self.assertTrue(any("数量" in warning for warning in result["warnings"]))
        with patch("fmemate.server.extract_requirements", return_value=["柜号", "电池寿命"]):
            _, result = self.request("POST", "/api/recommend", {"query": "接收光功率和电池寿命", "use_ai": True})
        self.assertEqual(result["requirements"][0]["text"], "接收光功率")
        self.assertEqual(result["recommendations"][0]["evidence"][0]["field_zh"], "接收光功率")

    def test_ai_normalization_shows_original_unknown_text(self):
        self.request("PUT", "/api/settings", {"claude_enabled": True})
        with patch("fmemate.server.extract_requirements", return_value=["接收光功率"]):
            _, result = self.request("POST", "/api/recommend", {"query": "收进来的光有多强", "use_ai": True})
        self.assertEqual(result["mode"], "claude_cli")
        self.assertEqual(result["plan"]["coverage"], 1)
        self.assertEqual(result["requirements"][0]["text"], "收进来的光有多强")
        self.assertEqual(result["requirements"][0]["normalized_text"], "接收光功率")
        self.assertEqual(result["recommendations"][0]["evidence"][0]["requirement"], "收进来的光有多强")

    def test_aliases_and_settings_persist(self):
        status, state = self.request("PUT", "/api/settings", {"claude_enabled": True, "claude_command": ["claude"], "claude_timeout_seconds": 60})
        self.assertEqual(status, 200)
        aliases = {"groups": [{"canonical": "power", "terms": ["接收光功率", "下行收光"]}]}
        status, state = self.request("PUT", "/api/aliases", {"aliases": aliases})
        self.assertEqual(status, 200)
        self.assertEqual(state["aliases"], aliases)
        self.assertTrue(Store(self.directory.name, {"groups": []}).state()["settings"]["claude_enabled"])

    def test_ai_failure_falls_back_and_success_still_uses_catalog(self):
        self.request("PUT", "/api/settings", {"claude_enabled": True})
        with patch("fmemate.server.extract_requirements", side_effect=ValueError("未找到 Claude 命令")):
            status, result = self.request("POST", "/api/recommend", {"query": "接收光功率", "use_ai": True})
        self.assertEqual(status, 200)
        self.assertEqual(result["mode"], "local")
        self.assertEqual(result["plan"]["coverage"], 1)
        self.assertTrue(any("本地匹配" in w for w in result["warnings"]))
        with patch("fmemate.server.extract_requirements", return_value=["虚构的宇宙射线计数"]):
            status, result = self.request("POST", "/api/recommend", {"query": "宇宙射线计数", "use_ai": True})
        self.assertEqual(status, 200)
        self.assertEqual(result["mode"], "claude_cli")
        self.assertEqual(result["plan"]["coverage"], 0)
        self.assertFalse(result["plan"]["function_ids"])

    def test_cross_origin_and_rebinding_rejected(self):
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/demo", {}, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Origin": f"http://localhost:{self.port}"})[0], 200)

    def test_bad_inputs_and_exports(self):
        cases = [("/api/recommend", {"query": ""}), ("/api/recommend", {"query": "光功率", "use_ai": "yes"}),
                 ("/api/import/preview", {"filename": "a.xlsx", "content_base64": "???"}),
                 ("/api/import/confirm", {"preview_id": "not-a-preview"})]
        for route, body in cases:
            self.assertEqual(self.request("POST", route, body)[0], 400)
        self.assertEqual(self.request("GET", "/../../data/state.json")[0], 404)
        self.assertTrue(self.request("GET", "/api/template.csv")[1].startswith(b"\xef\xbb\xbf"))
        self.assertIn("functions", self.request("GET", "/api/catalog/export")[1])


class StorageValidationTests(unittest.TestCase):
    def test_invalid_settings_and_aliases(self):
        for settings in [{"claude_timeout_seconds": True}, {"claude_command": "claude"}, {"unknown": True}, {"claude_command": ["\n"]}]:
            with self.assertRaises(ValueError):
                validate_settings(settings)
        for aliases in [{}, {"groups": "abc"}, {"groups": [{"canonical": "rx", "terms": []}]}]:
            with self.assertRaises(ValueError):
                validate_aliases(aliases)

    def test_corrupt_saved_state_does_not_silently_replace_data(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "state.json").write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "本地数据文件无法读取"):
                Store(directory, {"groups": []})


if __name__ == "__main__":
    unittest.main()
