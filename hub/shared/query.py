"""记忆库结构化查询，供 Agent 调用。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from hub.shared.family import (
    compute_age_at_photo,
    load_family_members,
    resolve_person,
    person_search_tokens,
)
from hub.shared.index_db import connect, init_db, list_timeline, search_photos

SEASON_MONTHS: dict[str, tuple[int, ...]] = {
    "春": (3, 4, 5),
    "夏": (6, 7, 8),
    "秋": (9, 10, 11),
    "冬": (12, 1, 2),
}


def _parse_day(value: str) -> date | None:
    raw = (value or "").strip()[:10]
    if len(raw) < 10:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _short_age_label(age: Any) -> str:
    if not age:
        return ""
    years = int(age.get("years") or 0)
    months = int(age.get("months") or 0)
    days = int(age.get("days") or 0)
    total_days = int(age.get("total_days") or 0)
    if years <= 0 and months <= 0:
        return f"{total_days}天" if total_days else ""
    if years <= 0:
        return f"{months}个月"
    if months:
        return f"{years}岁{months}个月"
    return f"{years}岁"


def _find_member(name: str) -> tuple[str, Any] | None:
    """按中文名、昵称或 id 查找家庭成员。"""
    resolved = resolve_person(name)
    if resolved is None:
        return None
    member = load_family_members().get(resolved.person_id)
    if member is None:
        return None
    return resolved.person_id, member


def get_recent_photos(
    conn: sqlite3.Connection,
    *,
    person: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    if person:
        return search_photos(conn, person=person, limit=limit)
    return list_timeline(conn, limit=limit)


def get_group_photos(
    conn: sqlite3.Connection,
    *,
    persons: list[str],
    limit: int = 20,
) -> dict[str, Any]:
    """多人同框：照片里同时识别到所有指定成员。"""
    if len(persons) < 2:
        return {"found": False, "persons": persons, "reason": "need_at_least_two"}

    resolved: list[tuple[str, str]] = []
    for person in persons:
        found = _find_member(person)
        if found is None:
            return {"found": False, "persons": persons, "unknown": person}
        person_id, member = found
        resolved.append((member.name, person_id))

    def _pair_count(name_a: str, id_a: str, name_b: str, id_b: str) -> int:
        return conn.execute(
            """
            SELECT COUNT(DISTINCT p.photo_id) FROM photos p
            WHERE EXISTS (
                SELECT 1 FROM photo_people pp
                WHERE pp.photo_id = p.photo_id
                  AND (pp.person_name = ? OR pp.person_id = ?)
            )
              AND EXISTS (
                SELECT 1 FROM photo_people pp
                WHERE pp.photo_id = p.photo_id
                  AND (pp.person_name = ? OR pp.person_id = ?)
            )
            """,
            (name_a, id_a, name_b, id_b),
        ).fetchone()[0]

    exists_parts: list[str] = []
    params: list[str] = []
    for name, person_id in resolved:
        exists_parts.append(
            """
            EXISTS (
                SELECT 1 FROM photo_people pp
                WHERE pp.photo_id = p.photo_id
                  AND (pp.person_name = ? OR pp.person_id = ?)
            )
            """
        )
        params.extend([name, person_id])

    where = " AND ".join(exists_parts)
    total_count = conn.execute(
        f"SELECT COUNT(DISTINCT p.photo_id) FROM photos p WHERE {where}",
        params,
    ).fetchone()[0]

    pair_counts: list[dict[str, Any]] = []
    if total_count == 0 and len(resolved) >= 2:
        for i in range(len(resolved)):
            name_a, id_a = resolved[i]
            for j in range(i + 1, len(resolved)):
                name_b, id_b = resolved[j]
                pair_counts.append(
                    {
                        "persons": [name_a, name_b],
                        "count": _pair_count(name_a, id_a, name_b, id_b),
                    }
                )

    rows = conn.execute(
        f"""
        SELECT
            p.photo_id,
            p.timestamp,
            p.scene,
            p.location,
            p.location_coords,
            p.source_path,
            GROUP_CONCAT(DISTINCT pp_all.person_name) AS people
        FROM photos p
        LEFT JOIN photo_people pp_all ON pp_all.photo_id = p.photo_id
        WHERE {where}
        GROUP BY p.photo_id
        ORDER BY p.timestamp DESC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()

    return {
        "found": True,
        "persons": [name for name, _ in resolved],
        "total_count": total_count,
        "pair_counts": pair_counts,
        "photos": [dict(row) for row in rows],
    }


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
    limit: int = 10,
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


def _person_photo_exists_sql(alias: str = "p") -> str:
    return f"""
        EXISTS (
            SELECT 1 FROM photo_people pp
            WHERE pp.photo_id = {alias}.photo_id
              AND (pp.person_name LIKE ? OR pp.person_id LIKE ?)
        )
    """


def _place_match_sql(alias: str = "p") -> str:
    """地点关键词：POI 名 + 省 / 市 / 区。"""
    return f"""(
        {alias}.location LIKE ?
        OR {alias}.location_province LIKE ?
        OR {alias}.location_city LIKE ?
        OR {alias}.location_district LIKE ?
    )"""


