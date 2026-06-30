"""图片批处理流水线：遍历目录、调用分析器、写入 JSON。"""

from __future__ import annotations

import json
import logging
import time
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


def _process_single_image(
    image_path: Path,
    memory_dir: Path,
    *,
    input_root: Path,
    skip_existing: bool,
    device_id: str,
) -> str:
    """处理单张图片。返回 'success' | 'skipped'。"""
    photo_id = get_photo_id(image_path, root=input_root)
    output_path = memory_dir / f"{photo_id}.json"

    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if existing.get("manual_edit"):
                logger.info("跳过（手动编辑）: %s", photo_id)
                return "skipped"
        except (json.JSONDecodeError, OSError):
            pass

    if skip_existing and output_path.exists():
        return "skipped"

    timestamp = extract_exif_timestamp(image_path)
    source = build_source_info(image_path)

    raw_analysis = analyze_image(
        str(image_path),
        timestamp=timestamp,
        photo_id=photo_id,
    )
    analysis, location_coords = enrich_analysis_location(
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
    )

    _write_json(output_path, dict(photo_json))
    return "success"


def process_folder(
    input_dir: str | Path | None = None,
    memory_dir: str | Path | None = None,
    *,
    skip_existing: bool = True,
    device_id: str = "mac",
) -> ProcessStats:
    """遍历输入目录中的图片，逐张分析并输出 JSON 到 memory 目录。

    单张图片失败不会中断整个流程。

    Args:
        input_dir: 图片所在目录，默认 data/photos/。
        memory_dir: JSON 输出目录，默认 data/memory/。
        skip_existing: 若对应 JSON 已存在则跳过。
        device_id: 写入 JSON 的 device_id 字段。
    """
    input_path = Path(input_dir or PHOTOS_DIR)
    memory_path = Path(memory_dir or MEMORY_DIR)
    stats = ProcessStats()
    start = time.perf_counter()

    logger.info(
        "开始处理: 输入=%s, 输出=%s",
        input_path.resolve(),
        memory_path.resolve(),
    )

    try:
        image_files = iter_image_files(input_path)
    except NotADirectoryError as exc:
        logger.error("失败: %s", exc)
        stats.elapsed_seconds = time.perf_counter() - start
        return stats

    stats.total = len(image_files)

    if stats.total == 0:
        logger.warning("输入目录中未找到支持的图片文件")
        stats.elapsed_seconds = time.perf_counter() - start
        return stats

    memory_path.mkdir(parents=True, exist_ok=True)

    for image_file in image_files:
        rel = image_file.relative_to(input_path)
        try:
            logger.info("处理中: %s", rel)
            result = _process_single_image(
                image_file,
                memory_path,
                input_root=input_path,
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
