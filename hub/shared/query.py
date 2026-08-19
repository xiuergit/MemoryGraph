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

# 口语地名 → 索引里省/市/POI 匹配词（「老家」勿搜字面，免命中「老家（眉山）」）
_PLACE_ALIASES: dict[str, tuple[str, ...]] = {
    "老家": ("忻州", "忻州市"),
    "山西老家": ("忻州", "忻州市"),
    "忻州老家": ("忻州", "忻州市"),
    "山西": ("山西", "山西省"),
    "山西省": ("山西", "山西省"),
    "忻州": ("忻州", "忻州市"),
    "忻州市": ("忻州", "忻州市"),
}


def expand_place_aliases(place: str) -> list[str]:
    """地名别名展开；无配置时返回原词。"""
    q = (place or "").strip()
    if not q:
        return []
    aliases = _PLACE_ALIASES.get(q)
    if not aliases:
        # 去后缀再试：山西省→已在表；「去山西玩」清洗后仍可能带「省」
        for suffix in ("省", "市", "区", "县"):
            if q.endswith(suffix) and len(q) > len(suffix):
                aliases = _PLACE_ALIASES.get(q[: -len(suffix)])
                if aliases:
                    break
    if not aliases:
        return [q]
    seen: set[str] = set()
    out: list[str] = []
    for term in aliases:
        if term not in seen:
            seen.add(term)
            out.append(term)
    return out


def is_place_alias_query(query: str) -> bool:
    q = (query or "").strip()
    if q in _PLACE_ALIASES:
        return True
    for suffix in ("省", "市"):
        if q.endswith(suffix) and q[: -len(suffix)] in _PLACE_ALIASES:
            return True
    return False


# 证据图默认取全量时的安全上限（Web/iOS 分页展示）
PHOTO_FETCH_CAP = 5000

# 口语关键词 → 索引里常见 objects/actions/tags
# 「骑车」类只扩动作，不含裸「自行车」（否则背景里有车也会中）
_KEYWORD_ALIASES: dict[str, tuple[str, ...]] = {
    "骑车": (
        "骑车",
        "骑自行车",
        "骑平衡车",
        "骑滑板车",
        "骑三轮车",
        "骑儿童自行车",
        "骑儿童平衡车",
        "骑儿童三轮车",
        "骑儿童滑板车",
        "玩滑板车",
        "骑行滑板车",
        "骑行平衡车",
        "骑玩具车",
        "骑童车",
        "骑儿童车",
        "骑学步车",
    ),
    "骑自行车": (
        "骑自行车",
        "骑车",
        "骑儿童自行车",
    ),
    "骑平衡车": (
        "骑平衡车",
        "骑儿童平衡车",
        "骑行平衡车",
        "手扶平衡车",
    ),
    "平衡车": (
        "骑平衡车",
        "骑儿童平衡车",
        "骑行平衡车",
        "手扶平衡车",
    ),
    "骑滑板车": (
        "骑滑板车",
        "玩滑板车",
        "骑儿童滑板车",
        "骑行滑板车",
        "站在滑板车上",
    ),
    "滑板车": (
        "骑滑板车",
        "玩滑板车",
        "骑儿童滑板车",
        "骑行滑板车",
        "站在滑板车上",
    ),
    "三轮车": (
        "骑三轮车",
        "骑儿童三轮车",
        "儿童骑三轮车",
    ),
    # 物体检索：画面里有自行车即可（不问是否在骑）
    "自行车": ("自行车", "儿童自行车", "红色儿童自行车", "蓝色自行车"),
    "轮滑": (
        "轮滑",
        "滑轮滑",
        "玩轮滑",
        "学习轮滑",
        "穿轮滑鞋",
        "穿着轮滑鞋",
        "穿戴轮滑鞋",
        "轮滑鞋",
        "滑轮鞋",
        "溜冰",
        "溜冰场",
    ),
    "溜冰": (
        "溜冰",
        "轮滑",
        "滑轮滑",
        "玩轮滑",
        "溜冰场",
        "室内溜冰场",
    ),
    # 赛事名：索引多为英文 SPARTAN / Spartan Kids
    "斯巴达": (
        "斯巴达",
        "SPARTAN",
        "Spartan",
        "spartan",
        "SPARTAN KIDS",
        "Spartan Kids",
        "儿童障碍赛",
    ),
    "spartan": (
        "SPARTAN",
        "Spartan",
        "spartan",
        "SPARTAN KIDS",
        "Spartan Kids",
        "斯巴达",
        "儿童障碍赛",
    ),
    # 活动短句（面面坐船 / 爬山 / 玩水…）
    "坐船": (
        "坐船",
        "乘船",
        "乘坐游船",
        "乘坐小船",
        "坐在船上",
        "坐在小船上",
        "划船",
        "坐船游览",
        "乘坐船只",
        "乘坐观光船",
    ),
    "爬树": ("爬树", "攀爬树木"),
    "爬山": ("爬山", "登山", "攀登"),
    "登山": ("登山", "爬山", "攀登"),
    "游泳": ("游泳", "使用游泳圈漂浮", "使用游泳圈"),
    "玩水": ("玩水", "戏水", "涉水"),
    "戏水": ("戏水", "玩水", "涉水"),
    "攀岩": ("攀岩", "攀爬岩石", "女孩攀爬岩石", "攀爬黄色攀岩墙", "室内攀岩"),
    "跑": ("跑", "跑步", "奔跑", "跑动", "小孩跑步", "儿童跑动", "小女孩跑动"),
    "跑步": ("跑步", "跑", "奔跑", "跑动", "小孩跑步"),
    "吃": (
        "吃",
        "吃东西",
        "吃饭",
        "进食",
        "吃食物",
        "吃西瓜",
        "吃水果",
        "吃零食",
        "吃面条",
        "吃冰淇淋",
        "吃冰激凌",
        "吃冰棍",
        "吃棉花糖",
        "吃棒棒糖",
        "吃苹果",
        "吃披萨",
    ),
    "吃饭": (
        "吃饭",
        "进食",
        "吃东西",
        "吃食物",
        "用勺子进食",
        "使用勺子进食",
        "坐着吃饭",
    ),
    # 成长里程碑：短词易误伤（坐→坐着、爬→攀爬、走→行人行走），收窄到发育相关动作
    "爬": (
        "爬行",
        "婴儿爬行",
        "儿童爬行",
        "正在爬行",
        "在围栏内爬行",
    ),
    "爬行": (
        "爬行",
        "婴儿爬行",
        "儿童爬行",
        "正在爬行",
        "在围栏内爬行",
    ),
    "走": (
        "走路",
        "正在走路",
        "手牵手走路",
        "牵着小孩走路",
        "推学步车",
        "扶学步车",
        "扶着学步车行走",
        "扶着学步车站立",
        "使用学步车",
        "抓握学步车",
        "握住学步车把手",
        "手握学步车把手",
        "扶着学步滑板车",
        "骑学步车",
    ),
    "走路": (
        "走路",
        "正在走路",
        "手牵手走路",
        "牵着小孩走路",
    ),
    "学步": (
        "推学步车",
        "扶学步车",
        "扶着学步车行走",
        "扶着学步车站立",
        "使用学步车",
        "抓握学步车",
        "骑学步车",
        "扶着学步滑板车",
    ),
    "抬头": (
        "抬头",
        "抬头看镜头",
        "抬头向上看",
        "抬头观看",
        "俯卧",
        "婴儿俯卧",
        "俯卧支撑身体",
    ),
    "翻身": ("翻身", "侧翻", "翻滚"),
    "坐": ("坐立", "端坐", "坐着玩耍"),
    "独坐": ("坐立", "端坐"),
    "刷牙": ("刷牙", "刷牙中", "正在刷牙"),
    "洗手": ("洗手", "双手扶住洗手池", "双手扶住洗手池边", "双手抓着洗手盆边缘"),
    "睡觉": ("睡觉", "闭眼睡觉", "入睡"),
}

