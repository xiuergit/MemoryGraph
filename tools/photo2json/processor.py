"""图片批处理流水线：遍历目录、调用分析器、写入 JSON。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from hub.shared.analyzer import analyze_image
from hub.shared.config import JSON_INDENT, MEMORY_DIR, PHOTOS_DIR
from hub.shared.location_cluster import apply_location_normalization
from hub.shared.schema import AnalysisResult, analysis_from_dict, build_photo_json
from hub.shared.family import enrich_people_with_age
from hub.shared.utils import (
    build_source_info,
    enrich_analysis_location,
    extract_exif_timestamp,
    get_photo_id,
    iter_image_files,
    media_path_matches_year,
)

logger = logging.getLogger(__name__)


@dataclass
class ProcessStats:
    """批处理统计信息。"""

    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    failed_files: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def _write_json(output_path: Path, data: dict) -> None:
    """将 dict 写入 JSON 文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=JSON_INDENT)
        f.write("\n")


def _photo_id_candidates(image_path: Path, photos_root: Path) -> list[str]:
    """photo_id 候选：规范 id（相对 data/photos）+ 历史误用子目录作 root 时的短 id。

    例如 photos/2026/1-3/IMG_1.jpeg：
      规范：2026_1-3_IMG_1
      旧短：1-3_IMG_1（曾用 --input data/photos/2026）
    写入始终用规范 id；跳过时任一候选 JSON 存在即可。
    """
    canonical = get_photo_id(image_path, root=photos_root)
    ids = [canonical]
    try:
        rel = image_path.resolve().relative_to(photos_root.resolve())
    except ValueError:
        return ids
    # 逐年 / 更深子目录曾被当作 input root → 去掉前若干段后的短 id
    for i in range(1, len(rel.parts)):
        sub_root = photos_root.joinpath(*rel.parts[:i])
        legacy = get_photo_id(image_path, root=sub_root)
        if legacy not in ids:
            ids.append(legacy)
    return ids


def _existing_memory_json(
    memory_dir: Path, image_path: Path, photos_root: Path
) -> tuple[str, Path] | None:
    """若已有对应 JSON，返回 (photo_id, path)；优先规范 id。"""
    for pid in _photo_id_candidates(image_path, photos_root):
        path = memory_dir / f"{pid}.json"
        if path.exists():
            return pid, path
    return None


def _process_single_image(
    image_path: Path,
    memory_dir: Path,
    *,
    photos_root: Path,
    skip_existing: bool,
    device_id: str,
) -> str:
    """处理单张图片。返回 'success' | 'skipped'。"""
    # photo_id 始终相对 data/photos/，与 --input 子目录无关（避免重复入库）
    photo_id = get_photo_id(image_path, root=photos_root)
    output_path = memory_dir / f"{photo_id}.json"
    existing = _existing_memory_json(memory_dir, image_path, photos_root)

    if existing is not None:
        existing_id, existing_path = existing
        try:
            data = json.loads(existing_path.read_text(encoding="utf-8"))
            if (
                data.get("manual_edit")
                or data.get("manual_people")
                or data.get("manual_vision")
                or data.get("manual_location")
            ):
                logger.info("跳过（手动编辑）: %s", existing_id)
                return "skipped"
        except (json.JSONDecodeError, OSError):
            pass
        if skip_existing:
            if existing_id != photo_id:
                logger.info(
                    "跳过（已有旧 photo_id JSON）: %s → 规范应为 %s",
                    existing_id,
                    photo_id,
                )
            return "skipped"

    timestamp = extract_exif_timestamp(image_path)
    source = build_source_info(image_path)

    raw_analysis = analyze_image(
        str(image_path),
        timestamp=timestamp,
        photo_id=photo_id,
    )
    analysis, location_coords, location_admin = enrich_analysis_location(
        analysis_from_dict(raw_analysis),
        image_path,
    )
    analysis = AnalysisResult(
        people=enrich_people_with_age(analysis["people"], timestamp),
        scene=analysis["scene"],
        location=analysis["location"],
        objects=analysis["objects"],
        actions=analysis["actions"],
        emotion=analysis["emotion"],
        tags=analysis["tags"],
        quality=analysis["quality"],
    )

    photo_json = build_photo_json(
        photo_id=photo_id,
        timestamp=timestamp,
        source=source,
        analysis=analysis,
        device_id=device_id,
        location_coords=location_coords,
        location_admin=location_admin,
    )
    payload = dict(photo_json)
    if location_coords and timestamp:
        try:
            from hub.shared.weather import apply_weather_to_memory_dict

            apply_weather_to_memory_dict(payload, only_empty=True)
        except Exception as exc:
            logger.debug("写入天气跳过 %s: %s", photo_id, exc)

    _write_json(output_path, payload)
    return "success"


