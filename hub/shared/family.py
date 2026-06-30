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
        members[pid] = FamilyMember(
            person_id=pid,
            name=str(raw.get("name", pid)),
            birth_date=_parse_birth_date(raw.get("birth_date")),
            role=str(raw.get("role", "")),
        )
    return members


def load_display_names(registry_file: Path | None = None) -> dict[str, str]:
    return {pid: m.name for pid, m in load_family_members(registry_file).items()}


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
