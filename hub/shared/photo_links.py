"""照片 photo_id → 原图路径，输出 Markdown 可点击链接。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hub.shared.config import MEMORY_DIR, PHOTOS_DIR


def resolve_photo_path(
    photo_id: str = "",
    *,
    source_path: str = "",
) -> Path | None:
    """解析原图绝对路径；优先 source_path，其次 memory JSON。"""
    if source_path:
        path = Path(source_path).expanduser()
        if path.is_file():
            return path.resolve()

    pid = (photo_id or "").strip()
    if not pid:
        return None

    json_path = MEMORY_DIR / f"{pid}.json"
    if json_path.is_file():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        src = str((data.get("source") or {}).get("path", "")).strip()
        if src:
            path = Path(src).expanduser()
            if path.is_file():
                return path.resolve()

    if not PHOTOS_DIR.is_dir():
        return None
    for candidate in PHOTOS_DIR.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.stem == pid or pid.endswith(f"_{candidate.stem}"):
            return candidate.resolve()
    return None


def format_photo_link(photo: dict[str, Any], *, enabled: bool = True) -> str:
    """Markdown 链接：[photo_id](file:///...)；无路径则退回 photo_id。"""
    pid = str(photo.get("photo_id") or "").strip()
    if not pid:
        return "—"
    if not enabled:
        return pid

    path = resolve_photo_path(pid, source_path=str(photo.get("source_path") or ""))
    if path is None:
        return pid
    return f"[{pid}]({path.as_uri()})"


def enrich_photo_dict(photo: dict[str, Any]) -> dict[str, Any]:
    """确保 photo 字典含 source_path（若可解析）。"""
    if photo.get("source_path"):
        return photo
    path = resolve_photo_path(
        str(photo.get("photo_id") or ""),
        source_path=str(photo.get("source_path") or ""),
    )
    if path is None:
        return photo
    out = dict(photo)
    out["source_path"] = str(path)
    return out
