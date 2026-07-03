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

from hub.shared.config import DATA_DIR
from hub.shared.schema import LocationAdmin, empty_location_admin

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
        "幼儿园",
    }
)

_PREFER_TYPE_PREFIXES = ("11", "08", "14", "06")
_SKIP_TYPE_PREFIXES = ("12", "13", "15", "19")  # 商务住宅、政府机构、交通、公司企业


def _load_cache() -> dict[str, dict[str, Any]]:
    if not GEOCODE_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(GEOCODE_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for key, value in data.items():
            if isinstance(value, dict) and "location" in value:
                out[str(key)] = value
            elif isinstance(value, str):
                out[str(key)] = {"location": value, "location_admin": empty_location_admin()}
        return out
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 geocode 缓存失败: %s", exc)
    return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    GEOCODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GEOCODE_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cache_key(coords: str) -> str:
    return f"{_CACHE_VERSION}|{coords}"


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
    if "幼儿" in text and text.endswith("园"):
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


def _type_rank(poi_type: str) -> int:
    poi_type = str(poi_type or "")
    for prefix in _SKIP_TYPE_PREFIXES:
        if poi_type.startswith(prefix):
            return 100
    for idx, prefix in enumerate(_PREFER_TYPE_PREFIXES):
        if poi_type.startswith(prefix):
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
    return _trim_location_label(text)


def _pick_poi_name(regeocode: dict) -> str:
    candidates: list[tuple[int, int, float, str]] = []

    for aoi in regeocode.get("aois") or []:
        name = _clean_poi_name(str(aoi.get("name", "")))
        if not name:
            continue
        candidates.append((0, 0, _distance_value(aoi.get("distance")), name))

    for poi in regeocode.get("pois") or []:
        raw_name = str(poi.get("name", "")).strip()
        if not raw_name or _is_noise_name(raw_name):
            continue
        rank = _type_rank(poi.get("type", ""))
        if rank >= 100:
            continue
        name = _clean_poi_name(raw_name)
        if not name:
            continue
        candidates.append((1, rank, _distance_value(poi.get("distance")), name))

    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


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


def resolve_location_geocode(location: str) -> GeocodeResult:
    """坐标或已有地址 → 短地名 + 行政区划结构。"""
    location = location.strip()
    if not location:
        return GeocodeResult(location="", location_admin=empty_location_admin())

    if not _looks_like_coords(location):
        simplified = _simplify_existing_location(location)
        return GeocodeResult(location=simplified, location_admin=empty_location_admin())

    cache = _load_cache()
    key = _cache_key(location)
    if key in cache:
        entry = cache[key]
        admin = entry.get("location_admin") or empty_location_admin()
        return GeocodeResult(
            location=str(entry.get("location") or ""),
            location_admin=LocationAdmin(
                province=str(admin.get("province", "")),
                city=str(admin.get("city", "")),
                district=str(admin.get("district", "")),
                formatted_address=str(admin.get("formatted_address", "")),
            ),
        )

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