# 仅「人在做」类走 actions 精确匹配；物体/场景词仍用通用标签检索
_ACTION_PRIORITY_KEYWORDS = frozenset({
    "骑车",
    "骑自行车",
    "骑平衡车",
    "平衡车",
    "骑滑板车",
    "滑板车",
    "三轮车",
    "坐船",
    "爬树",
    "爬山",
    "登山",
    "游泳",
    "玩水",
    "戏水",
    "跑",
    "跑步",
    "吃",
    "吃饭",
    "爬",
    "爬行",
    "走",
    "走路",
    "学步",
    "抬头",
    "翻身",
    "坐",
    "独坐",
    "刷牙",
    "洗手",
    "睡觉",
})

# 短动词：actions 上 LIKE 词干（补精确别名漏网，如「吃香蕉」）
_ACTION_LIKE_STEMS = frozenset({"吃", "跑", "跑步"})


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


def expand_keyword_aliases(query: str) -> list[str]:
    q = (query or "").strip()
    if not q:
        return []
    aliases = _KEYWORD_ALIASES.get(q)
    if not aliases:
        return [q]
    seen: set[str] = set()
    out: list[str] = []
    for term in aliases:
        if term not in seen:
            seen.add(term)
            out.append(term)
    return out


def search_photos_by_keywords(
    conn: sqlite3.Connection,
    *,
    person: str = "",
    query: str = "",
    limit: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """关键词检索；返回 (展示列表, 命中总数)。

    地名别名（山西/老家/忻州）走省市区字段；骑车类走 actions 精确词。
    """
    q = (query or "").strip()
    if not q:
        return [], 0

    if is_place_alias_query(q):
        return search_photos_by_place(conn, person=person, place=q, limit=limit)

    terms = expand_keyword_aliases(q)
    if not terms:
        return [], 0

    action_mode = q in _ACTION_PRIORITY_KEYWORDS or (
        q.startswith("骑") and "马" not in q and "雕塑" not in q
    )
    like_stem = q in _ACTION_LIKE_STEMS
    # 先尽量取全量再截断，避免「只有 10 张」的假总数
    fetch_cap = PHOTO_FETCH_CAP
    if action_mode:
        all_photos = _search_photos_by_action_terms(
            conn,
            person=person,
            terms=terms,
            limit=fetch_cap,
            like_stems=list(terms) if like_stem else None,
        )
    else:
        per_term = fetch_cap
        merged: dict[str, dict[str, Any]] = {}
        for term in terms:
            for photo in search_photos(conn, person=person, query=term, limit=per_term):
                pid = str(photo.get("photo_id") or "")
                if pid and pid not in merged:
                    merged[pid] = photo
        all_photos = sorted(
            merged.values(),
            key=lambda p: str(p.get("timestamp") or ""),
            reverse=True,
        )

    total = len(all_photos)
    # limit<=0：返回全部（fetch_cap 内）；勿写成 max(1, 0)=1
    if limit <= 0:
        return all_photos, total
    return all_photos[:limit], total


def search_photos_by_place(
    conn: sqlite3.Connection,
    *,
    person: str = "",
    place: str = "",
    limit: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """按地名（含省/市/区别名）检索照片。"""
    needles = expand_place_aliases(place)
    if not needles:
        return [], 0

    fetch_cap = PHOTO_FETCH_CAP if limit <= 0 else max(limit, 1)
    clauses = ["1=1"]
    params: list[Any] = []

    if person:
        tokens = person_search_tokens(person) or [person]
        token_clauses: list[str] = []
        for token in tokens:
            token_clauses.append("(pp.person_name LIKE ? OR pp.person_id LIKE ?)")
            pattern = f"%{token}%"
            params.extend([pattern, pattern])
        clauses.append(
            f"""
            EXISTS (
                SELECT 1 FROM photo_people pp
                WHERE pp.photo_id = p.photo_id
                  AND ({' OR '.join(token_clauses)})
            )
            """
        )

    clauses.append(_place_match_sql("p", n_terms=len(needles)))
    params.extend(_place_match_params(*needles))

    sql = f"""
        SELECT
            p.photo_id,
            p.timestamp,
            p.scene,
            p.location,
            p.location_coords,
            p.source_path,
            GROUP_CONCAT(DISTINCT pp.person_name) AS people
        FROM photos p
        LEFT JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE {' AND '.join(clauses)}
        GROUP BY p.photo_id
        ORDER BY p.timestamp DESC
        LIMIT ?
    """
    params.append(fetch_cap)
    rows = conn.execute(sql, params).fetchall()
    photos = [dict(row) for row in rows]
    return photos, len(photos)


def _search_photos_by_action_terms(
    conn: sqlite3.Connection,
    *,
    person: str,
    terms: list[str],
    limit: int,
    like_stems: list[str] | None = None,
) -> list[dict[str, Any]]:
    """只匹配 actions（默认精确词；可选词干 LIKE，如「吃%」）。"""
    from hub.shared.family import person_search_tokens

    clean_terms = [t for t in terms if t and t != "骑马"]
    stems = [s for s in (like_stems or []) if s and s != "骑马"]
    if not clean_terms and not stems:
        return []

    clauses = ["1=1"]
    params: list[Any] = []

    if person:
        tokens = person_search_tokens(person) or [person]
        token_clauses: list[str] = []
        for token in tokens:
            token_clauses.append("(pp.person_name LIKE ? OR pp.person_id LIKE ?)")
            pattern = f"%{token}%"
            params.extend([pattern, pattern])
        clauses.append(
            f"""
            EXISTS (
                SELECT 1 FROM photo_people pp
                WHERE pp.photo_id = p.photo_id
                  AND ({' OR '.join(token_clauses)})
            )
            """
        )

    action_parts: list[str] = []
    if clean_terms:
        placeholders = ",".join("?" for _ in clean_terms)
        action_parts.append(f"t.term IN ({placeholders})")
        params.extend(clean_terms)
    for stem in stems:
        # 「吃」用前缀，减少「手持」类误伤；「跑」用包含以覆盖「奔跑」
        if stem in {"吃"}:
            action_parts.append("t.term LIKE ?")
            params.append(f"{stem}%")
        else:
            action_parts.append("t.term LIKE ?")
            params.append(f"%{stem}%")
    clauses.append(
        f"""
        EXISTS (
            SELECT 1 FROM photo_terms t
            WHERE t.photo_id = p.photo_id
              AND t.term_type = 'actions'
              AND ({' OR '.join(action_parts)})
        )
        """
    )

    sql = f"""
        SELECT
            p.photo_id,
            p.timestamp,
            p.scene,
            p.location,
            p.location_coords,
            p.source_path,
            GROUP_CONCAT(DISTINCT pp.person_name) AS people
        FROM photos p
        LEFT JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE {' AND '.join(clauses)}
        GROUP BY p.photo_id
        ORDER BY p.timestamp DESC
        LIMIT ?
    """
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


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


def _count_person_photos(conn: sqlite3.Connection, *, person: str) -> int:
    """人物照片总数（与 search_photos(person=…) 同一套 token 匹配）。"""
    tokens = person_search_tokens(person) or [person]
    if not tokens:
        return 0
    token_clauses: list[str] = []
    params: list[Any] = []
    for token in tokens:
        token_clauses.append("(pp.person_name LIKE ? OR pp.person_id LIKE ?)")
        pattern = f"%{token}%"
        params.extend([pattern, pattern])
    sql = f"""
        SELECT COUNT(DISTINCT pp.photo_id) FROM photo_people pp
        WHERE {' OR '.join(token_clauses)}
    """
    return int(conn.execute(sql, params).fetchone()[0])


def get_group_photos(
    conn: sqlite3.Connection,
    *,
    persons: list[str],
    limit: int = 0,
) -> dict[str, Any]:
    """多人同框：照片里同时识别到所有指定成员。

    limit<=0：返回全部命中（PHOTO_FETCH_CAP 内）。
    """
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

    fetch_limit = limit if limit > 0 else PHOTO_FETCH_CAP
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
        [*params, fetch_limit],
    ).fetchall()

    photos = [dict(row) for row in rows]
    return {
        "found": True,
        "persons": [name for name, _ in resolved],
        "total_count": total_count,
        "photo_count": total_count,
        "pair_counts": pair_counts,
        "photos": photos,
        "shown": len(photos),
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


def _place_match_sql(alias: str = "p", *, n_terms: int = 1) -> str:
    """地点关键词：POI 名 + 省 / 市 / 区；支持多个别名 OR。"""
    one = f"""(
        {alias}.location LIKE ?
        OR {alias}.location_province LIKE ?
        OR {alias}.location_city LIKE ?
        OR {alias}.location_district LIKE ?
    )"""
    if n_terms <= 1:
        return one
    return "(" + " OR ".join([one] * n_terms) + ")"


def _place_match_params(*needles: str) -> list[str]:
    params: list[str] = []
    for needle in needles:
        pattern = f"%{needle}%"
        params.extend([pattern, pattern, pattern, pattern])
    return params


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
    # 无时间家事件 day=''；MIN('') 会盖住真实日期，须 NULLIF 掉
    rows = conn.execute(
        """
        SELECT
            e.location AS location,
            MIN(NULLIF(TRIM(e.day), '')) AS first_day,
            MAX(NULLIF(TRIM(e.day), '')) AS last_day,
            COUNT(*) AS event_count,
            SUM(e.photo_count) AS photo_count
        FROM events e
        WHERE e.is_home = 1
          AND e.location != ''
          AND e.people_json LIKE ?
        GROUP BY e.location
        ORDER BY (MIN(NULLIF(TRIM(e.day), '')) IS NULL),
                 MIN(NULLIF(TRIM(e.day), '')) ASC
        """,
        (f"%{name}%",),
    ).fetchall()

    homes: list[dict[str, Any]] = []
    for row in rows:
        first_day = str(row["first_day"] or "")
        last_day = str(row["last_day"] or "")
        d0 = _parse_day(first_day)
        d1 = _parse_day(last_day)
        if d0 and d1:
            span_days = (d1 - d0).days + 1
        elif d0 or d1:
            span_days = 1
        else:
            span_days = 0
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

    longest = None
    if homes:
        # 优先按日历跨度；全无跨度时退回事件数
        by_span = max(homes, key=lambda h: h["span_days"])
        if int(by_span["span_days"] or 0) > 0:
            longest = by_span
        else:
            longest = max(homes, key=lambda h: h["event_count"])
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


def get_companions_at_place(
    conn: sqlite3.Connection,
    *,
    person: str = "",
    place_query: str,
    limit: int = 0,
) -> dict[str, Any]:
    """某地同框人物：有 person 时统计与其同框；无人名时统计该地出现过的所有人。

    limit<=0：证据图全量（PHOTO_FETCH_CAP 内）。
    """
    needle = (place_query or "").strip()
    if not needle:
        return {"found": False, "place_query": place_query, "reason": "empty_place"}

    needles = expand_place_aliases(needle)
    place_filter = _place_match_sql("p", n_terms=len(needles))
    place_params = _place_match_params(*needles)

    anchor_name = ""
    anchor_id = ""
    if person:
        found = _find_member(person)
        if found is None:
            return {
                "found": False,
                "person": person,
                "place_query": place_query,
            }
        anchor_id, member = found
        anchor_name = member.name

    if anchor_id:
        companion_rows = conn.execute(
            f"""
            SELECT
                pp2.person_name AS name,
                pp2.person_id AS person_id,
                COUNT(DISTINCT p.photo_id) AS photo_count
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            JOIN photo_people pp2 ON pp2.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND {place_filter}
              AND pp2.person_name != ''
              AND pp2.person_id != ?
              AND pp2.person_name != ?
            GROUP BY pp2.person_id, pp2.person_name
            ORDER BY photo_count DESC, name ASC
            """,
            (anchor_name, anchor_id, *place_params, anchor_id, anchor_name),
        ).fetchall()
        photo_from = f"""
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            LEFT JOIN photo_people pp_all ON pp_all.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND {place_filter}
        """
        photo_params: list[Any] = [anchor_name, anchor_id, *place_params]
        count_sql = f"""
            SELECT COUNT(DISTINCT p.photo_id) FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND {place_filter}
        """
        count_params: list[Any] = [anchor_name, anchor_id, *place_params]
    else:
        companion_rows = conn.execute(
            f"""
            SELECT
                pp2.person_name AS name,
                pp2.person_id AS person_id,
                COUNT(DISTINCT p.photo_id) AS photo_count
            FROM photos p
            JOIN photo_people pp2 ON pp2.photo_id = p.photo_id
            WHERE {place_filter}
              AND pp2.person_name != ''
            GROUP BY pp2.person_id, pp2.person_name
            ORDER BY photo_count DESC, name ASC
            """,
            place_params,
        ).fetchall()
        photo_from = f"""
            FROM photos p
            LEFT JOIN photo_people pp_all ON pp_all.photo_id = p.photo_id
            WHERE {place_filter}
        """
        photo_params = [*place_params]
        count_sql = f"""
            SELECT COUNT(DISTINCT p.photo_id) FROM photos p
            WHERE {place_filter}
        """
        count_params = [*place_params]

    companions = [
        {
            "name": row["name"],
            "person_id": row["person_id"],
            "photo_count": int(row["photo_count"] or 0),
        }
        for row in companion_rows
        if not str(row["person_id"] or "").startswith("unk_")
    ]

    fetch_limit = limit if limit > 0 else PHOTO_FETCH_CAP
    photo_rows = conn.execute(
        f"""
        SELECT
            p.photo_id,
            p.timestamp,
            p.scene,
            p.location,
            p.location_coords,
            p.source_path,
            GROUP_CONCAT(DISTINCT pp_all.person_name) AS people
        {photo_from}
        GROUP BY p.photo_id
        ORDER BY p.timestamp DESC
        LIMIT ?
        """,
        [*photo_params, fetch_limit],
    ).fetchall()
    photos = [dict(row) for row in photo_rows]
    total = int(conn.execute(count_sql, count_params).fetchone()[0] or 0)

    return {
        "found": True,
        "person": anchor_name,
        "place_query": place_query,
        "companions": companions,
        "companion_count": len(companions),
        "photo_count": total,
        "photos": photos,
        "shown": len(photos),
    }


def get_person_companion_rank(
    conn: sqlite3.Connection,
    *,
    person: str,
    limit: int = 12,
    photo_limit: int = 0,
) -> dict[str, Any]:
    """某人全库同框人物排行（按合影张数）。

    photo_limit<=0：与第一名同框的证据图全量（PHOTO_FETCH_CAP 内）。
    """
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person}

    anchor_id, member = found
    anchor_name = member.name
    rank_limit = max(1, min(int(limit or 12), 50))

    companion_rows = conn.execute(
        """
        SELECT
            pp2.person_name AS name,
            pp2.person_id AS person_id,
            COUNT(DISTINCT p.photo_id) AS photo_count
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        JOIN photo_people pp2 ON pp2.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND pp2.person_name != ''
          AND pp2.person_id != ?
          AND pp2.person_name != ?
        GROUP BY pp2.person_id, pp2.person_name
        ORDER BY photo_count DESC, name ASC
        LIMIT ?
        """,
        (anchor_name, anchor_id, anchor_id, anchor_name, rank_limit),
    ).fetchall()

    companions = [
        {
            "name": row["name"],
            "person_id": row["person_id"],
            "photo_count": int(row["photo_count"] or 0),
        }
        for row in companion_rows
        if not str(row["person_id"] or "").startswith("unk_")
    ]

    # 含至少一名其他已识别成员的合影总数
    total_with = int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT p.photo_id)
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND EXISTS (
                SELECT 1 FROM photo_people pp2
                WHERE pp2.photo_id = p.photo_id
                  AND pp2.person_name != ''
                  AND pp2.person_id != ?
                  AND pp2.person_name != ?
                  AND pp2.person_id NOT LIKE 'unk_%'
              )
            """,
            (anchor_name, anchor_id, anchor_id, anchor_name),
        ).fetchone()[0]
        or 0
    )

    photos: list[dict[str, Any]] = []
    top_companion = companions[0]["name"] if companions else ""
    top_companion_id = companions[0]["person_id"] if companions else ""
    if top_companion:
        fetch_limit = photo_limit if photo_limit > 0 else PHOTO_FETCH_CAP
        photo_rows = conn.execute(
            """
            SELECT
                p.photo_id,
                p.timestamp,
                p.scene,
                p.location,
                p.location_coords,
                p.source_path,
                GROUP_CONCAT(DISTINCT pp_all.person_name) AS people
            FROM photos p
            JOIN photo_people pp ON pp.photo_id = p.photo_id
            JOIN photo_people pp2 ON pp2.photo_id = p.photo_id
            LEFT JOIN photo_people pp_all ON pp_all.photo_id = p.photo_id
            WHERE (pp.person_name = ? OR pp.person_id = ?)
              AND (pp2.person_name = ? OR pp2.person_id = ?)
            GROUP BY p.photo_id
            ORDER BY p.timestamp DESC
            LIMIT ?
            """,
            (
                anchor_name,
                anchor_id,
                top_companion,
                top_companion_id,
                fetch_limit,
            ),
        ).fetchall()
        photos = [dict(row) for row in photo_rows]

    return {
        "found": True,
        "person": anchor_name,
        "companions": companions,
        "companion_count": len(companions),
        "top_companion": top_companion,
        "photo_count": total_with,
        "photos": photos,
        "shown": len(photos),
    }


def get_person_at_place(
    conn: sqlite3.Connection,
    *,
    person: str,
    place_query: str,
    limit: int = 0,
) -> dict[str, Any]:
    """某人在某地（location 模糊匹配）的到访次数、首末时间与证据图。

    limit<=0：证据图返回全部命中（PHOTO_FETCH_CAP 内）。
    """
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person, "place_query": place_query}

    _, member = found
    pf = [member.name, member.person_id]
    needle = place_query.strip()
    needles = expand_place_aliases(needle)
    place_filter = _place_match_sql("p", n_terms=len(needles))
    place_params = _place_match_params(*needles)

    agg = conn.execute(
        f"""
        SELECT
            COUNT(DISTINCT p.photo_id) AS photo_count,
            COUNT(DISTINCT CASE
                WHEN p.timestamp != '' THEN substr(p.timestamp, 1, 10)
            END) AS day_count
        FROM photos p
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND {place_filter}
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

    # 证据图：默认全量（与问答其它意图一致）
    fetch_limit = limit if limit > 0 else PHOTO_FETCH_CAP
    photo_rows = conn.execute(
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
        JOIN photo_people pp ON pp.photo_id = p.photo_id
        LEFT JOIN photo_people pp_all ON pp_all.photo_id = p.photo_id
        WHERE (pp.person_name = ? OR pp.person_id = ?)
          AND {place_filter}
        GROUP BY p.photo_id
        ORDER BY p.timestamp DESC
        LIMIT ?
        """,
        (*pf, *place_params, fetch_limit),
    ).fetchall()
    photos = [dict(row) for row in photo_rows]

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
        "photos": photos,
        "shown": len(photos),
    }


def get_term_photo_stats(
    conn: sqlite3.Connection,
    *,
    term: str,
    term_type: str = "emotion",
    person: str = "",
    limit: int = 0,
) -> dict[str, Any]:
    """按 photo_terms 统计并返回匹配照片（如表情「哭」）。

    limit<=0：返回全部命中（供证据区分页）。
    """
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
        limit=limit if limit > 0 else 0,
        term_types=(term_type,),
        match_scene=False,
        match_location=False,
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
        "photos": photos,
        "shown": len(photos),
    }


# 画作匹配：偏「画本身」的标签/场景，避开墙面涂鸦、画板、教室背景装饰画等
_ARTWORK_MATCH_SQL = """
(
  (
    (
      p.scene LIKE '%手绘%'
      OR p.scene LIKE '%儿童画%'
      OR p.scene LIKE '%儿童绘画%'
      OR p.scene LIKE '%画作%'
      OR p.scene LIKE '%绘画作品%'
      OR p.scene LIKE '%一幅%画%'
      OR p.scene LIKE '%在画画%'
      OR p.scene LIKE '%正在画画%'
      OR p.scene LIKE '%画画%'
    )
    AND p.scene NOT LIKE '%绘本%'
    AND p.scene NOT LIKE '%壁画%'
    AND p.scene NOT LIKE '%装饰画%'
    AND p.scene NOT LIKE '%彩绘%'
    AND p.scene NOT LIKE '%墙面涂鸦%'
  )
  OR EXISTS (
    SELECT 1 FROM photo_terms t
    WHERE t.photo_id = p.photo_id
      AND t.term_type IN ('tags', 'actions', 'scene')
      AND (
        t.term IN ('儿童画', '儿童绘画', '画作', '手绘', '绘画', '画画', '涂鸦')
        OR t.term LIKE '儿童画%'
        OR t.term LIKE '%手绘%'
        OR t.term LIKE '%绘画作品%'
        OR t.term LIKE '%在画画%'
      )
      AND t.term NOT LIKE '%绘本%'
      AND t.term NOT LIKE '%壁画%'
      AND t.term NOT LIKE '%装饰%'
      AND t.term NOT LIKE '%彩绘%'
      AND t.term NOT LIKE '%画板%'
      AND t.term NOT LIKE '%画架%'
      AND t.term NOT LIKE '%墙面%'
  )
)
"""

# 作品集：进一步只要「作品特写」，不要过程照噪音
_ARTWORK_WORKS_SQL = """
(
  (
    p.scene LIKE '%手绘%'
    OR p.scene LIKE '%儿童画%'
    OR p.scene LIKE '%儿童绘画%'
    OR p.scene LIKE '%画作%'
    OR p.scene LIKE '%绘画作品%'
    OR p.scene LIKE '%一幅%'
    OR p.scene LIKE '%涂鸦画%'
  )
  OR EXISTS (
    SELECT 1 FROM photo_terms t
    WHERE t.photo_id = p.photo_id
      AND t.term_type IN ('tags', 'scene')
      AND (
        t.term IN ('儿童画', '儿童绘画', '画作', '手绘', '绘画作品')
        OR t.term LIKE '儿童画%'
        OR t.term LIKE '%手绘作品%'
        OR t.term LIKE '%绘画作品%'
      )
      AND t.term NOT LIKE '%画板%'
      AND t.term NOT LIKE '%墙面%'
  )
)
"""


def get_person_artwork(
    conn: sqlite3.Connection,
    *,
    person: str,
    limit: int = 0,
    works_only: bool = True,
) -> dict[str, Any]:
    """某人相关的画作集。

    不要求画作照片上必须有人物：只要同事件里出现过该成员，或该照片本身标了该成员。
    works_only=True 时偏作品特写，减少「正在画画」过程照。
    limit<=0 表示返回全部命中。
    """
    found = _find_member(person)
    if found is None:
        return {"found": False, "person": person, "works_only": works_only}

    _, member = found
    pf = [member.name, member.person_id, member.name, member.person_id]

    person_or_coevent = """
    (
      EXISTS (
        SELECT 1 FROM photo_people pp
        WHERE pp.photo_id = p.photo_id
          AND (pp.person_name = ? OR pp.person_id = ?)
      )
      OR EXISTS (
        SELECT 1 FROM event_photos ep
        JOIN event_photos ep2 ON ep2.event_id = ep.event_id
        JOIN photo_people pp2 ON pp2.photo_id = ep2.photo_id
        WHERE ep.photo_id = p.photo_id
          AND (pp2.person_name = ? OR pp2.person_id = ?)
      )
    )
    """

    where = f"{_ARTWORK_MATCH_SQL} AND {person_or_coevent}"
    if works_only:
        where = f"{where} AND {_ARTWORK_WORKS_SQL}"

    count = conn.execute(
        f"SELECT COUNT(DISTINCT p.photo_id) FROM photos p WHERE {where}",
        pf,
    ).fetchone()[0]

    limit_sql = ""
    select_params: list[Any] = [*pf[:2], *pf]
    if limit > 0:
        limit_sql = "LIMIT ?"
        select_params.append(limit)

    rows = conn.execute(
        f"""
        SELECT
            p.photo_id,
            p.timestamp,
            p.scene,
            p.location,
            p.source_path,
            p.face_detected,
            GROUP_CONCAT(DISTINCT pp.person_name) AS people,
            CASE
              WHEN EXISTS (
                SELECT 1 FROM photo_people pp0
                WHERE pp0.photo_id = p.photo_id
                  AND (pp0.person_name = ? OR pp0.person_id = ?)
              ) THEN 'person'
              ELSE 'event'
            END AS link_via
        FROM photos p
        LEFT JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE {where}
        GROUP BY p.photo_id
        ORDER BY
          CASE WHEN p.timestamp = '' OR p.timestamp IS NULL THEN 1 ELSE 0 END,
          p.timestamp DESC,
          p.photo_id DESC
        {limit_sql}
        """,
        select_params,
    ).fetchall()

    photos = [dict(row) for row in rows]
    via_event = sum(1 for p in photos if p.get("link_via") == "event")
    via_person = sum(1 for p in photos if p.get("link_via") == "person")

    return {
        "found": True,
        "person": member.name,
        "works_only": works_only,
        "photo_count": count,
        "via_event": via_event,
        "via_person": via_person,
        "photos": photos,
    }


def get_keyword_first_photo(
    conn: sqlite3.Connection,
    *,
    query: str,
    person: str = "",
    evidence_limit: int = 20,
) -> dict[str, Any]:
    """关键词最早出现的一张照片（按 timestamp 升序），并附带若干证据图。"""
    q = (query or "").strip()
    if not q:
        return {"found": False, "query": query}

    scope = ""
    birth_iso = ""
    member = None
    if person:
        found = _find_member(person)
        if found is None:
            return {"found": False, "person": person, "query": q}
        member = found[1]
        scope = member.name
        if member.birth_date:
            birth_iso = member.birth_date.isoformat()

    photos, total = search_photos_by_keywords(
        conn, person=person, query=q, limit=0
    )
    dated = [p for p in photos if str(p.get("timestamp") or "").strip()]
    if birth_iso:
        # 生日之后才算「第一次」（避免错标/更早百日宴混入）
        dated = [p for p in dated if str(p.get("timestamp") or "")[:10] >= birth_iso]
    if not dated:
        return {
            "found": True,
            "person": scope,
            "query": q,
            "photo": None,
            "photos": [],
            "photo_count": total,
        }

    oldest = min(dated, key=lambda p: str(p.get("timestamp") or ""))
    # 补 age_label（search 结果不一定带）
    if member is not None and not oldest.get("age_label"):
        row = conn.execute(
            """
            SELECT age_label FROM photo_people
            WHERE photo_id = ?
              AND (person_name = ? OR person_id = ?)
            LIMIT 1
            """,
            (oldest.get("photo_id"), member.name, member.person_id),
        ).fetchone()
        if row and row[0]:
            oldest = {**oldest, "age_label": row[0]}

    # 证据：最早一张置顶，其余按时间倒序截取
    rest = [
        p for p in sorted(dated, key=lambda p: str(p.get("timestamp") or ""), reverse=True)
        if p.get("photo_id") != oldest.get("photo_id")
    ]
    evidence = [oldest] + rest[: max(0, evidence_limit - 1)]
    return {
        "found": True,
        "person": scope,
        "query": q,
        "photo": oldest,
        "photos": evidence,
        "photo_count": len(dated),
        "shown": len(evidence),
        "matched_total": total,
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
        birth_clause = ""
        birth_params: list[Any] = []
        if member.birth_date:
            birth_clause = " AND p.timestamp >= ? "
            birth_params = [member.birth_date.isoformat()]
        row = conn.execute(
            f"""
            {base_select}
            JOIN photo_people ppf ON ppf.photo_id = p.photo_id
            WHERE (ppf.person_name = ? OR ppf.person_id = ?)
              AND t.term_type = ?
              AND t.term LIKE ?
              AND p.timestamp != ''
              {birth_clause}
            GROUP BY p.photo_id
            ORDER BY p.timestamp ASC
            LIMIT 1
            """,
            (member.name, member.person_id, term_type, pattern, *birth_params),
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
        list_all = bool(params.get("list_all")) or limit <= 0
        show_limit = limit if limit > 0 else PHOTO_FETCH_CAP
        photos = get_recent_photos(conn, person=person, limit=show_limit)
        # list_all 时尽量给真实总数（避免「只有 10 张」的假印象）
        if list_all and person:
            total = _count_person_photos(conn, person=person)
        else:
            total = len(photos)
        return {
            "intent": intent,
            "person": person,
            "photos": photos,
            "photo_count": total,
            "shown": len(photos),
            "list_all": list_all,
        }

    if intent == "keyword_search":
        query = str(params.get("query", "")).strip()
        # limit<=0：返回全部命中（fetch_cap 内）；界面分页
        show_limit = limit if limit > 0 else PHOTO_FETCH_CAP
        photos, total = search_photos_by_keywords(
            conn, person=person, query=query, limit=show_limit
        )
        return {
            "intent": intent,
            "person": person,
            "query": query,
            "photos": photos,
            "photo_count": total,
            "shown": len(photos),
        }

    if intent == "keyword_first":
        query = str(params.get("query", "")).strip()
        result = get_keyword_first_photo(conn, query=query, person=person)
        return {"intent": intent, "person": person, "query": query, **result}

    if intent == "unknown":
        return {"intent": "unknown", "question_params": params}

    if intent == "group_photos":
        persons = params.get("persons") or []
        group_limit = int(params.get("limit", 0))
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

    if intent == "companions_at_place":
        place = str(params.get("place", ""))
        photo_limit = int(params.get("limit", 0))
        result = get_companions_at_place(
            conn,
            person=person,
            place_query=place,
            limit=photo_limit,
        )
        return {
            "intent": intent,
            "person": person,
            "place": place,
            **result,
        }

    if intent == "person_companion_rank":
        rank_limit = int(params.get("limit", 12))
        photo_limit = int(params.get("photo_limit", 0))
        result = get_person_companion_rank(
            conn,
            person=person,
            limit=rank_limit,
            photo_limit=photo_limit,
        )
        return {"intent": intent, "person": person, **result}

    if intent == "person_at_place":
        place = str(params.get("place", ""))
        photo_limit = int(params.get("limit", 0))
        result = get_person_at_place(
            conn,
            person=person,
            place_query=place,
            limit=photo_limit,
        )
        return {
            "intent": intent,
            "person": person,
            "place": place,
            "focus": params.get("focus", ""),
            **result,
        }

    if intent == "person_artwork":
        art_limit = int(params.get("limit", 0))
        works_only = bool(params.get("works_only", True))
        result = get_person_artwork(
            conn,
            person=person,
            limit=art_limit,
            works_only=works_only,
        )
        return {"intent": intent, **result}

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
            "focus": params.get("focus", ""),
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