def _place_match_params(pattern: str) -> list[str]:
    return [pattern, pattern, pattern, pattern]


def _person_pattern(person: str) -> list[str]:
    tokens = person_search_tokens(person)
    patterns: list[str] = []
    for token in tokens:
        pat = f"%{token}%"
        if pat not in patterns:
            patterns.append(pat)
    return patterns or [f"%{person}%", f"%{person}%"]


def _term_type_count_sql(exists: str, term_type: str) -> str:
    return f"""
        SELECT COUNT(DISTINCT p.photo_id) FROM photos p
        WHERE {exists}
          AND EXISTS (
            SELECT 1 FROM photo_terms t
            WHERE t.photo_id = p.photo_id AND t.term_type = ?
          )
    """


def _term_distribution_sql(exists: str, term_type: str, limit: int) -> str:
    return f"""
        SELECT t.term, COUNT(DISTINCT p.photo_id) AS cnt
        FROM photos p
        JOIN photo_terms t ON t.photo_id = p.photo_id
        WHERE {exists} AND t.term_type = ?
        GROUP BY t.term
        ORDER BY cnt DESC
        LIMIT ?
    """


def _photo_coverage_row(conn: sqlite3.Connection, exists: str, params: list[Any]) -> sqlite3.Row:
    where = f"WHERE {exists}" if exists != "1=1" else ""
    return conn.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN p.timestamp != '' THEN 1 ELSE 0 END) AS with_timestamp,
            SUM(CASE WHEN p.device_id != '' THEN 1 ELSE 0 END) AS with_device_id,
            SUM(CASE WHEN p.location != '' THEN 1 ELSE 0 END) AS with_location,
            SUM(CASE WHEN p.location_coords != '' THEN 1 ELSE 0 END) AS with_location_coords,
            SUM(CASE WHEN p.location_province != '' THEN 1 ELSE 0 END) AS with_location_province,
            SUM(CASE WHEN p.location_city != '' THEN 1 ELSE 0 END) AS with_location_city,
            SUM(CASE WHEN p.location_district != '' THEN 1 ELSE 0 END) AS with_location_district,
            SUM(CASE WHEN p.scene != '' THEN 1 ELSE 0 END) AS with_scene,
            SUM(CASE WHEN p.face_detected = 1 THEN 1 ELSE 0 END) AS with_face
        FROM photos p
        {where}
        """,
        params,
    ).fetchone()


def _build_field_coverage(
    conn: sqlite3.Connection,
    *,
    total: int,
    exists: str,
    params: list[Any],
) -> list[dict[str, Any]]:
    row = _photo_coverage_row(conn, exists, params)

    def _pct(n: int) -> float:
        return round(100.0 * n / total, 1) if total else 0.0

    people_count = conn.execute(
        f"""
        SELECT COUNT(DISTINCT p.photo_id) FROM photos p
        WHERE {exists}
          AND EXISTS (SELECT 1 FROM photo_people pp WHERE pp.photo_id = p.photo_id)
        """,
        params,
    ).fetchone()[0]
    age_count = conn.execute(
        f"""
        SELECT COUNT(DISTINCT p.photo_id) FROM photos p
        WHERE {exists}
          AND EXISTS (
            SELECT 1 FROM photo_people pp
            WHERE pp.photo_id = p.photo_id AND pp.age_label != ''
          )
        """,
        params,
    ).fetchone()[0]

    term_counts: dict[str, int] = {}
    for term_type in ("objects", "actions", "emotion", "tags"):
        term_counts[term_type] = conn.execute(
            _term_type_count_sql(exists, term_type),
            (*params, term_type),
        ).fetchone()[0]

    fields = [
        ("timestamp", "拍摄时间", int(row["with_timestamp"])),
        ("device_id", "设备来源", int(row["with_device_id"])),
        ("people", "识别人物", people_count),
        ("age_label", "年龄标注", age_count),
        ("location", "地点名称", int(row["with_location"])),
        ("location_coords", "GPS 坐标", int(row["with_location_coords"])),
        ("location_province", "省份", int(row["with_location_province"])),
        ("location_city", "城市", int(row["with_location_city"])),
        ("location_district", "区县", int(row["with_location_district"])),
        ("scene", "场景描述", int(row["with_scene"])),
        ("objects", "物体 objects", term_counts["objects"]),
        ("actions", "动作 actions", term_counts["actions"]),
        ("emotion", "表情 emotion", term_counts["emotion"]),
        ("tags", "标签 tags", term_counts["tags"]),
        ("face_detected", "人脸检测 quality", int(row["with_face"])),
    ]
    return [
        {
            "field": field,
            "label": label,
            "count": count,
            "percent": _pct(count),
        }
        for field, label, count in fields
    ]


def _build_distributions(
    conn: sqlite3.Connection,
    *,
    exists: str,
    params: list[Any],
    limit: int = 10,
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for term_type, title in (
        ("emotion", "emotion"),
        ("tags", "tags"),
        ("objects", "objects"),
        ("actions", "actions"),
    ):
        rows = conn.execute(
            _term_distribution_sql(exists, term_type, limit),
            (*params, term_type, limit),
        ).fetchall()
        if rows:
            out[title] = [{"term": r["term"], "count": r["cnt"]} for r in rows]

    device_rows = conn.execute(
        f"""
        SELECT p.device_id AS term, COUNT(*) AS cnt
        FROM photos p
        WHERE {exists} AND p.device_id != ''
        GROUP BY p.device_id
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    if device_rows:
        out["device_id"] = [{"term": r["term"], "count": r["cnt"]} for r in device_rows]

    return out


