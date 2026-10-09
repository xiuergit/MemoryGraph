"""手机 Outbox story.upsert：稳定 story_id 幂等写故事。

合同：docs/mobile-outbox.md §4 / §6。
- links=[] 可建草稿
- link_type=photo 的 link_id 必须是已落地 photo_id（禁止未解析 local_id）
- 长期身份以 photo anchors 为准；event link 仅 Desk 可入，且默认展开为 photo
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import sqlite3

from hub.shared.config import (
    INGEST_REGISTRY_FILE,
    MEMORY_DB,
    MEMORY_DIR,
    STORY_UPSERT_REGISTRY_FILE,
)
from hub.shared.index_db import connect, init_db

logger = logging.getLogger(__name__)

_REGISTRY_LOCK = threading.Lock()
_SAFE_STORY_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


@dataclass
class StoryUpsertReceipt:
    """story.upsert 回执（对齐 ingest/describe）。"""

    status: str  # accepted | conflict
    story_id: str
    mutation_id: str = ""
    device_id: str = ""
    created: bool = False
    story: dict[str, Any] | None = None
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class StoryUpsertError(ValueError):
    """请求不合法（Desk → 400）。"""


class StoryLinkError(StoryUpsertError):
    """links 校验失败（含未落地 photo_id）。"""


def is_landed_photo_id(
    photo_id: str,
    *,
    memory_dir: Path | None = None,
    db_path: Path | None = None,
    ingest_registry_path: Path | None = None,
) -> bool:
    """是否已落地为可长期挂靠的 photo_id（非 Outbox local_id）。

    判定：memory JSON 存在，或索引 photos 表有行，或 ingest 旁路表已登记。
    不读原图像素。
    """
    pid = (photo_id or "").strip()
    if not pid:
        return False
    if (Path(memory_dir or MEMORY_DIR) / f"{pid}.json").is_file():
        return True

    db = Path(db_path or MEMORY_DB)
    if db.is_file():
        conn = connect(db)
        try:
            init_db(conn)
            row = conn.execute(
                "SELECT 1 FROM photos WHERE photo_id = ? LIMIT 1", (pid,)
            ).fetchone()
            if row:
                return True
        finally:
            conn.close()

    reg_path = Path(ingest_registry_path or INGEST_REGISTRY_FILE)
    if reg_path.is_file():
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reg = {}
        for entry in (reg.get("by_hash") or {}).values():
            if isinstance(entry, dict) and str(entry.get("photo_id") or "") == pid:
                return True
    return False


def _event_photo_ids(conn: sqlite3.Connection, event_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT photo_id FROM event_photos
        WHERE event_id = ?
        ORDER BY sort_ts, photo_id
        """,
        (event_id,),
    ).fetchall()
    return [str(r["photo_id"]) for r in rows if str(r["photo_id"] or "").strip()]


