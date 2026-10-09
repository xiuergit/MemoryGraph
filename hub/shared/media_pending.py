"""统计尚未生成 memory JSON 的照片/视频（维护工具 pending 概览）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hub.shared.config import MEMORY_DIR, PHOTOS_DIR
from hub.shared.utils import get_photo_id, iter_image_files, media_path_matches_year
from hub.shared.video_meta import get_video_id, iter_video_files

_YEAR_DIR_RE = re.compile(r"^(\d{4})年?$")


def _photo_id_candidates(image_path: Path, photos_root: Path) -> list[str]:
    canonical = get_photo_id(image_path, root=photos_root)
    ids = [canonical]
    try:
        rel = image_path.resolve().relative_to(photos_root.resolve())
    except ValueError:
        return ids
    for i in range(1, len(rel.parts)):
        sub_root = photos_root.joinpath(*rel.parts[:i])
        legacy = get_photo_id(image_path, root=sub_root)
        if legacy not in ids:
            ids.append(legacy)
    return ids


def _photo_has_json(memory_dir: Path, image_path: Path, photos_root: Path) -> bool:
    for pid in _photo_id_candidates(image_path, photos_root):
        if (memory_dir / f"{pid}.json").is_file():
            return True
    return False


def _video_has_json(memory_dir: Path, video_path: Path, photos_root: Path) -> bool:
    video_id = get_video_id(video_path, root=photos_root)
    return (memory_dir / f"{video_id}.json").is_file()


def _resolve_year_dir(photos_root: Path, year: str) -> Path | None:
    year = year.strip()
    if not year:
        return photos_root if photos_root.is_dir() else None
    year_dir = photos_root / year
    if year_dir.is_dir():
        return year_dir
    alt = photos_root / f"{year}年"
    if alt.is_dir():
        return alt
    return None


def list_available_years(photos_dir: Path | None = None) -> list[str]:
    """从 data/photos/ 子目录名推断可选年份（降序）。"""
    root = Path(photos_dir or PHOTOS_DIR)
    if not root.is_dir():
        return []
    years: set[str] = set()
    for child in root.iterdir():
        if not child.is_dir():
            continue
        m = _YEAR_DIR_RE.match(child.name)
        if m:
            years.add(m.group(1))
    return sorted(years, reverse=True)


def _safe_subdir_name(name: str) -> str | None:
    """拒绝路径穿越；只允许单层目录名。"""
    name = (name or "").strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return None
    return name


def _resolve_scan_dir(
    photos_root: Path, year: str, month: str = ""
) -> Path | None:
    """解析扫描根：年份目录，或年份下的月/时段子目录。"""
    base = _resolve_year_dir(photos_root, year)
    if base is None:
        return None
    safe = _safe_subdir_name(month)
    if not safe:
        return base
    month_dir = base / safe
    return month_dir if month_dir.is_dir() else None


def list_available_months(
    year: str, photos_dir: Path | None = None
) -> list[str]:
    """列出 data/photos/<year>/ 下的子目录（月或时段文件夹，如 07、5-8）。"""
    root = Path(photos_dir or PHOTOS_DIR)
    year_dir = _resolve_year_dir(root, year.strip())
    if year_dir is None:
        return []
    months: list[str] = []
    for child in year_dir.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        months.append(child.name)

    def sort_key(name: str) -> tuple[int, int, str]:
        m = re.match(r"^(\d+)", name)
        if m:
            return (0, int(m.group(1)), name)
        return (1, 0, name)

    return sorted(months, key=sort_key)


@dataclass
class MediaKindPending:
    total_files: int = 0
    with_json: int = 0
    pending: int = 0


def count_pending_photos(
    *,
    year: str = "",
    month: str = "",
    memory_dir: Path | None = None,
    photos_dir: Path | None = None,
) -> MediaKindPending:
    memory_path = Path(memory_dir or MEMORY_DIR)
    photos_root = Path(photos_dir or PHOTOS_DIR).resolve()
    scan_root = _resolve_scan_dir(photos_root, year, month)
    result = MediaKindPending()
    if scan_root is None:
        return result

    try:
        image_files = iter_image_files(scan_root)
    except NotADirectoryError:
        return result

    year = year.strip()
    if year:
        image_files = [
            f for f in image_files if media_path_matches_year(f, photos_root, year)
        ]

    result.total_files = len(image_files)
    for image_file in image_files:
        if _photo_has_json(memory_path, image_file, photos_root):
            result.with_json += 1
        else:
            result.pending += 1
    return result


def count_pending_videos(
    *,
    year: str = "",
    month: str = "",
    memory_dir: Path | None = None,
    photos_dir: Path | None = None,
) -> MediaKindPending:
    memory_path = Path(memory_dir or MEMORY_DIR)
    photos_root = Path(photos_dir or PHOTOS_DIR).resolve()
    scan_root = _resolve_scan_dir(photos_root, year, month)
    result = MediaKindPending()
    if scan_root is None:
        return result

    try:
        video_files = iter_video_files(scan_root)
    except NotADirectoryError:
        return result

    year = year.strip()
    if year:
        video_files = [
            f for f in video_files if media_path_matches_year(f, photos_root, year)
        ]

    result.total_files = len(video_files)
    for video_file in video_files:
        if _video_has_json(memory_path, video_file, photos_root):
            result.with_json += 1
        else:
            result.pending += 1
    return result


def media_pending_report(
    *,
    year: str = "",
    month: str = "",
    memory_dir: Path | None = None,
    photos_dir: Path | None = None,
) -> dict[str, object]:
    year = year.strip()
    month = (month or "").strip()
    # 照片仍按整年统计；month 只收窄视频待入库（维护工具视频可选到月文件夹）
    photos = count_pending_photos(
        year=year, memory_dir=memory_dir, photos_dir=photos_dir
    )
    videos = count_pending_videos(
        year=year, month=month, memory_dir=memory_dir, photos_dir=photos_dir
    )
    return {
        "year": year,
        "month": month,
        "photos": {
            "total_files": photos.total_files,
            "with_json": photos.with_json,
            "pending": photos.pending,
        },
        "videos": {
            "total_files": videos.total_files,
            "with_json": videos.with_json,
            "pending": videos.pending,
        },
        "available_years": list_available_years(photos_dir),
        "available_months": list_available_months(year, photos_dir) if year else [],
    }