def get_library_stats(
    conn: sqlite3.Connection,
    *,
    person: str = "",
) -> dict[str, Any]:
    """记忆库数量统计（全库或按人物）。"""
    if person:
        found = _find_member(person)
        if found is None:
            return {"found": False, "person": person}
        _, member = found
        person_name = member.name
        person_id = member.person_id
        pf = [person_name, person_id]
        exists = _person_photo_exists_sql("p")

        total = conn.execute(
            f"SELECT COUNT(*) FROM photos p WHERE {exists}",
            pf,
        ).fetchone()[0]
        with_face = conn.execute(
            f"SELECT COUNT(*) FROM photos p WHERE {exists} AND p.face_detected = 1",
            pf,
        ).fetchone()[0]
        with_location = conn.execute(
            f"SELECT COUNT(*) FROM photos p WHERE {exists} AND p.location != ''",
            pf,
        ).fetchone()[0]
        with_scene = conn.execute(
            f"SELECT COUNT(*) FROM photos p WHERE {exists} AND p.scene != ''",
            pf,
        ).fetchone()[0]
        with_emotion = conn.execute(
            f"""
            SELECT COUNT(DISTINCT p.photo_id) FROM photos p
            WHERE {exists}
              AND EXISTS (
                SELECT 1 FROM photo_terms t
                WHERE t.photo_id = p.photo_id AND t.term_type = 'emotion'
              )
            """,
            pf,
        ).fetchone()[0]
        emotion_rows = conn.execute(
            f"""
            SELECT t.term, COUNT(DISTINCT p.photo_id) AS cnt
            FROM photos p
            JOIN photo_terms t ON t.photo_id = p.photo_id
            WHERE {exists} AND t.term_type = 'emotion'
            GROUP BY t.term
            ORDER BY cnt DESC
            LIMIT 8
            """,
            pf,
        ).fetchall()
        scope = person_name
        exists_clause = exists
        query_params: list[Any] = list(pf)
    else:
        total = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        with_face = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE face_detected = 1"
        ).fetchone()[0]
        with_location = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE location != ''"
        ).fetchone()[0]
        with_scene = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE scene != ''"
        ).fetchone()[0]
        with_emotion = conn.execute(
            """
            SELECT COUNT(DISTINCT photo_id) FROM photo_terms
            WHERE term_type = 'emotion'
            """
        ).fetchone()[0]
        emotion_rows = conn.execute(
            """
            SELECT term, COUNT(DISTINCT photo_id) AS cnt
            FROM photo_terms
            WHERE term_type = 'emotion'
            GROUP BY term
            ORDER BY cnt DESC
            LIMIT 8
            """
        ).fetchall()
        scope = ""
        exists_clause = "1=1"
        query_params = []

    field_coverage = _build_field_coverage(
        conn, total=total, exists=exists_clause, params=query_params
    )
    distributions = _build_distributions(
        conn, exists=exists_clause, params=query_params
    )

    def _pct(n: int) -> float:
        return round(100.0 * n / total, 1) if total else 0.0

    return {
        "found": True,
        "person": scope,
        "total_photos": total,
        "with_face": with_face,
        "with_location": with_location,
        "with_scene": with_scene,
        "with_emotion": with_emotion,
        "emotion_breakdown": [
            {"term": row["term"], "count": row["cnt"]} for row in emotion_rows
        ],
        "field_coverage": field_coverage,
        "distributions": distributions,
        "percent": {
            "face": _pct(with_face),
            "location": _pct(with_location),
            "scene": _pct(with_scene),
            "emotion": _pct(with_emotion),
        },
    }


def get_person_age_place_rank(
    conn: sqlite3.Connection,
    *,
    person: str,
    age_years: int,
    limit: int = 10,
) -> dict[str, Any]:
    """某人在特定年龄（岁）时，按地点聚合照片数与天数。"""
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person, "age_years": age_years}

    _, member = found
    age_prefix = f"{age_years}岁"
    pf = [member.name, member.person_id, f"{age_prefix}%"]

    rows = conn.execute(
        """
        SELECT
            p.location AS location,
            COUNT(*) AS photo_count,
            COUNT(DISTINCT substr(p.timestamp, 1, 10)) AS day_count
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND pp.age_label LIKE ?
          AND p.location != ''
        GROUP BY p.location
        ORDER BY photo_count DESC, day_count DESC
        LIMIT ?
        """,
        (*pf, limit),
    ).fetchall()

    matched_photos = conn.execute(
        """
        SELECT COUNT(*) FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND pp.age_label LIKE ?
          AND p.location != ''
        """,
        pf,
    ).fetchone()[0]

    age_photos = conn.execute(
        """
        SELECT COUNT(*) FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND pp.age_label LIKE ?
        """,
        pf,
    ).fetchone()[0]

    return {
        "found": True,
        "person": member.name,
        "age_years": age_years,
        "age_photos": age_photos,
        "matched_photos": matched_photos,
        "places": [
            {
                "location": row["location"],
                "photo_count": row["photo_count"],
                "day_count": row["day_count"],
            }
            for row in rows
        ],
    }


