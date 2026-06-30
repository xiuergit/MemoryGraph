"""记忆库结构化查询，供 Agent 调用。"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from hub.shared.family import compute_age_at_photo, load_family_members
from hub.shared.index_db import connect, init_db, list_timeline, search_photos


def _find_member(name: str) -> tuple[str, Any] | None:
    """按中文名或 id 查找家庭成员。"""
    needle = name.strip()
    if not needle:
        return None
    for person_id, member in load_family_members().items():
        if needle in member.name or needle == person_id:
            return person_id, member
    return None


def get_recent_photos(
    conn: sqlite3.Connection,
    *,
    person: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    if person:
        return search_photos(conn, person=person, limit=limit)
    return list_timeline(conn, limit=limit)


def get_person_age(person: str) -> dict[str, Any]:
    """返回某人当前年龄（按 registry 生日）及最近一张照片里的年龄记录。"""
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person}

    person_id, member = found
    today = date.today()
    current_age = None
    if member.birth_date:
        current_age = compute_age_at_photo(
            member.birth_date,
            today,
            role=member.role,
        )

    return {
        "found": True,
        "person_id": person_id,
        "name": member.name,
        "birth_date": member.birth_date.isoformat() if member.birth_date else "",
        "current_age": dict(current_age) if current_age else None,
    }


def get_person_age_from_latest_photo(
    conn: sqlite3.Connection,
    person: str,
) -> dict[str, Any] | None:
    found = _find_member(person)
    if found is None:
        return None
    _, member = found

    row = conn.execute(
        """
        SELECT p.timestamp, pp.age_label
        FROM photo_people pp
        JOIN photos p ON p.photo_id = pp.photo_id
        WHERE pp.person_name = ? OR pp.person_id = ?
        ORDER BY p.timestamp DESC
        LIMIT 1
        """,
        (member.name, member.person_id),
    ).fetchone()
    if row is None:
        return None
    return {"timestamp": row["timestamp"], "age_label": row["age_label"]}


def get_person_recent_places(
    conn: sqlite3.Connection,
    *,
    person: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """某人最近有 location 的照片，附带解析后的地址。"""
    photos = search_photos(conn, person=person, limit=limit * 3)
    places: list[dict[str, Any]] = []
    seen: set[str] = set()

    for photo in photos:
        location = (photo.get("location") or "").strip()
        if not location or location in seen:
            continue
        seen.add(location)
        places.append(
            {
                "photo_id": photo["photo_id"],
                "timestamp": photo.get("timestamp", ""),
                "location": photo.get("location") or "",
                "location_coords": photo.get("location_coords") or "",
                "scene": photo.get("scene") or "",
            }
        )
        if len(places) >= limit:
            break
    return places


def gather_facts(
    conn: sqlite3.Connection,
    intent: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    person = params.get("person", "")
    limit = int(params.get("limit", 5))

    if intent == "recent_photos":
        photos = get_recent_photos(conn, person=person, limit=limit)
        return {"intent": intent, "person": person, "photos": photos}

    if intent == "person_age":
        age_info = get_person_age(person)
        latest = get_person_age_from_latest_photo(conn, person) if age_info.get("found") else None
        return {"intent": intent, "person": person, "age_info": age_info, "latest_photo_age": latest}

    if intent == "person_recent_places":
        places = get_person_recent_places(conn, person=person, limit=limit)
        return {"intent": intent, "person": person, "places": places}

    return {"intent": "unknown", "question_params": params}
