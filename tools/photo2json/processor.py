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
from hub.shared.schema import (
    AnalysisResult,
    analysis_from_dict,
    build_photo_json,
    bump_schema_for_user_note,
    refresh_manual_edit_flag,
)
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

# 重跑/合并分析时保留的手改真源字段
_PRESERVE_VISION_KEYS = ("scene", "objects", "actions", "emotion", "tags")


def _legacy_full_manual_lock(data: dict) -> bool:
    """旧版仅有 manual_edit、无分项锁 → 整文件跳过。"""
    if not data.get("manual_edit"):
        return False
    return not (
        data.get("manual_people")
        or data.get("manual_vision")
        or data.get("manual_location")
        or data.get("manual_note")
        or data.get("manual_transcript")
    )


def _vision_portion_empty(data: dict) -> bool:
    if str(data.get("scene") or "").strip():
        return False
    for key in ("objects", "actions", "emotion", "tags"):
        if data.get(key):
            return False
    return True


def _merge_preserve_hand_edits(payload: dict, existing: dict | None) -> dict:
    """把 AI 新结果与已有手改合并：旁白 / 分项锁字段不得冲掉。"""
    if not existing:
        return payload

    if existing.get("manual_note") or str(existing.get("user_note") or "").strip():
        payload["user_note"] = str(existing.get("user_note") or "")
        if existing.get("manual_note"):
            payload["manual_note"] = True

    if existing.get("manual_people"):
        payload["people"] = list(existing.get("people") or [])
        payload["manual_people"] = True

    if existing.get("manual_vision"):
        for key in _PRESERVE_VISION_KEYS:
            if key in existing:
                payload[key] = existing[key]
        payload["manual_vision"] = True

    if existing.get("manual_location"):
        payload["location"] = str(existing.get("location") or "")
        if "location_admin" in existing:
            payload["location_admin"] = existing["location_admin"]
        if "location_coords" in existing:
            payload["location_coords"] = existing["location_coords"]
        payload["manual_location"] = True

    if existing.get("manual_transcript") and isinstance(existing.get("transcript"), dict):
        payload["transcript"] = existing["transcript"]
        payload["manual_transcript"] = True

    if existing.get("related_ids"):
        payload["related_ids"] = existing["related_ids"]

    refresh_manual_edit_flag(payload)
    if payload.get("manual_note"):
        bump_schema_for_user_note(payload)
    return payload


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
    """处理单张图片。返回 'success' | 'skipped'。

    已有 JSON 时：
    - ingest stub / AI 仍空 → 分析后 **merge**，保留 user_note / manual_*；
    - skip_existing 且视觉+人物已齐 → 跳过；
    - 仅 manual_note 不阻止补 AI。
    """
    # photo_id 始终相对 data/photos/，与 --input 子目录无关（避免重复入库）
    photo_id = get_photo_id(image_path, root=photos_root)
    output_path = memory_dir / f"{photo_id}.json"
    existing = _existing_memory_json(memory_dir, image_path, photos_root)
    existing_data: dict | None = None

    if existing is not None:
        existing_id, existing_path = existing
        try:
            existing_data = json.loads(existing_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing_data = None

        if existing_data is not None:
            if _legacy_full_manual_lock(existing_data):
                logger.info("跳过（手动编辑）: %s", existing_id)
                return "skipped"

            if skip_existing:
                need_vision = (not existing_data.get("manual_vision")) and _vision_portion_empty(
                    existing_data
                )
                need_people = (not existing_data.get("manual_people")) and not (
                    existing_data.get("people") or []
                )
                if not need_vision and not need_people:
                    if existing_id != photo_id:
                        logger.info(
                            "跳过（已有旧 photo_id JSON）: %s → 规范应为 %s",
                            existing_id,
                            photo_id,
                        )
                    return "skipped"
                logger.info(
                    "合并分析（保留手改）: %s need_vision=%s need_people=%s",
                    existing_id,
                    need_vision,
                    need_people,
                )

    timestamp = extract_exif_timestamp(image_path)
    if existing_data and str(existing_data.get("timestamp") or "").strip():
        # stub/手补时间优先，避免 EXIF 空覆盖
        timestamp = str(existing_data.get("timestamp") or timestamp)
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

    # 已有 stub 的 device_id 优先
    use_device = device_id
    if existing_data and str(existing_data.get("device_id") or "").strip():
        use_device = str(existing_data.get("device_id") or device_id)

    if existing_data and existing_data.get("manual_location"):
        location_coords = str(existing_data.get("location_coords") or location_coords)
        # location_admin 在 merge 里保留

    photo_json = build_photo_json(
        photo_id=photo_id,
        timestamp=timestamp,
        source=source,
        analysis=analysis,
        device_id=use_device,
        location_coords=location_coords,
        location_admin=location_admin,
    )
    payload = dict(photo_json)
    if location_coords and timestamp and not (
        existing_data and existing_data.get("manual_location")
    ):
        try:
            from hub.shared.weather import apply_weather_to_memory_dict

            apply_weather_to_memory_dict(payload, only_empty=True)
        except Exception as exc:
            logger.debug("写入天气跳过 %s: %s", photo_id, exc)

    if existing_data and existing_data.get("weather") and "weather" not in payload:
        payload["weather"] = existing_data["weather"]

    payload = _merge_preserve_hand_edits(payload, existing_data)
    _write_json(output_path, payload)
    return "success"


def process_one_image(
    image_path: str | Path,
    memory_dir: str | Path | None = None,
    *,
    photos_root: Path | None = None,
    skip_existing: bool = True,
    device_id: str = "mac",
) -> str:
    """处理单张图片。返回 'success' | 'skipped'；失败抛异常。

    供 media.ingest 异步排队调用；photo_id 相对 data/photos/。
    """
    path = Path(image_path)
    memory_path = Path(memory_dir or MEMORY_DIR)
    root = Path(photos_root or PHOTOS_DIR).resolve()
    return _process_single_image(
        path,
        memory_path,
        photos_root=root,
        skip_existing=skip_existing,
        device_id=device_id,
    )


def process_folder(
    input_dir: str | Path | None = None,
    memory_dir: str | Path | None = None,
    *,
    skip_existing: bool = True,
    device_id: str = "mac",
    year: str = "",
    limit: int | None = None,
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
        limit: 本次最多成功写入 N 张（已存在会跳过并继续往后找）。
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

    if not image_files:
        logger.warning("输入目录中未找到支持的图片文件")
        stats.elapsed_seconds = time.perf_counter() - start
        return stats

    scan_total = len(image_files)
    memory_path.mkdir(parents=True, exist_ok=True)

    if progress_cb:
        progress_cb(
            {
                "phase": "process",
                "total": scan_total,
                "current": 0,
                "message": f"目录共 {scan_total} 张，开始扫描",
            }
        )
    if limit is not None and limit >= 0:
        logger.info(
            "本次上限 %d 张（按成功写入计；已存在会跳过并继续往后找）",
            limit,
        )

    for idx, image_file in enumerate(image_files, start=1):
        if should_cancel and should_cancel():
            logger.info("任务已取消，停止于 %d/%d", idx - 1, scan_total)
            break
        if limit is not None and limit >= 0 and stats.success >= limit:
            logger.info(
                "已达本次上限 %d 张，停止。下次再跑即可续补。",
                limit,
            )
            break

        stats.total += 1
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
                if limit is not None and limit >= 0:
                    logger.info(
                        "已写入（本次 %d/%d）: %s",
                        stats.success,
                        limit,
                        rel,
                    )
        except Exception as exc:
            stats.failed += 1
            stats.failed_files.append(str(rel))
            logger.error("失败: %s — %s", rel, exc)
        if progress_cb:
            progress_cb(
                {
                    "phase": "process",
                    "current": idx,
                    "total": scan_total,
                    "current_file": str(rel),
                    "success": stats.success,
                    "skipped": stats.skipped,
                    "failed": stats.failed,
                    "message": f"已扫描 {idx}/{scan_total}",
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