def normalize_story_links(
    links: list[dict[str, Any]] | None,
    *,
    memory_dir: Path | None = None,
    db_path: Path | None = None,
    ingest_registry_path: Path | None = None,
    allow_event: bool = False,
    expand_event_to_photos: bool = True,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """规范化 links；空列表合法。photo 必须已落地，否则抛 StoryLinkError。

    - 默认 allow_event=False（手机 Outbox / 长期挂靠）
    - Desk 可 allow_event=True：将 event 成员展开为 photo anchors，不再保留 event link
      （event_id = hash(成员集)，聚类一变就失效）
    """
    if not links:
        return []

    own_conn = False
    db_conn = conn
    if allow_event and expand_event_to_photos and db_conn is None:
        db_conn = connect(db_path or MEMORY_DB)
        init_db(db_conn)
        own_conn = True

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    try:
        for i, raw in enumerate(links):
            if not isinstance(raw, dict):
                raise StoryLinkError(f"links[{i}] 须为对象")
            link_type = str(raw.get("link_type") or "").strip()
            link_id = str(raw.get("link_id") or "").strip()
            if not link_type or not link_id:
                raise StoryLinkError(f"links[{i}] 缺少 link_type / link_id")
            try:
                sort_order = int(raw.get("sort_order", i))
            except (TypeError, ValueError):
                sort_order = i

            if link_type == "photo":
                if not is_landed_photo_id(
                    link_id,
                    memory_dir=memory_dir,
                    db_path=db_path,
                    ingest_registry_path=ingest_registry_path,
                ):
                    raise StoryLinkError(
                        f"links[{i}] photo link_id 未落地（禁止未解析 local_id）: {link_id}"
                    )
                key = ("photo", link_id)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "link_type": "photo",
                        "link_id": link_id,
                        "sort_order": sort_order,
                    }
                )
            elif link_type == "event":
                if not allow_event:
                    raise StoryLinkError(
                        f"links[{i}] 不允许 link_type=event"
                        "（故事长期挂靠须用已落地 photo；event_id 随聚类变化）"
                    )
                if expand_event_to_photos:
                    if db_conn is None:
                        raise StoryLinkError(
                            f"links[{i}] event→photo 展开需要数据库连接"
                        )
                    photo_ids = _event_photo_ids(db_conn, link_id)
                    if not photo_ids:
                        raise StoryLinkError(
                            f"links[{i}] event 无成员照片，无法展开为 photo anchors: {link_id}"
                        )
                    for j, pid in enumerate(photo_ids):
                        key = ("photo", pid)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(
                            {
                                "link_type": "photo",
                                "link_id": pid,
                                "sort_order": sort_order * 1000 + j,
                            }
                        )
                    logger.info(
                        "story link event %s → %d photo anchors",
                        link_id,
                        len(photo_ids),
                    )
                else:
                    key = ("event", link_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(
                        {
                            "link_type": "event",
                            "link_id": link_id,
                            "sort_order": sort_order,
                        }
                    )
            else:
                raise StoryLinkError(
                    f"links[{i}] link_type 须为 photo 或 event，收到: {link_type}"
                )
    finally:
        if own_conn and db_conn is not None:
            db_conn.close()

    return out


def _empty_registry() -> dict[str, Any]:
    return {"schema_version": 1, "by_mutation_id": {}}


def _load_registry(path: Path | None = None) -> dict[str, Any]:
    reg_path = Path(path or STORY_UPSERT_REGISTRY_FILE)
    if not reg_path.is_file():
        return _empty_registry()
    try:
        data = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("story upsert registry 损坏，重建空表: %s", exc)
        return _empty_registry()
    if not isinstance(data, dict):
        return _empty_registry()
    data.setdefault("schema_version", 1)
    data.setdefault("by_mutation_id", {})
    return data


def _save_registry(data: dict[str, Any], path: Path | None = None) -> None:
    reg_path = Path(path or STORY_UPSERT_REGISTRY_FILE)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = reg_path.with_suffix(reg_path.suffix + ".tmp")
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(reg_path)


def _payload_digest(
    *,
    story_id: str,
    title: str,
    body: str,
    time_start: str,
    time_end: str,
    people: list[str],
    links: list[dict[str, Any]],
) -> str:
    canonical = {
        "story_id": story_id,
        "title": title,
        "body": body,
        "time_start": time_start,
        "time_end": time_end,
        "people": people,
        "links": links,
    }
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_story_id(story_id: str) -> str:
    sid = (story_id or "").strip()
    if not sid:
        raise StoryUpsertError("story_id 不能为空")
    if not _SAFE_STORY_ID_RE.match(sid):
        raise StoryUpsertError(
            "story_id 仅允许字母数字与 _.-，建议 sty_ + uuid"
        )
    return sid


def upsert_story(
    *,
    story_id: str,
    title: str,
    body: str = "",
    time_start: str = "",
    time_end: str = "",
    people: list[str] | None = None,
    links: list[dict[str, Any]] | None = None,
    mutation_id: str = "",
    device_id: str = "",
    db_path: Path | None = None,
    memory_dir: Path | None = None,
    registry_path: Path | None = None,
    ingest_registry_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> StoryUpsertReceipt:
    """按稳定 story_id 创建或更新；mutation_id 同载荷可重放。"""
    from hub.shared.events import create_story, get_story, update_story

    sid = _validate_story_id(story_id)
    title_s = (title or "").strip()
    if not title_s:
        raise StoryUpsertError("title 不能为空")

    people_list = [str(p).strip() for p in (people or []) if str(p).strip()]
    body_s = str(body or "")
    start_s = str(time_start or "")
    end_s = str(time_end or "")
    norm_links = normalize_story_links(
        links,
        memory_dir=memory_dir,
        db_path=db_path,
        ingest_registry_path=ingest_registry_path,
        allow_event=False,
    )

    mut = (mutation_id or "").strip()
    device = (device_id or "").strip()
    digest = _payload_digest(
        story_id=sid,
        title=title_s,
        body=body_s,
        time_start=start_s,
        time_end=end_s,
        people=people_list,
        links=norm_links,
    )
    reg_file = Path(registry_path or STORY_UPSERT_REGISTRY_FILE)
    db = Path(db_path or MEMORY_DB)

    own_conn = conn is None
    if own_conn:
        conn = connect(db)
        init_db(conn)

    try:
        with _REGISTRY_LOCK:
            registry = _load_registry(reg_file)

            if mut:
                prev = registry["by_mutation_id"].get(mut)
                if isinstance(prev, dict) and prev:
                    prev_digest = str(prev.get("content_digest") or "")
                    prev_sid = str(prev.get("story_id") or "")
                    if prev_digest == digest and prev_sid == sid:
                        story = get_story(conn, sid)
                        return StoryUpsertReceipt(
                            status="accepted",
                            story_id=sid,
                            mutation_id=mut,
                            device_id=str(prev.get("device_id") or device),
                            created=False,
                            story=story,
                            message="mutation_id 幂等重放",
                        )
                    return StoryUpsertReceipt(
                        status="conflict",
                        story_id=prev_sid or sid,
                        mutation_id=mut,
                        device_id=str(prev.get("device_id") or ""),
                        created=False,
                        story=get_story(conn, prev_sid) if prev_sid else None,
                        message="同一 mutation_id 已绑定不同故事载荷",
                    )

            existing = get_story(conn, sid)
            if existing is None:
                story = create_story(
                    conn,
                    title=title_s,
                    body=body_s,
                    time_start=start_s,
                    time_end=end_s,
                    people=people_list,
                    links=norm_links,
                    story_id=sid,
                    memory_dir=memory_dir,
                    db_path=db,
                    ingest_registry_path=ingest_registry_path,
                )
                created = True
                message = "已创建故事"
            else:
                story = update_story(
                    conn,
                    sid,
                    title=title_s,
                    body=body_s,
                    time_start=start_s,
                    time_end=end_s,
                    people=people_list,
                    links=norm_links,
                    memory_dir=memory_dir,
                    db_path=db,
                    ingest_registry_path=ingest_registry_path,
                )
                created = False
                message = "已更新故事"

            if mut:
                registry["by_mutation_id"][mut] = {
                    "story_id": sid,
                    "content_digest": digest,
                    "device_id": device,
                    "status": "accepted",
                }
                _save_registry(registry, reg_file)

            return StoryUpsertReceipt(
                status="accepted",
                story_id=sid,
                mutation_id=mut,
                device_id=device,
                created=created,
                story=story,
                message=message,
            )
    finally:
        if own_conn and conn is not None:
            conn.close()
