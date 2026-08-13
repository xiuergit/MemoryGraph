"""家庭成员档案：生日、角色、拍照时年龄计算。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from hub.shared.config import FACE_REGISTRY_FILE
from hub.shared.schema import AgeAtPhoto, Person

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FamilyMember:
    person_id: str
    name: str
    birth_date: date | None = None
    role: str = ""
    match_threshold: float | None = None


def _parse_birth_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    logger.warning("无法解析出生日期: %s", raw)
    return None


def _parse_photo_date(timestamp: str) -> date | None:
    if not timestamp or not timestamp.strip():
        return None
    text = timestamp.strip()
    try:
        if "T" in text:
            return datetime.fromisoformat(text).date()
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        logger.debug("无法解析拍摄日期: %s", timestamp)
        return None


def load_family_members(registry_file: Path | None = None) -> dict[str, FamilyMember]:
    """读取家庭成员档案。兼容旧格式 {\"baby\": \"宝宝\"}。"""
    path = registry_file or FACE_REGISTRY_FILE
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 registry.json 失败: %s", exc)
        return {}

    if not isinstance(data, dict):
        return {}

    members: dict[str, FamilyMember] = {}
    for person_id, raw in data.items():
        pid = str(person_id)
        if isinstance(raw, str):
            members[pid] = FamilyMember(person_id=pid, name=raw)
            continue
        if not isinstance(raw, dict):
            continue
        # alias 条目仅用于人脸参考照目录合并，不参与家庭成员档案
        if str(raw.get("alias", "")).strip():
            continue
        birth = _parse_birth_date(raw.get("birth_date"))
        threshold_raw = raw.get("match_threshold")
        match_threshold: float | None = None
        if threshold_raw not in (None, ""):
            try:
                match_threshold = float(threshold_raw)
            except (TypeError, ValueError):
                logger.warning("无法解析 match_threshold: %s (%s)", threshold_raw, pid)
        members[pid] = FamilyMember(
            person_id=pid,
            name=str(raw.get("name", pid)),
            birth_date=birth,
            role=str(raw.get("role", "")),
            match_threshold=match_threshold,
        )
    return members


@dataclass(frozen=True)
class ResolvedPerson:
    person_id: str
    name: str
    search_values: tuple[str, ...]


# 常见叫法 → person_id（registry 中文名之外的口语）
PERSON_NICKNAMES: dict[str, tuple[str, ...]] = {
    "laoyiyi": ("老姨",),
    "laoyifu": ("姨夫",),
    "waigong": ("姥爷",),
    "mom": ("母亲",),
    "dad": ("父亲",),
}


def _is_placeholder_name(person_id: str, name: str) -> bool:
    if not name or name == person_id:
        return True
    return person_id.startswith("unk_") and name.startswith("unk_")


def _nickname_entries(
    members: dict[str, FamilyMember],
) -> list[tuple[str, str]]:
    """(nickname, person_id)"""
    rows: list[tuple[str, str]] = []
    for person_id, aliases in PERSON_NICKNAMES.items():
        if person_id not in members:
            continue
        for alias in aliases:
            if alias:
                rows.append((alias, person_id))
    return rows


def resolve_person(
    needle: str,
    *,
    registry_file: Path | None = None,
) -> ResolvedPerson | None:
    """把问句里的中文名 / 昵称 / person_id 解析为 registry 成员。"""
    text = needle.strip()
    if not text:
        return None

    members = load_family_members(registry_file)

    if text in members:
        member = members[text]
        return ResolvedPerson(
            person_id=text,
            name=member.name or text,
            search_values=_search_values(text, member),
        )

    best: tuple[int, str] | None = None
    for person_id, member in members.items():
        name = member.name.strip()
        if name and not _is_placeholder_name(person_id, name):
            if text == name or text in name:
                score = len(name) if text == name else len(text)
                if best is None or score > best[0]:
                    best = (score, person_id)
            if name in text:
                score = len(name)
                if best is None or score > best[0]:
                    best = (score, person_id)

    for alias, person_id in _nickname_entries(members):
        if text == alias or alias in text:
            score = len(alias)
            if best is None or score > best[0]:
                best = (score, person_id)

    if best is None:
        return None

    person_id = best[1]
    member = members[person_id]
    return ResolvedPerson(
        person_id=person_id,
        name=member.name or person_id,
        search_values=_search_values(person_id, member),
    )


def _search_values(person_id: str, member: FamilyMember) -> tuple[str, ...]:
    values: list[str] = [person_id]
    name = member.name.strip()
    if name and name not in values:
        values.append(name)
    for alias in PERSON_NICKNAMES.get(person_id, ()):
        if alias not in values:
            values.append(alias)
    return tuple(values)


def match_persons_in_text(
    text: str,
    *,
    registry_file: Path | None = None,
) -> list[ResolvedPerson]:
    """从文本中按最长匹配提取人物（去重，保持出现顺序）。"""
    members = load_family_members(registry_file)
    hits: list[tuple[int, int, str]] = []

    for person_id, member in members.items():
        name = member.name.strip()
        if name and not _is_placeholder_name(person_id, name) and name in text:
            hits.append((text.index(name), len(name), person_id))
        if person_id in text:
            hits.append((text.index(person_id), len(person_id), person_id))

    for alias, person_id in _nickname_entries(members):
        if alias in text:
            hits.append((text.index(alias), len(alias), person_id))

    hits.sort(key=lambda item: (item[0], -item[1]))
    seen: set[str] = set()
    ordered: list[ResolvedPerson] = []
    for _, _, person_id in hits:
        if person_id in seen:
            continue
        seen.add(person_id)
        member = members[person_id]
        ordered.append(
            ResolvedPerson(
                person_id=person_id,
                name=member.name or person_id,
                search_values=_search_values(person_id, member),
            )
        )
    return ordered


def person_search_tokens(
    needle: str,
    *,
    registry_file: Path | None = None,
) -> list[str]:
    """SQLite 检索用的 person_id / 中文名 / 昵称列表。"""
    resolved = resolve_person(needle, registry_file=registry_file)
    if resolved:
        return list(resolved.search_values)
    text = needle.strip()
    return [text] if text else []


def load_display_names(registry_file: Path | None = None) -> dict[str, str]:
    return {pid: m.name for pid, m in load_family_members(registry_file).items()}


def default_ask_person(registry_file: Path | None = None) -> str:
    """问答默认人物：仅一名 child 时用该人；否则仅一名有效成员时用该人。

    当前家庭 child 仅「面面」时，无人名短句（哭 / 骑车 / 最近去哪）会落到她。
    """
    members = [
        m
        for m in load_family_members(registry_file).values()
        if m.name and not _is_placeholder_name(m.person_id, m.name)
    ]
    children = [m for m in members if m.role == "child"]
    if len(children) == 1:
        return children[0].name
    if len(members) == 1:
        return members[0].name
    return ""


def compute_age_at_photo(
    birth_date: date,
    photo_date: date,
    *,
    role: str = "",
) -> AgeAtPhoto:
    """根据生日与拍摄日期计算年龄。"""
    if photo_date < birth_date:
        return AgeAtPhoto(
            years=0,
            months=0,
            days=0,
            total_days=0,
            label="",
        )

    total_days = (photo_date - birth_date).days
    years = photo_date.year - birth_date.year
    months = photo_date.month - birth_date.month
    days = photo_date.day - birth_date.day

    if days < 0:
        months -= 1
        prev_month_last = photo_date.replace(day=1) - timedelta(days=1)
        days += prev_month_last.day
    if months < 0:
        years -= 1
        months += 12

    if role == "child":
        label = f"{years}岁{months}个月{days}天"
        if total_days < 365 * 6:
            label = f"{label}（第{total_days}天）"
    else:
        label = f"{years}岁{months}个月"

    return AgeAtPhoto(
        years=years,
        months=months,
        days=days,
        total_days=total_days,
        label=label,
    )


def enrich_people_with_age(
    people: list[Person],
    timestamp: str,
    *,
    registry_file: Path | None = None,
) -> list[Person]:
    """为已识别的人物补充 role 与 age_at_photo。"""
    photo_date = _parse_photo_date(timestamp)
    if photo_date is None:
        return people

    members = load_family_members(registry_file)
    enriched: list[Person] = []

    for person in people:
        member = members.get(person["id"])
        if member is None:
            enriched.append(person)
            continue

        updated = dict(person)
        updated["name"] = member.name or person["name"]
        if person.get("match_method"):
            updated["match_method"] = person["match_method"]
        if member.role:
            updated["role"] = member.role
        if member.birth_date is not None:
            updated["age_at_photo"] = compute_age_at_photo(
                member.birth_date,
                photo_date,
                role=member.role,
            )
        enriched.append(Person(**updated))

    return enriched
