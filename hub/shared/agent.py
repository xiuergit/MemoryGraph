"""记忆问答 Agent：规则路由 → 查库 → Ollama 组织回答（失败则模板兜底）。"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hub.shared.config import (
    MEMORY_DB,
    OLLAMA_BASE_URL,
    OLLAMA_CHAT_ENABLED,
    OLLAMA_CHAT_MODEL,
    OLLAMA_TIMEOUT,
)
from hub.shared.family import load_family_members
from hub.shared.index_db import connect, init_db
from hub.shared.query import gather_facts

logger = logging.getLogger(__name__)

_RECENT_RE = re.compile(r"最近|近期|最新")
_PHOTO_RE = re.compile(r"照片|相片|图片|拍的|拍了")
_AGE_RE = re.compile(r"几岁|多大|年龄|年岁")
_PLACE_RE = re.compile(r"在哪|哪里|哪儿|去过|玩过|地方|地点")
_CITIES_RE = re.compile(r"哪些城市|什么城市|哪些省|什么省|哪些省份|去过.*城市|城市.*去过")
_STATS_RE = re.compile(r"多少|几张|几个|一共有|一共|总共|统计|有多少")
_AGE_RANK_RE = re.compile(r"最多|最长|常去|待得|待过|待的|去哪|哪个地方|哪.*地方.*最")
_PLACES_LIST_RE = re.compile(r"哪些地方|什么地方|去过哪些(?!城市)")
_GROUP_PHOTO_RE = re.compile(r"合影|合照|同框")
_PEAK_DAY_RE = re.compile(r"哪天的|哪一天|哪天.*最多|照片最多|最多.*哪天|一天.*最多")
_EMOTION_CTX_RE = re.compile(r"表情|情绪|emotion", re.IGNORECASE)
_TERM_QUESTION_RE = re.compile(r"有.*吗|有没有|没有.*吗|吗[？?]?$|是不是")
_FIRST_WHEN_RE = re.compile(r"第一次|首次|最早|什么时候|何时|哪天|哪年")
_EMOTION_TERM_HINTS = (
    "哭泣", "哭闹", "哭", "微笑", "笑", "开心", "高兴", "快乐", "平静", "专注",
    "好奇", "安静", "温和", "惊讶", "生气", "难过", "委屈",
)
_CN_AGE_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_PLACE_PLACEHOLDERS = frozenset({
    "哪里", "哪儿", "什么地方", "哪些地方", "哪里玩", "哪儿玩", "的地方",
})


@dataclass
class AskResult:
    intent: str
    facts: dict[str, Any]
    answer: str
    used_llm: bool


def _all_person_names() -> list[str]:
    return [m.name for m in load_family_members().values() if m.name]


def _extract_person(question: str) -> str:
    for name in _all_person_names():
        if name in question:
            return name
    for person_id, member in load_family_members().items():
        if person_id in question:
            return member.name or person_id
    names = _all_person_names()
    return names[0] if len(names) == 1 else ""


def _extract_group_persons(question: str) -> list[str]:
    """从问句中按出现顺序提取多个家庭成员名。"""
    hits: list[tuple[int, str]] = []
    for person_id, member in load_family_members().items():
        name = member.name
        if name and name in question:
            hits.append((question.index(name), name))
        elif person_id in question:
            label = member.name or person_id
            hits.append((question.index(person_id), label))
    hits.sort(key=lambda item: item[0])
    seen: set[str] = set()
    ordered: list[str] = []
    for _, name in hits:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _is_group_photo_question(question: str, persons: list[str]) -> bool:
    if len(persons) < 2:
        return False
    if _GROUP_PHOTO_RE.search(question):
        return True
    if re.search(r"和", question) and (
        _PHOTO_RE.search(question) or re.search(r"有哪些|哪些|列出", question)
    ):
        return True
    return False


def _extract_age_years(question: str) -> int | None:
    match = re.search(r"(\d+)\s*岁", question)
    if match:
        return int(match.group(1))
    match = re.search(r"([一二两三四五六七八九十])\s*岁", question)
    if match:
        return _CN_AGE_DIGITS.get(match.group(1))
    return None


def _extract_emotion_term(question: str) -> str:
    for hint in _EMOTION_TERM_HINTS:
        if hint in question:
            return hint
    return ""


def _extract_place_query(question: str) -> str:
    patterns = (
        r"去(?:过)?\s*(.+?)(?:是什么时候|是何时|几时|几次|吗)",
        r"在\s*(.+?)(?:去过|玩过|几次|的照片)",
        r"去(?:过)?\s*(.+?)(?:玩过|待过)",
        r"去(?:过)?\s*(.+?)(?:是几岁|几岁|多大|多少岁)",
        r"在\s*(.+?)(?:是几岁|几岁|多大|多少岁)",
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
        place = re.sub(r"^过+", "", place).strip()
        place = re.sub(r"(玩过|去过|待过)+$", "", place).strip()
        if place and place not in _PLACE_PLACEHOLDERS:
            return place
    return ""


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


def route_intent(question: str) -> tuple[str, dict[str, Any]]:
    q = question.strip()
    params: dict[str, Any] = {"limit": 10}

    age_years = _extract_age_years(q)
    if age_years is not None and _AGE_RANK_RE.search(q):
        params["person"] = _extract_person(q)
        params["age_years"] = age_years
        return "person_age_place_rank", params

    if _STATS_RE.search(q):
        params["person"] = _extract_person(q)
        params["focus"] = _detect_stats_focus(q)
        return "library_stats", params

    group_persons = _extract_group_persons(q)
    if _is_group_photo_question(q, group_persons):
        params["persons"] = group_persons
        params["limit"] = 20
        return "group_photos", params

    emotion_term = _extract_emotion_term(q)
    if emotion_term and _FIRST_WHEN_RE.search(q):
        params["person"] = _extract_person(q)
        params["term"] = emotion_term
        params["term_type"] = "emotion"
        return "term_first", params

    if emotion_term and (
        _EMOTION_CTX_RE.search(q)
        or _TERM_QUESTION_RE.search(q)
        or _PHOTO_RE.search(q)
    ):
        params["person"] = _extract_person(q)
        params["term"] = emotion_term
        params["term_type"] = "emotion"
        return "term_lookup", params

    if _PEAK_DAY_RE.search(q) and _PHOTO_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_peak_day", params

    place_query = _extract_place_query(q)
    if place_query:
        params["person"] = _extract_person(q)
        params["place"] = place_query
        if _AGE_RE.search(q):
            params["focus"] = "age"
        elif re.search(r"吗[？?]?$", q):
            params["focus"] = "yesno"
        return "person_at_place", params

    if _AGE_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_age", params

    if emotion_term and re.search(r"最多|最长|常去", q) and re.search(r"地方|地点", q):
        params["person"] = _extract_person(q)
        params["term"] = emotion_term
        params["term_type"] = "emotion"
        return "person_emotion_place_rank", params

    if _CITIES_RE.search(q):
        params["person"] = _extract_person(q)
        if re.search(r"哪些省|什么省|哪些省份", q):
            params["group_by"] = "province"
        return "person_cities_visited", params

    if _PLACES_LIST_RE.search(q):
        params["person"] = _extract_person(q)
        params["limit"] = 20
        return "person_places_visited", params

    if _AGE_RANK_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_place_rank", params

    if _PLACE_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_recent_places", params

    if _RECENT_RE.search(q) and _PHOTO_RE.search(q):
        person = _extract_person(q)
        if person:
            params["person"] = person
        return "recent_photos", params

    if _RECENT_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_recent_places" if params["person"] else "recent_photos", params

    if _PHOTO_RE.search(q):
        params["person"] = _extract_person(q)
        return "recent_photos", params

    return "recent_photos", params


def _format_photo_line(photo: dict[str, Any]) -> str:
    ts = photo.get("timestamp") or "未知时间"
    people = photo.get("people") or "—"
    scene = photo.get("scene") or "—"
    loc = photo.get("location") or "—"
    return f"- {photo.get('photo_id')} | {ts} | {people} | {loc} | {scene}"


def _pct_line(count: int, total: int, pct: float) -> str:
    return f"{count:,} 张（占 {pct}%）" if total else "0 张"


def _template_answer(facts: dict[str, Any]) -> str:
    intent = facts.get("intent", "unknown")

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

    if intent == "term_lookup":
        if not facts.get("found", True):
            who = facts.get("person") or ""
            if who:
                return f"没有在家庭成员档案里找到「{who}」。"
            return "请说明要查的表情关键词。"
        term = facts.get("term") or ""
        count = int(facts.get("photo_count") or 0)
        who = facts.get("person") or ""
        scope = f"{who}的照片里" if who else "记忆库"
        matched = facts.get("matched_terms") or []
        term_detail = ""
        if matched:
            term_detail = "（" + "、".join(f"{m['term']} {m['count']}" for m in matched) + "）"

        if count == 0:
            return (
                f"{scope}没有找到与「{term}」相关的表情标注。"
                "（部分照片可能尚未做 vision 补全）"
            )

        answer = f"有的，{scope}与「{term}」相关的表情共 {count} 张{term_detail}。"
        photos = facts.get("sample_photos") or []
        if photos:
            lines = [_format_photo_line(p) for p in photos]
            answer += "\n最近几张：\n" + "\n".join(lines)
        return answer

    if intent == "term_first":
        if not facts.get("found", True):
            who = facts.get("person") or ""
            if who:
                return f"没有在家庭成员档案里找到「{who}」。"
            return "请说明要查的表情关键词。"
        term = facts.get("term") or ""
        who = facts.get("person") or ""
        scope = who or "记忆库"
        photo = facts.get("photo")
        if not photo:
            whose = f"{who}的" if who else ""
            return (
                f"没有找到{whose}与「{term}」相关的表情记录。"
                "（部分照片可能尚未做 vision 补全）"
            )
        ts = photo.get("timestamp") or "未知时间"
        age = photo.get("age_label") or ""
        loc = photo.get("location") or ""
        terms = photo.get("matched_terms") or term
        pid = photo.get("photo_id") or ""
        parts = [f"{scope}最早记录到「{terms}」是在 {ts}"]
        if age:
            parts.append(f"当时 {age}")
        if loc:
            parts.append(f"地点 {loc}")
        parts.append(f"（{pid}）")
        return "，".join(parts[:-1]) + parts[-1]

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
            return f"没有在家庭成员档案里找到「{facts.get('person', '')}」。"
        person = facts.get("person") or "家人"
        matched = int(facts.get("matched_photos") or 0)
        total = int(facts.get("total_photos") or 0)
        total_places = int(facts.get("total_places") or 0)
        places = facts.get("places") or []
        if not places:
            return f"没有找到 {person} 带地点信息的记录。（共 {total} 张照片）"
        header = (
            f"{person} 去过的地点（共 {total_places} 处，"
            f"按照片数列出前 {len(places)} 个；{matched} 张有地点，总计 {total} 张）："
        )
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
                    f"（{first.get('photo_id', '')}）"
                )
            if last and last.get("photo_id") != (first or {}).get("photo_id"):
                loc = last.get("location") or last.get("location_city") or "—"
                lines.append(
                    f"最近一次：{last.get('timestamp', '')} @ {loc}"
                    f"（{last.get('photo_id', '')}）"
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
                f"（{first.get('photo_id', '')}）"
            )
        if last and last.get("photo_id") != (first or {}).get("photo_id"):
            loc = last.get("location") or last.get("location_city") or "—"
            age = f"，当时 {last['age_label']}" if last.get("age_label") else ""
            lines.append(
                f"最近一次：{last.get('timestamp', '')} @ {loc}{age}"
                f"（{last.get('photo_id', '')}）"
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
        if shown < total:
            header = f"{label} 的合影共 {total} 张，最近 {shown} 张："
        else:
            header = f"{label} 的合影共 {total} 张："
        lines = [_format_photo_line(p) for p in photos]
        return header + "\n" + "\n".join(lines)

    if intent == "recent_photos":
        photos = facts.get("photos") or []
        person = facts.get("person") or ""
        if not photos:
            who = f"{person}的" if person else ""
            return f"记忆库里还没有{who}最近照片记录。可以先跑 photo2json 和 memory_index sync。"
        header = f"{'最近 ' + person + ' 的' if person else '最近'}照片（共 {len(photos)} 张）："
        lines = [_format_photo_line(p) for p in photos]
        return header + "\n" + "\n".join(lines)

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
        lines = [
            f"- {p.get('timestamp', '')} | {p.get('location') or '—'}"
            + (f" | {p['scene']}" if p.get("scene") else "")
            for p in places
        ]
        return f"{person} 最近出现过的地点：\n" + "\n".join(lines)

    return (
        "暂时无法理解这个问题。可以试试：\n"
        "  · 有多少张有表情 / 表情里有哭吗 / 第一次哭是什么时候\n"
        "  · 面面有多少张照片\n"
        "  · 面面 4 岁时在哪个地方待的时间最长\n"
        "  · 面面几岁了 / 面面最近在哪里玩 / 面面常去的地方是哪里\n"
        "  · 面面去动物园是什么时候 / 去过几次\n"
        "  · 面面哪天的照片最多，在什么地方"
    )


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


def _llm_answer(question: str, facts: dict[str, Any]) -> str | None:
    if not OLLAMA_CHAT_ENABLED:
        return None
    system = (
        "你是家庭记忆助手 MemoryGraph。只能根据提供的「查询事实」回答，不要编造。"
        "如果事实不足，明确说不知道。用简体中文，语气自然简洁。"
    )
    user = (
        f"用户问题：{question}\n\n"
        f"查询事实（JSON）：\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
        "请用一段话回答，必要时列出 photo_id 或时间地点。"
    )
    try:
        return _call_ollama_chat(system, user)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Ollama 问答失败，使用模板回答: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Ollama 问答异常，使用模板回答: %s", exc)
        return None


def ask(question: str, db_path: Path | None = None) -> AskResult:
    path = db_path or MEMORY_DB
    conn = connect(path)
    init_db(conn)

    intent, params = route_intent(question)
    facts = gather_facts(conn, intent, params)
    conn.close()

    llm_text = _llm_answer(question, facts)
    template = _template_answer(facts)
    answer = llm_text if llm_text else template

    return AskResult(
        intent=intent,
        facts=facts,
        answer=answer,
        used_llm=bool(llm_text),
    )
