"""Atomic local JSON persistence. No credentials or original Excel are stored."""

import copy
import json
import os
import tempfile
import threading
from pathlib import Path

from .demo import demo_catalog

DEFAULT_SETTINGS = {"claude_enabled": False, "claude_command": ["claude"],
                    "claude_timeout_seconds": 45}


def summary(catalog):
    functions = catalog.get("functions", [])
    return {"functions": len(functions),
            "objects": sum(len(f.get("objects", [])) for f in functions),
            "fields": sum(len(o.get("fields", [])) for f in functions
                          for o in f.get("objects", []))}


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) - set(DEFAULT_SETTINGS):
        raise ValueError("AI 设置包含未知参数。")
    result = {**DEFAULT_SETTINGS, **settings}
    if not isinstance(result["claude_enabled"], bool):
        raise ValueError("claude_enabled 必须是布尔值。")
    command = result["claude_command"]
    if (not isinstance(command, list) or not 1 <= len(command) <= 20
            or any(not isinstance(c, str) or not c.strip() or len(c) > 2000
                   or any(x in c for x in ("\x00", "\n", "\r")) for c in command)):
        raise ValueError("Claude 命令应为非空字符串组成的 JSON 数组。")
    timeout = result["claude_timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 5 <= timeout <= 120:
        raise ValueError("Claude 超时需为 5～120 秒的整数。")
    return result


def validate_aliases(aliases):
    if not isinstance(aliases, dict) or set(aliases) != {"groups"}:
        raise ValueError('别名格式应为 {"groups": [{"canonical": "名称", "terms": ["别名"]}]}。')
    groups = aliases["groups"]
    if not isinstance(groups, list) or len(groups) > 1000:
        raise ValueError("别名组数不能超过 1000。")
    names = set()
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"canonical", "terms"}:
            raise ValueError("每个别名组必须包含 canonical 和 terms。")
        name, terms = group["canonical"], group["terms"]
        if not isinstance(name, str) or not name.strip() or len(name) > 100 or name in names:
            raise ValueError("别名组名称不能为空、重复或超过 100 字符。")
        names.add(name)
        if (not isinstance(terms, list) or not 1 <= len(terms) <= 100
                or any(not isinstance(t, str) or not t.strip() or len(t) > 200 for t in terms)):
            raise ValueError("每组需要 1～100 个非空别名，每个最长 200 字符。")
    return copy.deepcopy(aliases)


class Store:
    def __init__(self, data_dir, default_aliases):
        self.directory = Path(data_dir).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.json"
        self.lock = threading.RLock()
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(value.get("catalog", {}).get("functions"), list):
                    raise ValueError("缺少功能目录")
                value["settings"] = validate_settings(value.get("settings", {}))
                value["aliases"] = validate_aliases(value.get("aliases", default_aliases))
                self.value = value
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"本地数据文件无法读取：{self.path}。请检查 JSON，或移走此文件后重新导入。") from exc
        else:
            self.value = {"catalog": demo_catalog(), "settings": dict(DEFAULT_SETTINGS),
                          "aliases": validate_aliases(default_aliases)}

    def state(self):
        with self.lock:
            result = copy.deepcopy(self.value)
        result["summary"] = summary(result["catalog"])
        result["is_demo"] = bool(result["catalog"].get("metadata", {}).get("is_demo", False))
        return result

    def update(self, key, value):
        with self.lock:
            next_value = {**self.value, key: copy.deepcopy(value)}
            fd, temp_path = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=self.directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(next_value, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, self.path)
                self.value = next_value
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        return self.state()
