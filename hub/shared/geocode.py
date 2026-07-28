"""逆地理编码：EXIF 坐标 → 简短中文地名（高德 Web 服务 API）。"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hub.shared.config import DATA_DIR, MEMORY_DB
from hub.shared.schema import LocationAdmin, empty_location_admin, location_admin_from_dict

logger = logging.getLogger(__name__)

GEOCODE_CACHE_FILE = DATA_DIR / ".geocode_cache.json"
AMAP_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
_CACHE_VERSION = "6"
_MAX_LOCATION_LEN = 24

_MIN_REQUEST_INTERVAL_SEC = 0.2
_last_request_at = 0.0

_NOISE_KEYWORDS = (
    "停车场",
    "停车位",
    "停车区",
    "停车库",
    "地面停车",
    "地下车库",
    "出入口",
    "卫生间",
    "厕所",
    "公交站",
    "地铁站",
    "收费站",
    "工作站",
    "警务站",
    "诊所",
    "门诊部",
    "小区",
    "号楼",
    "弄",
    "项目部",
    "项目经理",
    "标段",
    "工区",
    "施工",
    "工地",
    "建设项目",
    "高速",
    "有限公司",
    "实业",
    "集团",
    "分公司",
    "股份",
    "公司",
)

_GENERIC_LANDMARKS = frozenset({"社区", "街道", "镇", "乡", "村"})

# 过短或截断误提取的地名，不作为 location
_BAD_LANDMARKS = frozenset(
    {
        "地铁",
        "公交",
        "公园",
        "风公园",
        "林公园",
        "野公园",
        "岛花园",
        "海花园",
    }
)

_PREFER_TYPE_KEYWORDS = (
    "风景名胜",
    "公园广场",
    "动物园",
    "植物园",
    "森林公园",
    "科教文化",
    "学校",
    "小学",
    "中学",
    "幼儿园",
    "医院",
    "体育馆",
    "图书馆",
    "博物馆",
)

_SKIP_TYPE_KEYWORDS = (
    "商务住宅",
    "公司企业",
    "通行设施",
    "政府机构",
)


def _load_cache_raw() -> dict[str, Any]:
    if not GEOCODE_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(GEOCODE_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 geocode 缓存失败: %s", exc)
    return {}


def _load_cache() -> dict[str, dict[str, Any]]:
    data = _load_cache_raw()
    out: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if isinstance(value, dict) and "location" in value:
            out[str(key)] = value
        elif isinstance(value, str):
            out[str(key)] = {"location": value, "location_admin": empty_location_admin()}
    return out


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    GEOCODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GEOCODE_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cache_key(coords: str) -> str:
    parsed = _parse_coords(coords.strip())
    if parsed:
        coords = f"{parsed[0]:.6f},{parsed[1]:.6f}"
    return f"{_CACHE_VERSION}|{coords}"


def cache_version() -> str:
    """当前 geocode 缓存 key 前缀版本号。"""
    return _CACHE_VERSION


def _normalize_cache_entry(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict) and "location" in raw:
        admin = raw.get("location_admin") or empty_location_admin()
        if not isinstance(admin, dict):
            admin = empty_location_admin()
        return {
            "location": str(raw.get("location") or ""),
            "location_admin": {
                "province": str(admin.get("province", "")),
                "city": str(admin.get("city", "")),
                "district": str(admin.get("district", "")),
                "formatted_address": str(admin.get("formatted_address", "")),
            },
        }
    if isinstance(raw, str):
        return {"location": raw, "location_admin": dict(empty_location_admin())}
    return {"location": "", "location_admin": dict(empty_location_admin())}


def _is_valid_cache_entry(entry: dict[str, Any]) -> bool:
    location = str(entry.get("location") or "").strip()
    return bool(location) and is_acceptable_location(location)


def geocode_cache_key(coords: str) -> str:
    """坐标 → 当前版本的缓存 key。"""
    return _cache_key(coords)


@dataclass
class MigrateGeocodeCacheStats:
    total_keys: int = 0
    migrated: int = 0
    skipped_existing: int = 0
    dropped_bad: int = 0
    removed_legacy: int = 0
    purged_current: int = 0


def migrate_geocode_cache(*, dry_run: bool = False, purge_bad: bool = True) -> MigrateGeocodeCacheStats:
    """将旧版本缓存 key（如 3|lat,lon）迁移到当前版本，并清理不合格条目。"""
    stats = MigrateGeocodeCacheStats()
    raw = _load_cache_raw()
    stats.total_keys = len(raw)
    current = _CACHE_VERSION
    rebuilt: dict[str, dict[str, Any]] = {}

    for key, value in raw.items():
        if not key.startswith(f"{current}|"):
            continue
        entry = _normalize_cache_entry(value)
        if purge_bad and not _is_valid_cache_entry(entry):
            stats.purged_current += 1
            continue
        if _is_valid_cache_entry(entry):
            rebuilt[key] = entry

    for key, value in raw.items():
        if "|" not in key or key.startswith(f"{current}|"):
            continue
        stats.removed_legacy += 1
        coords = key.split("|", maxsplit=1)[-1]
        new_key = _cache_key(coords)
        entry = _normalize_cache_entry(value)

        if not _is_valid_cache_entry(entry):
            stats.dropped_bad += 1
            continue

        if new_key in rebuilt:
            stats.skipped_existing += 1
            continue

        rebuilt[new_key] = entry
        stats.migrated += 1

    if not dry_run:
        _save_cache(rebuilt)

    logger.info(
        "缓存迁移: 总=%d, 迁入=%d, 已有跳过=%d, 丢弃=%d, 删旧=%d, 清当前坏项=%d%s",
        stats.total_keys,
        stats.migrated,
        stats.skipped_existing,
        stats.dropped_bad,
        stats.removed_legacy,
        stats.purged_current,
        " (dry-run)" if dry_run else "",
    )
    return stats


@dataclass
class GeocodeCacheRow:
    coords: str
    location: str
    province: str
    city: str
    district: str
    formatted_address: str
    valid: bool


def _coords_from_cache_key(key: str) -> str:
    return key.split("|", maxsplit=1)[-1] if "|" in key else key


def _row_from_cache_key(key: str, value: object) -> GeocodeCacheRow | None:
    if not key.startswith(f"{_CACHE_VERSION}|"):
        return None
    entry = _normalize_cache_entry(value)
    admin = entry.get("location_admin") or empty_location_admin()
    location = str(entry.get("location") or "")
    return GeocodeCacheRow(
        coords=_coords_from_cache_key(key),
        location=location,
        province=str(admin.get("province", "")),
        city=str(admin.get("city", "")),
        district=str(admin.get("district", "")),
        formatted_address=str(admin.get("formatted_address", "")),
        valid=_is_valid_cache_entry(entry),
    )


def _admin_sort_key(province: str, city: str, district: str, location: str) -> tuple[str, str, str, str]:
    """省 → 市 → 区 → 短地名；缺省排在该组末尾。"""
    return (
        province.strip() or "未分区",
        city.strip() or "未分区",
        district.strip() or "",
        location.strip() or "",
    )


def _filter_by_region(
    item: dict[str, Any],
    *,
    province: str = "",
    city: str = "",
) -> bool:
    if province:
        item_p = item.get("province", "").strip() or "未分区"
        if item_p != province:
            return False
    if city:
        item_c = item.get("city", "").strip() or "未分区"
        if item_c != city:
            return False
    return True


def list_geocode_cache_rows(
    *,
    search: str = "",
    province: str = "",
    city: str = "",
) -> list[GeocodeCacheRow]:
    """列出当前版本缓存条目（按坐标）。"""
    cache = _load_cache_raw()
    keyword = search.strip().lower()
    rows: list[GeocodeCacheRow] = []

    for key, value in cache.items():
        row = _row_from_cache_key(key, value)
        if row is None:
            continue
        if keyword:
            haystack = (
                f"{row.location} {row.formatted_address} {row.coords} "
                f"{row.province}{row.city}{row.district}"
            ).lower()
            if keyword not in haystack:
                continue
        row_dict = {
            "province": row.province,
            "city": row.city,
        }
        if not _filter_by_region(row_dict, province=province, city=city):
            continue
        rows.append(row)

    rows.sort(
        key=lambda item: (
            _admin_sort_key(item.province, item.city, item.district, item.location),
            item.coords,
        )
    )
    return rows


def _summarize_location_group(rows: list[GeocodeCacheRow]) -> dict[str, Any]:
    """同一短地名的多条坐标映射 → 汇总为代表省市区（多数票）。"""
    if not rows:
        return {}

    coord_count = len(rows)
    distinct_provinces = {r.province.strip() for r in rows if r.province.strip()}
    distinct_cities = {r.city.strip() for r in rows if r.city.strip()}
    admin_inconsistent = len(distinct_provinces) > 1 or len(distinct_cities) > 1

    province_votes = Counter(r.province.strip() for r in rows if r.province.strip())
    if province_votes:
        province = province_votes.most_common(1)[0][0]
        subset = [r for r in rows if r.province.strip() == province]
    else:
        province = ""
        subset = rows

    city_votes = Counter(r.city.strip() for r in subset if r.city.strip())
    city = city_votes.most_common(1)[0][0] if city_votes else ""

    district_votes = Counter(r.district.strip() for r in subset if r.district.strip())
    district = district_votes.most_common(1)[0][0] if district_votes else ""

    formatted_candidates = [
        r.formatted_address
        for r in subset
        if r.formatted_address.strip() and r.formatted_address.strip() != r.location.strip()
    ]
    if formatted_candidates:
        formatted_address = max(formatted_candidates, key=len)
    else:
        formatted_address = next((r.formatted_address for r in subset if r.formatted_address.strip()), "")

    missing_admin = sum(1 for r in rows if not r.province.strip())
    coords_sample = [r.coords for r in rows[:5]]

    return {
        "location": rows[0].location,
        "coord_count": coord_count,
        "coords_sample": coords_sample,
        "province": province,
        "city": city,
        "district": district,
        "formatted_address": formatted_address,
        "valid": all(r.valid for r in rows),
        "missing_admin": missing_admin == coord_count,
        "admin_inconsistent": admin_inconsistent,
        "missing_admin_count": missing_admin,
    }


def list_geocode_cache_grouped(
    *,
    search: str = "",
    province: str = "",
    city: str = "",
    sort: str = "coord_count",
) -> list[dict[str, Any]]:
    """按 location 合并：同一短地名只显示一条，附带坐标数量。"""
    buckets: dict[str, list[GeocodeCacheRow]] = {}

    for row in list_geocode_cache_rows(search=search, province=province, city=city):
        loc_key = row.location or ""
        buckets.setdefault(loc_key, []).append(row)

    items = [_summarize_location_group(rows) for rows in buckets.values() if rows]

    if sort == "region":
        items.sort(
            key=lambda item: (
                _admin_sort_key(
                    str(item.get("province", "")),
                    str(item.get("city", "")),
                    str(item.get("district", "")),
                    str(item.get("location", "")),
                ),
                -int(item["coord_count"]),
            )
        )
    else:
        items.sort(
            key=lambda item: (
                -int(item["coord_count"]),
                _admin_sort_key(
                    str(item.get("province", "")),
                    str(item.get("city", "")),
                    str(item.get("district", "")),
                    str(item.get("location", "")),
                ),
            )
        )
    return items


def list_geocode_cache_regions() -> dict[str, Any]:
    """按省 / 市汇总地名数量，供前端筛选。"""
    items = list_geocode_cache_grouped()
    province_map: dict[str, dict[str, Any]] = {}

    for item in items:
        p = str(item.get("province", "")).strip() or "未分区"
        c = str(item.get("city", "")).strip() or "未分区"
        if p not in province_map:
            province_map[p] = {
                "province": p,
                "location_count": 0,
                "coord_count": 0,
                "cities": {},
            }
        prov = province_map[p]
        prov["location_count"] += 1
        prov["coord_count"] += int(item.get("coord_count") or 0)
        cities = prov["cities"]
        if c not in cities:
            cities[c] = {"city": c, "location_count": 0, "coord_count": 0}
        cities[c]["location_count"] += 1
        cities[c]["coord_count"] += int(item.get("coord_count") or 0)

    provinces = sorted(province_map.values(), key=lambda row: str(row["province"]))
    for prov in provinces:
        city_list = sorted(prov["cities"].values(), key=lambda row: str(row["city"]))
        prov["cities"] = city_list

    return {"provinces": provinces, "province_count": len(provinces)}


def geocode_cache_stats() -> dict[str, int]:
    rows = list_geocode_cache_rows()
    grouped = list_geocode_cache_grouped()
    return {
        "coords": len(rows),
        "locations": len(grouped),
        "invalid": sum(1 for row in rows if not row.valid),
        "missing_admin": sum(1 for row in rows if not row.province.strip()),
    }


def _apply_admin_fields(
    admin: dict[str, str],
    *,
    province: str,
    city: str,
    district: str,
    formatted_address: str,
) -> None:
    if province.strip():
        admin["province"] = province.strip()
    if city.strip():
        admin["city"] = city.strip()
    if district.strip():
        admin["district"] = district.strip()
    if formatted_address.strip():
        admin["formatted_address"] = formatted_address.strip()


def update_geocode_cache_coords(
    coords: str,
    *,
    location: str,
    province: str = "",
    city: str = "",
    district: str = "",
    formatted_address: str = "",
) -> bool:
    """按坐标更新单条缓存。"""
    cache = _load_cache_raw()
    key = _cache_key(coords)
    if key not in cache:
        return False

    entry = _normalize_cache_entry(cache[key])
    entry["location"] = location.strip()
    admin = entry.setdefault("location_admin", dict(empty_location_admin()))
    _apply_admin_fields(
        admin,
        province=province,
        city=city,
        district=district,
        formatted_address=formatted_address,
    )
    if not _is_valid_cache_entry(entry):
        raise ValueError(f"地名不合格: {location}")

    cache[key] = entry
    _save_cache(
        {
            k: _normalize_cache_entry(v)
            for k, v in cache.items()
            if k.startswith(f"{_CACHE_VERSION}|")
        }
    )
    return True


def update_geocode_cache_by_location(
    old_location: str,
    *,
    new_location: str,
    province: str = "",
    city: str = "",
    district: str = "",
    formatted_address: str = "",
) -> int:
    """同一 location 的所有坐标映射批量更新。"""
    old = old_location.strip()
    new = new_location.strip()
    if not old or not new:
        raise ValueError("old_location 与 new_location 均不能为空")
    if not is_acceptable_location(new):
        raise ValueError(f"新地名不合格: {new}")

    cache = _load_cache_raw()
    updated = 0
    for key, value in list(cache.items()):
        if not key.startswith(f"{_CACHE_VERSION}|"):
            continue
        entry = _normalize_cache_entry(value)
        if str(entry.get("location") or "").strip() != old:
            continue
        entry["location"] = new
        admin = entry.setdefault("location_admin", dict(empty_location_admin()))
        _apply_admin_fields(
            admin,
            province=province,
            city=city,
            district=district,
            formatted_address=formatted_address,
        )
        cache[key] = entry
        updated += 1

    if updated:
        _save_cache(
            {
                k: _normalize_cache_entry(v)
                for k, v in cache.items()
                if k.startswith(f"{_CACHE_VERSION}|")
            }
        )
    return updated


def delete_geocode_cache_without_formatted_address(*, dry_run: bool = False) -> int:
    """删除缺少 formatted_address 的缓存条目，便于 regeocode 重新请求高德。"""
    cache = _load_cache_raw()
    to_delete: list[str] = []
    for key, value in cache.items():
        if not key.startswith(f"{_CACHE_VERSION}|"):
            continue
        entry = _normalize_cache_entry(value)
        admin = entry.get("location_admin") or {}
        if not str(admin.get("formatted_address", "")).strip():
            to_delete.append(key)

    if dry_run or not to_delete:
        return len(to_delete)

    for key in to_delete:
        cache.pop(key, None)
    _save_cache(
        {
            k: _normalize_cache_entry(v)
            for k, v in cache.items()
            if k.startswith(f"{_CACHE_VERSION}|")
        }
    )
    return len(to_delete)


def delete_geocode_cache_coords(coords: str) -> bool:
    """删除单条坐标缓存，后续 regeocode 会重新请求高德。"""
    cache = _load_cache_raw()
    key = _cache_key(coords)
    if key not in cache:
        return False
    del cache[key]
    _save_cache(
        {
            k: _normalize_cache_entry(v)
            for k, v in cache.items()
            if k.startswith(f"{_CACHE_VERSION}|")
        }
    )
    return True


def _parse_coords(coords: str) -> tuple[float, float] | None:
    parts = coords.split(",", maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None


def _looks_like_coords(text: str) -> bool:
    return _parse_coords(text) is not None


def is_acceptable_location(name: str) -> bool:
    """地名是否适合写入 location（过滤残片与交通设施）。"""
    text = name.strip()
    if len(text) < 3:
        return False
    if text in _BAD_LANDMARKS or text in _GENERIC_LANDMARKS:
        return False
    if _looks_like_coords(text):
        return False
    # 三字「X公园 / X花园」多为截断残片
    if len(text) == 3 and text.endswith(("公园", "花园")):
        return False
    if "幼儿" in text and text.endswith("园") and len(text) <= 3:
        return False
    return not _is_noise_name(text)


def _trim_location_label(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if len(text) > _MAX_LOCATION_LEN:
        return text[:_MAX_LOCATION_LEN]
    return text


def _is_noise_name(name: str) -> bool:
    if not name or name in _GENERIC_LANDMARKS:
        return True
    return any(keyword in name for keyword in _NOISE_KEYWORDS)


_SKIP_TYPE_PREFIXES = ("12", "17", "13", "19")
_PREFER_TYPE_PREFIXES = ("11", "08", "14", "06", "07", "09")


def _type_rank(poi_type: str) -> int:
    poi_type = str(poi_type or "")
    
    if poi_type.isdigit():
        for prefix in _SKIP_TYPE_PREFIXES:
            if poi_type.startswith(prefix):
                return 100
        for idx, prefix in enumerate(_PREFER_TYPE_PREFIXES):
            if poi_type.startswith(prefix):
                return idx
        return 50
    
    for keyword in _SKIP_TYPE_KEYWORDS:
        if keyword in poi_type:
            return 100
    for idx, keyword in enumerate(_PREFER_TYPE_KEYWORDS):
        if keyword in poi_type:
            return idx
    return 50


def _distance_value(raw: object) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 9999.0


def _is_valid_landmark(name: str) -> bool:
    """园名类地标：3～10 字，排除截断残片与交通设施。"""
    text = name.strip()
    if len(text) < 3 or len(text) > 10:
        return False
    if text in _BAD_LANDMARKS:
        return False
    # 三字且以「公园」结尾的多为截断残片，如 长风公园 → 风公园
    if len(text) == 3 and text.endswith("公园"):
        return False
    if any(ch in text for ch in "号镇区市县省道路"):
        return False
    if re.search(r"[()（）]", text):
        return False
    return not _is_noise_name(text)


def _scan_landmarks_in_text(text: str, counts: Counter[str]) -> None:
    """在每个「园」位置取最长有效园名，避免 长风公园 → 风公园。"""
    segments = [text]
    if "(" in text or "（" in text:
        tail = re.split(r"[（(]", text)[-1].strip()
        if tail:
            segments.append(tail)

    for segment in segments:
        for idx, ch in enumerate(segment):
            if ch != "园":
                continue
            best = ""
            for length in range(2, min(10, idx + 1)):
                start = idx - length
                name = segment[start : idx + 1]
                if _is_valid_landmark(name) and len(name) > len(best):
                    best = name
            if best:
                counts[best] += 1


def _extract_landmark_from_texts(texts: list[str]) -> str:
    """从地址/POI 文本里提取地标，如 古猗园路 → 古猗园、长风公园。"""
    counts: Counter[str] = Counter()
    shop_pattern = r"[\(（]([\u4e00-\u9fff]{2,8})(?:店|馆|院|站)"

    for text in texts:
        if not text:
            continue
        _scan_landmarks_in_text(text, counts)
        for match in re.finditer(shop_pattern, text):
            name = match.group(1).strip()
            if _is_valid_landmark(name):
                counts[name] += 1

    if not counts:
        return ""
    # 同票选时优先更长、更完整的园名
    return sorted(counts.items(), key=lambda item: (-item[1], -len(item[0])))[0][0]


def _collect_context_texts(regeocode: dict) -> list[str]:
    texts: list[str] = []
    formatted = str(regeocode.get("formatted_address") or "").strip()
    if formatted:
        texts.append(formatted)

    comp = regeocode.get("addressComponent") or {}
    street = comp.get("streetNumber") or {}
    if isinstance(street, dict):
        for key in ("street", "number"):
            val = str(street.get(key) or "").strip()
            if val:
                texts.append(val)
    for key in ("township", "neighborhood"):
        block = comp.get(key) or {}
        if isinstance(block, dict):
            val = str(block.get("name") or "").strip()
            if val:
                texts.append(val)

    for aoi in regeocode.get("aois") or []:
        texts.append(str(aoi.get("name") or ""))
    for poi in regeocode.get("pois") or []:
        texts.append(str(poi.get("name") or ""))

    return texts


def _clean_poi_name(name: str) -> str:
    """保留 POI 原名（适度截断），不再硬抽两字园名。"""
    text = name.strip()
    if not text or not is_acceptable_location(text):
        return ""
    if _is_noise_name(text):
        return ""
    
    if "-" in text:
        for keyword in ("动物园", "公园", "植物园", "森林公园", "学校", "幼儿园"):
            idx = text.find(keyword)
            if idx >= 0:
                main_name = text[:idx + len(keyword)]
                if is_acceptable_location(main_name):
                    text = main_name
                    break
    
    for keyword in ("动物园", "公园", "植物园", "森林公园", "学校", "幼儿园"):
        if keyword in text:
            parts = text.split(keyword)
            if len(parts) >= 2 and len(parts[1]) <= 4:
                text = parts[0] + keyword
                break
    
    return _trim_location_label(text)


def _poi_name_score(name: str) -> int:
    score = 0
    if "公园" in name or "动物园" in name or "植物园" in name or "森林公园" in name:
        score += 10
    if "学校" in name or "小学" in name or "中学" in name or "幼儿园" in name:
        score += 10
    if "馆" in name and len(name) >= 4:
        score += 5
    if "医院" in name or "体育馆" in name or "图书馆" in name or "博物馆" in name:
        score += 5
    if "-" in name:
        score -= 5
    if len(name) >= 4:
        score += len(name)
    return score


def _pick_poi_name(regeocode: dict) -> str:
    candidates: list[tuple[int, int, float, int, str]] = []
    fallback_candidates: list[tuple[int, float, str]] = []

    for aoi in regeocode.get("aois") or []:
        name = _clean_poi_name(str(aoi.get("name", "")))
        if not name:
            continue
        aoi_type = str(aoi.get("type", ""))
        rank = _type_rank(aoi_type)
        score = _poi_name_score(name)
        distance = _distance_value(aoi.get("distance"))
        
        if rank >= 100:
            fallback_candidates.append((0, distance, name))
        else:
            candidates.append((0, rank, distance, score, name))

    for poi in regeocode.get("pois") or []:
        raw_name = str(poi.get("name", "")).strip()
        if not raw_name or _is_noise_name(raw_name):
            continue
        rank = _type_rank(poi.get("type", ""))
        name = _clean_poi_name(raw_name)
        if not name:
            continue
        score = _poi_name_score(name)
        distance = _distance_value(poi.get("distance"))
        
        if rank >= 100:
            fallback_candidates.append((1, distance, name))
        else:
            candidates.append((1, rank, distance, score, name))

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1], -item[3], item[2]))
        best_pref = candidates[0]
        
        if fallback_candidates:
            fallback_candidates.sort(key=lambda item: (item[0], item[1]))
            best_fallback = fallback_candidates[0]
            
            if best_fallback[1] < 50 and best_pref[2] > 100:
                return best_fallback[2]
            if best_pref[2] > 300 and best_fallback[1] < 150:
                return best_fallback[2]
        
        return best_pref[4]
    
    if fallback_candidates:
        fallback_candidates.sort(key=lambda item: (item[0], item[1]))
        return fallback_candidates[0][2]
    
    return ""


def _pick_admin_label(regeocode: dict) -> str:
    """区 + 街道/镇，或道路名。"""
    comp = regeocode.get("addressComponent") or {}
    district = str(comp.get("district") or "").strip()
    township = str(comp.get("township") or "").strip()
    street_block = comp.get("streetNumber") or {}
    street = ""
    if isinstance(street_block, dict):
        street = str(street_block.get("street") or "").strip()

    if street:
        label = f"{district}{street}" if district else street
        return _trim_location_label(label)
    if township:
        label = f"{district}{township}" if district and district not in township else township
        return _trim_location_label(label)
    if district:
        return _trim_location_label(district)
    return ""


def _pick_simple_location(regeocode: dict) -> str:
    # 优先完整 POI 名，其次行政区/道路，最后才考虑园名提取
    poi_name = _pick_poi_name(regeocode)
    if poi_name:
        return poi_name

    admin = _pick_admin_label(regeocode)
    if admin:
        return admin

    texts = _collect_context_texts(regeocode)
    landmark = _extract_landmark_from_texts(texts)
    if landmark and len(landmark) >= 4 and is_acceptable_location(landmark):
        return landmark

    formatted = str(regeocode.get("formatted_address") or "").strip()
    return _trim_formatted_address(formatted)


def _trim_formatted_address(address: str) -> str:
    text = address.strip()
    if not text:
        return ""

    for keyword in _NOISE_KEYWORDS:
        idx = text.find(keyword)
        if idx > 0:
            text = text[:idx]
            break

    text = re.sub(r"\d+号?", "", text)
    text = text.strip(" ,，-")
    if is_acceptable_location(text):
        return _trim_location_label(text)
    return _trim_location_label(text)


def _simplify_existing_location(location: str) -> str:
    """已写入 JSON 的地址：够长且合理则保留，不再硬截短。"""
    text = location.strip()
    if not text or _looks_like_coords(text):
        return text

    if len(text) >= 4 and is_acceptable_location(text):
        return _trim_location_label(text)

    trimmed = _trim_formatted_address(text)
    return trimmed or text


def extract_location_admin(regeocode: dict) -> LocationAdmin:
    """从高德 regeocode 提取省市区与完整地址。"""
    comp = regeocode.get("addressComponent") or {}
    return LocationAdmin(
        province=str(comp.get("province") or "").strip(),
        city=str(comp.get("city") or "").strip(),
        district=str(comp.get("district") or "").strip(),
        formatted_address=str(regeocode.get("formatted_address") or "").strip(),
    )


@dataclass(frozen=True)
class GeocodeResult:
    location: str
    location_admin: LocationAdmin


def _amap_reverse_geocode(lat: float, lon: float, api_key: str) -> GeocodeResult | None:
    global _last_request_at

    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_REQUEST_INTERVAL_SEC:
        time.sleep(_MIN_REQUEST_INTERVAL_SEC - elapsed)

    query = urllib.parse.urlencode(
        {
            "key": api_key,
            "location": f"{lon:.6f},{lat:.6f}",
            "extensions": "all",
            "radius": 1000,
            "output": "JSON",
        }
    )
    url = f"{AMAP_REGEO_URL}?{query}"
    request = urllib.request.Request(url)

    try:
        _last_request_at = time.monotonic()
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("高德逆地理编码请求失败: %s", exc)
        return None

    if payload.get("status") != "1":
        logger.warning(
            "高德逆地理编码返回错误: status=%s info=%s",
            payload.get("status"),
            payload.get("info"),
        )
        return None

    regeocode = payload.get("regeocode") or {}
    location = _pick_simple_location(regeocode)
    if not location:
        return None
    return GeocodeResult(
        location=location,
        location_admin=extract_location_admin(regeocode),
    )


def _finalize_geocode_result(result: GeocodeResult) -> GeocodeResult:
    """应用 location_canonical.json 别名兜底。"""
    from hub.shared.location_canonical import merge_location_admin, resolve_canonical_location

    new_loc, admin_tpl = resolve_canonical_location(result.location)
    if new_loc == result.location:
        return result
    admin = merge_location_admin(result.location_admin, admin_tpl)
    return GeocodeResult(location=new_loc, location_admin=admin)


def resolve_location_geocode(location: str) -> GeocodeResult:
    """坐标或已有地址 → 短地名 + 行政区划结构。"""
    location = location.strip()
    if not location:
        return GeocodeResult(location="", location_admin=empty_location_admin())

    if not _looks_like_coords(location):
        simplified = _simplify_existing_location(location)
        return _finalize_geocode_result(
            GeocodeResult(location=simplified, location_admin=empty_location_admin())
        )

    cache = _load_cache()
    key = _cache_key(location)
    if key in cache:
        entry = _normalize_cache_entry(cache[key])
        if _is_valid_cache_entry(entry):
            admin = entry.get("location_admin") or empty_location_admin()
            return _finalize_geocode_result(
                GeocodeResult(
                    location=str(entry.get("location") or ""),
                    location_admin=LocationAdmin(
                        province=str(admin.get("province", "")),
                        city=str(admin.get("city", "")),
                        district=str(admin.get("district", "")),
                        formatted_address=str(admin.get("formatted_address", "")),
                    ),
                )
            )
        logger.info("缓存地名不合格，删除并重算: %s → %s", key, entry.get("location"))
        cache.pop(key, None)
        _save_cache(cache)

    api_key = os.environ.get("AMAP_KEY", "").strip()
    if not api_key:
        logger.debug("未设置 AMAP_KEY，location 保留为坐标: %s", location)
        return GeocodeResult(location=location, location_admin=empty_location_admin())

    parsed = _parse_coords(location)
    if parsed is None:
        logger.warning("无法解析坐标: %s", location)
        return GeocodeResult(location=location, location_admin=empty_location_admin())

    lat, lon = parsed
    result = _amap_reverse_geocode(lat, lon, api_key)
    if result and result.location:
        result = _finalize_geocode_result(result)
        cache[key] = {
            "location": result.location,
            "location_admin": dict(result.location_admin),
        }
        _save_cache(cache)
        logger.info("逆地理编码: %s → %s", location, result.location)
        return result

    return GeocodeResult(location=location, location_admin=empty_location_admin())


def resolve_location(location: str) -> str:
    """坐标 → 简短地名；已是长地址则本地化简（兼容旧调用）。"""
    return resolve_location_geocode(location).location


def normalize_location_coords(coords: str) -> str:
    """坐标字符串 → 六位小数字符串，与缓存 key 一致。"""
    parsed = _parse_coords(coords.strip())
    if parsed is None:
        return ""
    return f"{parsed[0]:.6f},{parsed[1]:.6f}"


def list_cache_coords_by_location(location: str) -> list[str]:
    """缓存中某短地名下的全部坐标（已归一化）。"""
    target = location.strip()
    if not target:
        return []
    cache = _load_cache()
    coords: list[str] = []
    prefix = f"{_CACHE_VERSION}|"
    for key, value in cache.items():
        if not key.startswith(prefix):
            continue
        entry = _normalize_cache_entry(value)
        if str(entry.get("location") or "").strip() != target:
            continue
        part = key.split("|", maxsplit=1)[-1]
        normalized = normalize_location_coords(part)
        if normalized:
            coords.append(normalized)
    return coords


def _pick_spread_indices(total: int, pick: int) -> list[int]:
    if total <= 0:
        return []
    if pick >= total:
        return list(range(total))
    if pick <= 1:
        return [0]
    step = (total - 1) / (pick - 1)
    indices: list[int] = []
    seen: set[int] = set()
    for i in range(pick):
        idx = int(round(i * step))
        if idx not in seen:
            seen.add(idx)
            indices.append(idx)
    return indices


def _photo_sample_dict(row: Any) -> dict[str, Any]:
    source_path = str(row["source_path"] or "")
    path = Path(source_path)
    has_file = path.is_file()
    return {
        "photo_id": str(row["photo_id"] or ""),
        "timestamp": str(row["timestamp"] or ""),
        "location": str(row["location"] or ""),
        "location_coords": str(row["location_coords"] or ""),
        "source_path": str(path) if has_file else "",
        "has_file": has_file,
    }


def _photos_for_coords(conn: Any, coords: str, *, limit: int) -> list[dict[str, Any]]:
    key = normalize_location_coords(coords)
    if not key or limit <= 0:
        return []

    rows = conn.execute(
        """
        SELECT photo_id, timestamp, location, location_coords, source_path
        FROM photos
        WHERE location_coords = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (key, limit),
    ).fetchall()
    if rows:
        return [_photo_sample_dict(r) for r in rows]

    lat = key.split(",", maxsplit=1)[0]
    rows = conn.execute(
        """
        SELECT photo_id, timestamp, location, location_coords, source_path
        FROM photos
        WHERE location_coords != '' AND location_coords LIKE ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (f"{lat}%", max(limit * 8, 40)),
    ).fetchall()
    matched: list[dict[str, Any]] = []
    for row in rows:
        if normalize_location_coords(str(row["location_coords"] or "")) != key:
            continue
        matched.append(_photo_sample_dict(row))
        if len(matched) >= limit:
            break
    return matched


def sample_photos_for_geocode_cache(
    *,
    coords: str = "",
    location: str = "",
    limit: int = 6,
) -> dict[str, Any]:
    """按缓存坐标或短地名返回样本照片（供 Desk 核对地址）。"""
    from hub.shared.index_db import connect, init_db

    limit = max(1, min(limit, 20))
    coords = coords.strip()
    location = location.strip()
    if not coords and not location:
        return {
            "coords": "",
            "location": "",
            "sample_coords": [],
            "items": [],
            "photo_count": 0,
        }

    conn = connect(MEMORY_DB)
    init_db(conn)
    try:
        sample_coords: list[str] = []
        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        if coords:
            key = normalize_location_coords(coords)
            sample_coords = [key] if key else []
            for photo in _photos_for_coords(conn, key, limit=limit):
                if photo["photo_id"] in seen_ids:
                    continue
                seen_ids.add(photo["photo_id"])
                items.append({**photo, "cache_coords": key})
            photo_count = 0
            if key:
                photo_count = conn.execute(
                    "SELECT COUNT(*) FROM photos WHERE location_coords = ?",
                    (key,),
                ).fetchone()[0]
        else:
            all_coords = list_cache_coords_by_location(location)
            pick_coords = min(5, len(all_coords))
            indices = _pick_spread_indices(len(all_coords), pick_coords)
            sample_coords = [all_coords[i] for i in indices if i < len(all_coords)]
            per_coord = max(1, limit // max(len(sample_coords), 1))
            for coord in sample_coords:
                for photo in _photos_for_coords(conn, coord, limit=per_coord):
                    if photo["photo_id"] in seen_ids:
                        continue
                    seen_ids.add(photo["photo_id"])
                    items.append({**photo, "cache_coords": coord})
                    if len(items) >= limit:
                        break
                if len(items) >= limit:
                    break
            photo_count = 0
            if all_coords:
                placeholders = ",".join("?" * len(all_coords))
                photo_count = conn.execute(
                    f"SELECT COUNT(*) FROM photos WHERE location_coords IN ({placeholders})",
                    all_coords,
                ).fetchone()[0]

        return {
            "coords": normalize_location_coords(coords) if coords else "",
            "location": location,
            "sample_coords": sample_coords,
            "items": items[:limit],
            "photo_count": int(photo_count),
        }
    finally:
        conn.close()
