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


def route_intent(question: str) -> tuple[str, dict[str, Any]]:
    q = question.strip()
    params: dict[str, Any] = {"limit": 5}

    if _AGE_RE.search(q):
        params["person"] = _extract_person(q)
        return "person_age", params

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


def _template_answer(facts: dict[str, Any]) -> str:
    intent = facts.get("intent", "unknown")

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

    return "暂时无法理解这个问题。可以试试：最近的照片 / 面面几岁了 / 面面最近在哪里玩"


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
