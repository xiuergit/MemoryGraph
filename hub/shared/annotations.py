"""事件意义 / 故事文件真源：data/memory_annotations.json。

与 .geocode_cache.json 同级：可随 data/ 跨机拷贝；SQLite 仅作索引。
稳定身份靠 overlay.anchor_photo_ids / story.links（photo），不用易变的 event_id。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import sqlite3

from hub.shared.config import MEMORY_ANNOTATIONS_FILE

logger = logging.getLogger(__name__)

ANNOTATIONS_SCHEMA_VERSION = "1"


def annotations_path(path: Path | None = None) -> Path:
    return path or MEMORY_ANNOTATIONS_FILE


def empty_annotations() -> dict[str, Any]:
    return {
        "schema_version": ANNOTATIONS_SCHEMA_VERSION,
        "overlays": [],
        "stories": [],
        "schedules": [],
        "diaries": [],
    }


def load_annotations(path: Path | None = None) -> dict[str, Any]:
    """读取标注文件；不存在或损坏时返回空结构。"""
    file_path = annotations_path(path)
    if not file_path.is_file():
        return empty_annotations()
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 memory_annotations 失败: %s", exc)
        return empty_annotations()
    if not isinstance(raw, dict):
        return empty_annotations()

    overlays: list[dict[str, Any]] = []
    for item in raw.get("overlays") or []:
        if not isinstance(item, dict):
            continue
        oid = str(item.get("overlay_id") or "").strip()
        if not oid:
            continue
        tags = item.get("tags")
        if not isinstance(tags, list):
            tags = []
        anchors = item.get("anchor_photo_ids")
        if not isinstance(anchors, list):
            anchors = []
        overlays.append(
            {
                "overlay_id": oid,
                "event_id": str(item.get("event_id") or ""),
                "anchor_photo_ids": [str(a) for a in anchors if str(a).strip()],
                "title": str(item.get("title") or ""),
                "body": str(item.get("body") or ""),
                "tags": [str(t) for t in tags if str(t).strip()],
                "manual": 1 if item.get("manual", True) else 0,
                "updated_at": str(item.get("updated_at") or ""),
            }
        )

    stories: list[dict[str, Any]] = []
    for item in raw.get("stories") or []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("story_id") or "").strip()
        if not sid:
            continue
        people = item.get("people")
        if not isinstance(people, list):
            people = []
        links_raw = item.get("links")
        links: list[dict[str, Any]] = []
        if isinstance(links_raw, list):
            for i, link in enumerate(links_raw):
                if not isinstance(link, dict):
                    continue
                link_type = str(link.get("link_type") or "").strip()
                link_id = str(link.get("link_id") or "").strip()
                if link_type not in ("event", "photo") or not link_id:
                    continue
                try:
                    sort_order = int(link.get("sort_order", i))
                except (TypeError, ValueError):
                    sort_order = i
                links.append(
                    {
                        "link_type": link_type,
                        "link_id": link_id,
                        "sort_order": sort_order,
                    }
                )
        stories.append(
            {
                "story_id": sid,
                "title": str(item.get("title") or ""),
                "body": str(item.get("body") or ""),
                "time_start": str(item.get("time_start") or ""),
                "time_end": str(item.get("time_end") or ""),
                "people": [str(p) for p in people if str(p).strip()],
                "links": links,
                "updated_at": str(item.get("updated_at") or ""),
            }
        )

    return {
        "schema_version": str(raw.get("schema_version") or ANNOTATIONS_SCHEMA_VERSION),
        "overlays": overlays,
        "stories": stories,
        "schedules": _plan_rows(raw.get("schedules")),
        "diaries": _plan_rows(raw.get("diaries")),
    }


def _plan_rows(raw: Any) -> list[dict[str, Any]]:
    """课表 / 日记按手机原样保留，只丢掉没有 id 的行。"""
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if not str(item.get("id") or "").strip():
            continue
        rows.append(item)
    return rows


def save_annotations(data: dict[str, Any], path: Path | None = None) -> Path:
    """原子写入标注文件。

    未带上 schedules / diaries 时保留文件里已有的课表和日记，
    避免事件同步把手机备份清掉。
    """
    file_path = annotations_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    previous: dict[str, Any] = {}
    if file_path.is_file():
        try:
            loaded = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (json.JSONDecodeError, OSError):
            previous = {}
    if "schedules" in data:
        schedules = _plan_rows(data.get("schedules"))
    else:
        schedules = _plan_rows(previous.get("schedules"))
    if "diaries" in data:
        diaries = _plan_rows(data.get("diaries"))
    else:
        diaries = _plan_rows(previous.get("diaries"))
    payload = {
        "schema_version": str(data.get("schema_version") or ANNOTATIONS_SCHEMA_VERSION),
        "overlays": data.get("overlays") or [],
        "stories": data.get("stories") or [],
        "schedules": schedules,
        "diaries": diaries,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".memory_annotations.",
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


def collect_annotations_from_db(conn: sqlite3.Connection) -> dict[str, Any]:
    """从 SQLite 导出 overlays + stories（含 links）。"""
    overlays: list[dict[str, Any]] = []
    for row in conn.execute(
        """
        SELECT overlay_id, event_id, anchor_photo_ids, title, body,
               tags_json, manual, updated_at
        FROM event_overlays
        ORDER BY overlay_id
        """
    ):
        try:
            anchors = json.loads(row["anchor_photo_ids"] or "[]")
        except json.JSONDecodeError:
            anchors = []
        try:
            tags = json.loads(row["tags_json"] or "[]")
        except json.JSONDecodeError:
            tags = []
        if not isinstance(anchors, list):
            anchors = []
        if not isinstance(tags, list):
            tags = []
        overlays.append(
            {
                "overlay_id": row["overlay_id"],
                "event_id": row["event_id"] or "",
                "anchor_photo_ids": [str(a) for a in anchors],
                "title": row["title"] or "",
                "body": row["body"] or "",
                "tags": [str(t) for t in tags],
                "manual": bool(row["manual"]),
                "updated_at": row["updated_at"] or "",
            }
        )

    stories: list[dict[str, Any]] = []
    for row in conn.execute(
        """
        SELECT story_id, title, body, time_start, time_end, people_json, updated_at
        FROM stories
        ORDER BY story_id
        """
    ):
        try:
            people = json.loads(row["people_json"] or "[]")
        except json.JSONDecodeError:
            people = []
        if not isinstance(people, list):
            people = []
        links = [
            {
                "link_type": r["link_type"],
                "link_id": r["link_id"],
                "sort_order": int(r["sort_order"] or 0),
            }
            for r in conn.execute(
                """
                SELECT link_type, link_id, sort_order
                FROM story_links
                WHERE story_id = ?
                ORDER BY sort_order ASC, link_type, link_id
                """,
                (row["story_id"],),
            )
        ]
        stories.append(
            {
                "story_id": row["story_id"],
                "title": row["title"] or "",
                "body": row["body"] or "",
                "time_start": row["time_start"] or "",
                "time_end": row["time_end"] or "",
                "people": [str(p) for p in people],
                "links": links,
                "updated_at": row["updated_at"] or "",
            }
        )

    return {
        "schema_version": ANNOTATIONS_SCHEMA_VERSION,
        "overlays": overlays,
        "stories": stories,
    }


def replace_annotations_in_db(
    conn: sqlite3.Connection,
    data: dict[str, Any],
    *,
    commit: bool = True,
) -> tuple[int, int]:
    """用文件内容整表替换 SQLite 中的 overlays / stories。返回 (overlays, stories)。"""
    conn.execute("DELETE FROM story_links")
    conn.execute("DELETE FROM stories")
    conn.execute("DELETE FROM event_overlays")

    overlay_count = 0
    overlays = data.get("overlays") or []
    for ov in overlays:
        if not isinstance(ov, dict):
            continue
        oid = str(ov.get("overlay_id") or "").strip()
        if not oid:
            continue
        anchors = ov.get("anchor_photo_ids") or []
        tags = ov.get("tags") or []
        if not isinstance(anchors, list):
            anchors = []
        if not isinstance(tags, list):
            tags = []
        manual = 1 if ov.get("manual", True) else 0
        conn.execute(
            """
            INSERT INTO event_overlays (
                overlay_id, event_id, anchor_photo_ids, title, body,
                tags_json, manual, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                oid,
                str(ov.get("event_id") or ""),
                json.dumps(anchors, ensure_ascii=False),
                str(ov.get("title") or ""),
                str(ov.get("body") or ""),
                json.dumps(tags, ensure_ascii=False),
                manual,
                str(ov.get("updated_at") or ""),
            ),
        )
        overlay_count += 1

    story_count = 0
    stories = data.get("stories") or []
    for st in stories:
        if not isinstance(st, dict):
            continue
        sid = str(st.get("story_id") or "").strip()
        if not sid:
            continue
        people = st.get("people") or []
        if not isinstance(people, list):
            people = []
        conn.execute(
            """
            INSERT INTO stories (
                story_id, title, body, time_start, time_end, people_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                str(st.get("title") or ""),
                str(st.get("body") or ""),
                str(st.get("time_start") or ""),
                str(st.get("time_end") or ""),
                json.dumps(people, ensure_ascii=False),
                str(st.get("updated_at") or ""),
            ),
        )
        story_count += 1
        links = st.get("links") or []
        if not isinstance(links, list):
            continue
        rows = []
        for i, link in enumerate(links):
            if not isinstance(link, dict):
                continue
            link_type = str(link.get("link_type") or "").strip()
            link_id = str(link.get("link_id") or "").strip()
            if link_type not in ("event", "photo") or not link_id:
                continue
            try:
                sort_order = int(link.get("sort_order", i))
            except (TypeError, ValueError):
                sort_order = i
            rows.append((sid, link_type, link_id, sort_order))
        if rows:
            conn.executemany(
                """
                INSERT INTO story_links (story_id, link_type, link_id, sort_order)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )

    if commit:
        conn.commit()
    return overlay_count, story_count


