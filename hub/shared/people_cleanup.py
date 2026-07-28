"""清理 people 字段中的误识别（如衣着兜底）。"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from hub.shared.config import JSON_INDENT, MEMORY_DIR, OUTFIT_CACHE_DIR
from hub.shared.family import enrich_people_with_age

logger = logging.getLogger(__name__)


@dataclass
class StripLowConfidenceStats:
    total: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    removed_entries: int = 0
    failed_files: list[str] = field(default_factory=list)


def strip_low_confidence_people(
    data: dict,
    *,
    min_confidence: float = 0.55,
) -> tuple[dict, int]:
    """从 people 中移除 confidence 严格小于 min_confidence 的条目。"""
    if data.get("manual_people") or data.get("manual_edit"):
        return data, 0

    people = data.get("people") or []
    kept: list[dict] = []
    removed = 0
    for person in people:
        if not isinstance(person, dict):
            kept.append(person)
            continue
        raw = person.get("confidence")
        if raw in (None, ""):
            kept.append(person)
            continue
        try:
            confidence = float(raw)
        except (TypeError, ValueError):
            kept.append(person)
            continue
        if confidence < min_confidence:
            removed += 1
            continue
        kept.append(person)

    if removed == 0:
        return data, 0

    data = dict(data)
    timestamp = str(data.get("timestamp", ""))
    data["people"] = enrich_people_with_age(kept, timestamp)
    return data, removed


def strip_low_confidence_people_from_memory(
    memory_dir: Path | None = None,
    *,
    min_confidence: float = 0.55,
    year: str = "",
    dry_run: bool = False,
) -> StripLowConfidenceStats:
    """批量移除 JSON 中低于阈值的 people 条目（遗留旧识别结果）。"""
    root = Path(memory_dir or MEMORY_DIR)
    stats = StripLowConfidenceStats()

    if not root.is_dir():
        logger.error("memory 目录不存在: %s", root)
        return stats

    from hub.shared.utils import json_matches_year

    for json_path in sorted(root.glob("*.json")):
        stats.total += 1
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            stats.failed += 1
            stats.failed_files.append(json_path.name)
            logger.warning("读取失败 %s: %s", json_path.name, exc)
            continue

        if year and not json_matches_year(data, json_path, year):
            stats.skipped += 1
            continue

        new_data, removed = strip_low_confidence_people(
            data,
            min_confidence=min_confidence,
        )
        if removed == 0:
            stats.skipped += 1
            continue

        stats.removed_entries += removed
        if dry_run:
            logger.info(
                "[dry-run] %s 将移除 %d 条 (<%.2f)",
                json_path.name,
                removed,
                min_confidence,
            )
            stats.updated += 1
            continue

        json_path.write_text(
            json.dumps(new_data, ensure_ascii=False, indent=JSON_INDENT) + "\n",
            encoding="utf-8",
        )
        stats.updated += 1
        logger.info(
            "已清理 %s: 移除 %d 条 (<%.2f)",
            json_path.name,
            removed,
            min_confidence,
        )

    logger.info(
        "清理低置信 people: 扫描=%d, 更新=%d, 跳过=%d, 失败=%d, 移除条目=%d%s",
        stats.total,
        stats.updated,
        stats.skipped,
        stats.failed,
        stats.removed_entries,
        " (dry-run)" if dry_run else "",
    )
    return stats


@dataclass
class StripOutfitStats:
    total: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    removed_entries: int = 0
    failed_files: list[str] = field(default_factory=list)


def strip_outfit_people(data: dict) -> tuple[dict, int]:
    """从 people 中移除 match_method=outfit 的条目。返回 (新 data, 移除条数)。"""
    if data.get("manual_people") or data.get("manual_edit"):
        return data, 0

    people = data.get("people") or []
    kept = [p for p in people if p.get("match_method") != "outfit"]
    removed = len(people) - len(kept)
    if removed == 0:
        return data, 0

    data = dict(data)
    timestamp = str(data.get("timestamp", ""))
    data["people"] = enrich_people_with_age(kept, timestamp)
    return data, removed


def strip_outfit_people_from_memory(
    memory_dir: Path | None = None,
    *,
    year: str = "",
    dry_run: bool = False,
    clear_outfit_cache: bool = True,
) -> StripOutfitStats:
    """批量移除 JSON 中 match_method=outfit 的人物识别。"""
    root = Path(memory_dir or MEMORY_DIR)
    stats = StripOutfitStats()

    if not root.is_dir():
        logger.error("memory 目录不存在: %s", root)
        return stats

    from hub.shared.utils import json_matches_year

    for json_path in sorted(root.glob("*.json")):
        stats.total += 1
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            stats.failed += 1
            stats.failed_files.append(json_path.name)
            logger.warning("读取失败 %s: %s", json_path.name, exc)
            continue

        if year and not json_matches_year(data, json_path, year):
            stats.skipped += 1
            continue

        new_data, removed = strip_outfit_people(data)
        if removed == 0:
            stats.skipped += 1
            continue

        stats.removed_entries += removed
        if dry_run:
            logger.info("[dry-run] %s 将移除 %d 条 outfit", json_path.name, removed)
            stats.updated += 1
            continue

        json_path.write_text(
            json.dumps(new_data, ensure_ascii=False, indent=JSON_INDENT) + "\n",
            encoding="utf-8",
        )
        stats.updated += 1
        logger.info("已清理 %s: 移除 %d 条 outfit", json_path.name, removed)

    if clear_outfit_cache and not dry_run and stats.updated > 0:
        if OUTFIT_CACHE_DIR.is_dir():
            shutil.rmtree(OUTFIT_CACHE_DIR)
            logger.info("已删除衣着缓存目录: %s", OUTFIT_CACHE_DIR)

    logger.info(
        "清理 outfit: 扫描=%d, 更新=%d, 跳过=%d, 失败=%d, 移除条目=%d%s",
        stats.total,
        stats.updated,
        stats.skipped,
        stats.failed,
        stats.removed_entries,
        " (dry-run)" if dry_run else "",
    )
    return stats
