"""增量补全 JSON 字段：在已有 memory/*.json 上只跑缺失的分析步骤。"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from hub.shared.analyzer import _strip_internal_person_fields, analyze_image
from hub.shared.config import JSON_INDENT, MEMORY_DIR, PHOTOS_DIR
from hub.shared.face import scan_faces
from hub.shared.family import enrich_people_with_age
from hub.shared.outfit import apply_outfit_fallback
from hub.shared.schema import AnalysisResult, analysis_from_dict
from hub.shared.utils import enrich_analysis_location, extract_exif_timestamp
from hub.shared.vision import analyze_image_ollama

logger = logging.getLogger(__name__)

BackfillMode = Literal["vision", "faces", "all"]


@dataclass
class BackfillStats:
    total: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    failed_files: list[str] = field(default_factory=list)


def _vision_is_empty(data: dict) -> bool:
    return not (
        (data.get("scene") or "").strip()
        or data.get("tags")
        or data.get("objects")
        or data.get("actions")
        or data.get("emotion")
    )


def _should_process(
    data: dict,
    *,
    mode: BackfillMode,
    only_empty: bool,
    has_people: bool,
) -> bool:
    if data.get("manual_edit"):
        return False

    if has_people:
        people = data.get("people") or []
        face = (data.get("quality") or {}).get("face_detected", False)
        if not people and not face:
            return False

    if not only_empty:
        return True

    if mode == "vision":
        return _vision_is_empty(data)
    if mode == "faces":
        return not (data.get("people") or [])
    return _vision_is_empty(data) or not (data.get("people") or [])


def _resolve_image_path(data: dict, photos_dir: Path) -> Path | None:
    source = data.get("source") or {}
    path_str = str(source.get("path", "")).strip()
    if path_str:
        p = Path(path_str)
        if p.is_file():
            return p

    photo_id = str(data.get("photo_id", ""))
    if not photo_id:
        return None

    for candidate in photos_dir.rglob("*"):
        if not candidate.is_file():
            continue
        stem = candidate.stem
        if stem == photo_id or photo_id.endswith(f"_{stem}"):
            return candidate
    return None


def _merge_vision(data: dict, vision: AnalysisResult) -> None:
    data["scene"] = vision["scene"]
    data["objects"] = vision["objects"]
    data["actions"] = vision["actions"]
    data["emotion"] = vision["emotion"]
    data["tags"] = vision["tags"]
    quality = data.get("quality") or {}
    vq = vision["quality"]
    quality["blur"] = vq["blur"]
    data["quality"] = quality


def _merge_faces(
    data: dict,
    *,
    image_path: Path,
    timestamp: str,
    photo_id: str,
) -> None:
    face_people, unmatched_bboxes, face_detected = scan_faces(str(image_path))
    people = apply_outfit_fallback(
        str(image_path),
        timestamp=timestamp,
        photo_id=photo_id,
        face_people=face_people,
        unmatched_bboxes=unmatched_bboxes,
    )
    people = enrich_people_with_age(
        _strip_internal_person_fields(people),
        timestamp,
    )
    data["people"] = people
    quality = data.get("quality") or {}
    quality["face_detected"] = face_detected
    data["quality"] = quality


def backfill_json_file(
    json_path: Path,
    *,
    mode: BackfillMode,
    photos_dir: Path,
    only_empty: bool = True,
    has_people: bool = False,
) -> str:
    """补全单个 JSON。返回 updated | skipped | failed。"""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取失败 %s: %s", json_path.name, exc)
        return "failed"

    if not _should_process(data, mode=mode, only_empty=only_empty, has_people=has_people):
        return "skipped"

    image_path = _resolve_image_path(data, photos_dir)
    if image_path is None:
        logger.warning("找不到原图: %s", json_path.stem)
        return "failed"

    photo_id = str(data.get("photo_id", json_path.stem))
    timestamp = str(data.get("timestamp") or extract_exif_timestamp(image_path))

    try:
        if mode in ("vision", "all"):
            vision = analyze_image_ollama(image_path)
            if mode == "vision":
                _merge_vision(data, vision)
            else:
                raw = analyze_image(
                    str(image_path),
                    timestamp=timestamp,
                    photo_id=photo_id,
                )
                analysis, location_coords = enrich_analysis_location(
                    analysis_from_dict(raw),
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
                data["people"] = analysis["people"]
                data["scene"] = analysis["scene"]
                data["location"] = analysis["location"]
                data["objects"] = analysis["objects"]
                data["actions"] = analysis["actions"]
                data["emotion"] = analysis["emotion"]
                data["tags"] = analysis["tags"]
                data["quality"] = analysis["quality"]
                if location_coords:
                    data["location_coords"] = location_coords
        elif mode == "faces":
            _merge_faces(
                data,
                image_path=image_path,
                timestamp=timestamp,
                photo_id=photo_id,
            )
    except Exception as exc:
        logger.error("补全失败 %s: %s", photo_id, exc)
        return "failed"

    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=JSON_INDENT) + "\n",
        encoding="utf-8",
    )
    return "updated"


def backfill_folder(
    memory_dir: Path | None = None,
    photos_dir: Path | None = None,
    *,
    mode: BackfillMode = "vision",
    only_empty: bool = True,
    has_people: bool = False,
    limit: int | None = None,
    sleep_sec: float = 0.0,
    batch_size: int = 0,
    batch_rest_sec: float = 0.0,
) -> BackfillStats:
    """遍历 memory/*.json，增量补全指定字段。

    limit: 本次最多成功更新几张（适合 Ollama 分批、歇机）
    sleep_sec: 每更新一张后暂停秒数
    batch_size / batch_rest_sec: 每更新 batch_size 张后额外休息
    """
    memory_path = Path(memory_dir or MEMORY_DIR)
    photos_path = Path(photos_dir or PHOTOS_DIR)
    stats = BackfillStats()

    if not memory_path.is_dir():
        logger.error("memory 目录不存在: %s", memory_path)
        return stats

    json_files = sorted(memory_path.glob("*.json"))
    stats.total = len(json_files)

    for json_path in json_files:
        if limit is not None and stats.updated >= limit:
            logger.info("已达本次上限 %d 张，停止。下次再跑即可续补。", limit)
            break

        result = backfill_json_file(
            json_path,
            mode=mode,
            photos_dir=photos_path,
            only_empty=only_empty,
            has_people=has_people,
        )
        if result == "updated":
            stats.updated += 1
            logger.info("已补全: %s（本次 %d/%s）", json_path.stem, stats.updated, limit or "∞")

            if sleep_sec > 0:
                logger.info("暂停 %.0f 秒，让电脑歇一歇…", sleep_sec)
                time.sleep(sleep_sec)

            if batch_size > 0 and batch_rest_sec > 0 and stats.updated % batch_size == 0:
                if limit is None or stats.updated < limit:
                    logger.info(
                        "已完成 %d 张，额外休息 %.0f 秒…",
                        stats.updated,
                        batch_rest_sec,
                    )
                    time.sleep(batch_rest_sec)
        elif result == "skipped":
            stats.skipped += 1
        else:
            stats.failed += 1
            stats.failed_files.append(json_path.name)

    logger.info(
        "补全统计: 扫描=%d, 更新=%d, 跳过=%d, 失败=%d",
        stats.total,
        stats.updated,
        stats.skipped,
        stats.failed,
    )
    return stats
