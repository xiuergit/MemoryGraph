"""同日相邻照片地点归一：避免单张 GPS 逆编码结果不一致。"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from hub.shared.config import JSON_INDENT, MEMORY_DIR
from hub.shared.geocode import is_acceptable_location, resolve_location, resolve_location_geocode
from hub.shared.schema import LocationAdmin
from hub.shared.utils import extract_exif_location

logger = logging.getLogger(__name__)

# 同一 outing 的 GPS 聚类半径（米）
_CLUSTER_RADIUS_M = 800
# 无 GPS 时，与聚类照片拍摄时间差在该范围内则继承地点
_TIME_JOIN_SECONDS = 3 * 3600


@dataclass
class PhotoLocationRecord:
    photo_id: str
    json_path: Path
    timestamp: str
    coords: tuple[float, float] | None
    coords_str: str
    location: str


def _parse_coords(text: str) -> tuple[float, float] | None:
    parts = text.split(",", maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None


def _looks_like_coords(text: str) -> bool:
    return _parse_coords(text.strip()) is not None


def _parse_timestamp_seconds(timestamp: str) -> float | None:
    if not timestamp or not timestamp.strip():
        return None
    text = timestamp.strip()
    try:
        if "T" in text:
            return datetime.fromisoformat(text).timestamp()
        return datetime.strptime(text, "%Y-%m-%d").timestamp()
    except ValueError:
        return None


def _date_key(timestamp: str) -> str:
    if not timestamp:
        return ""
    return timestamp[:10] if len(timestamp) >= 10 else timestamp


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def _location_quality_score(name: str) -> int:
    """地名越长越完整，分数越高（不再偏好两字截断）。"""
    text = name.strip()
    if not text or _looks_like_coords(text) or not is_acceptable_location(text):
        return -100

    score = min(len(text), 20)
    if text.endswith(("公园", "森林公园", "动物园", "植物园")):
        score += 12
    elif text.endswith(("园", "山", "湖", "馆", "寺", "塔")):
        score += 8

    if any(keyword in text for keyword in ("停车", "诊所", "工作站", "卫生间")):
        score -= 20
    if any(keyword in text for keyword in ("街", "路", "号", "社区", "小区")):
        score -= 4
    return score


def _pick_cluster_location(locations: list[str]) -> str:
    if not locations:
        return ""

    good = [loc.strip() for loc in locations if loc.strip() and is_acceptable_location(loc.strip())]
    pool = good if good else [loc.strip() for loc in locations if loc.strip()]
    counts = Counter(pool)
    if not counts:
        return ""

    ranked = sorted(
        counts.items(),
        key=lambda item: (_location_quality_score(item[0]), item[1], len(item[0])),
        reverse=True,
    )
    return ranked[0][0]


def _cluster_by_coords(records: list[PhotoLocationRecord]) -> list[list[PhotoLocationRecord]]:
    with_coords = [r for r in records if r.coords is not None]
    if not with_coords:
        return [records] if records else []

    assigned = [False] * len(with_coords)
    clusters: list[list[PhotoLocationRecord]] = []

    for i, seed in enumerate(with_coords):
        if assigned[i]:
            continue
        group = [seed]
        assigned[i] = True
        for j in range(i + 1, len(with_coords)):
            if assigned[j]:
                continue
            other = with_coords[j]
            assert seed.coords is not None and other.coords is not None
            if _haversine_m(seed.coords, other.coords) <= _CLUSTER_RADIUS_M:
                group.append(other)
                assigned[j] = True
        clusters.append(group)

    no_coords = [r for r in records if r.coords is None]
    for record in no_coords:
        ts = _parse_timestamp_seconds(record.timestamp)
        best_cluster: list[PhotoLocationRecord] | None = None
        best_delta = _TIME_JOIN_SECONDS + 1

        for cluster in clusters:
            for member in cluster:
                member_ts = _parse_timestamp_seconds(member.timestamp)
                if ts is None or member_ts is None:
                    continue
                delta = abs(ts - member_ts)
                if delta < best_delta:
                    best_delta = delta
                    best_cluster = cluster

        if best_cluster is not None and best_delta <= _TIME_JOIN_SECONDS:
            best_cluster.append(record)
        else:
            clusters.append([record])

    return clusters


def _normalize_records(records: list[PhotoLocationRecord]) -> dict[str, str]:
    by_day: dict[str, list[PhotoLocationRecord]] = defaultdict(list)
    for record in records:
        day = _date_key(record.timestamp)
        if day:
            by_day[day].append(record)

    updates: dict[str, str] = {}
    for day_records in by_day.values():
        for cluster in _cluster_by_coords(day_records):
            chosen = _pick_cluster_location([r.location for r in cluster if r.location])
            if not chosen:
                continue
            for record in cluster:
                if record.location != chosen:
                    updates[record.photo_id] = chosen
    return updates


@dataclass
class RegeocodeStats:
    total: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    no_coords: int = 0


def _admin_needs_refresh(
    old_admin: dict[str, Any],
    new_admin: LocationAdmin,
    *,
    old_location: str,
    new_location: str,
) -> bool:
    """formatted_address 缺失或与短地名相同 → 需要写回。"""
    if not str(old_admin.get("province", "")).strip():
        return True
    old_fmt = str(old_admin.get("formatted_address", "")).strip()
    new_fmt = str(new_admin.get("formatted_address", "")).strip()
    if not old_fmt:
        return True
    if old_fmt in {old_location.strip(), new_location.strip()}:
        return True
    if new_fmt and old_fmt != new_fmt:
        return True
    return False


def regeocode_locations_from_memory(
    memory_dir: Path | None = None,
    *,
    limit: int | None = None,
    normalize_after: bool = True,
) -> RegeocodeStats:
    """按 JSON 里的 location_coords 重新逆地理，覆盖 location（不读原图）。"""
    memory_path = Path(memory_dir or MEMORY_DIR)
    stats = RegeocodeStats()

    if not memory_path.is_dir():
        logger.warning("memory 目录不存在: %s", memory_path)
        return stats

    json_files = sorted(memory_path.glob("*.json"))
    stats.total = len(json_files)

    for json_path in json_files:
        if limit is not None and stats.updated >= limit:
            logger.info("已达本次上限 %d 条，停止。下次再跑即可续补。", limit)
            break

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            stats.failed += 1
            logger.warning("读取 JSON 失败 %s: %s", json_path.name, exc)
            continue

        if data.get("manual_location"):
            stats.skipped += 1
            continue

        coords_str = str(data.get("location_coords", "")).strip()
        coords = _parse_coords(coords_str)
        if coords is None:
            stats.no_coords += 1
            continue

        coords_key = f"{coords[0]:.6f},{coords[1]:.6f}"
        try:
            geocode = resolve_location_geocode(coords_key)
            new_location = geocode.location.strip()
            new_admin = geocode.location_admin
        except Exception as exc:
            stats.failed += 1
            logger.warning("逆地理失败 %s: %s", json_path.stem, exc)
            continue

        if not new_location or _looks_like_coords(new_location):
            stats.failed += 1
            logger.warning("逆地理无结果 %s", json_path.stem)
            continue

        if not is_acceptable_location(new_location):
            stats.failed += 1
            logger.warning("逆地理地名不理想 %s: %s", json_path.stem, new_location)
            continue

        old_location = str(data.get("location", "")).strip()
        old_admin = data.get("location_admin") or {}
        needs_admin = _admin_needs_refresh(
            old_admin,
            new_admin,
            old_location=old_location,
            new_location=new_location,
        )
        if (
            old_location == new_location
            and is_acceptable_location(old_location)
            and not needs_admin
        ):
            stats.skipped += 1
            continue

        data["location"] = new_location
        data["location_admin"] = dict(new_admin)
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=JSON_INDENT) + "\n",
            encoding="utf-8",
        )
        stats.updated += 1
        logger.info("重算地点: %s  %s → %s", json_path.stem, old_location or "(空)", new_location)

    if normalize_after and stats.updated > 0:
        apply_location_normalization(memory_path)

    logger.info(
        "逆地理重算: 扫描=%d, 更新=%d, 跳过=%d, 无坐标=%d, 失败=%d",
        stats.total,
        stats.updated,
        stats.skipped,
        stats.no_coords,
        stats.failed,
    )
    return stats


def collect_location_records(memory_dir: Path) -> list[PhotoLocationRecord]:
    records: list[PhotoLocationRecord] = []
    for json_path in sorted(memory_dir.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("读取 JSON 失败 %s: %s", json_path.name, exc)
            continue

        if data.get("manual_location"):
            continue

        source = data.get("source") or {}
        image_path = Path(str(source.get("path", "")))
        coords = _parse_coords(str(data.get("location_coords", "")))
        if coords is None:
            coords = _parse_coords(str(data.get("location", "")))
        if coords is None and image_path.is_file():
            coords = _parse_coords(extract_exif_location(image_path))

        location = str(data.get("location", "")).strip()
        if _looks_like_coords(location):
            location = resolve_location(location) if coords else ""
        elif not location and coords:
            location = resolve_location(f"{coords[0]:.6f},{coords[1]:.6f}")

        coords_str = ""
        if coords:
            coords_str = f"{coords[0]:.6f},{coords[1]:.6f}"

        records.append(
            PhotoLocationRecord(
                photo_id=str(data.get("photo_id", json_path.stem)),
                json_path=json_path,
                timestamp=str(data.get("timestamp", "")),
                coords=coords,
                coords_str=coords_str,
                location=location,
            )
        )
    return records


def apply_location_normalization(memory_dir: Path | None = None) -> int:
    """按同日 + 相近 GPS 统一 location 可读地名，并补全 location_coords。"""
    memory_path = Path(memory_dir or MEMORY_DIR)
    if not memory_path.is_dir():
        logger.warning("memory 目录不存在: %s", memory_path)
        return 0

    records = collect_location_records(memory_path)
    if not records:
        return 0

    location_updates = _normalize_records(records)
    changed = 0

    for record in records:
        try:
            data = json.loads(record.json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        updated = False
        new_location = location_updates.get(record.photo_id)
        if new_location and data.get("location") != new_location:
            data["location"] = new_location
            updated = True
            logger.info("地点归一: %s → %s", record.photo_id, new_location)

        if record.coords_str and not data.get("location_coords"):
            data["location_coords"] = record.coords_str
            updated = True
            logger.info("补全坐标: %s → %s", record.photo_id, record.coords_str)

        if not updated:
            continue

        record.json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=JSON_INDENT) + "\n",
            encoding="utf-8",
        )
        changed += 1

    if changed:
        logger.info("地点处理完成: 更新 %d 张", changed)
    else:
        logger.info("同日地点归一: 无需更新")
    return changed


@dataclass
class ClearManualLocationStats:
    total: int = 0
    cleared: int = 0
    skipped: int = 0
    failed: int = 0


def clear_manual_location_flags(
    memory_dir: Path | None = None,
    *,
    dry_run: bool = False,
) -> ClearManualLocationStats:
    """移除 JSON 上的 manual_location 标记，便于 --regeocode-locations 从缓存重算。"""
    memory_path = Path(memory_dir or MEMORY_DIR)
    stats = ClearManualLocationStats()

    if not memory_path.is_dir():
        logger.warning("memory 目录不存在: %s", memory_path)
        return stats

    for json_path in sorted(memory_path.glob("*.json")):
        stats.total += 1
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            stats.failed += 1
            logger.warning("读取 JSON 失败 %s: %s", json_path.name, exc)
            continue

        if not data.get("manual_location"):
            stats.skipped += 1
            continue

        if dry_run:
            stats.cleared += 1
            logger.info("[dry-run] 将清除 manual_location: %s", json_path.stem)
            continue

        data.pop("manual_location", None)
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=JSON_INDENT) + "\n",
            encoding="utf-8",
        )
        stats.cleared += 1
        logger.info("已清除 manual_location: %s", json_path.stem)

    logger.info(
        "清除 manual_location: 扫描=%d, 清除=%d, 跳过=%d, 失败=%d%s",
        stats.total,
        stats.cleared,
        stats.skipped,
        stats.failed,
        " (dry-run)" if dry_run else "",
    )
    return stats
