"""Run with: python app.py [--port 8765] [--data-dir ./data] [--no-browser]."""

import argparse
import logging
import threading
import webbrowser
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="FMEMate 功能导航（本地版）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default=str(Path(__file__).resolve().parent / "data"))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口需在 1～65535 之间")
    try:
        from fmemate.server import AppServer
    except ModuleNotFoundError as exc:
        raise SystemExit("缺少依赖，请先执行：python -m pip install -r requirements.txt") from exc
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        server = AppServer(("127.0.0.1", args.port), args.data_dir)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"启动失败：{exc}。端口被占用时可改用 --port 8766。") from exc
    url = f"http://127.0.0.1:{args.port}"
    print(f"FMEMate 功能导航已启动：{url}\n保留此窗口，按 Ctrl+C 停止。", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
