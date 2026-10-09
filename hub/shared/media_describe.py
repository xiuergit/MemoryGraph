"""手机 Outbox media.describe：按 photo_id 写 user_note（幂等 mutation_id）。

合同：docs/mobile-outbox.md §3 / §6；实施计划阶段 B。
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from hub.shared.config import DESCRIBE_REGISTRY_FILE, MEMORY_DIR
from hub.shared.memory_edit import MemoryEditError, apply_user_note

logger = logging.getLogger(__name__)

_REGISTRY_LOCK = threading.Lock()
# 旁白软上限（开放问题；防异常超大载荷）
USER_NOTE_MAX_CHARS = 8000


@dataclass
class DescribeReceipt:
    """media.describe 回执。"""

    status: str  # accepted | conflict
    photo_id: str
    user_note: str = ""
    manual_note: bool = True
    mutation_id: str = ""
    device_id: str = ""
    schema_version: str = ""
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class DescribeError(ValueError):
    """请求不合法（由 Desk 映射为 400）。"""


def _empty_registry() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "by_mutation_id": {},
    }


def _load_registry(path: Path | None = None) -> dict[str, Any]:
    reg_path = Path(path or DESCRIBE_REGISTRY_FILE)
    if not reg_path.is_file():
        return _empty_registry()
    try:
        data = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("describe registry 损坏，重建空表: %s", exc)
        return _empty_registry()
    if not isinstance(data, dict):
        return _empty_registry()
    data.setdefault("schema_version", 1)
    data.setdefault("by_mutation_id", {})
    return data


def _save_registry(data: dict[str, Any], path: Path | None = None) -> None:
    reg_path = Path(path or DESCRIBE_REGISTRY_FILE)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = reg_path.with_suffix(reg_path.suffix + ".tmp")
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(reg_path)


def _note_digest(photo_id: str, user_note: str) -> str:
    raw = f"{photo_id}\n{user_note}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _read_note_snapshot(
    photo_id: str,
    *,
    memory_dir: Path | None = None,
) -> tuple[str, str, bool]:
    path = Path(memory_dir or MEMORY_DIR) / f"{photo_id}.json"
    if not path.is_file():
        raise DescribeError(f"未找到 memory JSON: {photo_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DescribeError(f"无法读取 JSON: {photo_id}") from exc
    return (
        str(data.get("user_note") or ""),
        str(data.get("schema_version") or ""),
        bool(data.get("manual_note")),
    )


def describe_media(
    photo_id: str,
    user_note: str,
    *,
    mutation_id: str = "",
    device_id: str = "",
    memory_dir: Path | None = None,
    db_path: Path | None = None,
    registry_path: Path | None = None,
) -> DescribeReceipt:
    """写/改旁白。同 mutation_id + 同载荷 → accepted 重放；载荷不同 → conflict。"""
    pid = (photo_id or "").strip()
    if not pid:
        raise DescribeError("photo_id 不能为空")

    note = str(user_note if user_note is not None else "")
    if len(note) > USER_NOTE_MAX_CHARS:
        raise DescribeError(f"user_note 超过软上限 {USER_NOTE_MAX_CHARS} 字")

    mut = (mutation_id or "").strip()
    device = (device_id or "").strip()
    digest = _note_digest(pid, note)
    reg_file = Path(registry_path or DESCRIBE_REGISTRY_FILE)

    with _REGISTRY_LOCK:
        registry = _load_registry(reg_file)

        if mut:
            prev = registry["by_mutation_id"].get(mut)
            if isinstance(prev, dict) and prev:
                prev_digest = str(prev.get("content_digest") or "")
                prev_pid = str(prev.get("photo_id") or "")
                if prev_digest == digest and prev_pid == pid:
                    cur_note, schema_ver, manual = _read_note_snapshot(
                        pid, memory_dir=memory_dir
                    )
                    return DescribeReceipt(
                        status="accepted",
                        photo_id=pid,
                        user_note=cur_note,
                        manual_note=manual or True,
                        mutation_id=mut,
                        device_id=str(prev.get("device_id") or device),
                        schema_version=schema_ver,
                        message="mutation_id 幂等重放",
                    )
                return DescribeReceipt(
                    status="conflict",
                    photo_id=prev_pid or pid,
                    user_note=str(prev.get("user_note") or ""),
                    manual_note=True,
                    mutation_id=mut,
                    device_id=str(prev.get("device_id") or ""),
                    schema_version="",
                    message="同一 mutation_id 已绑定不同 photo_id/旁白",
                )

        try:
            apply_user_note(
                pid,
                note,
                memory_dir=memory_dir,
                db_path=db_path,
            )
        except MemoryEditError as exc:
            raise DescribeError(str(exc)) from exc

        cur_note, schema_ver, manual = _read_note_snapshot(pid, memory_dir=memory_dir)

        if mut:
            registry["by_mutation_id"][mut] = {
                "photo_id": pid,
                "user_note": note,
                "content_digest": digest,
                "device_id": device,
                "status": "accepted",
            }
            _save_registry(registry, reg_file)

        return DescribeReceipt(
            status="accepted",
            photo_id=pid,
            user_note=cur_note,
            manual_note=manual,
            mutation_id=mut,
            device_id=device,
            schema_version=schema_ver,
            message="已写入旁白",
        )
