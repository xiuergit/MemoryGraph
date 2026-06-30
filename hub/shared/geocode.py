"""逆地理编码：EXIF 坐标 → 中文地址（高德 Web 服务 API）。"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from hub.shared.config import DATA_DIR

logger = logging.getLogger(__name__)

GEOCODE_CACHE_FILE = DATA_DIR / ".geocode_cache.json"
AMAP_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"

# 高德免费额度下保守限速，避免瞬时并发
_MIN_REQUEST_INTERVAL_SEC = 0.2
_last_request_at = 0.0


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


def _parse_coords(coords: str) -> tuple[float, float] | None:
    """解析 '纬度,经度' 字符串。"""
    parts = coords.split(",", maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None


def _amap_reverse_geocode(lat: float, lon: float, api_key: str) -> str:
    """调用高德逆地理编码，成功返回 formatted_address，失败返回空字符串。"""
    global _last_request_at

    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_REQUEST_INTERVAL_SEC:
        time.sleep(_MIN_REQUEST_INTERVAL_SEC - elapsed)

    # 高德要求：经度在前，纬度在后
    query = urllib.parse.urlencode(
        {
            "key": api_key,
            "location": f"{lon:.6f},{lat:.6f}",
            "extensions": "base",
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
    address = regeocode.get("formatted_address") or ""
    return str(address).strip()


def resolve_location(coords: str) -> str:
    """将 EXIF 坐标解析为可读地址。

    优先级：本地缓存 → 高德 API（需环境变量 AMAP_KEY）→ 退回原始坐标。
    """
    coords = coords.strip()
    if not coords:
        return ""

    cache = _load_cache()
    if coords in cache:
        return cache[coords]

    api_key = os.environ.get("AMAP_KEY", "").strip()
    if not api_key:
        logger.debug("未设置 AMAP_KEY，location 保留为坐标: %s", coords)
        return coords

    parsed = _parse_coords(coords)
    if parsed is None:
        logger.warning("无法解析坐标: %s", coords)
        return coords

    lat, lon = parsed
    address = _amap_reverse_geocode(lat, lon, api_key)
    if address:
        cache[coords] = address
        _save_cache(cache)
        logger.info("逆地理编码: %s → %s", coords, address)
        return address

    return coords