def flush_annotations_from_db(
    conn: sqlite3.Connection,
    path: Path | None = None,
) -> Path:
    """把当前 SQLite 标注写回文件。"""
    data = collect_annotations_from_db(conn)
    return save_annotations(data, path)


def ensure_annotations_loaded(
    conn: sqlite3.Connection,
    path: Path | None = None,
) -> str:
    """sync 前：有文件则灌库；无文件但库里有数据则导出。返回动作说明。"""
    file_path = annotations_path(path)
    if file_path.is_file():
        data = load_annotations(file_path)
        n_ov, n_st = replace_annotations_in_db(conn, data, commit=False)
        return f"loaded file → {n_ov} overlays, {n_st} stories"
    existing = collect_annotations_from_db(conn)
    if existing["overlays"] or existing["stories"]:
        save_annotations(existing, file_path)
        return (
            f"bootstrapped file from db → "
            f"{len(existing['overlays'])} overlays, {len(existing['stories'])} stories"
        )
    save_annotations(empty_annotations(), file_path)
    return "created empty annotations file"


def mobile_plan(path: Path | None = None) -> dict[str, Any]:
    """手机课表和日记的 Mac 备份。"""
    data = load_annotations(path)
    return {
        "schedules": data.get("schedules") or [],
        "diaries": data.get("diaries") or [],
    }


def replace_mobile_plan(
    schedules: list[Any],
    diaries: list[Any],
    path: Path | None = None,
) -> dict[str, Any]:
    """用手机传来的整份课表和日记替换备份。不改 overlays / stories。"""
    data = load_annotations(path)
    data["schedules"] = _plan_rows(schedules)
    data["diaries"] = _plan_rows(diaries)
    save_annotations(data, path)
    return {
        "schedules": len(data["schedules"]),
        "diaries": len(data["diaries"]),
    }
