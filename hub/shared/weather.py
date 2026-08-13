"""天气：timestamp + GPS → Open-Meteo Historical（不传原图）。

气温/降水用日汇总；天气状况用**拍摄时刻所在小时**（避免日级 weather_code
取「当天最严重」——大晴天里两小时毛毛雨会整日记成雨天）。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hub.shared.config import DATA_DIR, JSON_INDENT, MEMORY_DIR, SCHEMA_VERSION
from hub.shared.schema import Weather
from hub.shared.utils import json_matches_year

logger = logging.getLogger(__name__)

WEATHER_CACHE_FILE = DATA_DIR / ".weather_cache.json"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DEFAULT_TIMEZONE = "Asia/Shanghai"
# 约 1 km 格点，同日同格共享一条缓存 / 一次 API
_GRID_DECIMALS = 2
# v2：缓存存整日 hourly，按拍摄小时取状况
_CACHE_VERSION = "2"
_MIN_REQUEST_INTERVAL_SEC = 0.15
_last_request_at = 0.0

# WMO Weather interpretation codes → 中文
_WMO_CONDITION: dict[int, str] = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "毛毛雨",
    55: "毛毛雨",
    56: "冻毛毛雨",
    57: "冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴冰雹",
    99: "雷阵雨伴冰雹",
}


@dataclass
class WeatherBackfillStats:
    total: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    failed_files: list[str] = field(default_factory=list)


def condition_from_wmo(code: int) -> str:
    if code in _WMO_CONDITION:
        return _WMO_CONDITION[code]
    if 1 <= code <= 3:
        return "多云"
    if 50 <= code < 60:
        return "毛毛雨"
    if 60 <= code < 70:
        return "雨"
    if 70 <= code < 80:
        return "雪"
    if 80 <= code < 90:
        return "阵雨"
    if code >= 95:
        return "雷阵雨"
    return f"天气码{code}"


def parse_coords(coords: str) -> tuple[float, float] | None:
    text = (coords or "").strip()
    if not text or "," not in text:
        return None
    lat_s, _, lon_s = text.partition(",")
    try:
        lat = float(lat_s.strip())
        lon = float(lon_s.strip())
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def date_from_timestamp(timestamp: str, *, timezone: str = DEFAULT_TIMEZONE) -> str:
    """从 ISO 时间戳取当地日历日；无 offset 时按 timezone 日历日（首版用前 10 字符）。"""
    text = (timestamp or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        # 已有本地墙钟日期（项目 EXIF 多为无 offset 的本地时间）
        return text[:10]
    _ = timezone
    return ""


def hour_from_timestamp(timestamp: str) -> int | None:
    """本地墙钟小时 0–23；无法解析则 None（回退白天众数）。"""
    text = (timestamp or "").strip()
    # 2026-07-24T16:03:03 或 2026-07-24 16:03:03
    if len(text) >= 13 and text[10] in "T ":
        try:
            hour = int(text[11:13])
        except ValueError:
            return None
        if 0 <= hour <= 23:
            return hour
    return None


def weather_cache_key(date: str, lat: float, lon: float) -> str:
    return (
        f"{_CACHE_VERSION}|{date}|"
        f"{round(lat, _GRID_DECIMALS):.{_GRID_DECIMALS}f}|"
        f"{round(lon, _GRID_DECIMALS):.{_GRID_DECIMALS}f}"
    )


def _soften_trace_drizzle(code: int, precip_mm: float | None) -> int:
    """毛毛雨码（51/53/55）在再分析里极易被微量降水触发，体感常仍是干的。

    小时降水 < 1mm：降为「多云」，不写毛毛雨。
    ≥ 1mm 或未知降水：保留毛毛雨（未知时偏保守仍降为多云）。
    小雨及以上（61+）不在此处理。
    """
    if code not in (51, 53, 55):
        return code
    if precip_mm is not None and precip_mm >= 1.0:
        return code
    return 2  # 多云


def _code_at_hour(
    hourly_codes: list[int],
    hour: int | None,
    *,
    hourly_precip: list[float] | None = None,
) -> int:
    if not hourly_codes:
        return 0
    if hour is not None and 0 <= hour < len(hourly_codes):
        code = int(hourly_codes[hour])
        precip = None
        if hourly_precip is not None and hour < len(hourly_precip):
            precip = float(hourly_precip[hour])
        return _soften_trace_drizzle(code, precip)
    # 无具体时刻：用白天 9–17 点众数（不是「最严重」）
    day_slice = []
    for h in range(9, 18):
        if h >= len(hourly_codes):
            break
        precip = None
        if hourly_precip is not None and h < len(hourly_precip):
            precip = float(hourly_precip[h])
        day_slice.append(_soften_trace_drizzle(int(hourly_codes[h]), precip))
    if day_slice:
        return Counter(day_slice).most_common(1)[0][0]
    mid = min(12, len(hourly_codes) - 1)
    return int(hourly_codes[mid])


def empty_weather() -> Weather:
    return Weather(
        date="",
        code=0,
        condition="",
        temp_max_c=None,
        temp_min_c=None,
        temp_mean_c=None,
        precipitation_mm=None,
        source="",
        timezone=DEFAULT_TIMEZONE,
    )


def weather_from_dict(raw: dict[str, Any] | None) -> Weather | None:
    if not raw or not isinstance(raw, dict):
        return None
    date = str(raw.get("date") or "").strip()
    condition = str(raw.get("condition") or "").strip()
    if not date or not condition:
        return None
    try:
        code = int(raw.get("code", 0))
    except (TypeError, ValueError):
        code = 0
    return Weather(
        date=date,
        code=code,
        condition=condition,
        temp_max_c=_as_optional_float(raw.get("temp_max_c")),
        temp_min_c=_as_optional_float(raw.get("temp_min_c")),
        temp_mean_c=_as_optional_float(raw.get("temp_mean_c")),
        precipitation_mm=_as_optional_float(raw.get("precipitation_mm")),
        source=str(raw.get("source") or "open-meteo"),
        timezone=str(raw.get("timezone") or DEFAULT_TIMEZONE),
    )


def weather_is_filled(data: dict[str, Any]) -> bool:
    return weather_from_dict(data.get("weather") if isinstance(data.get("weather"), dict) else None) is not None


def format_weather_label(
    condition: str,
    *,
    temp_min_c: float | None = None,
    temp_max_c: float | None = None,
    temp_mean_c: float | None = None,
) -> str:
    """列表/事件用短文案，如「小雨 · 26–37℃」。"""
    text = (condition or "").strip()
    if not text:
        return ""
    if temp_min_c is not None and temp_max_c is not None:
        return f"{text} · {round(temp_min_c)}–{round(temp_max_c)}℃"
    if temp_mean_c is not None:
        return f"{text} · {round(temp_mean_c)}℃"
    return text


def _as_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_cache() -> dict[str, dict[str, Any]]:
    if not WEATHER_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(WEATHER_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 weather 缓存失败: %s", exc)
    return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    WEATHER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    WEATHER_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_REQUEST_INTERVAL_SEC:
        time.sleep(_MIN_REQUEST_INTERVAL_SEC - elapsed)
    _last_request_at = time.monotonic()


def _parse_hourly_ints(raw: list[Any] | None) -> list[int]:
    out: list[int] = []
    for item in raw or []:
        try:
            out.append(int(item) if item is not None else 0)
        except (TypeError, ValueError):
            out.append(0)
    return out


def _parse_hourly_floats(raw: list[Any] | None) -> list[float]:
    out: list[float] = []
    for item in raw or []:
        try:
            out.append(float(item) if item is not None else 0.0)
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def _is_day_bundle(raw: dict[str, Any] | None) -> bool:
    if not raw or not isinstance(raw, dict):
        return False
    # 须含 hourly_precip，否则微量毛毛雨无法校正
    return (
        bool(raw.get("date"))
        and isinstance(raw.get("hourly_codes"), list)
        and isinstance(raw.get("hourly_precip"), list)
        and len(raw.get("hourly_codes") or []) > 0
    )


def _fetch_day_bundle(
    lat: float,
    lon: float,
    date: str,
    *,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, Any] | None:
    """一次请求：日气温/降水 + 24 小时 weather_code（写入缓存）。"""
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": date,
        "end_date": date,
        "daily": ",".join(
            [
                "temperature_2m_max",
                "temperature_2m_min",
                "temperature_2m_mean",
                "precipitation_sum",
            ]
        ),
        "hourly": "weather_code,precipitation",
        "timezone": timezone,
    }
    url = f"{ARCHIVE_URL}?{urllib.parse.urlencode(params)}"
    _throttle()
    request = urllib.request.Request(url, headers={"User-Agent": "MemoryGraph/weather"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Open-Meteo 请求失败 %s: %s", date, exc)
        return None

    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    hourly = payload.get("hourly") or {}
    hourly_codes = _parse_hourly_ints(hourly.get("weather_code"))
    hourly_precip = _parse_hourly_floats(hourly.get("precipitation"))
    if not times or not hourly_codes:
        logger.warning("Open-Meteo 无日/小时数据: %s (%.2f,%.2f)", date, lat, lon)
        return None

    return {
        "date": str(times[0]),
        "temp_max_c": _as_optional_float((daily.get("temperature_2m_max") or [None])[0]),
        "temp_min_c": _as_optional_float((daily.get("temperature_2m_min") or [None])[0]),
        "temp_mean_c": _as_optional_float((daily.get("temperature_2m_mean") or [None])[0]),
        "precipitation_mm": _as_optional_float(
            (daily.get("precipitation_sum") or [None])[0]
        ),
        "hourly_codes": hourly_codes,
        "hourly_precip": hourly_precip,
        "source": "open-meteo",
        "timezone": str(payload.get("timezone") or timezone),
    }


def _weather_from_bundle(bundle: dict[str, Any], hour: int | None) -> Weather:
    codes = [int(c) for c in bundle.get("hourly_codes") or []]
    precip = [float(x) for x in bundle.get("hourly_precip") or []]
    code = _code_at_hour(codes, hour, hourly_precip=precip or None)
    return Weather(
        date=str(bundle.get("date") or ""),
        code=code,
        condition=condition_from_wmo(code),
        temp_max_c=_as_optional_float(bundle.get("temp_max_c")),
        temp_min_c=_as_optional_float(bundle.get("temp_min_c")),
        temp_mean_c=_as_optional_float(bundle.get("temp_mean_c")),
        precipitation_mm=_as_optional_float(bundle.get("precipitation_mm")),
        source=str(bundle.get("source") or "open-meteo"),
        timezone=str(bundle.get("timezone") or DEFAULT_TIMEZONE),
    )


def _get_day_bundle(
    lat: float,
    lon: float,
    date: str,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    cache: dict[str, dict[str, Any]] | None = None,
    persist_cache: bool = True,
) -> dict[str, Any] | None:
    key = weather_cache_key(date, lat, lon)
    own_cache = cache is None
    store = _load_cache() if own_cache else cache
    assert store is not None

    bundle = store.get(key) if _is_day_bundle(store.get(key)) else None
    if bundle is None:
        bundle = _fetch_day_bundle(lat, lon, date, timezone=timezone)
        if bundle is None:
            return None
        store[key] = bundle
        if persist_cache and own_cache:
            _save_cache(store)
        elif persist_cache and cache is not None:
            _save_cache(cache)
    return bundle


def resolve_weather(
    coords: str,
    timestamp: str,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    cache: dict[str, dict[str, Any]] | None = None,
    persist_cache: bool = True,
) -> Weather | None:
    """按坐标 + 拍摄时刻解析天气；同日同格缓存整日 hourly，状况取拍摄小时。"""
    parsed = parse_coords(coords)
    date = date_from_timestamp(timestamp, timezone=timezone)
    if not parsed or not date:
        return None

    lat, lon = parsed
    bundle = _get_day_bundle(
        lat,
        lon,
        date,
        timezone=timezone,
        cache=cache,
        persist_cache=persist_cache,
    )
    if bundle is None:
        return None
    return _weather_from_bundle(bundle, hour_from_timestamp(timestamp))


def resolve_daytime_weather(
    coords: str,
    date: str,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    cache: dict[str, dict[str, Any]] | None = None,
    persist_cache: bool = True,
) -> Weather | None:
    """事件列表用：按拍摄日白天众数（9–17 点），同日同城不因时段拆成多种天气。"""
    parsed = parse_coords(coords)
    day = (date or "").strip()[:10]
    if not parsed or len(day) < 10:
        return None
    lat, lon = parsed
    bundle = _get_day_bundle(
        lat,
        lon,
        day,
        timezone=timezone,
        cache=cache,
        persist_cache=persist_cache,
    )
    if bundle is None:
        return None
    return _weather_from_bundle(bundle, None)


def apply_weather_to_memory_dict(
    data: dict[str, Any],
    *,
    only_empty: bool = True,
    timezone: str = DEFAULT_TIMEZONE,
    cache: dict[str, dict[str, Any]] | None = None,
    persist_cache: bool = True,
) -> str:
    """写入 data['weather']。返回 updated | skipped | failed。"""
    if only_empty and weather_is_filled(data):
        return "skipped"

    coords = str(data.get("location_coords") or "").strip()
    timestamp = str(data.get("timestamp") or "").strip()
    if not coords or not timestamp:
        return "skipped"

    weather = resolve_weather(
        coords,
        timestamp,
        timezone=timezone,
        cache=cache,
        persist_cache=persist_cache,
    )
    if weather is None:
        # 有坐标有时间却查不到 → 计失败（近期数据延迟等）
        return "failed"

    data["weather"] = dict(weather)
    # 触碰过天气字段时升到当前协议小版本（旧 1.0/1.1 仍可读）
    ver = str(data.get("schema_version") or "")
    if ver in ("", "1.0", "1.1"):
        data["schema_version"] = SCHEMA_VERSION
    return "updated"


def backfill_weather_folder(
    memory_dir: Path | None = None,
    *,
    only_empty: bool = True,
    limit: int | None = None,
    year: str = "",
    timezone: str = DEFAULT_TIMEZONE,
) -> WeatherBackfillStats:
    """遍历 memory/*.json，按日+GPS 补全 weather（不需原图）。"""
    memory_path = Path(memory_dir or MEMORY_DIR)
    stats = WeatherBackfillStats()
    if not memory_path.is_dir():
        logger.error("memory 目录不存在: %s", memory_path)
        return stats

    cache = _load_cache()
    json_files = sorted(memory_path.glob("*.json"))
    stats.total = 0

    for json_path in json_files:
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("读取失败 %s: %s", json_path.name, exc)
            stats.failed += 1
            stats.failed_files.append(json_path.name)
            continue

        if year and not json_matches_year(data, json_path, year):
            continue

        if limit is not None and stats.updated >= limit:
            logger.info("已达本次上限 %d 张，停止。", limit)
            break

        stats.total += 1
        result = apply_weather_to_memory_dict(
            data,
            only_empty=only_empty,
            timezone=timezone,
            cache=cache,
            persist_cache=False,
        )
        if result == "updated":
            try:
                json_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=JSON_INDENT) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.error("写入失败 %s: %s", json_path.name, exc)
                stats.failed += 1
                stats.failed_files.append(json_path.name)
                continue
            stats.updated += 1
            if stats.updated % 50 == 0:
                _save_cache(cache)
                logger.info("天气补全进度: %d 张…", stats.updated)
        elif result == "skipped":
            stats.skipped += 1
        else:
            stats.failed += 1
            stats.failed_files.append(json_path.name)

    _save_cache(cache)
    logger.info(
        "天气补全统计: 扫描=%d, 更新=%d, 跳过=%d, 失败=%d（缓存 %s）",
        stats.total,
        stats.updated,
        stats.skipped,
        stats.failed,
        WEATHER_CACHE_FILE,
    )
    if only_empty and stats.skipped and stats.updated == 0:
        logger.info(
            "提示：已有 weather 的照片默认跳过。要用拍摄小时重算覆盖，请加 --refill"
        )
    elif only_empty and stats.skipped > stats.updated * 5 and stats.updated < 20:
        logger.info(
            "提示：大量跳过是因为已有 weather。覆盖旧结果请加 --refill"
        )
    return stats
