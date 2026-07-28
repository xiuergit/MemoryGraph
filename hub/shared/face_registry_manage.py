"""人脸库管理：registry 属性、参考照列表与删除。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hub.shared.config import FACE_MATCH_THRESHOLD, FACES_DIR, SUPPORTED_EXTENSIONS
from hub.shared.face import build_face_index, iter_reference_images, save_face_index
from hub.shared.face_enroll import (
    _normalize_person_id,
    load_registry_data,
    save_registry_data,
)

logger = logging.getLogger(__name__)

_IMAGE_EXTS = SUPPORTED_EXTENSIONS


def _parse_match_threshold(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value > 1:
        raise ValueError(f"match_threshold 须在 (0, 1] 之间，收到: {raw!r}")
    return round(value, 4)


def _person_dir(person_id: str, faces_dir: Path) -> Path:
    return faces_dir / _normalize_person_id(person_id)


def _ref_item(person_id: str, path: Path, faces_dir: Path) -> dict[str, Any]:
    rel = str(path.relative_to(faces_dir / person_id))
    stat = path.stat()
    return {
        "file": rel,
        "name": path.name,
        "size_bytes": stat.st_size,
        "preview_path": str(path),
    }


def list_face_people(faces_dir: Path | None = None) -> list[dict[str, Any]]:
    """列出 registry 成员及参考照数量、识别阈值。"""
    root = faces_dir or FACES_DIR
    registry = load_registry_data(root / "registry.json")
    items: list[dict[str, Any]] = []

    seen: set[str] = set()
    for person_id in sorted(registry.keys()):
        raw = registry.get(person_id)
        if not isinstance(raw, dict):
            continue
        if str(raw.get("alias", "")).strip():
            continue
        pid = str(person_id)
        seen.add(pid)
        person_dir = root / pid
        refs = iter_reference_images(person_dir) if person_dir.is_dir() else []
        threshold = _parse_match_threshold(raw.get("match_threshold"))
        items.append(
            {
                "person_id": pid,
                "name": str(raw.get("name") or pid),
                "role": str(raw.get("role") or ""),
                "birth_date": str(raw.get("birth_date") or ""),
                "match_threshold": threshold,
                "effective_threshold": threshold if threshold is not None else FACE_MATCH_THRESHOLD,
                "ref_count": len(refs),
                "has_folder": person_dir.is_dir(),
            }
        )

    for person_dir in sorted(root.iterdir()) if root.is_dir() else []:
        if not person_dir.is_dir() or person_dir.name.startswith("."):
            continue
        pid = person_dir.name
        if pid in seen:
            continue
        refs = iter_reference_images(person_dir)
        if not refs:
            continue
        items.append(
            {
                "person_id": pid,
                "name": pid,
                "role": "",
                "birth_date": "",
                "match_threshold": None,
                "effective_threshold": FACE_MATCH_THRESHOLD,
                "ref_count": len(refs),
                "has_folder": True,
            }
        )

    items.sort(key=lambda x: (-x["ref_count"], x["person_id"]))
    return items


def get_face_person(person_id: str, faces_dir: Path | None = None) -> dict[str, Any]:
    root = faces_dir or FACES_DIR
    pid = _normalize_person_id(person_id)
    registry = load_registry_data(root / "registry.json")
    raw = registry.get(pid)
    if not isinstance(raw, dict):
        raw = {}

    person_dir = _person_dir(pid, root)
    refs = [ _ref_item(pid, p, root) for p in iter_reference_images(person_dir) ]
    threshold = _parse_match_threshold(raw.get("match_threshold"))

    return {
        "person_id": pid,
        "name": str(raw.get("name") or pid),
        "role": str(raw.get("role") or "other"),
        "birth_date": str(raw.get("birth_date") or ""),
        "match_threshold": threshold,
        "effective_threshold": threshold if threshold is not None else FACE_MATCH_THRESHOLD,
        "global_default_threshold": FACE_MATCH_THRESHOLD,
        "ref_count": len(refs),
        "refs": refs,
        "has_registry": pid in registry,
    }


def update_face_person(
    person_id: str,
    *,
    name: str | None = None,
    role: str | None = None,
    birth_date: str | None = None,
    match_threshold: Any = ...,  # type: ignore[assignment]
    faces_dir: Path | None = None,
    rebuild_index: bool = True,
) -> dict[str, Any]:
    root = faces_dir or FACES_DIR
    pid = _normalize_person_id(person_id)
    registry_path = root / "registry.json"
    data = load_registry_data(registry_path)
    entry = dict(data.get(pid)) if isinstance(data.get(pid), dict) else {}

    if name is not None:
        entry["name"] = name.strip() or pid
    if role is not None:
        entry["role"] = role.strip() or "other"
    if birth_date is not None:
        entry["birth_date"] = birth_date.strip()
    if match_threshold is not ...:
        if match_threshold is None or match_threshold == "":
            entry.pop("match_threshold", None)
        else:
            entry["match_threshold"] = _parse_match_threshold(match_threshold)

    entry.pop("alias", None)
    data[pid] = entry
    save_registry_data(data, registry_path)

    if rebuild_index:
        rebuild_face_index(root)

    return get_face_person(pid, root)


def delete_face_reference(
    person_id: str,
    file: str,
    *,
    faces_dir: Path | None = None,
    rebuild_index: bool = True,
) -> dict[str, Any]:
    root = faces_dir or FACES_DIR
    pid = _normalize_person_id(person_id)
    rel = file.strip().lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise ValueError("非法文件路径")

    target = (_person_dir(pid, root) / rel).resolve()
    person_root = _person_dir(pid, root).resolve()
    if not str(target).startswith(str(person_root) + "/") and target != person_root:
        raise ValueError("只能删除该成员目录下的参考照")
    if not target.is_file():
        raise FileNotFoundError(f"参考照不存在: {rel}")
    if target.suffix.lower() not in _IMAGE_EXTS:
        raise ValueError("仅支持删除图片参考照")

    target.unlink()
    logger.info("已删除参考照: %s/%s", pid, rel)

    if rebuild_index:
        rebuild_face_index(root)

    return get_face_person(pid, root)


def rebuild_face_index(faces_dir: Path | None = None) -> dict[str, Any]:
    root = faces_dir or FACES_DIR
    index = build_face_index(root)
    count = len(index.get("people", {}))
    if count == 0:
        raise RuntimeError("人脸库为空，无法重建 index.json")
    output = save_face_index(index, root)
    return {"people_count": count, "index_file": str(output)}