def get_person_home_timeline(
    conn: sqlite3.Connection,
    *,
    person: str,
) -> dict[str, Any]:
    """某人住过的地方：按 home 事件地点聚合日历跨度（迁居时间线）。"""
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person}

    _, member = found
    name = member.name
    rows = conn.execute(
        """
        SELECT
            e.location AS location,
            MIN(e.day) AS first_day,
            MAX(e.day) AS last_day,
            COUNT(*) AS event_count,
            SUM(e.photo_count) AS photo_count
        FROM events e
        WHERE e.is_home = 1
          AND e.location != ''
          AND e.people_json LIKE ?
        GROUP BY e.location
        ORDER BY first_day ASC
        """,
        (f"%{name}%",),
    ).fetchall()

    homes: list[dict[str, Any]] = []
    for row in rows:
        first_day = str(row["first_day"] or "")
        last_day = str(row["last_day"] or "")
        d0 = _parse_day(first_day)
        d1 = _parse_day(last_day)
        span_days = (d1 - d0).days + 1 if d0 and d1 else 0
        age_start = None
        age_end = None
        if member.birth_date and d0:
            age_start = dict(
                compute_age_at_photo(member.birth_date, d0, role=member.role)
            )
        if member.birth_date and d1:
            age_end = dict(
                compute_age_at_photo(member.birth_date, d1, role=member.role)
            )
        homes.append(
            {
                "location": row["location"],
                "first_day": first_day,
                "last_day": last_day,
                "span_days": span_days,
                "event_count": int(row["event_count"] or 0),
                "photo_count": int(row["photo_count"] or 0),
                "age_start": age_start,
                "age_end": age_end,
                "age_start_label": _short_age_label(age_start),
                "age_end_label": _short_age_label(age_end),
            }
        )

    longest = max(homes, key=lambda h: h["span_days"]) if homes else None
    return {
        "found": True,
        "person": name,
        "birth_date": member.birth_date.isoformat() if member.birth_date else "",
        "homes": homes,
        "longest": longest,
        "home_count": len(homes),
    }


def get_outings_by_period(
    conn: sqlite3.Connection,
    *,
    person: str = "",
    year: str = "",
    season: str = "",
    limit: int = 40,
) -> dict[str, Any]:
    """按年 / 季列出 outing 事件（不含家）。"""
    from hub.shared.events import count_events, list_events

    year = (year or "").strip()
    season = (season or "").strip()
    months = SEASON_MONTHS.get(season)
    day = year if year else ""
    events = list_events(
        conn,
        day=day,
        person=person,
        include_home=False,
        months=months,
        limit=limit,
    )
    total = count_events(
        conn,
        day=day,
        person=person,
        include_home=False,
        months=months,
    )
    period_bits = []
    if year:
        period_bits.append(f"{year}年")
    if season:
        period_bits.append(f"{season}季")
    return {
        "found": True,
        "person": person,
        "year": year,
        "season": season,
        "period_label": "".join(period_bits) or "全部时段",
        "events": events,
        "total": total,
        "returned": len(events),
    }


def get_person_place_rank(
    conn: sqlite3.Connection,
    *,
    person: str,
    limit: int = 10,
) -> dict[str, Any]:
    """某人全时期按地点聚合照片数与天数（常去哪里）。"""
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person}

    _, member = found
    pf = [member.name, member.person_id]

    rows = conn.execute(
        """
        SELECT
            p.location AS location,
            COUNT(*) AS photo_count,
            COUNT(DISTINCT substr(p.timestamp, 1, 10)) AS day_count
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND p.location != ''
        GROUP BY p.location
        ORDER BY photo_count DESC, day_count DESC
        LIMIT ?
        """,
        (*pf, limit),
    ).fetchall()

    matched_photos = conn.execute(
        """
        SELECT COUNT(*) FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND p.location != ''
        """,
        pf,
    ).fetchone()[0]

    total_photos = conn.execute(
        """
        SELECT COUNT(*) FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE pp.person_name = ? OR pp.person_id = ?
        """,
        pf,
    ).fetchone()[0]

    total_places = conn.execute(
        """
        SELECT COUNT(DISTINCT p.location) FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND p.location != ''
        """,
        pf,
    ).fetchone()[0]

    return {
        "found": True,
        "person": member.name,
        "total_photos": total_photos,
        "matched_photos": matched_photos,
        "total_places": total_places,
        "places": [
            {
                "location": row["location"],
                "photo_count": row["photo_count"],
                "day_count": row["day_count"],
            }
            for row in rows
        ],
    }


