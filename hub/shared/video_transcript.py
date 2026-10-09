"""视频 JSON 的 ASR 字幕 backfill（写入 transcript，不重跑视觉）。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from hub.shared.asr import asr_available, transcribe_audio
from hub.shared.config import ASR_MIN_DURATION_S, JSON_INDENT, MEMORY_DIR, PHOTOS_DIR
from hub.shared.photo_links import resolve_photo_path
from hub.shared.schema import is_manual_transcript, make_transcript, refresh_manual_edit_flag
from hub.shared.utils import media_path_matches_year

logger = logging.getLogger(__name__)


@dataclass
class TranscriptStats:
    total: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    failed_ids: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=JSON_INDENT)
        f.write("\n")


def _duration_s(data: dict) -> float:
    src = data.get("source") if isinstance(data.get("source"), dict) else {}
    try:
        return float(src.get("duration_s") or 0)
    except (TypeError, ValueError):
        return 0.0


def _has_transcript_field(data: dict) -> bool:
    """已写过 transcript 字段（含空 text=静音已跑过）。"""
    return isinstance(data.get("transcript"), dict)


def backfill_transcript_json(
    json_path: Path,
    *,
    force: bool = False,
    min_duration_s: float | None = None,
) -> str:
    """
    对单条 video JSON 写 transcript。
    返回: updated | skipped | failed（抛错由上层计 failed）。
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON 根须为对象")

    video_id = str(data.get("video_id") or json_path.stem)
    if is_manual_transcript(data):
        logger.info("跳过（manual_transcript）: %s", video_id)
        return "skipped"
    if _has_transcript_field(data) and not force:
        logger.info("跳过（已有 transcript）: %s", video_id)
        return "skipped"

    min_dur = ASR_MIN_DURATION_S if min_duration_s is None else min_duration_s
    duration = _duration_s(data)
    if min_dur > 0 and duration > 0 and duration < min_dur:
        logger.info(
            "跳过（时长 %.1fs < %.1fs）: %s",
            duration,
            min_dur,
            video_id,
        )
        return "skipped"

    source_path = ""
    src = data.get("source")
    if isinstance(src, dict):
        source_path = str(src.get("path") or "")
    media = resolve_photo_path(video_id, source_path=source_path)
    if media is None or not media.is_file():
        raise FileNotFoundError(f"找不到原视频: {video_id}")

    result = transcribe_audio(media)
    if result.skipped:
        logger.info("跳过 ASR（%s）: %s", result.skip_reason, video_id)
        return "skipped"

    transcript = result.as_transcript()
    if transcript is None or not transcript["text"]:
        # 静音 / 无人声：写空 text，便于下次 force 前可区分「已跑过」
        data["transcript"] = make_transcript(
            "",
            language=result.language or "",
            source=result.source or "whisper",
            status="draft",
        )
        logger.info("无有效人声，写入空 transcript: %s", video_id)
    else:
        data["transcript"] = dict(transcript)
        logger.info(
            "已转写 %s 字（草稿）: %s",
            len(transcript["text"]),
            video_id,
        )

    refresh_manual_edit_flag(data)
    _write_json(json_path, data)
    return "updated"


def _path_matches_month(path_s: str, year: str, month: str) -> bool:
    """source.path 是否落在 photos/<year>/<month>/ 下。"""
    month = (month or "").strip()
    if not month or "/" in month or "\\" in month:
        return True
    norm = path_s.replace("\\", "/")
    markers = (
        f"/photos/{year}/{month}/",
        f"/photos/{year}年/{month}/",
        f"/{year}/{month}/",
        f"/{year}年/{month}/",
    )
    return any(m in norm for m in markers)


