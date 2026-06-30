"""图片批处理流水线：遍历目录、调用分析器、写入 JSON。"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from photo2json.analyzer import analyze_image
from photo2json.config import JSON_INDENT
from photo2json.schema import analysis_from_dict, build_photo_json
from photo2json.utils import (
    build_source_info,
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
    failed: int = 0
    failed_files: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def _write_json(output_path: Path, data: dict) -> None:
    """将 dict 写入 JSON 文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=JSON_INDENT)
        f.write("\n")


def _process_single_image(image_path: Path, output_dir: Path) -> None:
    """处理单张图片：分析 + 组装 Schema + 写入 JSON。"""
    photo_id = get_photo_id(image_path)
    timestamp = extract_exif_timestamp(image_path)
    source = build_source_info(image_path)

    raw_analysis = analyze_image(str(image_path))
    analysis = analysis_from_dict(raw_analysis)

    photo_json = build_photo_json(
        photo_id=photo_id,
        timestamp=timestamp,
        source=source,
        analysis=analysis,
    )

    output_path = output_dir / f"{photo_id}.json"
    _write_json(output_path, dict(photo_json))


def process_folder(input_dir: str | Path, output_dir: str | Path) -> ProcessStats:
    """遍历输入目录中的图片，逐张分析并输出 JSON。

    单张图片失败不会中断整个流程。

    Args:
        input_dir: 图片所在目录。
        output_dir: JSON 输出目录。

    Returns:
        处理统计信息。
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    stats = ProcessStats()
    start = time.perf_counter()

    logger.info("开始处理: 输入=%s, 输出=%s", input_path.resolve(), output_path.resolve())

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

    output_path.mkdir(parents=True, exist_ok=True)

    for image_file in image_files:
        try:
            logger.info("处理中: %s", image_file.name)
            _process_single_image(image_file, output_path)
            stats.success += 1
            logger.info("完成: %s", image_file.name)
        except Exception as exc:
            stats.failed += 1
            stats.failed_files.append(image_file.name)
            logger.error("失败: %s — %s", image_file.name, exc)

    stats.elapsed_seconds = time.perf_counter() - start

    logger.info(
        "最终统计: 总数=%d, 成功=%d, 失败=%d, 耗时=%.2f秒",
        stats.total,
        stats.success,
        stats.failed,
        stats.elapsed_seconds,
    )

    if stats.failed_files:
        logger.info("失败文件: %s", ", ".join(stats.failed_files))

    return stats
