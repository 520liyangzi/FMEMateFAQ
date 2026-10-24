"""Loopback HTTP API and static application, using only the Python stdlib."""

import base64
import binascii
import csv
import io
import json
import logging
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .claude_cli import extract_requirements
from .demo import demo_catalog
from .importer import preview_import
from .matcher import recommend
from .storage import Store, validate_aliases, validate_settings

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 29 * 1024 * 1024
MAX_FILE = 20 * 1024 * 1024
LOGGER = logging.getLogger("fmemate")


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, data_dir):
        aliases = json.loads((ROOT / "config" / "aliases.json").read_text(encoding="utf-8"))
        self.store = Store(data_dir, aliases)
        self.previews = {}
        self.preview_lock = threading.Lock()
        super().__init__(address, Handler)

    def add_preview(self, preview):
        with self.preview_lock:
            now = time.monotonic()
            self.previews = {k: v for k, v in self.previews.items() if now - v[0] < 1800}
            if len(self.previews) >= 5:
                oldest = min(self.previews, key=lambda k: self.previews[k][0])
                del self.previews[oldest]
            token = secrets.token_urlsafe(24)
            self.previews[token] = (now, preview["catalog"])
            return token


class Handler(BaseHTTPRequestHandler):
    server_version = "FMEMateFAQ/0.1"

    def log_message(self, fmt, *args):
        # Never log query text, uploaded data or CLI output.
        LOGGER.info("%s %s", self.command, self.path.split("?", 1)[0])

    def respond(self, status, body, content_type="application/json; charset=utf-8", filename=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def check_origin(self):
        try:
            host = urlsplit("http://" + self.headers.get("Host", ""))
            port = self.server.server_address[1]
            if host.hostname not in {"127.0.0.1", "localhost"} or (host.port or 80) != port:
                return False
            origin = self.headers.get("Origin")
            if origin:
                parsed = urlsplit(origin)
                return (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
                        and (parsed.port or 80) == port and not parsed.username and not parsed.password)
            return self.headers.get("Sec-Fetch-Site") != "cross-site"
        except ValueError:
            return False

    def read_json(self):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("不支持分块请求，请发送 Content-Length。")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效。") from exc
        if not 0 < length <= MAX_BODY:
            raise ValueError("请求为空或过大，Excel 文件最大 20 MB。")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("请求应为 application/json。")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求 JSON 格式无效。") from exc
        if not isinstance(body, dict):
            raise ValueError("请求应为 JSON 对象。")
        return body

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PUT(self):
        self.handle_request("PUT")

    def handle_request(self, method):
        if not self.check_origin():
            self.respond(403, {"error": "仅允许从本机页面访问，请通过启动时显示的地址打开。"})
            return
        try:
            self.dispatch(method)
        except ValueError as exc:
            self.respond(400, {"error": str(exc)})
        except OSError:
            LOGGER.exception("Local file operation failed")
            self.respond(500, {"error": "本地文件读写失败，请检查数据目录权限与剩余空间。"})
        except Exception:
            LOGGER.exception("Request failed")
            self.respond(500, {"error": "服务处理失败，请查看启动窗口中的错误信息。"})

    def dispatch(self, method):
        path = urlsplit(self.path).path
        if method == "GET":
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/index.html": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in assets:
                name, mime = assets[path]
                self.respond(200, (ROOT / "static" / name).read_bytes(), mime)
            elif path == "/api/state":
                self.respond(200, self.server.store.state())
            elif path == "/api/catalog/export":
                self.respond(200, self.server.store.state()["catalog"], filename="fmemate-catalog.json")
            elif path == "/api/template.csv":
                output = io.StringIO(newline="")
                writer = csv.writer(output)
                writer.writerow(["触发问题", "英文触发问题", "对象中文", "对象英文", "字段中文", "字段英文"])
                writer.writerows([
                    ["请帮我分析一下这个工单", "Help me analyze this ticket", "故障端口表", "Faulty port table", "接收光功率", "Receive Optical Power"],
                    ["", "", "", "", "发射光功率", "Transmit Optical Power"],
                    ["", "", "GNSS信息", "GNSS information", "GNSS工作模式", "GNSS Working Mode"],
                ])
                self.respond(200, "\ufeff" + output.getvalue(), "text/csv; charset=utf-8", "fmemate-template.csv")
            else:
                self.respond(404, {"error": "页面或接口不存在。"})
            return

        body = self.read_json()
        if method == "POST" and path == "/api/import/preview":
            filename = body.get("filename", "")
            if not isinstance(filename, str) or len(filename) > 255 or not filename:
                raise ValueError("请选择 Excel 或 CSV 文件。")
            encoded = body.get("content_base64", "")
            if not isinstance(encoded, str) or len(encoded) > (MAX_FILE * 4 // 3 + 8):
                raise ValueError("文件过大，最大 20 MB。")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("文件编码无效，请重新选择文件。") from exc
            if not content or len(content) > MAX_FILE:
                raise ValueError("文件为空或超过 20 MB。")
            sheet = body.get("sheet") or None
            if sheet is not None and (not isinstance(sheet, str) or len(sheet) > 100):
                raise ValueError("工作表名称无效。")
            result = preview_import(content, Path(filename).name, sheet=sheet,
                                    columns=body.get("columns"), header_row=body.get("header_row"))
            result["catalog"].setdefault("metadata", {})["is_demo"] = False
            result["preview_id"] = self.server.add_preview(result)
            self.respond(200, result)
        elif method == "POST" and path == "/api/import/confirm":
            preview_id = body.get("preview_id")
            if not isinstance(preview_id, str):
                raise ValueError("请先预览待导入的文件。")
            with self.server.preview_lock:
                preview = self.server.previews.get(preview_id)
                if not preview or time.monotonic() - preview[0] > 1800:
                    raise ValueError("预览已过期，请重新预览文件。")
                result = self.server.store.update("catalog", preview[1])
                del self.server.previews[preview_id]
            self.respond(200, result)
        elif method == "POST" and path == "/api/recommend":
            query = body.get("query", "")
            if not isinstance(query, str) or not query.strip() or len(query) > 2000:
                raise ValueError("请输入 1～2000 字符的查询需求。")
            use_ai = body.get("use_ai", False)
            if not isinstance(use_ai, bool):
                raise ValueError("use_ai 必须是布尔值。")
            state = self.server.store.state()
            result = recommend(state["catalog"], query.strip(), aliases=state["aliases"])
            warning = None
            if use_ai:
                if not state["settings"]["claude_enabled"]:
                    raise ValueError("请先在“别名与 AI”中启用 Claude CLI。")
                try:
                    normalized = extract_requirements(query, state["catalog"], state["settings"])
                    originals = result["requirements"]
                    if len(normalized) != len(originals):
                        raise ValueError("Claude 返回的需求数量与原始需求不一致，已保留全部原始需求。")
                    known = set(result["plan"]["covered_requirement_ids"])
                    # Existing matches cannot be reinterpreted by the model. Every
                    # original need keeps its position, even when unknown locally.
                    effective = [item["text"] if item["id"] in known else normalized[i]
                                 for i, item in enumerate(originals)]
                    enhanced = recommend(state["catalog"], query.strip(), aliases=state["aliases"], requirements=effective)
                    if len(enhanced["requirements"]) != len(originals):
                        raise ValueError("Claude 合并了不同原始需求，已保留全部原始需求。")
                    for i, item in enumerate(enhanced["requirements"]):
                        if item["text"] != originals[i]["text"]:
                            item["normalized_text"] = item["text"]
                        item["text"] = originals[i]["text"]
                    by_id = {item["id"]: item for item in enhanced["requirements"]}
                    for candidate in enhanced["recommendations"]:
                        for evidence in candidate["evidence"]:
                            original = by_id[evidence["requirement_id"]]
                            evidence["requirement"] = original["text"]
                            if "normalized_text" in original:
                                evidence["normalized_requirement"] = original["normalized_text"]
                    enhanced["unmatched_requirements"] = [by_id[rid] for rid in enhanced["plan"]["uncovered_requirement_ids"]]
                    enhanced["mode"] = "claude_cli"
                    enhanced["warnings"].append("所有原始需求均已保留；AI 归一化词会显示在需求旁，请核对语义是否一致。")
                    result = enhanced
                except (ValueError, RuntimeError) as exc:
                    warning = str(exc)
            if warning:
                result["warnings"].append("Claude 增强未完成，已使用本地匹配：" + warning)
            if state["is_demo"]:
                result["warnings"].append("当前使用演示数据，推荐不代表你的真实功能目录。")
            self.respond(200, result)
        elif method == "POST" and path == "/api/demo":
            self.respond(200, self.server.store.update("catalog", demo_catalog()))
        elif method == "PUT" and path == "/api/settings":
            self.respond(200, self.server.store.update("settings", validate_settings(body)))
        elif method == "PUT" and path == "/api/aliases":
            self.respond(200, self.server.store.update("aliases", validate_aliases(body.get("aliases"))))
        else:
            self.respond(404, {"error": "接口不存在。"})