def process_folder(
    input_dir: str | Path | None = None,
    memory_dir: str | Path | None = None,
    *,
    skip_existing: bool = True,
    device_id: str = "mac",
    year: str = "",
    progress_cb: Callable[[dict[str, object]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ProcessStats:
    """遍历输入目录中的图片，逐张分析并输出 JSON 到 memory 目录。

    单张图片失败不会中断整个流程。

    Args:
        input_dir: 图片所在目录，默认 data/photos/。
        memory_dir: JSON 输出目录，默认 data/memory/。
        skip_existing: 若对应 JSON 已存在则跳过。
        device_id: 写入 JSON 的 device_id 字段。
        year: 只处理某年路径下的图片，如 2026。
    """
    input_path = Path(input_dir or PHOTOS_DIR)
    memory_path = Path(memory_dir or MEMORY_DIR)
    # --input 只缩小扫描范围；photo_id 一律相对 PHOTOS_DIR
    photos_root = PHOTOS_DIR.resolve()
    year = year.strip()
    if year:
        year_dir = photos_root / year
        if year_dir.is_dir():
            input_path = year_dir
        else:
            alt = photos_root / f"{year}年"
            if alt.is_dir():
                input_path = alt
    stats = ProcessStats()
    start = time.perf_counter()

    logger.info(
        "开始处理: 输入=%s, 输出=%s, photo_id根=%s%s",
        input_path.resolve(),
        memory_path.resolve(),
        photos_root,
        f", 年份={year}" if year else "",
    )

    try:
        image_files = iter_image_files(input_path)
    except NotADirectoryError as exc:
        logger.error("失败: %s", exc)
        stats.elapsed_seconds = time.perf_counter() - start
        return stats

    if year:
        image_files = [
            f for f in image_files if media_path_matches_year(f, photos_root, year)
        ]

    stats.total = len(image_files)

    if stats.total == 0:
        logger.warning("输入目录中未找到支持的图片文件")
        stats.elapsed_seconds = time.perf_counter() - start
        return stats

    memory_path.mkdir(parents=True, exist_ok=True)

    if progress_cb:
        progress_cb(
            {
                "phase": "process",
                "total": stats.total,
                "current": 0,
                "message": f"共 {stats.total} 张待扫描",
            }
        )

    for idx, image_file in enumerate(image_files, start=1):
        if should_cancel and should_cancel():
            logger.info("任务已取消，停止于 %d/%d", idx - 1, stats.total)
            break
        rel = image_file.relative_to(input_path)
        try:
            logger.info("处理中: %s", rel)
            result = _process_single_image(
                image_file,
                memory_path,
                photos_root=photos_root,
                skip_existing=skip_existing,
                device_id=device_id,
            )
            if result == "skipped":
                stats.skipped += 1
                logger.info("跳过（已存在 JSON）: %s", rel)
            else:
                stats.success += 1
                logger.info("完成: %s", rel)
        except Exception as exc:
            stats.failed += 1
            stats.failed_files.append(str(rel))
            logger.error("失败: %s — %s", rel, exc)
        if progress_cb:
            progress_cb(
                {
                    "phase": "process",
                    "current": idx,
                    "total": stats.total,
                    "current_file": str(rel),
                    "success": stats.success,
                    "skipped": stats.skipped,
                    "failed": stats.failed,
                    "message": f"已扫描 {idx}/{stats.total}",
                }
            )

    stats.elapsed_seconds = time.perf_counter() - start

    logger.info(
        "最终统计: 总数=%d, 成功=%d, 跳过=%d, 失败=%d, 耗时=%.2f秒",
        stats.total,
        stats.success,
        stats.skipped,
        stats.failed,
        stats.elapsed_seconds,
    )

    if stats.failed_files:
        logger.info("失败文件: %s", ", ".join(stats.failed_files))

    apply_location_normalization(memory_path)

    return stats
