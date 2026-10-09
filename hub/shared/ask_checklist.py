"""问答错题本：data/ask_checklist.json。

状态：untested | pass | fail（未测 / 好了 / 没好）。
缺文件时用内置种子初始化；之后以文件为准，可增删自定义条目。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from hub.shared.config import ASK_CHECKLIST_FILE

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
VALID_STATUS = frozenset({"untested", "pass", "fail"})

# 内置验收种子（与 Vue 示例芯片对齐；id 稳定便于跨机合并）
_SEED_ITEMS: list[dict[str, str]] = [
    {"id": "a1", "section": "出门与时间", "question": "面面最近去哪了", "intent_hint": "person_recent_places"},
    {"id": "a2", "section": "出门与时间", "question": "最近出去玩了哪些", "intent_hint": "recent_outings"},
    {"id": "a3", "section": "出门与时间", "question": "去年国庆去哪里玩了", "intent_hint": "outings_by_period"},
    {
        "id": "a3c",
        "section": "出门与时间",
        "question": "2023年的国庆节相关照片",
        "intent_hint": "keyword_search",
    },
    {
        "id": "a3b",
        "section": "出门与时间",
        "question": "去年国庆去哪里玩了？开心吗？见了哪些人？",
        "intent_hint": "period_recap",
    },
    {"id": "a4", "section": "出门与时间", "question": "去年春天出门", "intent_hint": "outings_by_period"},
    {"id": "a5", "section": "出门与时间", "question": "面面2024年出去玩了哪些", "intent_hint": "outings_by_period"},
    {"id": "a6", "section": "出门与时间", "question": "面面去动物园是什么时候", "intent_hint": "person_at_place"},
    {"id": "a7", "section": "出门与时间", "question": "面面哪些人去过动物园", "intent_hint": "companions_at_place"},
    {"id": "b1", "section": "住与家", "question": "面面住过哪些地方", "intent_hint": "person_home_timeline"},
    {"id": "b2", "section": "住与家", "question": "面面在哪个地方呆的时间最长", "intent_hint": "person_home_timeline"},
    {"id": "c1", "section": "活动/关键词", "question": "面面骑车的照片", "intent_hint": "keyword_search"},
    {"id": "c2", "section": "活动/关键词", "question": "有没有轮滑", "intent_hint": "keyword_search"},
    {"id": "c3", "section": "活动/关键词", "question": "面面的画作", "intent_hint": "person_artwork"},
    {"id": "c4", "section": "活动/关键词", "question": "有没有笑", "intent_hint": "term_lookup"},
    {"id": "c5", "section": "活动/关键词", "question": "面面哭", "intent_hint": "term_lookup"},
    {"id": "c6", "section": "活动/关键词", "question": "面面第一次轮滑", "intent_hint": "keyword_first"},
    {"id": "d1", "section": "人和合影", "question": "妈妈和面面的合影", "intent_hint": "group_photos"},
    {"id": "d2", "section": "人和合影", "question": "面面和哪个人的合影最多", "intent_hint": "person_companion_rank"},
    {"id": "d3", "section": "人和合影", "question": "面面和笑笑合影", "intent_hint": "group_photos"},
    {"id": "e1", "section": "档案与库", "question": "面面几岁了", "intent_hint": "person_age"},
    {"id": "e2", "section": "档案与库", "question": "一共多少张照片", "intent_hint": "library_stats"},
    {"id": "e3", "section": "档案与库", "question": "面面最近10张照片", "intent_hint": "recent_photos"},
    {"id": "f1", "section": "故事", "question": "轮滑故事", "intent_hint": "story_lookup"},
]


def checklist_path(path: Path | None = None) -> Path:
    return path or ASK_CHECKLIST_FILE


def _normalize_item(raw: dict[str, Any], *, fallback_id: str = "") -> dict[str, Any] | None:
    q = str(raw.get("question") or "").strip()
    if not q:
        return None
    status = str(raw.get("status") or "untested").strip().lower()
    if status not in VALID_STATUS:
        status = "untested"
    item_id = str(raw.get("id") or fallback_id or "").strip() or uuid.uuid4().hex[:10]
    return {
        "id": item_id,
        "section": str(raw.get("section") or "自家补充").strip() or "自家补充",
        "question": q,
        "intent_hint": str(raw.get("intent_hint") or "").strip(),
        "status": status,
        "note": str(raw.get("note") or "").strip(),
    }


def empty_checklist() -> dict[str, Any]:
    items = []
    for seed in _SEED_ITEMS:
        items.append(
            {
                **seed,
                "status": "untested",
                "note": "",
            }
        )
    return {"schema_version": SCHEMA_VERSION, "items": items}


def load_checklist(path: Path | None = None) -> dict[str, Any]:
    file_path = checklist_path(path)
    if not file_path.is_file():
        data = empty_checklist()
        save_checklist(data, file_path)
        return data
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 ask_checklist 失败，用种子重建: %s", exc)
        data = empty_checklist()
        save_checklist(data, file_path)
        return data

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, row in enumerate(raw.get("items") or []):
        if not isinstance(row, dict):
            continue
        item = _normalize_item(row, fallback_id=f"row{i}")
        if not item or item["id"] in seen:
            continue
        seen.add(item["id"])
        items.append(item)

    if not items:
        data = empty_checklist()
        save_checklist(data, file_path)
        return data

    # 合并新增种子 id（保留用户状态；不覆盖已有题）
    merged = False
    for seed in _SEED_ITEMS:
        sid = seed["id"]
        if sid in seen:
            continue
        items.append({**seed, "status": "untested", "note": ""})
        seen.add(sid)
        merged = True
    data = {
        "schema_version": str(raw.get("schema_version") or SCHEMA_VERSION),
        "items": items,
    }
    if merged:
        try:
            save_checklist(data, file_path)
        except OSError as exc:
            logger.warning("合并错题本种子失败: %s", exc)
    return data


def save_checklist(data: dict[str, Any], path: Path | None = None) -> Path:
    file_path = checklist_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        item = _normalize_item(row)
        if item:
            items.append(item)
    payload = {"schema_version": SCHEMA_VERSION, "items": items}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".ask_checklist.",
        suffix=".tmp",
        dir=str(file_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, file_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return file_path


def checklist_stats(items: list[dict[str, Any]]) -> dict[str, int]:
    stats = {"total": 0, "untested": 0, "pass": 0, "fail": 0}
    for item in items:
        stats["total"] += 1
        st = item.get("status") or "untested"
        if st in stats:
            stats[st] += 1
        else:
            stats["untested"] += 1
    return stats


def find_item(data: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for item in data.get("items") or []:
        if item.get("id") == item_id:
            return item
    return None


def update_item(
    item_id: str,
    *,
    status: str | None = None,
    note: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    data = load_checklist(path)
    item = find_item(data, item_id)
    if item is None:
        raise KeyError(item_id)
    if status is not None:
        st = status.strip().lower()
        if st not in VALID_STATUS:
            raise ValueError(f"invalid status: {status}")
        item["status"] = st
    if note is not None:
        item["note"] = note.strip()
    save_checklist(data, path)
    return item


def add_item(
    question: str,
    *,
    section: str = "自家补充",
    intent_hint: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    q = question.strip()
    if not q:
        raise ValueError("question required")
    data = load_checklist(path)
    item = {
        "id": uuid.uuid4().hex[:10],
        "section": (section or "自家补充").strip() or "自家补充",
        "question": q,
        "intent_hint": intent_hint.strip(),
        "status": "untested",
        "note": "",
    }
    data.setdefault("items", []).append(item)
    save_checklist(data, path)
    return item


def delete_item(item_id: str, path: Path | None = None) -> bool:
    data = load_checklist(path)
    items = data.get("items") or []
    new_items = [x for x in items if x.get("id") != item_id]
    if len(new_items) == len(items):
        return False
    data["items"] = new_items
    save_checklist(data, path)
    return True
