"""记忆问答 Agent：规则路由 → 查库 → Ollama 组织回答（失败则模板兜底）。"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
import calendar
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from hub.shared.config import (
    MEMORY_DB,
    OLLAMA_BASE_URL,
    OLLAMA_CHAT_ENABLED,
    OLLAMA_CHAT_MODEL,
    OLLAMA_TIMEOUT,
)
from hub.shared.family import (
    default_ask_person,
    load_family_members,
    match_persons_in_text,
    resolve_person,
)
from hub.shared.photo_links import enrich_photo_dict, format_photo_link
from hub.shared.evidence import (
    build_evidence,
    evidence_id_samples,
    media_noun_for_mix,
)
from hub.shared.holidays import (
    default_holiday_year,
    extract_holiday,
    resolve_holiday_range,
)
from hub.shared.index_db import connect, init_db
from hub.shared.query import gather_facts

logger = logging.getLogger(__name__)

_RECENT_RE = re.compile(r"最近|近期|最新")
_PHOTO_RE = re.compile(r"照片|相片|图片|拍的|拍了")
_AGE_RE = re.compile(r"几岁|多大|年龄|年岁")
_PLACE_RE = re.compile(r"在哪|哪里|哪儿|去过|玩过|地方|地点")
_CITIES_RE = re.compile(r"哪些城市|什么城市|哪些省|什么省|哪些省份|去过.*城市|城市.*去过")
_STATS_RE = re.compile(r"多少|几张|几个|一共有|一共|总共|统计|有多少")
_AGE_RANK_RE = re.compile(
    r"最多|最长|常去|待得|待过|待的|哪个地方|哪.{0,6}地方.*最|最常去"
)
_PHOTO_LIST_RE = re.compile(
    r"(?:最后|最近|最新)\s*\d+\s*张"
    r"|列出\s*(?:最后|最近|最新)?\s*\d*\s*张"
    r"|\d+\s*张(?:照片|相片|图片)?"
)
_PLACES_LIST_RE = re.compile(
    r"哪些地方|什么地方|去过哪些(?!城市)|(?:去过|玩过)(?:的)?地方"
)
_GROUP_PHOTO_RE = re.compile(r"合影|合照|同框")
# 「和谁合影最多 / 哪个人合照最多」——同框人物排行（勿落到地点排行）
_COMPANION_RANK_RE = re.compile(
    r"(?:合影|合照|同框).{0,12}(?:最多|比较多|较多)|"
    r"(?:最多|比较多|较多).{0,12}(?:合影|合照|同框)|"
    r"和(?:哪个人|谁|哪个).{0,10}(?:合影|合照|同框)|"
    r"(?:哪个人|谁|哪些人).{0,10}(?:合影|合照|同框).{0,8}(?:最|比较多|较多)|"
    r"(?:合影|合照|同框).{0,8}(?:最多的人|最多的是谁|和谁最多)"
)
# 「最近3个月 / 近半年 / 最近两周」——相对时间窗（合影排行等复合条件）
_REL_TIME_CN_NUM = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}
_REL_TIME_WINDOW_RE = re.compile(
    r"(?:最近|近期|近)\s*"
    r"(?:"
    r"(?P<half>半)\s*年|"
    r"(?P<year_one>一)\s*年|"
    r"(?P<n_year>\d+|[一二两三四五六七八九十]+)\s*年|"
    r"(?P<n_month>\d+|[一二两三四五六七八九十]+)\s*个?\s*月|"
    r"(?P<n_week>\d+|[一二两三四五六七八九十]+)\s*(?:个)?(?:星期|周)|"
    r"(?P<n_day>\d+|[一二两三四五六七八九十]+)\s*天|"
    r"(?P<week_one>一)?\s*(?:个)?(?:星期|周)"
    r")"
)
_PEAK_DAY_RE = re.compile(r"哪天的|哪一天|哪天.*最多|照片最多|最多.*哪天|一天.*最多")
_EMOTION_CTX_RE = re.compile(r"表情|情绪|emotion", re.IGNORECASE)
_TERM_QUESTION_RE = re.compile(r"有.*吗|有没有|没有.*吗|吗[？?]?$|是不是")
_FIRST_WHEN_RE = re.compile(r"第一次|首次|最早|什么时候|何时|哪天|哪年")
_OUTING_RE = re.compile(r"出去玩|出门玩|出门了哪些|出去了哪些|最近出门|最近出去|几趟出门|几次出门|几次活动")
_STORY_RE = re.compile(r"故事")
# 复合口语：开心吗 / 见了谁 / 依据是什么（追问）
_HAPPY_ASK_RE = re.compile(r"开心|高兴|快乐|好玩|愉快|玩得开|玩的开")
_WHO_MET_RE = re.compile(
    r"见了哪些人|见到谁|见了谁|见过谁|和谁一起|同行(?:的人)?|哪些人(?:一起|同行)?"
)
_BASIS_ASK_RE = re.compile(
    r"依据(?:是什么|呢)?|根据什么|怎么知道|证据(?:是什么|呢|在哪)?|"
    r"为什么这么[说答]|从哪(?:里)?看出来|凭什么"
)
_FOLLOW_MORE_RE = re.compile(r"^(?:还有吗|还有呢|还有没有|继续吧?|再说说)$")
# 画作作品集（不含「故事」；绘本/壁画等由 query 侧过滤）
_ARTWORK_RE = re.compile(
    r"作品集|画过的画|画的画|哪些画|什么画|画作|儿童画|涂鸦|"
    r"画了什么|画了哪些|绘画作品|画画作品"
)
_PAINTING_PROCESS_RE = re.compile(r"在画画|正在画画|画画的照片|绘画课")
_HOME_TIMELINE_RE = re.compile(
    r"住过|住在哪|住哪|搬过|迁居|换过家|哪个家|家住哪|住址|"
    r"呆的时间最|待的时间最|呆最久|待最久|"
    r"在哪(?:里|儿)?(?:呆|待)(?:的|得)?(?:时间)?最|"
    r"哪个地方(?:呆|待)(?:的|得)?(?:时间)?最"
)
_SEASON_RE = re.compile(r"([春夏秋冬])(?:天|季)?")
_YEAR_NUM_RE = re.compile(r"(20\d{2})\s*年")
_REL_YEAR_RE = re.compile(r"(今|去|前)年")
_OUTINGS_PERIOD_HINT_RE = re.compile(
    r"出去玩|出门玩|出门|出游|出去了|出门了|出门清单|列出.*出门|出门.*列出|按年|按季"
)
# 假日 +「去哪玩了」类：不要求字面「出门」
_HOLIDAY_OUTINGS_RE = re.compile(
    r"去哪|在哪|哪儿|哪里|哪里玩|哪儿玩|去了哪|玩了哪|去玩|玩了|"
    r"出去玩|出门玩|出门|出游|出去了|出门了|去了"
)
_EMOTION_TERM_HINTS = (
    "哭泣", "哭闹", "哭", "微笑", "笑", "开心", "高兴", "快乐", "平静", "专注",
    "好奇", "安静", "温和", "惊讶", "生气", "难过", "委屈",
)
_CN_AGE_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_PLACE_PLACEHOLDERS = frozenset({
    "哪里", "哪儿", "什么地方", "哪些地方", "哪里玩", "哪儿玩", "的地方",
    "哪了", "哪儿了", "哪里了", "哪", "谁", "哪些人", "和谁", "有谁",
    "最多", "最少", "最长", "最久",
})
_KEYWORD_STOP = frozenset({
    "", "照片", "相片", "图片", "最近", "最新", "一些", "一下", "什么",
    "哪些", "哪个", "哪", "吗", "呢", "啊", "呀", "嘛", "的", "了", "着",
    "相关", "有关", "看看", "看下", "找找", "搜搜", "地方", "地点",
})
_ASK_EXAMPLES = (
    "面面最近去哪了",
    "最近出去玩了哪些",
    "去年国庆去哪里玩了",
    "面面骑车",
    "面面过生日",
    "有没有轮滑",
    "面面哭",
    "面面的画作",
    "面面几岁了",
    "一共多少张照片",
    "面面去动物园是什么时候",
    "面面哪些人去过动物园",
    "面面和谁去过动物园，分别是什么时候",
    "妈妈和面面的合影",
    "面面和哪个人的合影最多",
    "面面最近3个月和谁合影比较多",
    "面面最近三个月和抱补去了哪些地方",
    "面面住过哪些地方",
)

_WHY_RE = re.compile(r"为什么|为啥|为何|怎么会")

# 结构化排名/列表类意图：模板已完整，LLM 润色易漏项或编造细节
# 统计 / 排行类走模板（可复现、不靠润色）；叙事回顾类可走 LLM（仍锁 facts）
_LLM_SKIP_INTENTS = frozenset({
    "library_stats",
    "group_photos",
    "person_age_place_rank",
    "person_place_rank",
    "person_places_visited",
    "person_cities_visited",
    "person_emotion_place_rank",
    "person_peak_day",
    "recent_photos",
    "person_home_timeline",
    "person_artwork",
    "keyword_first",
    "term_lookup",
    "term_first",
    "person_companion_rank",
    "person_at_place",
    "unknown",
    "explain_basis",
})


@dataclass
class AskResult:
    intent: str
    facts: dict[str, Any]
    answer: str
    used_llm: bool
    photo_links: bool = True
    follow_ups: list[str] = field(default_factory=list)
    turn_context: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


def _links_enabled(facts: dict[str, Any]) -> bool:
    return bool(facts.get("_photo_links", True))


def _photo_ref(photo: dict[str, Any] | None, *, facts: dict[str, Any]) -> str:
    if not photo:
        return ""
    return format_photo_link(enrich_photo_dict(photo), enabled=_links_enabled(facts))


def _enrich_facts_photos(facts: dict[str, Any]) -> None:
    for key in ("photos", "sample_photos"):
        items = facts.get(key)
        if isinstance(items, list):
            facts[key] = [enrich_photo_dict(p) for p in items]
    for key in ("photo", "first_visit", "last_visit"):
        item = facts.get(key)
        if isinstance(item, dict):
            facts[key] = enrich_photo_dict(item)
    # person_recent_places 等：带 photo_id 的地点样例
    places = facts.get("places")
    if isinstance(places, list):
        facts["places"] = [
            enrich_photo_dict(p) if isinstance(p, dict) and p.get("photo_id") else p
            for p in places
        ]


def _all_person_names() -> list[str]:
    names = [m.name for m in load_family_members().values() if m.name]
    return sorted({n for n in names if n and not n.startswith("unk_")}, key=len, reverse=True)


def _extract_person(question: str, *, allow_default: bool = True) -> str:
    # 「第一次叫妈妈」里的妈妈是宾语，不是提问主语
    cleaned = question
    for name in sorted(_all_person_names(), key=len, reverse=True):
        if not name:
            continue
        cleaned = cleaned.replace(f"叫{name}", " ")
        cleaned = cleaned.replace(f"喊{name}", " ")
    matched = match_persons_in_text(cleaned)
    if matched:
        return matched[0].name
    if allow_default:
        return default_ask_person()
    return ""


def _extract_group_persons(question: str) -> list[str]:
    """从问句中按出现顺序提取多个家庭成员名。"""
    return [m.name for m in match_persons_in_text(question)]


def _is_group_photo_question(question: str, persons: list[str]) -> bool:
    if len(persons) < 2:
        return False
    # 「和抱补去了哪些地方」是地点列表，不是合影清单
    if re.search(r"地方|地点|去哪|在哪|哪儿|哪里", question):
        return False
    if _GROUP_PHOTO_RE.search(question):
        return True
    if re.search(r"和", question) and (
        _PHOTO_RE.search(question) or re.search(r"有哪些|哪些|列出", question)
    ):
        return True
    return False


def _is_places_list_question(question: str) -> bool:
    """「去过哪些地方 / 去了哪些地方 / 什么地方」。"""
    if _PLACES_LIST_RE.search(question):
        return True
    return bool(re.search(r"去了哪些|去了什么地方|都去了哪", question))


def _extract_age_years(question: str) -> int | None:
    match = re.search(r"(\d+)\s*岁", question)
    if match:
        return int(match.group(1))
    match = re.search(r"([一二两三四五六七八九十])\s*岁", question)
    if match:
        return _CN_AGE_DIGITS.get(match.group(1))
    return None


def _extract_emotion_term(question: str) -> str:
    """提取表情/情绪词；若仅为人物名的一部分（如「笑笑」里的「笑」）则跳过。"""
    person_names: set[str] = set()
    for member in match_persons_in_text(question):
        person_names.add(member.name)
        if member.person_id:
            person_names.add(member.person_id)
    for hint in _EMOTION_TERM_HINTS:
        if hint not in question:
            continue
        if any(hint in name and hint != name for name in person_names):
            continue
        return hint
    return ""


def _wants_emotion_term_lookup(question: str, emotion_term: str) -> bool:
    """表情检索：有没有/照片/表情上下文，或「面面哭」「为什么哭」短句。

    「笑的最多的地方」等排行句不在此列，留给 person_emotion_place_rank。
    """
    if not emotion_term:
        return False
    if re.search(r"最多|最长|常去", question) and re.search(r"地方|地点", question):
        return False
    if _EMOTION_CTX_RE.search(question) or _TERM_QUESTION_RE.search(question) or _PHOTO_RE.search(question):
        return True
    if _WHY_RE.search(question):
        return True
    rest = question
    for name in sorted(_all_person_names(), key=len, reverse=True):
        if name:
            rest = rest.replace(name, "")
    rest = rest.replace(emotion_term, "")
    rest = re.sub(
        r"(?:的)?(?:照片|相片|图片)|有没有|看看|找找|搜搜|一下|"
        r"几次|多少次|了|的|吗|呢|啊|呀|嘛|？|\?|\s+",
        "",
        rest,
    )
    return rest == ""


def _extract_place_query(question: str) -> str:
    patterns = (
        r"去(?:过)?\s*(.+?)(?:是什么时候|是何时|几时|几次|吗)",
        r"在\s*(.+?)(?:去过|玩过|几次|的照片)",
        r"去(?:过)?\s*(.+?)(?:玩过|待过)",
        r"去(?:过)?\s*(.+?)(?:是几岁|几岁|多大|多少岁)",
        r"在\s*(.+?)(?:是几岁|几岁|多大|多少岁)",
        # 「哪些人去过动物园 / 和谁去过公园」
        r"(?:哪些人|和谁|谁|有谁).{0,8}去(?:过)?\s*(.+?)$",
        r"去(?:过)?\s*(.+?).{0,8}(?:哪些人|和谁|有谁|谁)",
        # 「去过动物园」落句
        r"去(?:过)?\s*(.+?)$",
    )
    for pattern in patterns:
        match = re.search(pattern, question)
        if not match:
            continue
        place = match.group(1).strip()
        for name in _all_person_names():
            place = place.replace(name, "")
        place = re.sub(r"[？?，,。\s]", "", place)
        place = place.removesuffix("是").strip()
        place = place.removeprefix("的").strip()
        place = re.sub(r"^过+", "", place).strip()
        place = re.sub(r"^了+", "", place).strip()
        place = re.sub(r"(玩过|去过|待过|几次|几趟)+$", "", place).strip()
        # 「动物园，分别是什么时候」→ 去掉时间尾缀，避免抽成「动物园分别」
        place = re.sub(
            r"(?:分别)?(?:是)?(?:什么时候|何时|几时).*$",
            "",
            place,
        ).strip()
        place = re.sub(r"分别$", "", place).strip()
        # 去掉「哪些人」残留
        place = re.sub(r"^(?:哪些人|和谁|有谁|谁)+", "", place).strip()
        place = re.sub(r"(?:哪些人|和谁|有谁|谁)+$", "", place).strip()
        # 「去了哪些地方」落句勿当成具体地名
        if re.search(r"哪些地方|什么地方|哪里|哪儿", place):
            continue
        if (
            place
            and place not in _PLACE_PLACEHOLDERS
            and len(place) <= 20
            and not place.startswith("哪")
        ):
            return place
    return ""


def _is_place_when_question(question: str, place_query: str) -> bool:
    """「去动物园是什么时候 / 第一次去动物园」——按地点查，勿走 keyword_first。"""
    if not place_query:
        return False
    if re.search(r"去(?:过)?\s*.+?(?:是什么时候|是何时|几时)", question):
        return True
    if re.search(r"(?:什么时候|何时).{0,12}去(?:过|的)?", question):
        return True
    if re.search(r"(?:第一次|首次|最早).{0,8}去(?:过)?", question):
        return True
    return False


def _is_companions_at_place_question(question: str) -> bool:
    """「面面哪些人去过动物园 / 和谁去过公园」——问同框人物，不是最近地点。"""
    return bool(
        re.search(
            r"哪些人|和谁|有谁|谁一起|一起去|同去|都有谁|还有谁",
            question,
        )
    )


def _is_companion_rank_question(question: str) -> bool:
    """「面面和哪个人合影最多 / 和谁合照最多」——同框排行，不是地点排行。"""
    if re.search(r"地方|地点|哪里|哪儿|去过|去哪|常去", question):
        return False
    return bool(_COMPANION_RANK_RE.search(question))


def _parse_rel_time_number(token: str) -> int | None:
    raw = (token or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    if raw in _REL_TIME_CN_NUM:
        return _REL_TIME_CN_NUM[raw]
    if raw.startswith("十") and len(raw) == 2:
        ones = _REL_TIME_CN_NUM.get(raw[1])
        return 10 + ones if ones is not None else None
    if raw.endswith("十") and len(raw) == 2:
        tens = _REL_TIME_CN_NUM.get(raw[0])
        return tens * 10 if tens is not None else None
    return None


def _shift_months(day: date, months: int) -> date:
    """向前（months>0）或向后偏移整月，日期钳在当月最后一天。"""
    y = day.year
    m = day.month - months
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(day.day, last))


def _extract_relative_time_window(
    question: str,
    *,
    today: date | None = None,
) -> dict[str, str]:
    """解析「最近3个月 / 近半年 / 最近两周」→ since(YYYY-MM-DD) + period_label。

    无明确相对时间窗时返回空 dict（全库、不按时间裁剪）。
    """
    match = _REL_TIME_WINDOW_RE.search(question or "")
    if not match:
        return {}
    now = today or date.today()
    if match.group("half"):
        since = _shift_months(now, 6)
        return {"since": since.isoformat(), "period_label": "最近半年"}
    if match.group("year_one"):
        since = _shift_months(now, 12)
        return {"since": since.isoformat(), "period_label": "最近一年"}
    n_year = match.group("n_year")
    if n_year:
        n = _parse_rel_time_number(n_year)
        if n and 1 <= n <= 20:
            since = _shift_months(now, n * 12)
            label = f"最近{n}年" if str(n_year).isdigit() else f"最近{n_year}年"
            return {"since": since.isoformat(), "period_label": label}
    n_month = match.group("n_month")
    if n_month:
        n = _parse_rel_time_number(n_month)
        if n and 1 <= n <= 36:
            since = _shift_months(now, n)
            label = f"最近{n}个月" if str(n_month).isdigit() else f"最近{n_month}个月"
            return {"since": since.isoformat(), "period_label": label}
    n_week = match.group("n_week")
    if n_week:
        n = _parse_rel_time_number(n_week)
        if n and 1 <= n <= 52:
            since = now - timedelta(days=n * 7)
            label = f"最近{n}周" if str(n_week).isdigit() else f"最近{n_week}周"
            return {"since": since.isoformat(), "period_label": label}
    n_day = match.group("n_day")
    if n_day:
        n = _parse_rel_time_number(n_day)
        if n and 1 <= n <= 366:
            since = now - timedelta(days=n)
            label = f"最近{n}天" if str(n_day).isdigit() else f"最近{n_day}天"
            return {"since": since.isoformat(), "period_label": label}
    if match.group("week_one") is not None or (
        not any(
            match.group(k)
            for k in ("half", "year_one", "n_year", "n_month", "n_week", "n_day")
        )
        and ("周" in match.group(0) or "星期" in match.group(0))
    ):
        since = now - timedelta(days=7)
        return {"since": since.isoformat(), "period_label": "最近一周"}
    return {}


def _detect_stats_focus(question: str) -> str:
    if re.search(r"字段|分布|每个|全覆盖", question):
        return "fields"
    if re.search(r"表情|emotion", question, re.IGNORECASE):
        return "emotion"
    if re.search(r"场景|scene|描述", question, re.IGNORECASE):
        return "scene"
    if re.search(r"人脸|脸部|识别到", question):
        return "face"
    if re.search(r"地点|位置|在哪", question):
        return "location"
    return "all"


def _extract_photo_limit(question: str, default: int = 10, *, max_limit: int = 50) -> int:
    match = re.search(r"(\d+)\s*张", question)
    if match:
        return max(1, min(int(match.group(1)), max_limit))
    match = re.search(r"列出\s*(\d+)", question)
    if match:
        return max(1, min(int(match.group(1)), max_limit))
    return default


def _route_photo_limit(question: str) -> int:
    """证据图张数：未写「N张 / 列出N」→ 0=全量；写了则按用户数。"""
    if re.search(r"\d+\s*张|列出\s*\d+", question):
        return _extract_photo_limit(question, default=40, max_limit=5000)
    return 0


def _extract_year(question: str) -> str:
    match = _YEAR_NUM_RE.search(question)
    if match:
        return match.group(1)
    rel = _REL_YEAR_RE.search(question)
    if not rel:
        return ""
    today_year = date.today().year
    token = rel.group(1)
    if token == "今":
        return str(today_year)
    if token == "去":
        return str(today_year - 1)
    return str(today_year - 2)


def _extract_season(question: str) -> str:
    # 去掉假日词，避免「春节」命中「春」
    q = question or ""
    holiday = extract_holiday(q)
    if holiday:
        for token in ("春节", "过年", "清明节", "清明", "中秋节", "中秋"):
            q = q.replace(token, " ")
    match = _SEASON_RE.search(q)
    return match.group(1) if match else ""


def _wants_holiday_outings(question: str, holiday: str) -> bool:
    """假日问句是否应按出门事件回答（相对「国庆的照片」按日期窗搜图）。"""
    if not holiday:
        return False
    q = question or ""
    # 明确要照片且无「去哪/出门」→ 按放假日期窗搜图，不靠 tags 里的「国庆」
    if re.search(r"照片|相片|图片", q) and not _HOLIDAY_OUTINGS_RE.search(q):
        return False
    if _OUTINGS_PERIOD_HINT_RE.search(q) or _HOLIDAY_OUTINGS_RE.search(q):
        return True
    # 「去年国庆」「2024国庆」裸问 → 列该假日出门
    if _extract_year(q) or _REL_YEAR_RE.search(q):
        return True
    return False


def _holiday_media_params(question: str) -> dict[str, Any] | None:
    """「2023年国庆相关照片」→ 假日日期窗；抽不出则 None。"""
    holiday = extract_holiday(question)
    if not holiday:
        return None
    if _wants_holiday_outings(question, holiday):
        return None
    q = question or ""
    if not (_PHOTO_RE.search(q) or "相关" in q):
        return None
    hp = _holiday_period_params(q, holiday)
    params: dict[str, Any] = {
        "person": _extract_person(q, allow_default=False),
        "query": str(hp.get("period_label") or f"{hp.get('year') or ''}年{holiday}"),
        "limit": _route_photo_limit(q),
    }
    params.update(hp)
    return params


def _holiday_period_params(question: str, holiday: str) -> dict[str, Any]:
    year = _extract_year(question)
    if not year:
        year = str(default_holiday_year(holiday))
    rng = resolve_holiday_range(holiday, year)
    return {
        "holiday": holiday,
        "year": str(rng.get("year") or year),
        "day_from": str(rng.get("day_from") or ""),
        "day_to": str(rng.get("day_to") or ""),
        "period_label": str(rng.get("label") or f"{year}年{holiday}"),
        "season": "",
    }


def _wants_recent_photo_list(question: str) -> bool:
    if _PHOTO_LIST_RE.search(question):
        return True
    return bool(
        re.search(r"列出", question)
        and (_PHOTO_RE.search(question) or re.search(r"\d+\s*张", question))
    )


def _is_pure_recent_photo_list(question: str) -> bool:
    """「最近10张 / 列出最后5张」；「面面轮滑20张」不算。"""
    if not _wants_recent_photo_list(question):
        return False
    if re.search(r"最近|最后|最新", question):
        return True
    # 仅「照片」「N张照片」且抽不出主题词
    kw = _extract_keyword_query(re.sub(r"\d+\s*张", "", question))
    return not kw


def _clean_keyword_term(raw: str) -> str:
    term = re.sub(r"[？?，,。！!\s]", "", (raw or "")).strip()
    term = term.strip("的了吗呢啊呀嘛")
    # 「第一次轮滑」→「轮滑」；时间词留给 keyword_first 路由
    term = re.sub(r"^(?:的)?(?:第一次|首次|最早)+", "", term)
    term = re.sub(r"(?:第一次|首次|最早)$", "", term)
    term = re.sub(r"什么时候|何时|哪天|哪年", "", term)
    term = re.sub(r"^(?:有关|关于)+", "", term)
    # 「有没有生日的照片」捕获组可能仍带「的照片」
    term = re.sub(r"(?:的)?(?:照片|相片|图片)$", "", term)
    if not term or term in _KEYWORD_STOP or term in _PLACE_PLACEHOLDERS:
        return ""
    if len(term) > 20:
        return ""
    if term in _EMOTION_TERM_HINTS:
        return ""
    return term


def _extract_keyword_query(question: str) -> str:
    """从「有没有X / 搜X / X的照片 / 面面骑车」等句式提取关键词。"""
    q = question.strip()
    # 「叫妈妈 / 喊爸爸」整词保留（勿先删掉人名）
    for name in sorted(_all_person_names(), key=len, reverse=True):
        if not name:
            continue
        for verb in ("叫", "喊"):
            token = f"{verb}{name}"
            if token in q:
                return token

    # 只去掉问句主语人名，保留其它称谓
    subject = _extract_person(question, allow_default=False) or default_ask_person()
    if subject and subject in q:
        q = q.replace(subject, " ", 1)
    q = re.sub(r"\s+", " ", q).strip()

    patterns = (
        r"有没有\s*(.+?)(?:吗|嘛|呢|？|\?|$)",
        r"(?<![没])有\s*(.+?)吗",
        r"搜(?:索|一?下)?\s*(.+)$",
        r"找(?:一?下|找)?\s*(.+)$",
        r"(.+?)的照片",
        r"照片里(?:有|带)\s*(.+?)(?:吗|嘛|呢|？|\?|$)",
        r"有关\s*(.+?)(?:的照片|吗|嘛|呢|？|\?|$)",
        r"关于\s*(.+?)(?:的照片|吗|嘛|呢|？|\?|$)",
        r"带\s*(.+?)的(?:照片|图)",
        r"(?:第一次|首次|最早)\s*(.+)$",
        r"(.+?)(?:第一次|首次|最早)",
    )
    for pattern in patterns:
        match = re.search(pattern, q)
        if not match:
            continue
        term = _clean_keyword_term(match.group(1))
        if not term or term == subject:
            continue
        return term

    # 「面面骑自行车 / 面面轮滑20张」：去掉人名与张数后的剩余词
    remainder = re.sub(
        r"(?:的)?(?:照片|相片|图片)|有没有|看看|找找|搜搜|一下|吗|呢|啊|呀|嘛|？|\?",
        "",
        q,
    )
    remainder = re.sub(r"\d+\s*张", "", remainder)
    remainder = re.sub(r"第一次|首次|最早|什么时候|何时|哪天|哪年", "", remainder)
    remainder = _clean_keyword_term(remainder)
    if (
        remainder
        and remainder != subject
        and not re.search(r"最近|哪里|哪儿|几岁|多少|合影|合照|住过|出门", remainder)
    ):
        return remainder
    return ""


def _unknown_answer() -> str:
    lines = ["暂时无法理解这个问题。可以试试："]
    for ex in _ASK_EXAMPLES:
        lines.append(f"  · {ex}")
    return "\n".join(lines)


def _detect_recap_extras(question: str) -> dict[str, bool]:
    """一句里是否还问了「开心吗 / 见了谁」。"""
    q = question or ""
    return {
        "want_emotion": bool(_HAPPY_ASK_RE.search(q)),
        "want_companions": bool(_WHO_MET_RE.search(q)),
    }


def _wants_period_recap(question: str) -> bool:
    extras = _detect_recap_extras(question)
    return extras["want_emotion"] or extras["want_companions"]


def _context_has_period(context: dict[str, Any] | None) -> bool:
    if not context:
        return False
    return bool(
        (context.get("day_from") or context.get("day_to") or context.get("period_label"))
        and (context.get("last_intent") or context.get("intent"))
    )


def _route_followup(
    question: str,
    context: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """短追问：挂上一轮时段 / 意图。无匹配返回 None。"""
    q = (question or "").strip()
    if not q or not context:
        return None

    last_intent = str(context.get("last_intent") or context.get("intent") or "")
    person = str(context.get("person") or "")
    day_from = str(context.get("day_from") or "")
    day_to = str(context.get("day_to") or "")
    period_label = str(context.get("period_label") or "")
    year = str(context.get("year") or "")
    season = str(context.get("season") or "")
    holiday = str(context.get("holiday") or "")

    base_period = {
        "person": person or _extract_person(q),
        "day_from": day_from,
        "day_to": day_to,
        "period_label": period_label,
        "year": year,
        "season": season,
        "holiday": holiday,
        "limit": 40,
        "photo_limit": 40,
    }

    if _BASIS_ASK_RE.search(q) or q in {"依据", "证据", "为什么"}:
        return "explain_basis", {
            **base_period,
            "last_intent": last_intent,
            "last_answer": str(context.get("last_answer") or ""),
            "basis_summary": context.get("basis_summary") or {},
        }

    if _HAPPY_ASK_RE.search(q) and (
        _context_has_period(context)
        or last_intent in ("outings_by_period", "period_recap", "recent_outings", "outings_at_place")
    ):
        return "period_emotion", base_period

    if _WHO_MET_RE.search(q) and (
        _context_has_period(context)
        or last_intent
        in (
            "outings_by_period",
            "period_recap",
            "recent_outings",
            "outings_at_place",
            "person_recent_places",
        )
    ):
        return "period_companions", base_period

    if _FOLLOW_MORE_RE.match(q) and last_intent:
        # 「还有吗」：同一意图再答一轮（仍用上一轮 params）
        reused = dict(context.get("last_params") or {})
        if not reused:
            reused = {k: v for k, v in base_period.items() if v}
        reused.setdefault("person", person)
        return last_intent if last_intent != "explain_basis" else "outings_by_period", reused

    return None


def _period_params_from_question(q: str) -> dict[str, Any] | None:
    """从问句抽年/季/假日时段参数；抽不出返回 None。"""
    holiday = extract_holiday(q)
    if holiday and _wants_holiday_outings(q, holiday):
        params: dict[str, Any] = {"person": _extract_person(q), "limit": 40}
        params.update(_holiday_period_params(q, holiday))
        return params
    year = _extract_year(q)
    season = _extract_season(q)
    if (year or season) and _OUTINGS_PERIOD_HINT_RE.search(q):
        return {
            "person": _extract_person(q),
            "year": year or (str(date.today().year) if season else ""),
            "season": season,
            "limit": 40,
            "period_label": "".join(
                filter(
                    None,
                    [
                        f"{year}年" if year else "",
                        f"{season}季" if season else "",
                    ],
                )
            )
            or "该时段",
            "day_from": "",
            "day_to": "",
            "holiday": "",
        }
    return None


def _intent_label_cn(intent: str) -> str:
    labels = {
        "outings_by_period": "按时段查出门事件",
        "period_recap": "按时段汇总出门、情绪与同行人",
        "period_emotion": "按时段看照片里的表情词",
        "period_companions": "按时段统计同框人物",
        "recent_outings": "查最近出门事件",
        "outings_at_place": "按地点查出门事件",
        "companions_at_place": "按地点统计同框人物",
        "keyword_search": "按关键词搜记忆（照片/视频/音频）",
        "person_recent_places": "查最近去过的地点",
        "story_lookup": "搜故事",
        "explain_basis": "解释上一轮答案依据",
    }
    return labels.get(intent, intent or "未知意图")


def _build_basis_summary(intent: str, params: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    events = facts.get("events") or []
    photos = facts.get("photos") or facts.get("sample_photos") or []
    companions = facts.get("companions") or []
    evidence = facts.get("_evidence") if isinstance(facts.get("_evidence"), dict) else None
    if evidence is None:
        evidence = build_evidence(facts)
    id_samples = evidence_id_samples(evidence)
    return {
        "intent": intent,
        "intent_label": _intent_label_cn(intent),
        "person": facts.get("person") or params.get("person") or "",
        "period_label": facts.get("period_label") or params.get("period_label") or "",
        "day_from": facts.get("day_from") or params.get("day_from") or "",
        "day_to": facts.get("day_to") or params.get("day_to") or "",
        "event_count": int(facts.get("total") or len(events) or 0),
        "photo_count": int(facts.get("photo_count") or len(photos) or 0),
        "media_count": int((evidence.get("counts") or {}).get("media") or 0),
        "by_media_type": dict((evidence.get("counts") or {}).get("by_media_type") or {}),
        "story_count": int((evidence.get("counts") or {}).get("stories") or 0),
        "companion_count": int(facts.get("companion_count") or len(companions) or 0),
        "with_emotion": int(facts.get("with_emotion") or 0),
        "emotion_top": [
            f"{e.get('term')}×{e.get('count')}"
            for e in (facts.get("emotion_breakdown") or [])[:3]
            if isinstance(e, dict)
        ],
        "places_sample": [
            _outing_place_name(ev)
            for ev in events[:5]
            if _outing_place_name(ev)
        ],
        "media_ids": id_samples.get("media_ids") or [],
        "event_ids": id_samples.get("event_ids") or [],
        "story_ids": id_samples.get("story_ids") or [],
    }


def _build_turn_context(
    intent: str,
    params: dict[str, Any],
    facts: dict[str, Any],
    answer: str,
) -> dict[str, Any]:
    basis = _build_basis_summary(intent, params, facts)
    slim_params = {
        k: params[k]
        for k in (
            "person",
            "year",
            "season",
            "holiday",
            "day_from",
            "day_to",
            "period_label",
            "limit",
            "place",
            "want_emotion",
            "want_companions",
            "photo_limit",
        )
        if k in params and params[k] not in (None, "")
    }
    return {
        "last_intent": intent,
        "intent": intent,
        "last_params": slim_params,
        "person": basis["person"],
        "period_label": basis["period_label"],
        "day_from": basis["day_from"],
        "day_to": basis["day_to"],
        "year": str(params.get("year") or facts.get("year") or ""),
        "season": str(params.get("season") or facts.get("season") or ""),
        "holiday": str(params.get("holiday") or facts.get("holiday") or ""),
        "last_answer": (answer or "")[:500],
        "basis_summary": basis,
    }


def _build_follow_ups(intent: str, facts: dict[str, Any], params: dict[str, Any]) -> list[str]:
    """答后可点的继续问芯片（伪多轮）。"""
    chips: list[str] = []
    period = str(facts.get("period_label") or params.get("period_label") or "").strip()
    has_period = bool(
        period
        or facts.get("day_from")
        or params.get("day_from")
        or intent
        in (
            "outings_by_period",
            "period_recap",
            "recent_outings",
            "outings_at_place",
            "period_emotion",
            "period_companions",
        )
    )

    if intent == "explain_basis":
        return ["见了谁？", "开心吗？"] if has_period else []

    if has_period:
        if intent not in ("period_companions",):
            chips.append("见了谁？")
        if intent not in ("period_emotion",):
            chips.append("开心吗？")
        chips.append("依据是什么？")
    elif intent in ("companions_at_place", "person_recent_places", "keyword_search"):
        chips.append("依据是什么？")
    elif intent == "story_lookup":
        chips.append("依据是什么？")

    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for c in chips:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:4]


def route_intent(
    question: str,
    context: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    q = question.strip()
    # 排行/出门等非证据图意图自带默认；证据图意图用 _route_photo_limit（默认全量）
    params: dict[str, Any] = {"limit": 10}

    follow = _route_followup(q, context or {})
    if follow:
        return follow

    if _wants_recent_photo_list(q) and _is_pure_recent_photo_list(q):
        params["person"] = _extract_person(q)
        params["limit"] = _route_photo_limit(q)
        if params["limit"] <= 0 and params.get("person"):
            params["list_all"] = True
        return "recent_photos", params

    if _STORY_RE.search(q):
        params["query"] = re.sub(r"故事|讲讲|什么|有没有|吗|？|\?", "", q).strip()
        params["person"] = _extract_person(q)
        return "story_lookup", params

    if _ARTWORK_RE.search(q) or _PAINTING_PROCESS_RE.search(q):
        params["person"] = _extract_person(q)
        params["limit"] = _route_photo_limit(q)
        params["works_only"] = not bool(_PAINTING_PROCESS_RE.search(q))
        return "person_artwork", params

    if _HOME_TIMELINE_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_home_timeline", params

    age_years = _extract_age_years(q)
    if age_years is not None and _AGE_RANK_RE.search(q):
        params["person"] = _extract_person(q)
        params["age_years"] = age_years
        return "person_age_place_rank", params

    if _STATS_RE.search(q):
        # 全库统计不默认某人；「面面多少张」仍抽人名
        params["person"] = _extract_person(q, allow_default=False)
        params["focus"] = _detect_stats_focus(q)
        return "library_stats", params

    group_persons = _extract_group_persons(q)
    # 「面面和抱补去了哪些地方」须先于合影（否则「和+哪些」会误入 group_photos）
    if len(group_persons) >= 2 and _is_places_list_question(q):
        params["person"] = group_persons[0]
        params["companions"] = group_persons[1:]
        params["limit"] = 20
        params.update(_extract_relative_time_window(q))
        return "person_places_visited", params

    if _is_group_photo_question(q, group_persons):
        params["persons"] = group_persons
        params["limit"] = _route_photo_limit(q)
        return "group_photos", params

    # 「和谁合影最多」须在地点排行（「最多」）之前
    if _is_companion_rank_question(q):
        params["person"] = _extract_person(q)
        params["limit"] = _extract_photo_limit(q, default=12, max_limit=50)
        params["photo_limit"] = _route_photo_limit(q)
        params.update(_extract_relative_time_window(q))
        return "person_companion_rank", params

    emotion_term = _extract_emotion_term(q)
    if emotion_term and _FIRST_WHEN_RE.search(q):
        params["person"] = _extract_person(q)
        params["term"] = emotion_term
        params["term_type"] = "emotion"
        return "term_first", params

    # 「去动物园是什么时候」须在 keyword_first 之前（否则会抽成「去动物园是」）
    place_query = _extract_place_query(q)

    # 「和谁去过动物园，分别是什么时候」——同框+到访日，须先于 person_at_place
    if place_query and _is_companions_at_place_question(q):
        params["person"] = _extract_person(q)
        params["place"] = place_query
        params["limit"] = _route_photo_limit(q)
        if _FIRST_WHEN_RE.search(q) or "分别" in q:
            params["focus"] = "when"
        return "companions_at_place", params

    if _FIRST_WHEN_RE.search(q) and _is_place_when_question(q, place_query):
        params["person"] = _extract_person(q)
        params["place"] = place_query
        params["limit"] = _route_photo_limit(q)
        if _AGE_RE.search(q):
            params["focus"] = "age"
        elif re.search(r"吗[？?]?$", q):
            params["focus"] = "yesno"
        return "person_at_place", params

    if _FIRST_WHEN_RE.search(q):
        keyword = _extract_keyword_query(q)
        if keyword:
            params["person"] = _extract_person(q)
            params["query"] = keyword
            params["limit"] = _route_photo_limit(q)
            return "keyword_first", params

    if emotion_term and re.search(r"最多|最长|常去", q) and re.search(r"地方|地点", q):
        params["person"] = _extract_person(q)
        params["term"] = emotion_term
        params["term_type"] = "emotion"
        return "person_emotion_place_rank", params

    if emotion_term and _wants_emotion_term_lookup(q, emotion_term):
        params["person"] = _extract_person(q)
        params["term"] = emotion_term
        params["term_type"] = "emotion"
        params["limit"] = _route_photo_limit(q)
        if _WHY_RE.search(q):
            params["focus"] = "why"
        return "term_lookup", params

    if place_query and re.search(r"几趟|几次出门|几次活动|去过几次", q):
        params["person"] = _extract_person(q)
        params["place"] = place_query
        return "outings_at_place", params

    # 「出去玩了哪些」优先于地名抽取（避免「出去」里的「去」被当成去某地）
    # 假日（国庆/春节…）须先于季，且「去哪里玩了」也走时段出门；复合口语 → period_recap
    period_params = _period_params_from_question(q)
    if period_params is not None:
        extras = _detect_recap_extras(q)
        if _wants_period_recap(q):
            period_params.update(extras)
            period_params["photo_limit"] = 40
            return "period_recap", period_params
        return "outings_by_period", period_params

    if _OUTING_RE.search(q) or re.search(r"出去玩了哪些|出门玩了哪些", q):
        params["person"] = _extract_person(q)
        params["limit"] = _extract_photo_limit(q, default=10)
        extras = _detect_recap_extras(q)
        if extras["want_emotion"] or extras["want_companions"]:
            # 无明确时段时仍按最近出门 + 旁证
            params.update(extras)
            params["photo_limit"] = 40
            params["period_label"] = "最近"
            return "period_recap", params
        return "recent_outings", params

    if place_query:
        params["person"] = _extract_person(q)
        params["place"] = place_query
        params["limit"] = _route_photo_limit(q)
        if _AGE_RE.search(q):
            params["focus"] = "age"
        elif re.search(r"吗[？?]?$", q):
            params["focus"] = "yesno"
        return "person_at_place", params

    if _PEAK_DAY_RE.search(q) and _PHOTO_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_peak_day", params

    if _AGE_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_age", params

    if _CITIES_RE.search(q):
        params["person"] = _extract_person(q)
        if re.search(r"哪些省|什么省|哪些省份", q):
            params["group_by"] = "province"
        return "person_cities_visited", params

    if _PLACES_LIST_RE.search(q) or _is_places_list_question(q):
        params["person"] = _extract_person(q)
        if _RECENT_RE.search(q) and re.search(r"(?:去过|玩过)(?:的)?地方", q) and not _extract_relative_time_window(q):
            return "person_recent_places", params
        params["limit"] = 20
        params.update(_extract_relative_time_window(q))
        return "person_places_visited", params

    if _AGE_RANK_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_place_rank", params

    if _PLACE_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_recent_places", params

    holiday_media = _holiday_media_params(q)
    if holiday_media:
        return "keyword_search", holiday_media

    keyword = _extract_keyword_query(q)
    if keyword:
        params["person"] = _extract_person(q)
        params["query"] = keyword
        params["limit"] = _route_photo_limit(q)
        return "keyword_search", params

    if _RECENT_RE.search(q) and _PHOTO_RE.search(q):
        person = _extract_person(q)
        if person:
            params["person"] = person
        params["limit"] = _route_photo_limit(q)
        if params["limit"] <= 0 and person:
            params["list_all"] = True
        return "recent_photos", params

    if _RECENT_RE.search(q):
        params["person"] = _extract_person(q)
        # 「面面最近」→ 最近地点；裸「最近」不再误答最近照片
        if params["person"]:
            return "person_recent_places", params
        return "unknown", params

    if _PHOTO_RE.search(q):
        person = _extract_person(q)
        params["person"] = person
        params["limit"] = _route_photo_limit(q)
        # 「抱补的照片」/ 裸「照片」：默认全量证据
        if params["limit"] <= 0:
            if person:
                params["list_all"] = True
        return "recent_photos", params

    return "unknown", params

def _format_photo_line(photo: dict[str, Any], *, facts: dict[str, Any]) -> str:
    ts = photo.get("timestamp") or "未知时间"
    people = photo.get("people") or "—"
    scene = photo.get("scene") or "—"
    loc = photo.get("location") or "—"
    pid = _photo_ref(photo, facts=facts)
    return f"- {pid} | {ts} | {people} | {loc} | {scene}"


def _format_day_cn(ts: str) -> str:
    """把 ISO 时间收成口语日期，如 5月7日。"""
    raw = (ts or "").strip()
    if len(raw) < 10:
        return ""
    try:
        d = date.fromisoformat(raw[:10])
    except ValueError:
        return raw[:10]
    return f"{d.month}月{d.day}日"


def _unique_locations(photos: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    seen: list[str] = []
    for photo in photos:
        loc = (photo.get("location") or "").strip()
        if not loc or loc in seen:
            continue
        seen.append(loc)
        if len(seen) >= limit:
            break
    return seen


def _spoken_places_phrase(photos: list[dict[str, Any]]) -> str:
    locs = _unique_locations(photos, limit=3)
    if not locs:
        return ""
    if len(locs) == 1:
        return f"，比如在{locs[0]}"
    if len(locs) == 2:
        return f"，例如在{locs[0]}、{locs[1]}"
    return f"，例如在{locs[0]}、{locs[1]}等地"


def _with_cli_photo_lines(
    answer: str,
    photos: list[dict[str, Any]],
    *,
    facts: dict[str, Any],
) -> str:
    """Web/iOS（photo_links=False）只留口语短答；CLI 再附可点的照片行。"""
    if not photos or not _links_enabled(facts):
        return answer
    lines = [_format_photo_line(p, facts=facts) for p in photos]
    return answer + "\n" + "\n".join(lines)


def _pct_line(count: int, total: int, pct: float) -> str:
    return f"{count:,} 张（占 {pct}%）" if total else "0 张"


def _outing_day_label(day: str) -> str:
    """2025-10-07 → 10月7日。"""
    day = (day or "").strip()[:10]
    if len(day) >= 10 and day[4] == "-" and day[7] == "-":
        try:
            return f"{int(day[5:7])}月{int(day[8:10])}日"
        except ValueError:
            pass
    return day or "某日"


def _outing_place_name(ev: dict[str, Any]) -> str:
    """口语用地名：优先 overlay 标题，否则 location（不要带日期前缀）。"""
    ov = ev.get("overlay") or {}
    title = str(ov.get("title") or "").strip()
    if title:
        return title
    loc = str(ev.get("location") or "").strip()
    if loc and loc not in {"未知地点", "未知", "—", "-"}:
        return loc
    display = str(ev.get("display_title") or "").strip()
    if " · " in display:
        rest = display.split(" · ", 1)[1].strip()
        if rest and rest not in {"未知地点", "未知"}:
            return rest
    return ""


def _format_outings_spoken(
    events: list[dict[str, Any]],
    *,
    who: str,
    context: str,
    total: int | None = None,
    returned: int | None = None,
    empty_hint: str = "",
) -> str:
    """出门清单口语化：按天汇总，少堆张数/人名。细节留给证据区。"""
    if not events:
        return empty_hint or f"没有找到{who}{context}的出门。"

    total_n = int(total if total is not None else len(events))
    returned_n = int(returned if returned is not None else len(events))

    by_day: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        day = str(ev.get("day") or "").strip()[:10]
        by_day.setdefault(day, []).append(ev)

    day_keys = sorted(by_day.keys(), reverse=True)
    day_count = len([d for d in day_keys if d])

    head_who = who.strip()
    head_ctx = context.strip()
    if head_who and head_ctx:
        lead = f"{head_who}{head_ctx}"
    elif head_who:
        lead = head_who
    else:
        lead = head_ctx or "这段时间"

    if day_count > 1:
        head = f"{lead}大约覆盖 {day_count} 天"
    else:
        head = f"{lead}"
    head += f"，按地点聚成 {total_n} 趟出门"
    if returned_n < total_n:
        head += f"（这里列出 {returned_n} 趟）"
    head += "："

    lines = [head]
    for day in day_keys:
        places: list[str] = []
        seen: set[str] = set()
        for ev in by_day[day]:
            name = _outing_place_name(ev)
            key = name.casefold()
            if not name or key in seen:
                continue
            seen.add(key)
            places.append(name)
        if not places:
            continue
        # 同一天地点过多时收一收，避免又变成流水账
        if len(places) > 4:
            shown = "、".join(places[:3]) + f" 等 {len(places)} 处"
        else:
            shown = "、".join(places)
        lines.append(f"· {_outing_day_label(day)}：{shown}")

    top = max(events, key=lambda e: int(e.get("photo_count") or 0))
    top_place = _outing_place_name(top)
    top_n = int(top.get("photo_count") or 0)
    if top_place and top_n > 0:
        lines.append(f"照片拍得最多的是{top_place}（约 {top_n} 张）。")
    lines.append("具体同行人和每趟详情，可看右侧证据。")
    return "\n".join(lines)


def _spoken_emotion_line(facts: dict[str, Any], *, period: str = "") -> str:
    breakdown = facts.get("emotion_breakdown") or []
    with_n = int(facts.get("with_emotion") or 0)
    when = period or facts.get("period_label") or "那段时间"
    if not breakdown or with_n <= 0:
        return (
            f"{when}的照片里，表情标注很少，看不太出当时开不开心；"
            "有故事旁白会更准。"
        )
    top = "、".join(
        f"{e.get('term')}（{e.get('count')} 张）"
        for e in breakdown[:3]
        if isinstance(e, dict) and e.get("term")
    )
    happy_hints = {"开心", "高兴", "快乐", "微笑", "笑", "愉快"}
    top_terms = {str(e.get("term") or "") for e in breakdown[:3] if isinstance(e, dict)}
    if top_terms & happy_hints:
        vibe = "看起来偏开心"
    elif top_terms & {"哭", "哭泣", "哭闹"}:
        vibe = "有些照片像在哭或闹"
    else:
        vibe = "情绪词比较杂"
    return f"{when}有表情标注的照片约 {with_n} 张，多见：{top}。{vibe}（仅依据 AI 标注，不是主观感受）。"


def _spoken_companions_line(facts: dict[str, Any], *, period: str = "") -> str:
    companions = facts.get("companions") or []
    when = period or facts.get("period_label") or "那段时间"
    who = facts.get("person") or ""
    if not companions:
        return f"{when}照片里没统计到其他明确的家庭成员同框。"
    parts = [f"{c.get('name')}（{c.get('photo_count')} 张）" for c in companions[:8] if c.get("name")]
    more = f"等 {len(companions)} 人" if len(companions) > 8 else ""
    head = f"{who}{when}" if who else when
    return f"{head}同框较多的有：" + "、".join(parts) + more + "。"


def _template_answer(facts: dict[str, Any]) -> str:
    intent = facts.get("intent", "unknown")

    if intent == "unknown":
        return _unknown_answer()

    if intent == "explain_basis":
        summary = facts.get("basis_summary") or {}
        last_intent = str(facts.get("last_intent") or summary.get("intent") or "")
        label = summary.get("intent_label") or _intent_label_cn(last_intent)
        period = summary.get("period_label") or facts.get("period_label") or ""
        lines = [f"上一轮是按「{label}」查库回答的，不是瞎编。"]
        if period:
            lines.append(f"时间范围：{period}。")
        day_from = summary.get("day_from") or ""
        day_to = summary.get("day_to") or ""
        if day_from or day_to:
            lines.append(f"日期窗：{day_from or '…'}～{day_to or '…'}。")
        if summary.get("person"):
            lines.append(f"人物：{summary['person']}。")
        bits = []
        media_n = int(summary.get("media_count") or 0)
        by_type = summary.get("by_media_type") or {}
        if media_n:
            bits.append(media_noun_for_mix(by_type, media_n))
        elif int(summary.get("photo_count") or 0):
            bits.append(f"相关照片约 {summary['photo_count']} 张")
        if int(summary.get("event_count") or 0):
            bits.append(f"出门事件 {summary['event_count']} 趟")
        if int(summary.get("story_count") or 0):
            bits.append(f"故事 {summary['story_count']} 条")
        if int(summary.get("companion_count") or 0):
            bits.append(f"同框人物 {summary['companion_count']} 人")
        if int(summary.get("with_emotion") or 0):
            bits.append(f"有表情标注 {summary['with_emotion']} 张")
        if bits:
            lines.append("依据量：" + "、".join(bits) + "。")
        media_ids = summary.get("media_ids") or []
        if media_ids:
            lines.append("媒体样例 id：" + "、".join(str(x) for x in media_ids[:5]) + "。")
        event_ids = summary.get("event_ids") or []
        if event_ids:
            lines.append("事件样例 id：" + "、".join(str(x) for x in event_ids[:3]) + "。")
        story_ids = summary.get("story_ids") or []
        if story_ids:
            lines.append("故事样例 id：" + "、".join(str(x) for x in story_ids[:3]) + "。")
        places = summary.get("places_sample") or []
        if places:
            lines.append("地点样例：" + "、".join(places[:5]) + "。")
        emotions = summary.get("emotion_top") or []
        if emotions:
            lines.append("表情词样例：" + "、".join(emotions) + "。")
        lines.append("右侧证据区可以点开核对原片 / JSON；evidence 字段可追溯 media/event/story id。")
        return "\n".join(lines)

    if intent == "period_emotion":
        return _spoken_emotion_line(facts)

    if intent == "period_companions":
        return _spoken_companions_line(facts)

    if intent == "period_recap":
        events = facts.get("events") or []
        person = facts.get("person") or ""
        who = f"{person}" if person else ""
        period = facts.get("period_label") or ""
        total = int(facts.get("total") or 0)
        returned = int(facts.get("returned") or len(events))
        outings_text = _format_outings_spoken(
            events,
            who=who,
            context=period,
            total=total,
            returned=returned,
            empty_hint=(
                f"没有找到{who}{'在' + period if period else ''}的出门事件。"
                "可先跑：python tools/memory_events/main.py sync"
            ),
        )
        parts = [outings_text]
        if facts.get("want_emotion", True):
            parts.append(_spoken_emotion_line(facts, period=period))
        if facts.get("want_companions", True):
            parts.append(_spoken_companions_line(facts, period=period))
        return "\n".join(parts)

    if intent == "keyword_search":
        query = str(facts.get("query") or "").strip() or "关键词"
        period = str(facts.get("period_label") or "").strip()
        who = facts.get("person") or ""
        photos = facts.get("photos") or []
        total = int(facts.get("photo_count") or len(photos))
        shown = len(photos)
        evidence = facts.get("_evidence") if isinstance(facts.get("_evidence"), dict) else build_evidence(facts)
        by_type = (evidence.get("counts") or {}).get("by_media_type") or {}
        noun = media_noun_for_mix(by_type, total) if total else "记忆"
        topic = f"{period}期间" if period else f"「{query}」相关"
        if total <= 0 or not photos:
            scope = f"{who}相关、" if who else ""
            if period:
                return f"没找到{scope}{topic}的照片。"
            return f"没找到{scope}和「{query}」有关的记忆。"
        places = _spoken_places_phrase(photos)
        who_bit = f"{who}" if who else ""
        if who_bit:
            answer = f"有的。{who_bit}{topic}一共找到 {noun}"
        else:
            answer = f"有的。{topic}一共找到 {noun}"
        # 仅当用户主动要求截断（如「20张」）且未取全时提示
        if shown < total:
            answer += f"，本次列出 {shown} 条"
        answer += places + "。"
        return _with_cli_photo_lines(answer, photos, facts=facts)

    if intent == "library_stats":
        stats = facts.get("stats") or {}
        if not stats.get("found", True):
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。"
        focus = facts.get("focus", "all")
        person = stats.get("person") or ""
        total = int(stats.get("total_photos") or 0)
        pct = stats.get("percent") or {}
        scope = f"{person}的" if person else "记忆库"

        if focus == "fields":
            lines = [f"{scope}照片一共 {total:,} 张。", "", "字段覆盖："]
            for item in stats.get("field_coverage") or []:
                lines.append(
                    f"- {item['label']}（{item['field']}）："
                    f"{item['count']:,} 张（{item['percent']}%）"
                )
            dist = stats.get("distributions") or {}
            dist_labels = {
                "emotion": "表情分布",
                "tags": "标签分布",
                "objects": "物体分布",
                "actions": "动作分布",
                "device_id": "设备来源",
            }
            for key, title in dist_labels.items():
                items = dist.get(key) or []
                if not items:
                    continue
                parts = [f"{i['term']} {i['count']}" for i in items]
                lines.append("")
                lines.append(f"{title}（Top {len(items)}）：" + " · ".join(parts))
            lines.append("")
            lines.append("（scene/objects/actions/emotion/tags 依赖 vision backfill，数字会随补全增加）")
            return "\n".join(lines)

        lines = [f"{scope}照片一共 {total:,} 张。"]
        metric_lines = {
            "face": f"识别到人脸：{_pct_line(stats.get('with_face', 0), total, pct.get('face', 0))}",
            "location": f"有地点：{_pct_line(stats.get('with_location', 0), total, pct.get('location', 0))}",
            "scene": f"有场景描述：{_pct_line(stats.get('with_scene', 0), total, pct.get('scene', 0))}",
            "emotion": f"有表情：{_pct_line(stats.get('with_emotion', 0), total, pct.get('emotion', 0))}",
        }
        if focus != "all" and focus in metric_lines:
            lines.append(metric_lines[focus])
        else:
            lines.extend(metric_lines.values())

        breakdown = stats.get("emotion_breakdown") or []
        if breakdown and focus in ("all", "emotion"):
            parts = [f"{item['term']} {item['count']}" for item in breakdown[:6]]
            lines.append("表情分布：" + " · ".join(parts))
        if int(stats.get("with_scene") or 0) < total and focus in ("all", "scene"):
            lines.append("（场景/表情仍在 vision 补全中，数字会随 backfill 增加）")
        return "\n".join(lines)

    if intent == "person_artwork":
        if not facts.get("found", True):
            who = facts.get("person") or ""
            return f"没有在家庭成员档案里找到「{who}」。请检查 data/faces/registry.json。"
        who = facts.get("person") or "家人"
        count = int(facts.get("photo_count") or 0)
        works_only = bool(facts.get("works_only", True))
        label = "画作" if works_only else "画画相关的照片"
        if count == 0:
            return f"还没找到{who}的{label}。"
        photos = facts.get("photos") or []
        shown = len(photos)
        places = _spoken_places_phrase(photos)
        if shown and shown < count:
            answer = f"找到{who}的{label}一共 {count} 张，这里先看 {shown} 张{places}。"
        else:
            answer = f"找到{who}的{label}一共 {count} 张{places}。"
        return _with_cli_photo_lines(answer, photos, facts=facts)

    if intent == "term_lookup":
        if not facts.get("found", True):
            who = facts.get("person") or ""
            if who:
                return f"没有在家庭成员档案里找到「{who}」。"
            return "请说明要查的表情关键词。"
        term = facts.get("term") or ""
        count = int(facts.get("photo_count") or 0)
        who = facts.get("person") or ""
        scope = f"{who}的照片里" if who else "记忆库里"
        matched = facts.get("matched_terms") or []
        term_detail = ""
        if matched:
            term_detail = "（" + "、".join(f"{m['term']} {m['count']}" for m in matched) + "）"

        if count == 0:
            return f"{scope}还没找到和「{term}」相关的表情记录。"

        photos = facts.get("sample_photos") or facts.get("photos") or []
        if facts.get("focus") == "why":
            lines = [
                f"照片里没有标注「为什么{term}」的原因；"
                f"{scope}和「{term}」相关的大约有 {count} 张{term_detail}。",
                "可以看当时的场景：",
            ]
            for photo in photos[:5]:
                day = _format_day_cn(str(photo.get("timestamp") or ""))
                loc = (photo.get("location") or "").strip() or "地点未知"
                scene = (photo.get("scene") or "").strip() or "（无场景描述）"
                lines.append(f"- {day} · {loc}：{scene}")
            return _with_cli_photo_lines("\n".join(lines), photos, facts=facts)

        answer = f"有的，{scope}和「{term}」相关的大约有 {count} 张{term_detail}。"
        places = _spoken_places_phrase(photos)
        if places:
            answer = answer.rstrip("。") + places + "。"
        return _with_cli_photo_lines(answer, photos, facts=facts)

    if intent == "term_first":
        if not facts.get("found", True):
            who = facts.get("person") or ""
            if who:
                return f"没有在家庭成员档案里找到「{who}」。"
            return "请说明要查的表情关键词。"
        term = facts.get("term") or ""
        who = facts.get("person") or ""
        scope = who or "家里"
        photo = facts.get("photo")
        if not photo:
            whose = f"{who}的" if who else ""
            return f"没有找到{whose}和「{term}」相关的表情记录。"
        day = _format_day_cn(str(photo.get("timestamp") or ""))
        age = photo.get("age_label") or ""
        loc = (photo.get("location") or "").strip()
        terms = photo.get("matched_terms") or term
        parts = [f"{scope}最早一次「{terms}」"]
        if day:
            parts.append(f"是在{day}")
        else:
            parts.append(f"是在 {photo.get('timestamp') or '未知时间'}")
        if age:
            parts.append(f"当时{age}")
        if loc:
            parts.append(f"地点在{loc}")
        answer = "，".join(parts) + "。"
        if _links_enabled(facts):
            answer += f"（{_photo_ref(photo, facts=facts)}）"
        return answer

    if intent == "keyword_first":
        if not facts.get("found", True):
            who = facts.get("person") or ""
            if who:
                return f"没有在家庭成员档案里找到「{who}」。"
            return "请说明要查的关键词。"
        query = facts.get("query") or ""
        who = facts.get("person") or ""
        scope = who or "家里"
        photo = facts.get("photo")
        count = int(facts.get("photo_count") or 0)
        if not photo:
            whose = f"{who}" if who else ""
            prefix = f"{whose}相关、" if whose else ""
            return f"没有找到{prefix}和「{query}」有关的照片。"
        day = _format_day_cn(str(photo.get("timestamp") or ""))
        age = photo.get("age_label") or ""
        loc = (photo.get("location") or "").strip()
        scene = (photo.get("scene") or "").strip()
        parts = [f"{scope}最早一次「{query}」"]
        if day:
            parts.append(f"是在{day}")
        else:
            parts.append(f"是在 {photo.get('timestamp') or '未知时间'}")
        if age:
            parts.append(f"当时{age}")
        if loc:
            parts.append(f"地点在{loc}")
        answer = "，".join(parts) + "。"
        if scene:
            answer += f"场景：{scene}。"
        if count > 1:
            answer += f"这类照片一共约 {count} 张。"
        photos = facts.get("photos") or ([photo] if photo else [])
        return _with_cli_photo_lines(answer, photos, facts=facts)

    if intent == "person_age_place_rank":
        if not facts.get("found"):
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。"
        person = facts.get("person") or "家人"
        age = facts.get("age_years")
        age_photos = int(facts.get("age_photos") or 0)
        matched = int(facts.get("matched_photos") or 0)
        places = facts.get("places") or []
        if not places:
            return (
                f"没有找到 {person} {age}岁 时带地点信息的记录。"
                f"（该年龄段共 {age_photos} 张照片）"
            )
        header = (
            f"{person} {age}岁时，按照片记录统计（共 {matched} 张有地点，"
            f"该岁段共 {age_photos} 张；「待得最久」以拍照张数/天数估算）："
        )
        lines = [
            f"- {p['location']}：{p['photo_count']} 张 / {p['day_count']} 天"
            for p in places
        ]
        return header + "\n" + "\n".join(lines)

    if intent == "person_peak_day":
        if not facts.get("found"):
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。"
        person = facts.get("person") or "家人"
        peak_days = facts.get("peak_days") or []
        if not peak_days:
            return f"没有找到 {person} 带拍摄日期的照片记录。"
        max_count = int(facts.get("max_photo_count") or 0)
        lines: list[str] = []
        for peak in peak_days:
            day = peak.get("day") or ""
            loc = peak.get("primary_location") or ""
            locs = peak.get("locations") or []
            if loc:
                loc_detail = f"，主要在 {loc}"
                if len(locs) > 1:
                    others = "、".join(
                        f"{item['location']} {item['count']}"
                        for item in locs[1:3]
                    )
                    if others:
                        loc_detail += f"（另有 {others}）"
            else:
                loc_detail = "，当天无地点记录"
            age = peak.get("age_label") or ""
            age_detail = f"，当时 {age}" if age else ""
            lines.append(
                f"- {day}：{peak.get('photo_count', max_count)} 张{loc_detail}{age_detail}"
            )
        header = f"{person} 照片最多的一天（{max_count} 张）："
        if len(peak_days) > 1:
            header = f"{person} 照片最多的日子（并列 {max_count} 张/天）："
        return header + "\n" + "\n".join(lines)

    if intent == "person_place_rank":
        if not facts.get("found"):
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。"
        person = facts.get("person") or "家人"
        matched = int(facts.get("matched_photos") or 0)
        total = int(facts.get("total_photos") or 0)
        places = facts.get("places") or []
        if not places:
            return f"没有找到 {person} 带地点信息的记录。（共 {total} 张照片）"
        header = (
            f"{person} 常去的地方（按照片张数/天数统计，"
            f"共 {matched} 张有地点，总计 {total} 张）："
        )
        lines = [
            f"- {p['location']}：{p['photo_count']} 张 / {p['day_count']} 天"
            for p in places
        ]
        return header + "\n" + "\n".join(lines)

    if intent == "person_places_visited":
        if not facts.get("found"):
            unknown = facts.get("unknown")
            if unknown:
                return f"没有在家庭成员档案里找到「{unknown}」。"
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。"
        person = facts.get("person") or "家人"
        companions = [str(c) for c in (facts.get("companions") or []) if c]
        period = str(facts.get("period_label") or "").strip()
        who = "和".join([person, *companions]) if companions else person
        when = f"{period}里" if period else ""
        matched = int(facts.get("matched_photos") or 0)
        total = int(facts.get("total_photos") or 0)
        total_places = int(facts.get("total_places") or 0)
        places = facts.get("places") or []
        if not places:
            scope = f"{who}{when}" if when else who
            tip = "同框且带地点" if companions else "带地点信息"
            return f"没有找到 {scope} 的{tip}记录。（范围内共 {total} 张相关照片）"
        together = "一起" if companions else ""
        header = (
            f"{who}{when}{together}去过的地点（共 {total_places} 处，"
            f"按照片数列出前 {len(places)} 个；{matched} 张有地点"
        )
        if total and not companions and not period:
            header += f"，总计 {total} 张"
        header += "）："
        lines = [
            f"- {p['location']}：{p['photo_count']} 张 / {p['day_count']} 天"
            for p in places
        ]
        return header + "\n" + "\n".join(lines)

    if intent == "person_emotion_place_rank":
        if not facts.get("found"):
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。"
        person = facts.get("person") or "家人"
        term = facts.get("term") or ""
        term_photos = int(facts.get("term_photos") or 0)
        matched = int(facts.get("matched_photos") or 0)
        places = facts.get("places") or []
        matched_terms = facts.get("matched_terms") or []
        term_detail = ""
        if matched_terms:
            term_detail = "（" + "、".join(f"{m['term']} {m['count']}" for m in matched_terms[:4]) + "）"
        if not places:
            return (
                f"没有找到 {person} 在带地点的照片里与「{term}」相关的表情记录"
                f"（共 {term_photos} 张匹配表情{term_detail}；部分照片可能尚未 vision 补全）。"
            )
        header = (
            f"{person} 在哪些地方「{term}」最多"
            f"（按有该表情的照片统计，共 {matched} 张有地点{term_detail}）："
        )
        lines = [
            f"- {p['location']}：{p['photo_count']} 张 / {p['day_count']} 天"
            for p in places
        ]
        return header + "\n" + "\n".join(lines)

    if intent == "person_cities_visited":
        if not facts.get("found"):
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。"
        person = facts.get("person") or "家人"
        group_by = facts.get("group_by") or "city"
        unit = "省份" if group_by == "province" else "城市"
        places = facts.get("places") or []
        total_places = int(facts.get("total_places") or 0)
        matched = int(facts.get("matched_photos") or 0)
        if not places:
            return f"没有找到 {person} 带省/市信息的记录。（共 {facts.get('total_photos', 0)} 张照片）"
        header = (
            f"{person} 去过的{unit}（共 {total_places} 个，"
            f"按照片数；{matched} 张有省/市信息）："
        )
        lines = [
            f"- {p['label']}：{p['photo_count']} 张 / {p['day_count']} 天"
            for p in places
        ]
        return header + "\n" + "\n".join(lines)

    if intent == "person_at_place":
        if not facts.get("found"):
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。"
        person = facts.get("person") or "家人"
        place = facts.get("place") or facts.get("place_query") or ""
        photo_count = int(facts.get("photo_count") or 0)
        day_count = int(facts.get("day_count") or 0)
        locations = facts.get("matched_locations") or []
        regions = facts.get("matched_regions") or []
        if photo_count == 0:
            if facts.get("focus") == "yesno":
                return f"没有找到 {person} 去过「{place}」的记录。"
            return f"没有找到 {person} 在「{place}」相关地点的照片记录。"

        if regions and any(place in r for r in regions):
            loc_label = "、".join(regions[:5])
            if len(regions) > 5:
                loc_label += f" 等 {len(regions)} 处"
        elif regions and not locations:
            loc_label = "、".join(regions[:5])
            if len(regions) > 5:
                loc_label += f" 等 {len(regions)} 处"
        else:
            loc_label = "、".join(locations[:3]) if locations else place
            if len(locations) > 3:
                loc_label += f" 等 {len(locations)} 处"

        if facts.get("focus") == "yesno":
            lines = [
                f"去过。{person} 在「{loc_label}」（匹配「{place}」）"
                f"共 {photo_count} 张照片 / {day_count} 天。"
            ]
            first = facts.get("first_visit")
            last = facts.get("last_visit")
            if first:
                loc = first.get("location") or first.get("location_city") or "—"
                lines.append(
                    f"第一次：{first.get('timestamp', '')} @ {loc}"
                    f"（{_photo_ref(first, facts=facts)}）"
                )
            if last and last.get("photo_id") != (first or {}).get("photo_id"):
                loc = last.get("location") or last.get("location_city") or "—"
                lines.append(
                    f"最近一次：{last.get('timestamp', '')} @ {loc}"
                    f"（{_photo_ref(last, facts=facts)}）"
                )
            return "\n".join(lines)

        if facts.get("focus") == "age":
            visit_days = facts.get("visit_days") or []
            ages = [v for v in visit_days if v.get("age_label")]
            if ages:
                if len(ages) == 1:
                    v = ages[0]
                    return (
                        f"{person} 去「{place}」时 {v['age_label']}"
                        f"（{v['day']}，{v.get('location') or '—'}）。"
                    )
                first_v, last_v = ages[0], ages[-1]
                if first_v["age_label"] == last_v["age_label"]:
                    return (
                        f"{person} 去「{place}」时约 {first_v['age_label']}"
                        f"（{day_count} 天，{photo_count} 张照片）。"
                    )
                lines = [
                    f"{person} 去「{place}」时的年龄（共 {day_count} 天）：",
                    f"- 第一次（{first_v['day']}）：{first_v['age_label']}",
                    f"- 最近一次（{last_v['day']}）：{last_v['age_label']}",
                ]
                if len(ages) > 2:
                    for v in ages[1:-1]:
                        lines.append(f"- {v['day']}：{v['age_label']}")
                return "\n".join(lines)
            first = facts.get("first_visit")
            if first and first.get("age_label"):
                loc = first.get("location") or first.get("location_city") or "—"
                return (
                    f"{person} 去「{place}」时 {first['age_label']}"
                    f"（{first.get('timestamp', '')} @ {loc}）。"
                )
            return f"找到了 {person} 在「{place}」的 {photo_count} 张照片，但没有记录当时年龄。"

        lines = [
            f"{person} 在「{loc_label}」（匹配「{place}」）"
            f"共 {photo_count} 张照片 / {day_count} 天。"
        ]
        first = facts.get("first_visit")
        last = facts.get("last_visit")
        if first:
            loc = first.get("location") or first.get("location_city") or "—"
            age = f"，当时 {first['age_label']}" if first.get("age_label") else ""
            lines.append(
                f"第一次：{first.get('timestamp', '')} @ {loc}{age}"
                f"（{_photo_ref(first, facts=facts)}）"
            )
        if last and last.get("photo_id") != (first or {}).get("photo_id"):
            loc = last.get("location") or last.get("location_city") or "—"
            age = f"，当时 {last['age_label']}" if last.get("age_label") else ""
            lines.append(
                f"最近一次：{last.get('timestamp', '')} @ {loc}{age}"
                f"（{_photo_ref(last, facts=facts)}）"
            )
        visit_days = facts.get("visit_days") or []
        if visit_days:
            lines.append(f"各次到访（共 {len(visit_days)} 天，按时间）：")
            for v in visit_days:
                age = f" | {v['age_label']}" if v.get("age_label") else ""
                lines.append(
                    f"- {v['day']} | {v['location']} | {v['photo_count']} 张{age}"
                )
        return "\n".join(lines)

    if intent == "group_photos":
        if not facts.get("found"):
            unknown = facts.get("unknown")
            if unknown:
                return f"没有在家庭成员档案里找到「{unknown}」。请检查 data/faces/registry.json。"
            persons = facts.get("persons") or []
            if len(persons) < 2:
                return "请说明合影里的至少两位家庭成员，例如「妈妈和面面的合影有哪些」。"
            return "无法查询该合影。"
        persons = facts.get("persons") or []
        label = "和".join(persons)
        total = int(facts.get("total_count") or 0)
        photos = facts.get("photos") or []
        if total == 0:
            lines = [
                f"没有找到 {label} 三人同时识别到的合影。",
                "（需同一张照片里 InsightFace 同时认出所有成员）",
            ]
            pair_counts = facts.get("pair_counts") or []
            if pair_counts:
                lines.append("")
                lines.append("两两同框统计：")
                for pair in pair_counts:
                    a, b = pair["persons"]
                    lines.append(f"- {a} + {b}：{pair['count']} 张")
            return "\n".join(lines)
        shown = len(photos)
        places = _spoken_places_phrase(photos)
        if shown < total:
            answer = f"{label}的合影一共有 {total} 张，本次列出 {shown} 张{places}。"
        else:
            answer = f"{label}的合影一共有 {total} 张{places}。"
        return _with_cli_photo_lines(answer, photos, facts=facts)

    if intent == "recent_photos":
        photos = facts.get("photos") or []
        person = facts.get("person") or ""
        list_all = bool(facts.get("list_all"))
        total = int(facts.get("photo_count") or len(photos))
        shown = len(photos)
        evidence = facts.get("_evidence") if isinstance(facts.get("_evidence"), dict) else build_evidence(facts)
        by_type = (evidence.get("counts") or {}).get("by_media_type") or {}
        noun = media_noun_for_mix(by_type, total) if total else "记忆"
        if not photos:
            who = f"{person}的" if person else ""
            if list_all:
                return f"记忆库里还没有{who}记录。"
            return f"记忆库里还没有{who}最近记录。"
        places = _spoken_places_phrase(photos)
        if list_all:
            who = f"{person}" if person else ""
            prefix = f"{who}一共找到 " if who else "一共找到 "
            answer = f"{prefix}{noun}"
            if shown < total:
                answer += f"，本次列出 {shown} 条"
            answer += places + "。"
            return _with_cli_photo_lines(answer, photos, facts=facts)
        who = f"{person}最近有 " if person else "最近有 "
        answer = f"{who}{noun}"
        if shown < total:
            answer += f"，本次列出 {shown} 条"
        answer += places + "。"
        return _with_cli_photo_lines(answer, photos, facts=facts)

    if intent == "person_age":
        age_info = facts.get("age_info") or {}
        if not age_info.get("found"):
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。请检查 data/faces/registry.json。"
        name = age_info.get("name", "")
        current = age_info.get("current_age")
        if current and current.get("label"):
            answer = f"{name} 今天 {current['label']}。"
        else:
            answer = f"找到了 {name}，但 registry 里没有 birth_date，无法计算年龄。"
        latest = facts.get("latest_photo_age")
        if latest and latest.get("age_label"):
            answer += f"\n最近一张照片（{latest.get('timestamp', '')}）里记录的是：{latest['age_label']}。"
        return answer

    if intent == "person_recent_places":
        places = facts.get("places") or []
        person = facts.get("person") or "家人"
        if not places:
            return f"还没有找到 {person} 带地点信息的最近记录。"
        top = places[0]
        loc = (top.get("location") or "").strip() or "某个地方"
        day = _format_day_cn(str(top.get("timestamp") or ""))
        if day:
            answer = f"{person}最近常去的地方是{loc}，最近一次大概在{day}。"
        else:
            answer = f"{person}最近常去的地方是{loc}。"
        extras = [
            (p.get("location") or "").strip()
            for p in places[1:4]
            if (p.get("location") or "").strip()
            and (p.get("location") or "").strip() != loc
        ]
        # 去重保序
        seen: set[str] = set()
        unique_extras: list[str] = []
        for name in extras:
            if name in seen:
                continue
            seen.add(name)
            unique_extras.append(name)
        if unique_extras:
            answer += f"另外还去过{'、'.join(unique_extras)}。"
        return answer

    if intent == "companions_at_place":
        if not facts.get("found", True):
            who = facts.get("person") or ""
            if who:
                return f"没有在家庭成员档案里找到「{who}」。请检查 data/faces/registry.json。"
            return "请说明地点，例如「面面哪些人去过动物园」。"
        place = str(facts.get("place_query") or facts.get("place") or "那里").strip()
        who = facts.get("person") or ""
        companions = facts.get("companions") or []
        photos = facts.get("photos") or []
        total = int(facts.get("photo_count") or len(photos))
        if not companions:
            scope = f"{who}在「{place}」" if who else f"「{place}」"
            return f"{scope}相关照片里，还没识别到其他同框的人。"

        def _companion_label(c: dict) -> str:
            name = str(c.get("name") or "某人")
            n = int(c.get("photo_count") or 0)
            days = [str(d) for d in (c.get("visit_days") or []) if d]
            if not days:
                return f"{name}（{n} 张）"
            shown = days[:6]
            day_str = "、".join(shown)
            if len(days) > 6:
                day_str += f" 等 {len(days)} 天"
            # 「分别是什么时候」突出日期；普通「和谁」也附日期更有用
            if facts.get("focus") == "when":
                return f"{name}（{day_str}）"
            return f"{name}（{day_str}；{n} 张）"

        parts = [_companion_label(c) for c in companions[:12]]
        more = ""
        if len(companions) > 12:
            more = f"等 {len(companions)} 人"
        names = "、".join(parts) + more
        if who:
            answer = f"{who}去「{place}」时，同框出现过：{names}。"
        else:
            answer = f"「{place}」相关照片里出现过：{names}。"
        if total:
            answer = answer.rstrip("。") + f"。相关照片一共 {total} 张。"
        return _with_cli_photo_lines(answer, photos, facts=facts)

    if intent == "person_companion_rank":
        if not facts.get("found", True):
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。请检查 data/faces/registry.json。"
        person = facts.get("person") or "家人"
        companions = facts.get("companions") or []
        photos = facts.get("photos") or []
        total_with = int(facts.get("photo_count") or 0)
        period = str(facts.get("period_label") or "").strip()
        when = period or ""
        if not companions:
            if when:
                return f"{when}还没有找到与{person}同框的其他家庭成员（需照片里同时识别到两人）。"
            return f"还没有找到与{person}同框的其他家庭成员（需照片里同时识别到两人）。"
        top = companions[0]
        top_name = top.get("name") or "某人"
        top_count = int(top.get("photo_count") or 0)
        parts = [f"{c['name']}（{c['photo_count']} 张）" for c in companions[:12]]
        more = ""
        if len(companions) > 12:
            more = f"等 {len(companions)} 人"
        ranking = "、".join(parts) + more
        if when:
            answer = (
                f"{person}{when}里，合影最多的是{top_name}（{top_count} 张）。"
                f"同框排行：{ranking}。"
            )
        else:
            answer = (
                f"{person}合影最多的是{top_name}（{top_count} 张）。"
                f"同框排行：{ranking}。"
            )
        if total_with:
            scope = f"{when}里" if when else ""
            answer += f"{scope}含其他成员的合影共 {total_with} 张。"
        return _with_cli_photo_lines(answer, photos, facts=facts)

    if intent == "recent_outings":
        events = facts.get("events") or []
        person = facts.get("person") or ""
        who = f"{person}" if person else ""
        return _format_outings_spoken(
            events,
            who=who,
            context="最近",
            empty_hint=(
                f"还没有聚出{who + '的' if who else ''}出门事件。"
                "可先跑：python tools/memory_events/main.py sync"
            ),
        )

    if intent == "outings_by_period":
        events = facts.get("events") or []
        person = facts.get("person") or ""
        who = f"{person}" if person else ""
        period = facts.get("period_label") or ""
        total = int(facts.get("total") or 0)
        returned = int(facts.get("returned") or len(events))
        return _format_outings_spoken(
            events,
            who=who,
            context=period,
            total=total,
            returned=returned,
            empty_hint=(
                f"没有找到{who}{'在' + period if period else ''}的出门事件。"
                "可先跑：python tools/memory_events/main.py sync"
            ),
        )

    if intent == "person_home_timeline":
        if not facts.get("found"):
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。"
        person = facts.get("person") or "家人"
        homes = facts.get("homes") or []
        if not homes:
            return (
                f"还没有聚出 {person} 的长期住址时间线。"
                "确认住址已标为「家」，并跑：python tools/memory_events/main.py sync"
            )

        def _home_name(loc: str) -> str:
            name = (loc or "未知").strip()
            # 列表本身就是「家」，口语里去掉后缀（家）
            if name.endswith("（家）"):
                name = name[:-3].strip()
            elif name.endswith("(家)"):
                name = name[:-3].strip()
            return name or "未知"

        def _home_period(h: dict[str, Any]) -> str:
            first = (h.get("first_day") or "").strip()[:10]
            last = (h.get("last_day") or "").strip()[:10]
            span = int(h.get("span_days") or 0)

            def _ym(day: str) -> str:
                if len(day) >= 7 and day[4] == "-":
                    try:
                        return f"{int(day[:4])}年{int(day[5:7])}月"
                    except ValueError:
                        pass
                return day

            if first and last and first != last:
                base = f"{_ym(first)}～{_ym(last)}"
                return f"{base}（约 {span} 天）" if span > 0 else base
            if first or last:
                day = first or last
                return f"有记录于 {_ym(day)}"
            return "有家事件记录（缺日期）"

        lines = [
            f"{person}长期住过这些家（共 {len(homes)} 处；"
            "按标成「家」的照片统计，不含出门住酒店）："
        ]
        narrative_bits: list[str] = []
        for i, h in enumerate(homes):
            loc = _home_name(str(h.get("location") or ""))
            age0 = h.get("age_start_label") or ""
            age1 = h.get("age_end_label") or ""
            age_bit = ""
            if age0 and age1 and age0 != age1:
                age_bit = f"，大约从{age0}到{age1}"
            elif age0:
                age_bit = f"，大约{age0}"
            lines.append(f"· {loc}：{_home_period(h)}{age_bit}")
            if i == 0:
                narrative_bits.append(f"先是{loc}")
            elif i == len(homes) - 1:
                narrative_bits.append(f"再到{loc}")
            else:
                narrative_bits.append(f"然后{loc}")
        if len(narrative_bits) >= 2:
            lines.append("搬家顺序：" + "，".join(narrative_bits) + "。")
        longest = facts.get("longest") or {}
        if longest.get("location"):
            long_name = _home_name(str(longest.get("location") or ""))
            span = int(longest.get("span_days") or 0)
            if span > 0:
                lines.append(
                    f"按照片记录，住得最久的是{long_name}（约 {span} 天）。"
                )
            else:
                lines.append(f"家事件最多的是{long_name}。")
        return "\n".join(lines)

    if intent == "outings_at_place":
        events = facts.get("events") or []
        place = facts.get("place") or ""
        person = facts.get("person") or ""
        who = f"{person}" if person else ""
        return _format_outings_spoken(
            events,
            who=who,
            context=f"在「{place}」相关",
            empty_hint=f"没有找到{who}{'在「' + place + '」' if place else ''}的出门事件。",
        )

    if intent == "story_lookup":
        stories = facts.get("stories") or []
        query = facts.get("query") or ""
        if not stories:
            hint = f"「{query}」" if query else ""
            return f"还没有匹配{hint}的故事。可在 Vue「事件」Tab 里创建跨天故事。"
        lines: list[str] = []
        for s in stories:
            lines.append(f"【{s.get('title') or '未命名'}】")
            body = (s.get("body") or "").strip()
            if body:
                lines.append(body if len(body) <= 800 else body[:800] + "…")
            links = s.get("links") or []
            if links:
                lines.append(
                    "关联："
                    + ", ".join(
                        f"{l.get('link_type')}:{l.get('link_id')}" for l in links[:8]
                    )
                )
            lines.append("")
        return "\n".join(lines).strip()

    return _unknown_answer()


def _call_ollama_chat(system: str, user: str) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": OLLAMA_CHAT_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))
    message = data.get("message") or {}
    return str(message.get("content", "")).strip()


def _sanitize_facts_for_llm(
    facts: dict[str, Any],
    *,
    photo_links: bool,
) -> dict[str, Any]:
    """送给 LLM 的事实：去掉内部字段；无链接模式再去掉 photo_id / 路径，避免答出文件名。"""

    drop = {"_photo_links", "_evidence"}
    if not photo_links:
        drop |= {"photo_id", "source_path"}

    def scrub(obj: Any) -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for key, value in obj.items():
                if key in drop or key.startswith("_"):
                    continue
                out[key] = scrub(value)
            return out
        if isinstance(obj, list):
            return [scrub(item) for item in obj]
        return obj

    cleaned = scrub(facts)
    photos = cleaned.get("photos")
    if isinstance(photos, list) and len(photos) > 12:
        # 大结果按地点轮转取样，避免 LLM 只看到时段末尾同一地点
        by_loc: dict[str, list[Any]] = {}
        for p in photos:
            if not isinstance(p, dict):
                continue
            loc = str(p.get("location") or "").strip() or "（无地点）"
            by_loc.setdefault(loc, []).append(p)
        sample: list[Any] = []
        keys = list(by_loc.keys())
        while len(sample) < 12 and keys:
            next_keys: list[str] = []
            for loc in keys:
                bucket = by_loc[loc]
                if not bucket:
                    continue
                sample.append(bucket.pop(0))
                if bucket:
                    next_keys.append(loc)
                if len(sample) >= 12:
                    break
            keys = next_keys
        cleaned["photos"] = sample
        cleaned["photos_omitted"] = len(photos) - len(sample)
        # 时段概览：地点去重，避免润色只讲样例里最后一天
        locs = _unique_locations(
            [p for p in photos if isinstance(p, dict)],
            limit=8,
        )
        if locs:
            cleaned["places_overview"] = locs
    return cleaned


def _llm_answer(question: str, facts: dict[str, Any]) -> str | None:
    if not OLLAMA_CHAT_ENABLED:
        return None
    photo_links = _links_enabled(facts)
    if photo_links:
        style_hint = (
            "若需要指向某张照片，可用 Markdown 链接 [说明](file:///绝对路径)；"
            "facts 里已含 source_path。"
        )
        cite_hint = "可用一两句口语回答，必要时附上地点或可点链接。"
    else:
        style_hint = (
            "界面另有照片证据区，回答里不要出现 photo_id、文件名、路径、"
            "「【照片】」或类似调试标注。"
        )
        cite_hint = "用一两句自然口语回答，只说人物、地点、大概时间即可。"

    system = (
        "你是家庭记忆助手 MemoryGraph。只能根据提供的「查询事实」回答，不要编造。"
        "如果事实不足，明确说不知道或看不太出来。用简体中文，语气自然亲切，像家人讲故事，"
        "两三句到一小段即可，不要写成报表。"
        + style_hint
    )
    payload_facts = _sanitize_facts_for_llm(facts, photo_links=photo_links)
    period = str(facts.get("period_label") or "").strip()
    period_hint = ""
    if period:
        period_hint = (
            f"这是「{period}」时段的检索结果。优先依据 places_overview / photo_count 概括去过哪些地方，"
            "不要把样例照片里的单一地点说成整段假期唯一去处。"
        )
    user = (
        f"用户问题：{question}\n\n"
        f"查询事实（JSON）：\n{json.dumps(payload_facts, ensure_ascii=False, indent=2)}\n\n"
        f"{period_hint}"
        f"{cite_hint}"
        "若事实含出门事件、同行人、表情词，请按用户问到的点组织，勿虚构开心程度。"
    )
    try:
        text = _call_ollama_chat(system, user)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Ollama 问答失败，使用模板回答: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Ollama 问答异常，使用模板回答: %s", exc)
        return None
    if not text:
        return None
    if not photo_links:
        # 兜底：去掉模型仍可能吐出的文件名调试句
        text = re.sub(r"[（(]?【照片】[^）)\n。]*[）)]?[。]?", "", text)
        text = re.sub(
            r"[（(]?照片\s*(?:ID|id|编号)?[:：]?\s*[A-Za-z0-9_\-./]+[）)]?",
            "",
            text,
        )
        text = re.sub(r"\n{2,}", "\n", text).strip()
    return text or None


def ask(
    question: str,
    db_path: Path | None = None,
    *,
    photo_links: bool = True,
    context: dict[str, Any] | None = None,
) -> AskResult:
    path = db_path or MEMORY_DB
    conn = connect(path)
    init_db(conn)

    intent, params = route_intent(question, context=context)
    # 追问 explain_basis：把上一轮摘要灌进 facts，避免空依据
    if intent == "explain_basis" and context:
        params.setdefault("basis_summary", context.get("basis_summary") or {})
        params.setdefault("last_answer", context.get("last_answer") or "")
        params.setdefault("last_intent", context.get("last_intent") or "")
    facts = gather_facts(conn, intent, params)
    conn.close()

    facts["_photo_links"] = photo_links
    _enrich_facts_photos(facts)

    evidence = build_evidence(facts)
    facts["_evidence"] = evidence

    llm_text = None if intent in _LLM_SKIP_INTENTS else _llm_answer(question, facts)
    template = _template_answer(facts)
    answer = llm_text if llm_text else template

    follow_ups = _build_follow_ups(intent, facts, params)
    turn_context = _build_turn_context(intent, params, facts, answer)

    # 内部字段不进入 API facts
    facts.pop("_evidence", None)

    return AskResult(
        intent=intent,
        facts=facts,
        answer=answer,
        used_llm=bool(llm_text),
        photo_links=photo_links,
        follow_ups=follow_ups,
        turn_context=turn_context,
        evidence=evidence,
    )
