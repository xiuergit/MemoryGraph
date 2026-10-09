"""中国常用节假日 → 公历日期窗（供问答按假日筛出门事件）。

优先用国务院放假调休区间；未知年份回退到固定/近似窗。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

# 别名 → 规范名（长词优先匹配）
_HOLIDAY_ALIASES: tuple[tuple[str, str], ...] = (
    ("劳动节", "五一"),
    ("国庆节", "国庆"),
    ("国庆黄金周", "国庆"),
    ("十一黄金周", "国庆"),
    ("春节", "春节"),
    ("过年", "春节"),
    ("清明节", "清明"),
    ("端午节", "端午"),
    ("中秋节", "中秋"),
    ("元旦", "元旦"),
    ("国庆", "国庆"),
    ("五一", "五一"),
    ("十一", "国庆"),
    ("清明", "清明"),
    ("端午", "端午"),
    ("中秋", "中秋"),
)

_HOLIDAY_RE = re.compile(
    "|".join(re.escape(a) for a, _ in sorted(_HOLIDAY_ALIASES, key=lambda x: -len(x[0])))
)

# 已知年份的官方放假窗（含调休）；跨年用实际起止日。
# 键：规范名 → {年: (start_iso, end_iso)}
_OFFICIAL: dict[str, dict[int, tuple[str, str]]] = {
    "元旦": {
        2020: ("2020-01-01", "2020-01-01"),
        2021: ("2021-01-01", "2021-01-03"),
        2022: ("2022-01-01", "2022-01-03"),
        2023: ("2022-12-31", "2023-01-02"),
        2024: ("2023-12-30", "2024-01-01"),
        2025: ("2025-01-01", "2025-01-01"),
        2026: ("2026-01-01", "2026-01-03"),
    },
    "春节": {
        2020: ("2020-01-24", "2020-01-30"),
        2021: ("2021-02-11", "2021-02-17"),
        2022: ("2022-01-31", "2022-02-06"),
        2023: ("2023-01-21", "2023-01-27"),
        2024: ("2024-02-10", "2024-02-17"),
        2025: ("2025-01-28", "2025-02-04"),
        2026: ("2026-02-15", "2026-02-23"),
    },
    "清明": {
        2020: ("2020-04-04", "2020-04-06"),
        2021: ("2021-04-03", "2021-04-05"),
        2022: ("2022-04-03", "2022-04-05"),
        2023: ("2023-04-05", "2023-04-05"),
        2024: ("2024-04-04", "2024-04-06"),
        2025: ("2025-04-04", "2025-04-06"),
        2026: ("2026-04-04", "2026-04-06"),
    },
    "五一": {
        2020: ("2020-05-01", "2020-05-05"),
        2021: ("2021-05-01", "2021-05-05"),
        2022: ("2022-04-30", "2022-05-04"),
        2023: ("2023-04-29", "2023-05-03"),
        2024: ("2024-05-01", "2024-05-05"),
        2025: ("2025-05-01", "2025-05-05"),
        2026: ("2026-05-01", "2026-05-05"),
    },
    "端午": {
        2020: ("2020-06-25", "2020-06-27"),
        2021: ("2021-06-12", "2021-06-14"),
        2022: ("2022-06-03", "2022-06-05"),
        2023: ("2023-06-22", "2023-06-24"),
        2024: ("2024-06-08", "2024-06-10"),
        2025: ("2025-05-31", "2025-06-02"),
        2026: ("2026-06-19", "2026-06-21"),
    },
    "中秋": {
        2020: ("2020-10-01", "2020-10-08"),  # 与国庆合并
        2021: ("2021-09-19", "2021-09-21"),
        2022: ("2022-09-10", "2022-09-12"),
        2023: ("2023-09-29", "2023-10-06"),  # 与国庆合并
        2024: ("2024-09-15", "2024-09-17"),
        2025: ("2025-10-01", "2025-10-08"),  # 与国庆合并
        2026: ("2026-09-25", "2026-09-27"),
    },
    "国庆": {
        2020: ("2020-10-01", "2020-10-08"),
        2021: ("2021-10-01", "2021-10-07"),
        2022: ("2022-10-01", "2022-10-07"),
        2023: ("2023-09-29", "2023-10-06"),
        2024: ("2024-10-01", "2024-10-07"),
        2025: ("2025-10-01", "2025-10-08"),
        2026: ("2026-10-01", "2026-10-07"),
    },
}

# 未知年份的近似窗：month, start_day, duration_days（含首日）
_FALLBACK_SOLAR: dict[str, tuple[int, int, int]] = {
    "元旦": (1, 1, 3),
    "清明": (4, 4, 3),
    "五一": (5, 1, 5),
    "国庆": (10, 1, 7),
}

# 农历假日未知年：用近年窗口中位数近似（仅兜底）
_FALLBACK_ROUGH: dict[str, tuple[int, int, int]] = {
    "春节": (1, 25, 8),   # 约 1 月底起 8 天
    "端午": (6, 10, 3),
    "中秋": (9, 15, 3),
}


def extract_holiday(question: str) -> str:
    """从问句抽出规范假日名；无则空串。"""
    q = (question or "").strip()
    if not q:
        return ""
    m = _HOLIDAY_RE.search(q)
    if not m:
        return ""
    token = m.group(0)
    for alias, canonical in _HOLIDAY_ALIASES:
        if alias == token:
            return canonical
    return ""


def _add_days(iso: str, days: int) -> str:
    d = date.fromisoformat(iso[:10])
    return (d + timedelta(days=days)).isoformat()


def _fallback_range(holiday: str, year: int) -> tuple[str, str]:
    if holiday in _FALLBACK_SOLAR:
        month, day, dur = _FALLBACK_SOLAR[holiday]
        start = date(year, month, day)
        end = start + timedelta(days=dur - 1)
        return start.isoformat(), end.isoformat()
    if holiday in _FALLBACK_ROUGH:
        month, day, dur = _FALLBACK_ROUGH[holiday]
        # 春节可能跨年边界：钳到合法日
        try:
            start = date(year, month, day)
        except ValueError:
            start = date(year, month, 28)
        end = start + timedelta(days=dur - 1)
        return start.isoformat(), end.isoformat()
    # 未知：整年（调用方一般不会走到）
    return f"{year}-01-01", f"{year}-12-31"


def resolve_holiday_range(
    holiday: str,
    year: int | str,
    *,
    pad_days: int = 1,
) -> dict[str, Any]:
    """假日 + 年 → day_from / day_to（ISO）。

    pad_days: 前后各扩几天，兼顾提前出发 / 晚归。
    """
    name = (holiday or "").strip()
    try:
        y = int(year)
    except (TypeError, ValueError):
        y = date.today().year
    if not name:
        return {"holiday": "", "year": y, "day_from": "", "day_to": "", "label": ""}

    official = _OFFICIAL.get(name, {}).get(y)
    if official:
        day_from, day_to = official
    else:
        day_from, day_to = _fallback_range(name, y)

    if pad_days > 0:
        day_from = _add_days(day_from, -pad_days)
        day_to = _add_days(day_to, pad_days)

    label = f"{y}年{name}"
    return {
        "holiday": name,
        "year": y,
        "day_from": day_from,
        "day_to": day_to,
        "label": label,
    }


def default_holiday_year(holiday: str, *, today: date | None = None) -> int:
    """未写年份时：若今年该假日已过（含进行中）用今年，否则用去年。"""
    today = today or date.today()
    y = today.year
    rng = resolve_holiday_range(holiday, y, pad_days=0)
    day_from = rng.get("day_from") or ""
    if not day_from:
        return y
    try:
        start = date.fromisoformat(day_from[:10])
    except ValueError:
        return y
    # 假日开始日已到 → 问的是今年；否则问去年
    if today >= start:
        return y
    return y - 1
