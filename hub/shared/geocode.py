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
from pathlib import Path

from hub.shared.config import DATA_DIR

logger = logging.getLogger(__name__)

GEOCODE_CACHE_FILE = DATA_DIR / ".geocode_cache.json"
AMAP_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
_CACHE_VERSION = "3"

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

_PREFER_TYPE_PREFIXES = ("11", "08", "14", "06")
_SKIP_TYPE_PREFIXES = ("12", "13", "15", "19")  # 商务住宅、政府机构、交通、公司企业


def _load_cache() -> dict[str, str]:
    if not GEOCODE_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(GEOCODE_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 geocode 缓存失败: %s", exc)
    return {}


def _save_cache(cache: dict[str, str]) -> None:
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


def _clean_landmark(name: str) -> bool:
    if not name or len(name) > 4:
        return False
    if any(ch in name for ch in "号镇区市县省道路"):
        return False
    return not _is_noise_name(name)


def _scan_landmarks_in_text(text: str, counts: Counter[str]) -> None:
    """扫描文本中所有 XX园 候选，允许重叠匹配。"""
    for idx, ch in enumerate(text):
        if ch != "园":
            continue
        for length in range(2, 5):
            start = idx - length
            if start < 0:
                continue
            name = text[start : idx + 1]
            if _clean_landmark(name):
                counts[name] += 1


def _extract_landmark_from_texts(texts: list[str]) -> str:
    """从地址/POI 文本里提取简短地标，如 古猗园路 → 古猗园。"""
    counts: Counter[str] = Counter()
    shop_pattern = r"[\(（]([\u4e00-\u9fff]{2,8})(?:店|馆|院|站)"

    for text in texts:
        if not text:
            continue
        _scan_landmarks_in_text(text, counts)
        for match in re.finditer(shop_pattern, text):
            name = match.group(1).strip()
            if _clean_landmark(name):
                counts[name] += 1

    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: (-item[1], len(item[0])))[0][0]


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


def _pick_poi_name(regeocode: dict) -> str:
    candidates: list[tuple[int, int, float, str]] = []

    for aoi in regeocode.get("aois") or []:
        name = str(aoi.get("name", "")).strip()
        if not name or _is_noise_name(name):
            continue
        candidates.append((0, 0, _distance_value(aoi.get("distance")), name))

    for poi in regeocode.get("pois") or []:
        name = str(poi.get("name", "")).strip()
        if not name or _is_noise_name(name):
            continue
        rank = _type_rank(poi.get("type", ""))
        if rank >= 100:
            continue
        candidates.append((1, rank, _distance_value(poi.get("distance")), name))

    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def _pick_simple_location(regeocode: dict) -> str:
    texts = _collect_context_texts(regeocode)

    landmark = _extract_landmark_from_texts(texts)
    if landmark:
        return landmark

    poi_name = _pick_poi_name(regeocode)
    if poi_name:
        return poi_name

    comp = regeocode.get("addressComponent") or {}
    township = str(comp.get("township") or "").strip()
    district = str(comp.get("district") or "").strip()
    if township:
        return township
    if district:
        return district

    formatted = str(regeocode.get("formatted_address") or "").strip()
    return _shorten_formatted_address(formatted)


def _shorten_formatted_address(address: str) -> str:
    landmark = _extract_landmark_from_texts([address])
    if landmark:
        return landmark

    text = address.strip()
    if not text:
        return ""

    for keyword in _NOISE_KEYWORDS:
        idx = text.find(keyword)
        if idx > 0:
            text = text[:idx]
            break

    text = re.sub(r"\d+号?", "", text)
    return text.strip(" ,，-")


def _simplify_existing_location(location: str) -> str:
    """已写入 JSON 的长地址，本地规则化简，不再请求 API。"""
    text = location.strip()
    if not text or _looks_like_coords(text):
        return text

    landmark = _extract_landmark_from_texts([text])
    if landmark:
        return landmark

    simplified = _shorten_formatted_address(text)
    return simplified or text


def _amap_reverse_geocode(lat: float, lon: float, api_key: str) -> str:
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
        return ""

    if payload.get("status") != "1":
        logger.warning(
            "高德逆地理编码返回错误: status=%s info=%s",
            payload.get("status"),
            payload.get("info"),
        )
        return ""

    regeocode = payload.get("regeocode") or {}
    return _pick_simple_location(regeocode)


def resolve_location(location: str) -> str:
    """坐标 → 简短地名；已是长地址则本地化简。

    优先级：缓存 → 高德 API（AMAP_KEY）→ 本地化简 → 原样返回。
    """
    location = location.strip()
    if not location:
        return ""

    if not _looks_like_coords(location):
        return _simplify_existing_location(location)

    cache = _load_cache()
    key = _cache_key(location)
    if key in cache:
        return cache[key]

    api_key = os.environ.get("AMAP_KEY", "").strip()
    if not api_key:
        logger.debug("未设置 AMAP_KEY，location 保留为坐标: %s", location)
        return location

    parsed = _parse_coords(location)
    if parsed is None:
        logger.warning("无法解析坐标: %s", location)
        return location

    lat, lon = parsed
    address = _amap_reverse_geocode(lat, lon, api_key)
    if address:
        cache[key] = address
        _save_cache(cache)
        logger.info("逆地理编码: %s → %s", location, address)
        return address

    return location