def get_person_emotion_place_rank(
    conn: sqlite3.Connection,
    *,
    person: str,
    term: str,
    term_type: str = "emotion",
    limit: int = 10,
) -> dict[str, Any]:
    """某人带某表情标注时，按地点聚合照片数与天数。"""
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person, "term": term, "term_type": term_type}

    _, member = found
    needle = term.strip()
    if not needle:
        return {"found": False, "person": person, "term": term, "term_type": term_type}

    pf = [member.name, member.person_id]
    pattern = f"%{needle}%"

    rows = conn.execute(
        """
        SELECT
            p.location AS location,
            COUNT(DISTINCT p.photo_id) AS photo_count,
            COUNT(DISTINCT substr(p.timestamp, 1, 10)) AS day_count
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        JOIN photo_terms t ON t.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND t.term_type = ?
          AND t.term LIKE ?
          AND p.location != ''
        GROUP BY p.location
        ORDER BY photo_count DESC, day_count DESC
        LIMIT ?
        """,
        (*pf, term_type, pattern, limit),
    ).fetchall()

    matched_photos = conn.execute(
        """
        SELECT COUNT(DISTINCT p.photo_id)
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        JOIN photo_terms t ON t.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND t.term_type = ?
          AND t.term LIKE ?
          AND p.location != ''
        """,
        (*pf, term_type, pattern),
    ).fetchone()[0]

    term_photos = conn.execute(
        """
        SELECT COUNT(DISTINCT p.photo_id)
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        JOIN photo_terms t ON t.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND t.term_type = ?
          AND t.term LIKE ?
        """,
        (*pf, term_type, pattern),
    ).fetchone()[0]

    matched_terms = conn.execute(
        """
        SELECT t.term, COUNT(DISTINCT p.photo_id) AS cnt
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        JOIN photo_terms t ON t.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND t.term_type = ?
          AND t.term LIKE ?
        GROUP BY t.term
        ORDER BY cnt DESC
        """,
        (*pf, term_type, pattern),
    ).fetchall()

    return {
        "found": True,
        "person": member.name,
        "term": needle,
        "term_type": term_type,
        "term_photos": term_photos,
        "matched_photos": matched_photos,
        "matched_terms": [{"term": row["term"], "count": row["cnt"]} for row in matched_terms],
        "places": [
            {
                "location": row["location"],
                "photo_count": row["photo_count"],
                "day_count": row["day_count"],
            }
            for row in rows
        ],
    }


def _admin_place_label(province: str, city: str) -> str:
    """结构化地址 → 展示名（直辖市无 city 时用 province）。"""
    province = (province or "").strip()
    city = (city or "").strip()
    if city:
        if province and province not in city:
            return f"{city}（{province}）"
        return city
    return province