def backfill_transcript_folder(
    memory_dir: str | Path | None = None,
    *,
    force: bool = False,
    limit: int | None = None,
    year: str = "",
    month: str = "",
    min_duration_s: float | None = None,
    video_ids: list[str] | None = None,
    progress_cb: Callable[[dict[str, object]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> TranscriptStats:
    """扫描 memory 下 *_v.json（或指定 id）补 transcript。"""
    ok, reason = asr_available()
    if not ok:
        raise RuntimeError(reason)

    memory_path = Path(memory_dir or MEMORY_DIR)
    stats = TranscriptStats()
    start = time.perf_counter()
    year = year.strip()
    month = (month or "").strip()
    if "/" in month or "\\" in month or month in (".", ".."):
        month = ""

    if video_ids:
        paths = []
        for vid in video_ids:
            p = memory_path / f"{vid}.json"
            if not p.is_file() and not vid.endswith("_v"):
                p = memory_path / f"{vid}_v.json"
            if p.is_file():
                paths.append(p)
            else:
                logger.warning("找不到 JSON: %s", vid)
                stats.failed += 1
                stats.failed_ids.append(vid)
    else:
        paths = sorted(memory_path.rglob("*_v.json"))
        if year:
            # 用 source.path / id 里是否含年份粗筛；无 path 时看文件名
            filtered: list[Path] = []
            photos_root = PHOTOS_DIR.resolve()
            for p in paths:
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                src = data.get("source") if isinstance(data, dict) else None
                path_s = str((src or {}).get("path") or "") if isinstance(src, dict) else ""
                if path_s:
                    try:
                        if media_path_matches_year(Path(path_s), photos_root, year):
                            if month and not _path_matches_month(path_s, year, month):
                                continue
                            filtered.append(p)
                            continue
                    except Exception:  # noqa: BLE001
                        pass
                ts = str(data.get("timestamp") or "") if isinstance(data, dict) else ""
                if ts.startswith(year):
                    if month:
                        # timestamp 月：2026-10-… → 10；文件夹名可能是 10 / 5-8，仅精确两位月匹配
                        ts_month = ts[5:7] if len(ts) >= 7 else ""
                        if month.isdigit() and ts_month == month.zfill(2):
                            filtered.append(p)
                        elif month in p.name:
                            filtered.append(p)
                    else:
                        filtered.append(p)
                    continue
                if year in p.name and (not month or month in p.name):
                    filtered.append(p)
            paths = filtered

    total = len(paths)
    scope = f"{year}/{month}" if year and month else year
    logger.info(
        "transcript backfill: 候选 %d 条, force=%s%s",
        total,
        force,
        f", 范围={scope}" if scope else "",
    )
    if progress_cb:
        progress_cb(
            {
                "phase": "transcript",
                "total": total,
                "current": 0,
                "message": f"共 {total} 条视频 JSON",
            }
        )

    for idx, json_path in enumerate(paths, start=1):
        if should_cancel and should_cancel():
            logger.info("任务已取消")
            break
        if limit is not None and limit >= 0 and stats.updated >= limit:
            logger.info("已达本次上限 %d 条", limit)
            break

        stats.total += 1
        video_id = json_path.stem
        try:
            result = backfill_transcript_json(
                json_path,
                force=force,
                min_duration_s=min_duration_s,
            )
            if result == "updated":
                stats.updated += 1
            else:
                stats.skipped += 1
        except Exception as exc:  # noqa: BLE001 — 单条失败不中断
            stats.failed += 1
            stats.failed_ids.append(video_id)
            logger.exception("transcript 失败 %s: %s", video_id, exc)

        if progress_cb:
            progress_cb(
                {
                    "phase": "transcript",
                    "current": idx,
                    "total": total,
                    "current_file": video_id,
                    "updated": stats.updated,
                    "skipped": stats.skipped,
                    "failed": stats.failed,
                    "message": f"已扫描 {idx}/{total}",
                }
            )

    stats.elapsed_seconds = time.perf_counter() - start
    logger.info(
        "transcript 完成: scanned=%s updated=%s skipped=%s failed=%s elapsed=%.1fs",
        stats.total,
        stats.updated,
        stats.skipped,
        stats.failed,
        stats.elapsed_seconds,
    )
    return stats
