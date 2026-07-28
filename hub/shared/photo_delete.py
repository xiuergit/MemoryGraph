"""删除照片：原图 + memory JSON 移入 data/.trash/，并更新 SQLite 索引。"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from hub.shared.config import DATA_DIR, FACES_DIR, MEMORY_DB, MEMORY_DIR, PHOTOS_DIR
from hub.shared.file_search import memory_json_for_photo
from hub.shared.index_db import connect, init_db
from hub.shared.photo_links import resolve_photo_path

logger = logging.getLogger(__name__)

TRASH_DIR = DATA_DIR / ".trash"


class PhotoDeleteError(ValueError):
    """删除被拒绝或失败。"""


@dataclass
class DeletePhotoResult:
    photo_id: str
    photo_trashed: str | None = None
    memory_trashed: str | None = None
    index_removed: bool = False


@dataclass
class BatchDeleteResult:
    deleted: list[DeletePhotoResult] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _under_dir(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _reject_faces(path: Path) -> None:
    if _under_dir(path, FACES_DIR):
        raise PhotoDeleteError("人脸参考照不能在这里删除，请用 face_enroll 管理")


def _trash_file(path: Path) -> Path:
    if not path.is_file():
        raise PhotoDeleteError(f"文件不存在: {path}")
    _reject_faces(path)

    if _under_dir(path, PHOTOS_DIR):
        bucket = TRASH_DIR / "photos"
    elif _under_dir(path, MEMORY_DIR):
        bucket = TRASH_DIR / "memory"
    else:
        raise PhotoDeleteError(f"只能删除 photos/ 或 memory/ 下的文件: {path}")

    bucket.mkdir(parents=True, exist_ok=True)
    dest = bucket / path.name
    if dest.exists():
        dest = bucket / f"{int(time.time())}_{path.name}"
    shutil.move(str(path), str(dest))
    logger.info("已移入回收站: %s -> %s", path, dest)
    return dest


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PhotoDeleteError(f"无法读取 JSON: {path}") from exc


def _resolve_targets(
    *,
    photo_id: str = "",
    photo_path: Path | None = None,
    memory_path: Path | None = None,
) -> tuple[str, Path | None, Path | None]:
    pid = photo_id.strip()
    photo: Path | None = photo_path.resolve() if photo_path else None
    memory: Path | None = memory_path.resolve() if memory_path else None

    if memory and memory.is_file():
        _reject_faces(memory)
        data = _load_json(memory)
        pid = str(data.get("photo_id") or memory.stem)
        if photo is None:
            src = str((data.get("source") or {}).get("path", "")).strip()
            if src:
                candidate = Path(src).expanduser()
                if candidate.is_file():
                    photo = candidate.resolve()

    if photo and photo.is_file():
        _reject_faces(photo)
        if not pid:
            linked = memory_json_for_photo(photo)
            if linked and linked.is_file():
                memory = linked
                data = _load_json(linked)
                pid = str(data.get("photo_id") or linked.stem)
            else:
                pid = photo.stem

    if pid and memory is None:
        candidate = MEMORY_DIR / f"{pid}.json"
        if candidate.is_file():
            memory = candidate

    if pid and photo is None:
        resolved = resolve_photo_path(pid)
        if resolved and resolved.is_file():
            photo = resolved

    if not pid:
        raise PhotoDeleteError("无法确定 photo_id")

    return pid, photo, memory


def delete_photo_record(
    *,
    photo_id: str = "",
    photo_path: str | Path = "",
    memory_path: str | Path = "",
    db_path: Path | None = None,
) -> DeletePhotoResult:
    """移入 data/.trash/ 并清理索引。至少提供 photo_id、原图路径或 JSON 路径之一。"""
    p_path = Path(photo_path).expanduser() if photo_path else None
    m_path = Path(memory_path).expanduser() if memory_path else None
    pid, photo, memory = _resolve_targets(
        photo_id=photo_id,
        photo_path=p_path,
        memory_path=m_path,
    )

    result = DeletePhotoResult(photo_id=pid)

    if memory and memory.is_file():
        trashed = _trash_file(memory)
        result.memory_trashed = str(trashed)

    if photo and photo.is_file():
        trashed = _trash_file(photo)
        result.photo_trashed = str(trashed)

    if not result.photo_trashed and not result.memory_trashed:
        raise PhotoDeleteError(f"没有找到可删除的文件（photo_id={pid}）")

    db = db_path or MEMORY_DB
    conn = connect(db)
    init_db(conn)
    cur = conn.execute("DELETE FROM photos WHERE photo_id = ?", (pid,))
    conn.commit()
    conn.close()
    result.index_removed = cur.rowcount > 0
    return result


def batch_delete_photo_records(
    photo_ids: list[str],
    *,
    db_path: Path | None = None,
) -> BatchDeleteResult:
    """批量删除；单条失败不中断，汇总 deleted / failed。"""
    result = BatchDeleteResult()
    seen: set[str] = set()
    for raw in photo_ids:
        pid = raw.strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        try:
            result.deleted.append(
                delete_photo_record(photo_id=pid, db_path=db_path)
            )
        except PhotoDeleteError as exc:
            result.failed.append((pid, str(exc)))
            logger.warning("批量删除失败 %s: %s", pid, exc)
    return result
