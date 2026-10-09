"""视频批处理：遍历目录、抽帧分析、写入 video.v1 JSON。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from hub.shared.analyzer import analyze_video
from hub.shared.config import JSON_INDENT, MEMORY_DIR, PHOTOS_DIR
from hub.shared.family import enrich_people_with_age
from hub.shared.geocode import resolve_location_geocode
from hub.shared.schema import (
    AnalysisResult,
    RelatedId,
    VideoSource,
    analysis_from_dict,
    build_video_json,
    empty_analysis,
    empty_location_admin,
)
from hub.shared.utils import get_photo_id, media_path_matches_year
from hub.shared.video_meta import (
    find_live_photo_still,
    get_video_id,
    iter_video_files,
    probe_video,
)

logger = logging.getLogger(__name__)


@dataclass
class ProcessStats:
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    failed_files: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    written: list[str] = field(default_factory=list)


def _write_json(output_path: Path, data: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=JSON_INDENT)
        f.write("\n")


def _related_live_photo(video_path: Path, photos_root: Path) -> list[RelatedId]:
    still = find_live_photo_still(video_path)
    if still is None:
        return []
    photo_id = get_photo_id(still, root=photos_root)
    return [
        RelatedId(id=photo_id, media_type="photo", relation="live_photo"),
    ]


def _process_single_video(
    video_path: Path,
    memory_dir: Path,
    *,
    photos_root: Path,
    skip_existing: bool,
    device_id: str,
    run_ai: bool,
) -> str:
    video_id = get_video_id(video_path, root=photos_root)
    output_path = memory_dir / f"{video_id}.json"

    if output_path.exists() and skip_existing:
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
            if (
                data.get("manual_edit")
                or data.get("manual_people")
                or data.get("manual_vision")
                or data.get("manual_location")
            ):
                logger.info("跳过（手动编辑）: %s", video_id)
                return "skipped"
        except (json.JSONDecodeError, OSError):
            pass
        logger.info("跳过（已存在）: %s", video_id)
        return "skipped"

    probe = probe_video(video_path)
    timestamp = probe.timestamp
    location_coords = probe.location_coords
    location_admin = empty_location_admin()
    location = ""

    if run_ai:
        raw = analyze_video(
            str(video_path),
            timestamp=timestamp,
            video_id=video_id,
        )
        analysis = analysis_from_dict(raw)
    else:
        analysis = empty_analysis()

    if location_coords:
        geo = resolve_location_geocode(location_coords)
        location = geo.location
        location_admin = geo.location_admin
        analysis = AnalysisResult(
            people=analysis["people"],
            scene=analysis["scene"],
            location=location or analysis["location"],
            objects=analysis["objects"],
            actions=analysis["actions"],
            emotion=analysis["emotion"],
            tags=analysis["tags"],
            quality=analysis["quality"],
        )
    elif analysis["location"]:
        location = analysis["location"]

    analysis = AnalysisResult(
        people=enrich_people_with_age(analysis["people"], timestamp),
        scene=analysis["scene"],
        location=location or analysis["location"],
        objects=analysis["objects"],
        actions=analysis["actions"],
        emotion=analysis["emotion"],
        tags=analysis["tags"],
        quality=analysis["quality"],
    )

    source = VideoSource(
        path=str(video_path.resolve()),
        width=probe.width,
        height=probe.height,
        duration_s=probe.duration_s,
        fps=probe.fps,
        container=probe.container,
    )
    payload = build_video_json(
        video_id=video_id,
        timestamp=timestamp,
        source=source,
        analysis=analysis,
        device_id=device_id,
        location_coords=location_coords,
        location_admin=location_admin,
        related_ids=_related_live_photo(video_path, photos_root) or None,
    )

    if location_coords and timestamp:
        try:
            from hub.shared.weather import apply_weather_to_memory_dict

            apply_weather_to_memory_dict(payload, only_empty=True)
        except Exception as exc:
            logger.debug("写入天气跳过 %s: %s", video_id, exc)

    _write_json(output_path, payload)
    logger.info("已写入: %s", output_path.name)
    return "success"


def process_folder(
    input_dir: str | Path | None = None,
    memory_dir: str | Path | None = None,
    *,
    skip_existing: bool = True,
    device_id: str = "mac",
    run_ai: bool = True,
    limit: int | None = None,
    files: list[Path] | None = None,
    year: str = "",
    month: str = "",
    progress_cb: Callable[[dict[str, object]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ProcessStats:
    input_path = Path(input_dir or PHOTOS_DIR)
    memory_path = Path(memory_dir or MEMORY_DIR)
    photos_root = PHOTOS_DIR.resolve()
    year = year.strip()
    month = (month or "").strip()
    if "/" in month or "\\" in month or month in (".", ".."):
        month = ""
    if year and files is None:
        year_dir = photos_root / year
        if year_dir.is_dir():
            input_path = year_dir
        else:
            alt = photos_root / f"{year}年"
            if alt.is_dir():
                input_path = alt
        if month:
            month_dir = input_path / month
            if month_dir.is_dir():
                input_path = month_dir
            else:
                logger.warning("月/时段目录不存在: %s/%s", year, month)
    stats = ProcessStats()
    start = time.perf_counter()

    scope = f"{year}/{month}" if year and month else year
    logger.info(
        "开始处理视频: 输入=%s, 输出=%s, AI=%s%s",
        input_path.resolve() if files is None else "(指定文件)",
        memory_path.resolve(),
        run_ai,
        f", 范围={scope}" if scope else "",
    )

    if files is not None:
        video_files = []
        for f in files:
            p = Path(f).resolve()
            if not p.is_file():
                logger.error("不是文件: %s", p)
                stats.failed += 1
                stats.failed_files.append(str(p))
                continue
            video_files.append(p)
    else:
        try:
            video_files = iter_video_files(input_path)
        except NotADirectoryError as exc:
            logger.error("失败: %s", exc)
            stats.elapsed_seconds = time.perf_counter() - start
            return stats

    if not video_files:
        logger.warning("输入目录中未找到支持的视频文件")
        stats.elapsed_seconds = time.perf_counter() - start
        return stats

    if year:
        video_files = [
            f for f in video_files if media_path_matches_year(f, photos_root, year)
        ]
        if not video_files:
            logger.warning("该年份下未找到支持的视频文件")
            stats.elapsed_seconds = time.perf_counter() - start
            return stats

    memory_path.mkdir(parents=True, exist_ok=True)
    scan_total = len(video_files)
    if progress_cb:
        progress_cb(
            {
                "phase": "process",
                "total": scan_total,
                "current": 0,
                "message": f"共 {scan_total} 个视频待扫描",
            }
        )
    if limit is not None and limit >= 0:
        logger.info(
            "本次上限 %d 条（按成功写入计；已存在会跳过并继续往后找）",
            limit,
        )

    for idx, video_file in enumerate(video_files, start=1):
        if should_cancel and should_cancel():
            logger.info("任务已取消，停止于 %d/%d", idx - 1, scan_total)
            break
        if limit is not None and limit >= 0 and stats.success >= limit:
            logger.info(
                "已达本次上限 %d 条，停止。下次再跑即可续补。",
                limit,
            )
            break

        stats.total += 1
        try:
            rel = str(video_file.relative_to(photos_root))
        except ValueError:
            rel = str(video_file)
        try:
            logger.info("处理中: %s", rel)
            result = _process_single_video(
                video_file,
                memory_path,
                photos_root=photos_root,
                skip_existing=skip_existing,
                device_id=device_id,
                run_ai=run_ai,
            )
            if result == "success":
                stats.success += 1
                stats.written.append(get_video_id(video_file, root=photos_root))
                if limit is not None and limit >= 0:
                    logger.info(
                        "已写入（本次 %d/%d）: %s",
                        stats.success,
                        limit,
                        get_video_id(video_file, root=photos_root),
                    )
            else:
                stats.skipped += 1
        except Exception as exc:
            stats.failed += 1
            stats.failed_files.append(rel)
            logger.exception("失败: %s (%s)", rel, exc)
        if progress_cb:
            progress_cb(
                {
                    "phase": "process",
                    "current": idx,
                    "total": scan_total,
                    "current_file": rel,
                    "success": stats.success,
                    "skipped": stats.skipped,
                    "failed": stats.failed,
                    "message": f"已扫描 {idx}/{scan_total}",
                }
            )

    stats.elapsed_seconds = time.perf_counter() - start
    logger.info(
        "完成: scanned=%s success=%s skipped=%s failed=%s elapsed=%.1fs",
        stats.total,
        stats.success,
        stats.skipped,
        stats.failed,
        stats.elapsed_seconds,
    )
    return stats
