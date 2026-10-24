"""Deterministic bilingual capability search with evidence and minimum query plans.

This module never calls a model or network service.  A capability is recommended
only when its imported question/object/field text supplies matching evidence.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from functools import lru_cache
from typing import Any

DEFAULT_ALIASES_PATH = Path(__file__).resolve().parent.parent / "config" / "aliases.json"
MAX_REQUIREMENTS = 24
MAX_RECOMMENDATIONS = 8


def _norm(value: Any) -> str:
    return _normalize_text(str(value or ""))


@lru_cache(maxsize=8192)
def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"(?<=\w)的(?=\w)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@lru_cache(maxsize=4096)
def _pattern(term: str) -> str:
    term = _norm(term)
    parts = re.split(r"[\s_\-]+", term)
    pattern = r"[\s_\-]*".join(re.escape(part) for part in parts)
    if term and term[0].isascii() and term[0].isalnum():
        pattern = r"(?<![a-z0-9])" + pattern
    if term and term[-1].isascii() and term[-1].isalnum():
        pattern += r"(?![a-z0-9])"
    return pattern


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle and re.search(_pattern(needle), _norm(haystack)))


def _load_groups(aliases: dict | None) -> list[dict]:
    if aliases is None:
        try:
            aliases = json.loads(DEFAULT_ALIASES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            aliases = {"groups": []}
    groups = aliases.get("groups", [])
    if isinstance(groups, dict):
        groups = [{"canonical": key, "terms": value} for key, value in groups.items()]
    result = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        terms = group.get("terms", [])
        if isinstance(terms, list):
            result.append({"canonical": str(group.get("canonical", "")),
                           "terms": [_norm(t) for t in terms if isinstance(t, str) and t.strip()]})
    return result


def _concept_spans(text: str, groups: list[dict]) -> list[tuple[int, int, str]]:
    """Prefer a specific label (rx optical power) over nested generic labels."""
    normalized = _norm(text)
    cache = groups[0].setdefault("_span_cache", {}) if groups else {}
    if normalized in cache:
        return cache[normalized]
    matches = []
    for group in groups:
        for term in group["terms"]:
            for match in re.finditer(_pattern(term), normalized):
                matches.append((match.start(), match.end(), group["canonical"]))
    selected: list[tuple[int, int, str]] = []
    for start, end, concept in sorted(matches, key=lambda m: (-(m[1] - m[0]), m[0], m[2])):
        if not any(start < b and end > a for a, b, _ in selected):
            selected.append((start, end, concept))
    selected.sort()
    if len(cache) < 20000:
        cache[normalized] = selected
    return selected


def _clean_requirement(text: str) -> str:
    text = text.strip(" \t\r\n,，。.;；:：?!？！")
    text = re.sub(r"^(?:请|麻烦|帮我|帮忙|帮助我|我想|我需要|想知道|想要|知道|需要|能否|能不能|可以|我要|一下|查询下|查下|查询|查看|检查|检索|查找|查|了解|获取|看一下|看看|看)+", "", text)
    text = re.sub(r"^(?:(?:please|help\s+me|i\s+want\s+to|i\s+need\s+to|i\s+need|show\s+me|could\s+you|can\s+you|check|query|find|look\s+up|get|the)\s+)+", "", text, flags=re.I)
    text = re.sub(r"(?:一下|是多少|是什么|的情况|情况|有哪些功能|可以用什么功能|可以用哪些功能)$", "", text)
    return text.strip(" \t\r\n,，。.;；:：?!？！")


def split_requirements(query: str) -> list[str]:
    """Split conjunctions and expand paired Tx/Rx requests without discarding unknowns."""
    text = unicodedata.normalize("NFKC", query).strip()
    text = re.sub(r"(?:收发|收[、和与及/]发|接收[和与及/]发射|接收[和与及/]发送)光功率", "接收光功率 和 发射光功率", text)
    text = re.sub(r"(?:rx\s*(?:[/&+]|and)\s*tx|tx\s*(?:[/&+]|and)\s*rx|receive\s*[/&+]\s*transmit|transmit\s*[/&+]\s*receive|receive\s+and\s+transmit|transmit\s+and\s+receive)(\s+optical\s+power)", "receive optical power and transmit optical power", text, flags=re.I)
    text = re.sub(r"(?:接收光功率)[、/]?(?:发射光功率)", "接收光功率 和 发射光功率", text)
    text = re.sub(r"/(?=GNSS|[\u3400-\u9fff])", " 和 ", text, flags=re.I)
    pieces = re.split(r"(?:以及|并且|同时|还有|和|与|及|、|[,，;；\n]|\s*\+\s*|\s*&\s*|\band\b|\balso\b)", text, flags=re.I)
    result = []
    seen = set()
    for piece in pieces:
        item = _clean_requirement(piece)
        key = _norm(item)
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


# These words describe the query or broad object context, rather than a
# capability. They may be left over after a specific field/alias is matched.
_CONTEXT_ZH = ("端口", "单板", "板卡", "设备", "网元", "站点", "工单", "故障", "当前", "这个", "该", "有关", "相关", "信息", "数据", "数值", "参数", "的", "一下", "了", "吗", "呢")
_CONTEXT_EN = {"port", "ports", "board", "card", "device", "site", "ticket", "current", "this", "that", "the", "a", "an", "of", "for", "on", "in", "with", "value", "values", "information", "data", "parameter", "parameters", "please", "me", "show", "check", "query", "get", "need", "want", "to", "i"}


def _meaningful_residual(text: str) -> str:
    text = _norm(text)
    for word in _CONTEXT_ZH:
        text = text.replace(word, " ")
    tokens = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", text)
    return " ".join(token for token in tokens if token not in _CONTEXT_EN)


def _residual_supported(residual: str, context: str) -> bool:
    rest = _meaningful_residual(residual)
    if not rest:
        return True
    for token in rest.split():
        if not _contains(context, token):
            return False
    return True


def _document_matches(requirement: str, doc: dict, groups: list[dict]) -> str | None:
    req = _norm(requirement)
    if not req:
        return None
    text = doc["text"]
    if doc.get("level") == "field" and doc.get("object_text"):
        object_doc = {"text": doc["object_text"], "labels": doc["object_labels"], "level": "object"}
        if _document_matches(requirement, object_doc, groups):
            field_doc = {"text": doc["field_text"], "labels": doc["labels"], "level": "field_only"}
            if not _document_matches(requirement, field_doc, groups):
                return None
    if _contains(text, req):
        return "exact"
    spans = _concept_spans(req, groups)
    if spans:
        doc_concepts = doc.get("concepts")
        if doc_concepts is None:
            doc_concepts = {c for _, _, c in _concept_spans(text, groups)}
        if _contains(text, "gnss") and any(_contains(text, label) for label in ("工作模式", "运行模式", "working mode", "operating mode", "operation mode")):
            doc_concepts = doc_concepts | {"gnss_working_mode"}
        def supported(concept: str) -> bool:
            return concept in doc_concepts or (concept == "optical_power" and bool(doc_concepts & {"receive_optical_power", "transmit_optical_power"}))
        if not all(supported(c) for _, _, c in spans):
            return None
        leftover = req
        for start, end, _ in reversed(spans):
            leftover = leftover[:start] + " " + leftover[end:]
        if _residual_supported(leftover, text):
            return "alias"
        return None
    # For labels not in the alias dictionary, require a whole imported label.
    # This deliberately avoids fuzzy character/token scores claiming coverage.
    labels = sorted(doc["labels"], key=lambda s: len(_norm(s)), reverse=True)
    for label in labels:
        norm_label = _norm(label)
        if len(norm_label) < 2 or not _contains(req, norm_label):
            continue
        residual = re.sub(_pattern(norm_label), " ", req)
        if _residual_supported(residual, text):
            return "label"
    return None


def _documents(function: dict) -> list[dict]:
    documents = []
    question_labels = [function.get("question_zh", ""), function.get("question_en", "")]
    question_text = " / ".join(str(v) for v in question_labels if v)
    documents.append({"text": question_text, "labels": question_labels,
                      "object": None, "field": None, "source": next(iter(function.get("sources", [])), None), "level": "question"})
    for obj in function.get("objects", []):
        object_labels = [obj.get("name_zh", ""), obj.get("name_en", "")]
        object_text = " / ".join(str(v) for v in object_labels if v)
        documents.append({"text": object_text, "labels": object_labels, "object": obj, "field": None,
                          "source": next(iter(obj.get("sources", [])), None), "level": "object"})
        for field in obj.get("fields", []):
            field_labels = [field.get("name_zh", ""), field.get("name_en", "")]
            documents.append({"text": object_text + " / " + " / ".join(str(v) for v in field_labels if v),
                              "labels": field_labels, "object_text": object_text, "object_labels": object_labels, "field_text": " / ".join(str(v) for v in field_labels if v), "object": obj, "field": field,
                              "source": next(iter(field.get("sources", [])), None), "level": "field"})
    return documents


def _evidence(requirement: dict, document: dict, match_type: str) -> dict:
    obj, field = document["object"] or {}, document["field"] or {}
    return {"requirement_id": requirement["id"], "requirement": requirement["text"],
            "object_zh": obj.get("name_zh", ""), "object_en": obj.get("name_en", ""),
            "field_zh": field.get("name_zh", ""), "field_en": field.get("name_en", ""),
            "match_type": match_type, "source": document["source"], "level": document["level"]}


def _plan(candidates: list[dict], count: int) -> tuple[list[str], set[str], bool]:
    """Exact minimum set cover for modest inputs, bounded greedy for large ones."""
    req_ids = [f"r{i + 1}" for i in range(count)]
    masks = []
    for candidate in candidates:
        mask = sum(1 << req_ids.index(rid) for rid in candidate["matched_requirement_ids"])
        if mask:
            masks.append((candidate["function_id"], mask))
    target = 0
    for _, mask in masks:
        target |= mask
    if not target:
        return [], set(), True
    # Remove duplicate/subset masks; candidates are already ranked by coverage,
    # then specificity. This also makes exact DP practical for typical FAQ data.
    useful = []
    for fid, mask in masks:
        if not any(mask | existing_mask == existing_mask for _, existing_mask in useful):
            useful.append((fid, mask))
    optimal = count <= 18 and len(useful) <= 120
    if optimal:
        states: dict[int, tuple[str, ...]] = {0: ()}
        for fid, mask in useful:
            for state, chosen in list(states.items()):
                new_state = state | mask
                proposal = chosen + (fid,)
                previous = states.get(new_state)
                if previous is None or len(proposal) < len(previous):
                    states[new_state] = proposal
            # Bound work on inputs with many overlapping combinations.
            if len(states) > 50000:
                optimal = False
                break
        if optimal:
            ids = list(states[target])
            return ids, {rid for i, rid in enumerate(req_ids) if target & (1 << i)}, True
    selected, covered = [], 0
    remaining = list(useful)
    while covered != target and remaining:
        fid, mask = max(remaining, key=lambda item: ((item[1] & ~covered).bit_count(), item[1].bit_count()))
        selected.append(fid)
        covered |= mask
        remaining = [item for item in remaining if item[0] != fid]
    return selected, {rid for i, rid in enumerate(req_ids) if covered & (1 << i)}, False


def recommend(catalog: dict, query: str, aliases: dict | None = None,
              requirements: list[str] | None = None) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("请输入想查询的内容。")
    if len(query) > 4000:
        raise ValueError("需求最多支持 4000 个字符。")
    if requirements is not None and (not isinstance(requirements, list) or not all(isinstance(r, str) and r.strip() for r in requirements)):
        raise ValueError("需求列表必须包含非空文本。")
    texts = requirements if requirements is not None else split_requirements(query)
    texts = list(dict.fromkeys(t.strip() for t in texts if t.strip()))
    if len(texts) > MAX_REQUIREMENTS:
        raise ValueError(f"一次最多支持 {MAX_REQUIREMENTS} 项需求，请分批查询。")
    if not texts:
        raise ValueError("请补充具体想查询的对象或字段，例如：收发光功率和 GNSS 工作模式。")
    items = [{"id": f"r{i + 1}", "text": t} for i, t in enumerate(texts)]
    groups = _load_groups(aliases)
    candidates = []
    for function in catalog.get("functions", []):
        docs = _documents(function)
        for doc in docs:
            doc["concepts"] = {c for _, _, c in _concept_spans(doc["text"], groups)}
        evidence = []
        matched_ids = []
        for item in items:
            matches = []
            for doc in docs:
                kind = _document_matches(item["text"], doc, groups)
                if kind:
                    # Prefer a precise field path to a more general object.
                    rank = {"field": 0, "object": 1, "question": 2}[doc["level"]]
                    matches.append((rank, {"exact": 0, "alias": 1, "label": 2}[kind], doc, kind))
            if matches:
                matches.sort(key=lambda m: (m[0], m[1]))
                matched_ids.append(item["id"])
                # One grounded path per requirement keeps results readable.
                _, _, doc, kind = matches[0]
                evidence.append(_evidence(item, doc, kind))
        if matched_ids:
            candidates.append({"function_id": function["id"],
                               "question_zh": function.get("question_zh", ""),
                               "question_en": function.get("question_en", ""),
                               "coverage": len(matched_ids) / len(items),
                               "matched_requirement_ids": matched_ids,
                               "missing_requirement_ids": [i["id"] for i in items if i["id"] not in matched_ids],
                               "evidence": evidence,
                               "object_count": len(function.get("objects", []))})
    # Broad questions win on coverage. For identical coverage prefer a focused
    # feature with fewer unrelated objects, then stable labels for repeatability.
    candidates.sort(key=lambda c: (-len(c["matched_requirement_ids"]), c["object_count"], c["question_zh"], c["function_id"]))
    plan_ids, covered, optimal = _plan(candidates, len(items))
    selected = [c for c in candidates if c["function_id"] in plan_ids]
    selected.extend(c for c in candidates if c["function_id"] not in plan_ids)
    recommendations = selected[:max(MAX_RECOMMENDATIONS, len(plan_ids))]
    all_ids = [i["id"] for i in items]
    uncovered = [rid for rid in all_ids if rid not in covered]
    warnings = []
    if not optimal:
        warnings.append("需求或候选功能较多，组合方案使用近似搜索，可能存在更少的功能组合。")
    return {"query": query, "requirements": items, "recommendations": recommendations,
            "plan": {"function_ids": plan_ids, "covered_requirement_ids": [rid for rid in all_ids if rid in covered],
                     "uncovered_requirement_ids": uncovered, "coverage": len(covered) / len(items), "optimal": optimal},
            "unmatched_requirements": [item for item in items if item["id"] in uncovered],
            "mode": "local", "warnings": warnings}