def get_person_cities_visited(
    conn: sqlite3.Connection,
    *,
    person: str,
    limit: int = 20,
    group_by: str = "city",
) -> dict[str, Any]:
    """某人去过的城市/省份列表（按 location_admin 聚合）。"""
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person}

    _, member = found
    pf = [member.name, member.person_id]

    if group_by == "province":
        rows = conn.execute(
            """
            SELECT
                p.location_province AS province,
                '' AS city,
                COUNT(*) AS photo_count,
                COUNT(DISTINCT substr(p.timestamp, 1, 10)) AS day_count
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND p.location_province != ''
            GROUP BY p.location_province
            ORDER BY photo_count DESC, day_count DESC
            LIMIT ?
            """,
            (*pf, limit),
        ).fetchall()
        total_places = conn.execute(
            """
            SELECT COUNT(DISTINCT p.location_province)
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND p.location_province != ''
            """,
            pf,
        ).fetchone()[0]
    else:
        rows = conn.execute(
            """
            SELECT
                p.location_province AS province,
                p.location_city AS city,
                COUNT(*) AS photo_count,
                COUNT(DISTINCT substr(p.timestamp, 1, 10)) AS day_count
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND (p.location_city != '' OR p.location_province != '')
            GROUP BY p.location_province, p.location_city
            ORDER BY photo_count DESC, day_count DESC
            LIMIT ?
            """,
            (*pf, limit),
        ).fetchall()
        total_places = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT 1
                FROM photos p
                JOIN photo_people pp ON pp.photo_id = p.photo_id
                WHERE (pp.person_name = ? OR pp.person_id = ?)
                  AND (p.location_city != '' OR p.location_province != '')
                GROUP BY p.location_province, p.location_city
            )
            """,
            pf,
        ).fetchone()[0]

    matched_photos = conn.execute(
        """
        SELECT COUNT(*) FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND (p.location_city != '' OR p.location_province != '')
        """,
        pf,
    ).fetchone()[0]

    total_photos = conn.execute(
        """
        SELECT COUNT(*) FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE pp.person_name = ? OR pp.person_id = ?
        """,
        pf,
    ).fetchone()[0]

    places = [
        {
            "label": _admin_place_label(row["province"], row["city"]),
            "province": row["province"] or "",
            "city": row["city"] or "",
            "photo_count": row["photo_count"],
            "day_count": row["day_count"],
        }
        for row in rows
    ]

    return {
        "found": True,
        "person": member.name,
        "group_by": group_by,
        "total_places": total_places,
        "total_photos": total_photos,
        "matched_photos": matched_photos,
        "places": places,
    }


def get_person_peak_day(
    conn: sqlite3.Connection,
    *,
    person: str,
    limit: int = 10,
) -> dict[str, Any]:
    """某人单日照片最多的一天（及当天主要地点）。"""
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person}

    _, member = found
    pf = [member.name, member.person_id]

    daily_rows = conn.execute(
        """
        SELECT
            substr(p.timestamp, 1, 10) AS day,
            COUNT(*) AS photo_count
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND p.timestamp != ''
        GROUP BY substr(p.timestamp, 1, 10)
        ORDER BY photo_count DESC, day DESC
        LIMIT ?
        """,
        (*pf, limit),
    ).fetchall()

    if not daily_rows:
        return {"found": True, "person": member.name, "peak_days": [], "max_photo_count": 0}

    max_count = int(daily_rows[0]["photo_count"])
    peak_days: list[dict[str, Any]] = []
    for row in daily_rows:
        if int(row["photo_count"]) < max_count:
            break
        day = row["day"]
        loc_rows = conn.execute(
            """
            SELECT p.location, COUNT(*) AS cnt
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND substr(p.timestamp, 1, 10) = ?
              AND p.location != ''
            GROUP BY p.location
            ORDER BY cnt DESC
            LIMIT 5
            """,
            (*pf, day),
        ).fetchall()
        locations = [{"location": r["location"], "count": r["cnt"]} for r in loc_rows]
        age_row = conn.execute(
            """
            SELECT pp.age_label, COUNT(*) AS cnt
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND substr(p.timestamp, 1, 10) = ?
              AND pp.age_label != ''
            GROUP BY pp.age_label
            ORDER BY cnt DESC
            LIMIT 1
            """,
            (*pf, day),
        ).fetchone()
        peak_days.append(
            {
                "day": day,
                "photo_count": max_count,
                "locations": locations,
                "primary_location": locations[0]["location"] if locations else "",
                "age_label": age_row["age_label"] if age_row else "",
            }
        )

    return {
        "found": True,
        "person": member.name,
        "max_photo_count": max_count,
        "peak_days": peak_days,
    }


def get_person_at_place(
    conn: sqlite3.Connection,
    *,
    person: str,
    place_query: str,
    limit: int = 10,
) -> dict[str, Any]:
    """某人在某地（location 模糊匹配）的到访次数、首末时间。"""
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person, "place_query": place_query}

    _, member = found
    pf = [member.name, member.person_id]
    needle = place_query.strip()
    pattern = f"%{needle}%"
    place_filter = _place_match_sql("p")
    place_params = _place_match_params(pattern)

    agg = conn.execute(
        f"""
        SELECT
            COUNT(*) AS photo_count,
            COUNT(DISTINCT substr(p.timestamp, 1, 10)) AS day_count
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND {place_filter}
          AND p.timestamp != ''
        """,
        (*pf, *place_params),
    ).fetchone()

    locations = conn.execute(
        f"""
        SELECT DISTINCT p.location
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND {place_filter}
          AND p.location != ''
        ORDER BY p.location
        LIMIT 10
        """,
        (*pf, *place_params),
    ).fetchall()

    regions = conn.execute(
        f"""
        SELECT DISTINCT
            p.location_province AS province,
            p.location_city AS city
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND {place_filter}
          AND (p.location_province != '' OR p.location_city != '')
        ORDER BY p.location_province, p.location_city
        LIMIT 10
        """,
        (*pf, *place_params),
    ).fetchall()

    def _visit_row(order: str) -> dict[str, Any] | None:
        row = conn.execute(
            f"""
            SELECT p.photo_id, p.timestamp, p.location, p.location_city,
                   p.location_province, p.source_path, pp.age_label
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND {place_filter}
              AND p.timestamp != ''
            ORDER BY p.timestamp {order}
            LIMIT 1
            """,
            (*pf, *place_params),
        ).fetchone()
        return dict(row) if row else None

    visit_days = conn.execute(
        f"""
        SELECT
            substr(p.timestamp, 1, 10) AS day,
            COUNT(*) AS photo_count,
            MIN(p.timestamp) AS first_ts,
            MIN(p.location) AS location,
            MIN(p.location_city) AS city
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND {place_filter}
          AND p.timestamp != ''
        GROUP BY substr(p.timestamp, 1, 10)
        ORDER BY day ASC
        """,
        (*pf, *place_params),
    ).fetchall()

    enriched_visits: list[dict[str, Any]] = []
    for row in visit_days:
        age_row = conn.execute(
            f"""
            SELECT pp.age_label, COUNT(*) AS cnt
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND {place_filter}
              AND substr(p.timestamp, 1, 10) = ?
              AND pp.age_label != ''
            GROUP BY pp.age_label
            ORDER BY cnt DESC
            LIMIT 1
            """,
            (*pf, *place_params, row["day"]),
        ).fetchone()
        loc = row["location"] or row["city"] or ""
        enriched_visits.append(
            {
                "day": row["day"],
                "photo_count": row["photo_count"],
                "first_timestamp": row["first_ts"],
                "location": loc,
                "age_label": age_row["age_label"] if age_row else "",
            }
        )

    region_labels: list[str] = []
    for r in regions:
        prov = r["province"] or ""
        city = r["city"] or ""
        if prov and city and prov not in city:
            region_labels.append(f"{prov}{city}")
        elif city:
            region_labels.append(city)
        elif prov:
            region_labels.append(prov)

    return {
        "found": True,
        "person": member.name,
        "place_query": place_query,
        "matched_locations": [r["location"] for r in locations],
        "matched_regions": region_labels,
        "photo_count": int(agg["photo_count"] or 0),
        "day_count": int(agg["day_count"] or 0),
        "first_visit": _visit_row("ASC"),
        "last_visit": _visit_row("DESC"),
        "visit_days": enriched_visits,
    }


def get_term_photo_stats(
    conn: sqlite3.Connection,
    *,
    term: str,
    term_type: str = "emotion",
    person: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """按 photo_terms 统计并抽样（如表情「哭」）。"""
    needle = term.strip()
    if not needle:
        return {"found": False, "term": term, "term_type": term_type}

    pattern = f"%{needle}%"
    if person:
        found = _find_member(person)
        if found is None:
            return {"found": False, "person": person, "term": needle, "term_type": term_type}
        _, member = found
        pf = [member.name, member.person_id]
        exists = _person_photo_exists_sql("p")
        count = conn.execute(
            f"""
            SELECT COUNT(DISTINCT p.photo_id) FROM photos p
            JOIN photo_terms t ON t.photo_id = p.photo_id
            WHERE {exists}
              AND t.term_type = ?
              AND t.term LIKE ?
            """,
            (*pf, term_type, pattern),
        ).fetchone()[0]
        matched_terms = conn.execute(
            f"""
            SELECT t.term, COUNT(DISTINCT p.photo_id) AS cnt
            FROM photos p
            JOIN photo_terms t ON t.photo_id = p.photo_id
            WHERE {exists} AND t.term_type = ? AND t.term LIKE ?
            GROUP BY t.term
            ORDER BY cnt DESC
            """,
            (*pf, term_type, pattern),
        ).fetchall()
        scope = member.name
        sample_person = member.name
    else:
        count = conn.execute(
            """
            SELECT COUNT(DISTINCT photo_id) FROM photo_terms
            WHERE term_type = ? AND term LIKE ?
            """,
            (term_type, pattern),
        ).fetchone()[0]
        matched_terms = conn.execute(
            """
            SELECT term, COUNT(DISTINCT photo_id) AS cnt
            FROM photo_terms
            WHERE term_type = ? AND term LIKE ?
            GROUP BY term
            ORDER BY cnt DESC
            """,
            (term_type, pattern),
        ).fetchall()
        scope = ""
        sample_person = ""

    photos = search_photos(
        conn,
        person=sample_person,
        query=needle,
        limit=limit,
    )
    return {
        "found": True,
        "person": scope,
        "term": needle,
        "term_type": term_type,
        "photo_count": count,
        "matched_terms": [
            {"term": row["term"], "count": row["cnt"]} for row in matched_terms
        ],
        "sample_photos": photos,
    }


def get_term_first_photo(
    conn: sqlite3.Connection,
    *,
    term: str,
    term_type: str = "emotion",
    person: str = "",
) -> dict[str, Any]:
    """某表情/词条最早出现的一张照片（按 timestamp 升序）。"""
    needle = term.strip()
    if not needle:
        return {"found": False, "term": term, "term_type": term_type}

    pattern = f"%{needle}%"
    base_select = """
        SELECT
            p.photo_id,
            p.timestamp,
            p.scene,
            p.location,
            pp.age_label,
            GROUP_CONCAT(DISTINCT t.term) AS matched_terms,
            GROUP_CONCAT(DISTINCT pp.person_name) AS people
        FROM photos p
        JOIN photo_terms t ON t.photo_id = p.photo_id
        LEFT JOIN photo_people pp ON pp.photo_id = p.photo_id
    """

    if person:
        found = _find_member(person)
        if found is None:
            return {"found": False, "person": person, "term": needle, "term_type": term_type}
        _, member = found
        row = conn.execute(
            f"""
            {base_select}
            JOIN photo_people ppf ON ppf.photo_id = p.photo_id
            WHERE (ppf.person_name = ? OR ppf.person_id = ?)
              AND t.term_type = ?
              AND t.term LIKE ?
              AND p.timestamp != ''
            GROUP BY p.photo_id
            ORDER BY p.timestamp ASC
            LIMIT 1
            """,
            (member.name, member.person_id, term_type, pattern),
        ).fetchone()
        scope = member.name
    else:
        row = conn.execute(
            f"""
            {base_select}
            WHERE t.term_type = ?
              AND t.term LIKE ?
              AND p.timestamp != ''
            GROUP BY p.photo_id
            ORDER BY p.timestamp ASC
            LIMIT 1
            """,
            (term_type, pattern),
        ).fetchone()
        scope = ""

    if row is None:
        return {
            "found": True,
            "person": scope,
            "term": needle,
            "term_type": term_type,
            "photo": None,
        }

    return {
        "found": True,
        "person": scope,
        "term": needle,
        "term_type": term_type,
        "photo": dict(row),
    }


def gather_facts(
    conn: sqlite3.Connection,
    intent: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    person = params.get("person", "")
    limit = int(params.get("limit", 10))

    if intent == "recent_photos":
        photos = get_recent_photos(conn, person=person, limit=limit)
        return {"intent": intent, "person": person, "photos": photos}

    if intent == "group_photos":
        persons = params.get("persons") or []
        group_limit = int(params.get("limit", 20))
        result = get_group_photos(conn, persons=persons, limit=group_limit)
        return {"intent": intent, **result}

    if intent == "person_age":
        age_info = get_person_age(person)
        latest = get_person_age_from_latest_photo(conn, person) if age_info.get("found") else None
        return {"intent": intent, "person": person, "age_info": age_info, "latest_photo_age": latest}

    if intent == "person_recent_places":
        places = get_person_recent_places(conn, person=person, limit=limit)
        return {"intent": intent, "person": person, "places": places}

    if intent == "library_stats":
        stats = get_library_stats(conn, person=person)
        return {
            "intent": intent,
            "person": person,
            "focus": params.get("focus", "all"),
            "stats": stats,
        }

    if intent == "person_age_place_rank":
        age_years = int(params.get("age_years", 0))
        rank_limit = int(params.get("limit", 10))
        rank = get_person_age_place_rank(
            conn,
            person=person,
            age_years=age_years,
            limit=rank_limit,
        )
        return {
            "intent": intent,
            "person": person,
            "age_years": age_years,
            **rank,
        }

    if intent == "person_place_rank":
        rank_limit = int(params.get("limit", 10))
        rank = get_person_place_rank(conn, person=person, limit=rank_limit)
        return {"intent": intent, "person": person, **rank}

    if intent == "person_places_visited":
        visit_limit = int(params.get("limit", 20))
        rank = get_person_place_rank(conn, person=person, limit=visit_limit)
        return {"intent": intent, "person": person, **rank}

    if intent == "person_emotion_place_rank":
        emo_limit = int(params.get("limit", 10))
        term = str(params.get("term", ""))
        term_type = str(params.get("term_type", "emotion"))
        rank = get_person_emotion_place_rank(
            conn,
            person=person,
            term=term,
            term_type=term_type,
            limit=emo_limit,
        )
        return {
            "intent": intent,
            "person": person,
            "term": term,
            "term_type": term_type,
            **rank,
        }

    if intent == "person_cities_visited":
        cities_limit = int(params.get("limit", 20))
        group_by = str(params.get("group_by", "city"))
        result = get_person_cities_visited(
            conn,
            person=person,
            limit=cities_limit,
            group_by=group_by,
        )
        return {"intent": intent, "person": person, **result}

    if intent == "person_peak_day":
        peak_limit = int(params.get("limit", 10))
        result = get_person_peak_day(conn, person=person, limit=peak_limit)
        return {"intent": intent, "person": person, **result}

    if intent == "person_at_place":
        place = str(params.get("place", ""))
        visit_limit = int(params.get("limit", 10))
        result = get_person_at_place(
            conn,
            person=person,
            place_query=place,
            limit=visit_limit,
        )
        return {
            "intent": intent,
            "person": person,
            "place": place,
            "focus": params.get("focus", ""),
            **result,
        }

    if intent == "term_lookup":
        term = str(params.get("term", ""))
        term_type = str(params.get("term_type", "emotion"))
        stats = get_term_photo_stats(
            conn,
            term=term,
            term_type=term_type,
            person=person,
            limit=limit,
        )
        return {
            "intent": intent,
            "person": person,
            "term": term,
            "term_type": term_type,
            **stats,
        }

    if intent == "term_first":
        term = str(params.get("term", ""))
        term_type = str(params.get("term_type", "emotion"))
        result = get_term_first_photo(
            conn,
            term=term,
            term_type=term_type,
            person=person,
        )
        return {
            "intent": intent,
            "person": person,
            "term": term,
            "term_type": term_type,
            **result,
        }

    if intent == "recent_outings":
        from hub.shared.events import list_events

        events = list_events(
            conn,
            person=person,
            include_home=False,
            limit=limit,
        )
        return {"intent": intent, "person": person, "events": events}

    if intent == "outings_by_period":
        result = get_outings_by_period(
            conn,
            person=person,
            year=str(params.get("year", "")),
            season=str(params.get("season", "")),
            limit=limit,
        )
        return {"intent": intent, **result}

    if intent == "person_home_timeline":
        result = get_person_home_timeline(conn, person=person)
        return {"intent": intent, **result}

    if intent == "outings_at_place":
        from hub.shared.events import list_events

        place = str(params.get("place", ""))
        events = list_events(
            conn,
            person=person,
            location=place,
            include_home=False,
            limit=limit,
        )
        return {
            "intent": intent,
            "person": person,
            "place": place,
            "events": events,
        }

    if intent == "story_lookup":
        from hub.shared.events import get_story, search_stories

        query = str(params.get("query", "")).strip()
        stories = search_stories(conn, query, limit=limit)
        # 附带 links 详情
        detailed = []
        for s in stories:
            full = get_story(conn, s["story_id"])
            if full:
                detailed.append(full)
        return {
            "intent": intent,
            "person": person,
            "query": query,
            "stories": detailed,
        }

    return {"intent": "unknown", "question_params": params}
