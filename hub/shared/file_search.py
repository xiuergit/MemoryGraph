"""按文件名在 MemoryGraph 数据目录中搜索。"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from hub.shared.config import DATA_DIR, FACES_DIR, MEMORY_DIR, PHOTOS_DIR


@dataclass(frozen=True)
class FileSearchHit:
    path: Path
    root_label: str


def _match_name(name: str, query: str, *, exact: bool) -> bool:
    q = query.strip()
    if not q:
        return False
    if exact:
        return name == q or Path(name).stem == Path(q).stem
    lower = q.lower()
    return lower in name.lower() or fnmatch.fnmatch(name.lower(), f"*{lower}*")


def search_files(
    query: str,
    *,
    roots: list[tuple[str, Path]] | None = None,
    exact: bool = False,
    limit: int = 50,
) -> list[FileSearchHit]:
    """在指定根目录下递归搜索文件名（不含内容）。"""
    if not query.strip():
        return []

    search_roots = roots or [
        ("photos", PHOTOS_DIR),
        ("memory", MEMORY_DIR),
        ("faces", FACES_DIR),
    ]

    hits: list[FileSearchHit] = []
    for label, root in search_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            if not _match_name(path.name, query, exact=exact):
                continue
            hits.append(FileSearchHit(path=path.resolve(), root_label=label))
            if len(hits) >= limit:
                return hits

    order = {label: i for i, (label, _) in enumerate(search_roots)}
    hits.sort(key=lambda h: (order.get(h.root_label, 99), str(h.path)))
    return hits


def memory_json_for_photo(photo_path: Path) -> Path | None:
    """根据原图路径推断 memory JSON（photo_id 规则）。"""
    stem = photo_path.stem
    parent = photo_path.parent
    parts: list[str] = []
    cursor = parent
    while cursor != cursor.parent:
        parts.insert(0, cursor.name)
        if cursor == PHOTOS_DIR:
            break
        cursor = cursor.parent
    if parts and parts[0] == PHOTOS_DIR.name:
        parts = parts[1:]
    photo_id = "_".join(parts + [stem]) if parts else stem
    candidate = MEMORY_DIR / f"{photo_id}.json"
    if candidate.is_file():
        return candidate.resolve()
    return None


def format_path_link(path: Path, *, label: str | None = None) -> str:
    text = label or path.name
    return f"[{text}]({path.as_uri()})"
