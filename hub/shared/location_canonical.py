"""常住地 / 熟悉地点：别名 → 统一短地名（逆地理 POI 兜底）。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hub.shared.config import DATA_DIR
from hub.shared.schema import LocationAdmin, empty_location_admin, location_admin_from_dict

logger = logging.getLogger(__name__)

CANONICAL_FILE = DATA_DIR / "location_canonical.json"


@dataclass(frozen=True)
class CanonicalPlace:
    canonical: str
    aliases: frozenset[str]
    location_admin: LocationAdmin


def _normalize_place(raw: dict[str, Any]) -> CanonicalPlace | None:
    canonical = str(raw.get("canonical") or "").strip()
    if not canonical:
        return None
    aliases_raw = raw.get("aliases") or []
    if not isinstance(aliases_raw, list):
        aliases_raw = []
    aliases = {canonical, *(str(a).strip() for a in aliases_raw if str(a).strip())}
    admin = location_admin_from_dict(raw.get("location_admin"))
    return CanonicalPlace(canonical=canonical, aliases=frozenset(aliases), location_admin=admin)


def load_canonical_places(path: Path | None = None) -> list[CanonicalPlace]:
    file_path = Path(path or CANONICAL_FILE)
    if not file_path.is_file():
        return []
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 location_canonical 失败 %s: %s", file_path, exc)
        return []

    places_raw = data.get("places") if isinstance(data, dict) else data
    if not isinstance(places_raw, list):
        return []

    places: list[CanonicalPlace] = []
    for item in places_raw:
        if not isinstance(item, dict):
            continue
        place = _normalize_place(item)
        if place:
            places.append(place)
    return places


def build_alias_index(places: list[CanonicalPlace] | None = None) -> dict[str, CanonicalPlace]:
    index: dict[str, CanonicalPlace] = {}
    for place in places or load_canonical_places():
        for alias in place.aliases:
            index[alias] = place
    return index


def resolve_canonical_location(
    location: str,
    *,
    places: list[CanonicalPlace] | None = None,
) -> tuple[str, LocationAdmin | None]:
    """别名 → canonical；未命中则原样返回。"""
    text = location.strip()
    if not text:
        return "", None
    hit = build_alias_index(places).get(text)
    if hit is None:
        return text, None
    admin = hit.location_admin
    has_admin = any(admin.get(k, "").strip() for k in ("province", "city", "district", "formatted_address"))
    return hit.canonical, admin if has_admin else None


def merge_location_admin(base: LocationAdmin, override: LocationAdmin | None) -> LocationAdmin:
    if override is None:
        return base
    merged = dict(base)
    for key in ("province", "city", "district", "formatted_address"):
        val = str(override.get(key, "")).strip()
        if val:
            merged[key] = val
    return LocationAdmin(**merged)


@dataclass
class ApplyCanonicalStats:
    cache_updated: int = 0
    cache_skipped: int = 0


def delete_geocode_cache_by_locations(*locations: str) -> int:
    """按短地名删除缓存条目，便于重新请求高德以拆开 POI + 详细地址。"""
    from hub.shared.geocode import _CACHE_VERSION, _load_cache_raw, _normalize_cache_entry, _save_cache

    targets = {loc.strip() for loc in locations if loc.strip()}
    if not targets:
        return 0

    cache = _load_cache_raw()
    deleted = 0
    for key, value in list(cache.items()):
        if not key.startswith(f"{_CACHE_VERSION}|"):
            continue
        entry = _normalize_cache_entry(value)
        if str(entry.get("location") or "").strip() in targets:
            del cache[key]
            deleted += 1

    if deleted:
        _save_cache(
            {
                k: _normalize_cache_entry(v)
                for k, v in cache.items()
                if k.startswith(f"{_CACHE_VERSION}|")
            }
        )
    return deleted


def apply_canonical_to_cache(*, dry_run: bool = False) -> ApplyCanonicalStats:
    """把缓存里命中别名的 location 统一为 canonical（合并场景才用）。"""
    from hub.shared.geocode import _CACHE_VERSION, _load_cache_raw, _normalize_cache_entry, _save_cache

    places = load_canonical_places()
    if not places:
        logger.warning("未找到 %s，跳过 canonical 应用", CANONICAL_FILE)
        return ApplyCanonicalStats()

    cache = _load_cache_raw()
    stats = ApplyCanonicalStats()

    for key, value in list(cache.items()):
        if not key.startswith(f"{_CACHE_VERSION}|"):
            continue
        entry = _normalize_cache_entry(value)
        old_loc = str(entry.get("location") or "").strip()
        if not old_loc:
            stats.cache_skipped += 1
            continue

        new_loc, admin_tpl = resolve_canonical_location(old_loc, places=places)
        if new_loc == old_loc:
            stats.cache_skipped += 1
            continue

        entry["location"] = new_loc
        if admin_tpl is not None:
            entry["location_admin"] = dict(
                merge_location_admin(location_admin_from_dict(entry.get("location_admin")), admin_tpl)
            )

        if not dry_run:
            cache[key] = entry
        stats.cache_updated += 1
        logger.info("canonical: %s → %s (%s)", old_loc, new_loc, key.split("|")[-1])

    if not dry_run and stats.cache_updated:
        _save_cache(
            {
                k: _normalize_cache_entry(v)
                for k, v in cache.items()
                if k.startswith(f"{_CACHE_VERSION}|")
            }
        )
    return stats
