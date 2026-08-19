"""Outing 事件聚合：同日同地簇 + overlay 重挂 + stories。"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import sqlite3

logger = logging.getLogger(__name__)

CLUSTER_RADIUS_M = 800
TIME_JOIN_SECONDS = 3 * 3600
MIN_PHOTOS_OUTING = 2
OVERLAY_REMATCH_JACCARD = 0.5

# 住过的家：只与同类家照片聚类，绝不和非家地点合并
_DEFAULT_HOME_MARKERS = (
    "馨越公寓",
    "同济城市融景雅苑",
    "泰翔嘉苑",
    "荣和怡景园",
)


def home_location_markers() -> tuple[str, ...]:
    raw = os.environ.get("EVENT_HOME_LOCATIONS", "").strip()
    if not raw:
        return _DEFAULT_HOME_MARKERS
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(parts) if parts else _DEFAULT_HOME_MARKERS


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_coords(text: str) -> tuple[float, float] | None:
    parts = text.split(",", maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None


def _parse_timestamp_seconds(timestamp: str) -> float | None:
    if not timestamp or not timestamp.strip():
        return None
    text = timestamp.strip()
    try:
        if "T" in text:
            return datetime.fromisoformat(text).timestamp()
        return datetime.strptime(text, "%Y-%m-%d").timestamp()
    except ValueError:
        return None


def _date_key(timestamp: str) -> str:
    if not timestamp:
        return ""
    return timestamp[:10] if len(timestamp) >= 10 else timestamp


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def _location_quality_score(name: str) -> int:
    text = name.strip()
    if not text:
        return -100
    score = min(len(text), 20)
    if text.endswith(("公园", "森林公园", "动物园", "植物园")):
        score += 12
    elif text.endswith(("园", "山", "湖", "馆", "寺", "塔")):
        score += 8
    if any(k in text for k in ("停车", "诊所", "工作站", "卫生间")):
        score -= 20
    return score


def _pick_cluster_location(locations: list[str], *, majority_first: bool = False) -> str:
    pool = [loc.strip() for loc in locations if loc.strip()]
    if not pool:
        return ""
    counts = Counter(pool)
    if majority_first:
        ranked = sorted(
            counts.items(),
            key=lambda item: (item[1], _location_quality_score(item[0]), len(item[0])),
            reverse=True,
        )
    else:
        ranked = sorted(
            counts.items(),
            key=lambda item: (_location_quality_score(item[0]), item[1], len(item[0])),
            reverse=True,
        )
    return ranked[0][0]


def is_home_location(location: str, markers: tuple[str, ...] | None = None) -> bool:
    loc = (location or "").strip()
    if not loc:
        return False
    marks = markers or home_location_markers()
    for m in marks:
        if m and (loc == m or m in loc):
            return True
    return False


def _event_id_for_photos(photo_ids: list[str]) -> str:
    payload = "\n".join(sorted(photo_ids))
    return "evt_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class PhotoPoint:
    photo_id: str
    timestamp: str
    location: str
    coords: tuple[float, float] | None
    coords_str: str
    people: list[str] = field(default_factory=list)
    manual_location: bool = False


SOURCE_AUTO = "auto"
SOURCE_UNTIMED_LOC = "untimed_loc"


@dataclass
class BuiltEvent:
    event_id: str
    day: str
    location: str
    location_coords: str
    time_start: str
    time_end: str
    photo_count: int
    people: list[str]
    is_home: bool
    photo_ids: list[str]  # sorted by timestamp
    photo_timestamps: dict[str, str]
    source: str = SOURCE_AUTO


def _home_site_key(location: str, markers: tuple[str, ...]) -> str:
    loc = (location or "").strip()
    for m in markers:
        if m and (loc == m or m in loc):
            return m
    return ""


def _merge_manual_location_clusters(
    clusters: list[list[PhotoPoint]],
) -> list[list[PhotoPoint]]:
    """手改地名：同日同名强制合并（忽略 GPS 距离）。

    若某 location 在当日至少有一张 manual_location 照片，
    则所有该精确地名的照片并入同一簇。
    """
    if not clusters:
        return []

    merge_names: set[str] = set()
    for cluster in clusters:
        for p in cluster:
            loc = (p.location or "").strip()
            if loc and p.manual_location:
                merge_names.add(loc)
    if not merge_names:
        return clusters

    buckets: dict[str, list[PhotoPoint]] = defaultdict(list)
    residuals: list[list[PhotoPoint]] = []
    for cluster in clusters:
        leftover: list[PhotoPoint] = []
        for p in cluster:
            loc = (p.location or "").strip()
            if loc in merge_names:
                buckets[loc].append(p)
            else:
                leftover.append(p)
        if leftover:
            residuals.append(leftover)

    merged = [photos for name, photos in buckets.items() if photos]
    return merged + residuals


def _cluster_day_photos_spatial(records: list[PhotoPoint]) -> list[list[PhotoPoint]]:
    """同日空间聚类：有 GPS 按半径；无 GPS 按同 location，再按时间吸附。"""
    if not records:
        return []

    with_coords = [r for r in records if r.coords is not None]
    clusters: list[list[PhotoPoint]] = []

    if with_coords:
        assigned = [False] * len(with_coords)
        for i, seed in enumerate(with_coords):
            if assigned[i]:
                continue
            group = [seed]
            assigned[i] = True
            for j in range(i + 1, len(with_coords)):
                if assigned[j]:
                    continue
                other = with_coords[j]
                assert seed.coords is not None and other.coords is not None
                if _haversine_m(seed.coords, other.coords) <= CLUSTER_RADIUS_M:
                    group.append(other)
                    assigned[j] = True
            clusters.append(group)
    else:
        by_loc: dict[str, list[PhotoPoint]] = defaultdict(list)
        no_loc: list[PhotoPoint] = []
        for r in records:
            if r.location.strip():
                by_loc[r.location.strip()].append(r)
            else:
                no_loc.append(r)
        clusters.extend(by_loc.values())
        for r in no_loc:
            clusters.append([r])
        return clusters

    no_coords = [r for r in records if r.coords is None]
    remaining: list[PhotoPoint] = []
    for record in no_coords:
        loc = record.location.strip()
        joined = False
        if loc:
            for cluster in clusters:
                if any(m.location.strip() == loc for m in cluster):
                    cluster.append(record)
                    joined = True
                    break
        if not joined:
            remaining.append(record)

    for record in remaining:
        ts = _parse_timestamp_seconds(record.timestamp)
        best_cluster: list[PhotoPoint] | None = None
        best_delta = TIME_JOIN_SECONDS + 1
        for cluster in clusters:
            for member in cluster:
                member_ts = _parse_timestamp_seconds(member.timestamp)
                if ts is None or member_ts is None:
                    continue
                delta = abs(ts - member_ts)
                if delta < best_delta:
                    best_delta = delta
                    best_cluster = cluster
        if best_cluster is not None and best_delta <= TIME_JOIN_SECONDS:
            best_cluster.append(record)
        else:
            clusters.append([record])

    return clusters


def _cluster_day_photos(
    records: list[PhotoPoint],
    *,
    markers: tuple[str, ...] | None = None,
) -> list[list[PhotoPoint]]:
    """同日聚类：住过的家与非家先拆开，互不合并；不同住址之间也不混。

    之后对手改地名做同名强制合并（GPS 再远也对）。
    """
    if not records:
        return []
    marks = markers or home_location_markers()
    home_records = [r for r in records if is_home_location(r.location, marks)]
    other_records = [r for r in records if not is_home_location(r.location, marks)]

    home_clusters: list[list[PhotoPoint]] = []
    by_home_key: dict[str, list[PhotoPoint]] = defaultdict(list)
    for r in home_records:
        key = _home_site_key(r.location, marks) or r.location.strip() or r.photo_id
        by_home_key[key].append(r)
    for group in by_home_key.values():
        home_clusters.extend(_cluster_day_photos_spatial(group))

    clusters = home_clusters + _cluster_day_photos_spatial(other_records)
    return _merge_manual_location_clusters(clusters)


def _mean_coords(points: list[PhotoPoint]) -> str:
    coords = [p.coords for p in points if p.coords is not None]
    if not coords:
        for p in points:
            if p.coords_str:
                return p.coords_str
        return ""
    lat = sum(c[0] for c in coords) / len(coords)
    lon = sum(c[1] for c in coords) / len(coords)
    return f"{lat:.6f},{lon:.6f}"


def build_events_from_points(points: list[PhotoPoint]) -> list[BuiltEvent]:
    by_day: dict[str, list[PhotoPoint]] = defaultdict(list)
    for p in points:
        day = _date_key(p.timestamp)
        if day:
            by_day[day].append(p)

    events: list[BuiltEvent] = []
    markers = home_location_markers()

    for day, day_points in sorted(by_day.items()):
        for cluster in _cluster_day_photos(day_points, markers=markers):
            if len(cluster) < MIN_PHOTOS_OUTING:
                continue
            cluster_is_home = all(
                is_home_location(c.location, markers) for c in cluster if c.location.strip()
            ) and any(c.location.strip() for c in cluster)
            location = _pick_cluster_location(
                [c.location for c in cluster],
                majority_first=cluster_is_home,
            )
            # 无地名也允许成簇（仅 GPS）
            timestamps = sorted(c.timestamp for c in cluster if c.timestamp)
            photo_sorted = sorted(cluster, key=lambda c: (c.timestamp or "", c.photo_id))
            photo_ids = [c.photo_id for c in photo_sorted]
            people_set: set[str] = set()
            for c in cluster:
                people_set.update(n for n in c.people if n)
            people = sorted(people_set)
            is_home = cluster_is_home or is_home_location(location, markers)
            events.append(
                BuiltEvent(
                    event_id=_event_id_for_photos(photo_ids),
                    day=day,
                    location=location,
                    location_coords=_mean_coords(cluster),
                    time_start=timestamps[0] if timestamps else "",
                    time_end=timestamps[-1] if timestamps else "",
                    photo_count=len(photo_ids),
                    people=people,
                    is_home=is_home,
                    photo_ids=photo_ids,
                    photo_timestamps={c.photo_id: c.timestamp for c in cluster},
                    source=SOURCE_AUTO,
                )
            )

    events.sort(key=lambda e: (e.day, e.time_start, e.event_id), reverse=True)
    return events


def _rows_to_photo_points(rows: list[Any]) -> list[PhotoPoint]:
    points: list[PhotoPoint] = []
    for row in rows:
        coords_str = (row["location_coords"] or "").strip()
        people_raw = row["people"] or ""
        people = [n.strip() for n in people_raw.split(",") if n and n.strip()]
        points.append(
            PhotoPoint(
                photo_id=row["photo_id"],
                timestamp=row["timestamp"] or "",
                location=row["location"] or "",
                coords=_parse_coords(coords_str),
                coords_str=coords_str,
                people=people,
                manual_location=bool(row["manual_location"]),
            )
        )
    return points


def load_photo_points(conn: sqlite3.Connection) -> list[PhotoPoint]:
    rows = conn.execute(
        """
        SELECT
            p.photo_id,
            p.timestamp,
            p.location,
            p.location_coords,
            p.manual_location,
            GROUP_CONCAT(DISTINCT pp.person_name) AS people
        FROM photos p
        LEFT JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE p.timestamp != ''
        GROUP BY p.photo_id
        """
    ).fetchall()
    return _rows_to_photo_points(rows)


def load_untimed_located_points(conn: sqlite3.Connection) -> list[PhotoPoint]:
    """无时间且有地址：按地点聚合成事件用。"""
    rows = conn.execute(
        """
        SELECT
            p.photo_id,
            p.timestamp,
            p.location,
            p.location_coords,
            p.manual_location,
            GROUP_CONCAT(DISTINCT pp.person_name) AS people
        FROM photos p
        LEFT JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE (p.timestamp = '' OR p.timestamp IS NULL)
          AND p.location != ''
        GROUP BY p.photo_id
        """
    ).fetchall()
    return _rows_to_photo_points(rows)


def build_untimed_location_events(points: list[PhotoPoint]) -> list[BuiltEvent]:
    """无时间有地址：同一 location 一桶（≥1 张）。day/time 留空，不写假时间。"""
    by_loc: dict[str, list[PhotoPoint]] = defaultdict(list)
    for p in points:
        loc = (p.location or "").strip()
        if not loc:
            continue
        by_loc[loc].append(p)

    markers = home_location_markers()
    events: list[BuiltEvent] = []
    for location, cluster in by_loc.items():
        if not cluster:
            continue
        photo_sorted = sorted(cluster, key=lambda c: c.photo_id)
        photo_ids = [c.photo_id for c in photo_sorted]
        people_set: set[str] = set()
        for c in cluster:
            people_set.update(n for n in c.people if n)
        is_home = is_home_location(location, markers)
        events.append(
            BuiltEvent(
                event_id=_event_id_for_photos(photo_ids),
                day="",
                location=location,
                location_coords=_mean_coords(cluster),
                time_start="",
                time_end="",
                photo_count=len(photo_ids),
                people=sorted(people_set),
                is_home=is_home,
                photo_ids=photo_ids,
                photo_timestamps={c.photo_id: c.timestamp for c in cluster},
                source=SOURCE_UNTIMED_LOC,
            )
        )

    events.sort(key=lambda e: (-e.photo_count, e.location, e.event_id))
    return events


@dataclass
class EventSyncStats:
    events: int = 0
    event_photos: int = 0
    home_events: int = 0
    outing_events: int = 0
    untimed_location_events: int = 0
    overlays_rematched: int = 0
    overlays_orphaned: int = 0
    photos_with_ts: int = 0
    photos_in_events: int = 0


def rematch_overlays(conn: sqlite3.Connection) -> tuple[int, int]:
    """按 anchor_photo_ids 与现有 event 的 Jaccard 重挂；返回 (rematched, orphaned)。"""
    overlays = conn.execute(
        "SELECT overlay_id, event_id, anchor_photo_ids FROM event_overlays"
    ).fetchall()
    if not overlays:
        return 0, 0

    event_sets: dict[str, set[str]] = {}
    for row in conn.execute("SELECT event_id, photo_id FROM event_photos"):
        event_sets.setdefault(row["event_id"], set()).add(row["photo_id"])

    rematched = 0
    orphaned = 0
    for ov in overlays:
        try:
            anchors = set(json.loads(ov["anchor_photo_ids"] or "[]"))
        except json.JSONDecodeError:
            anchors = set()
        if not anchors:
            conn.execute(
                "UPDATE event_overlays SET event_id = '' WHERE overlay_id = ?",
                (ov["overlay_id"],),
            )
            orphaned += 1
            continue

        best_id = ""
        best_score = 0.0
        # 优先：锚点代表照仍在簇内
        for eid, photos in event_sets.items():
            if anchors & photos:
                score = _jaccard(anchors, photos)
                if score > best_score:
                    best_score = score
                    best_id = eid
        if best_score < OVERLAY_REMATCH_JACCARD:
            best_id = ""
            best_score = 0.0
            for eid, photos in event_sets.items():
                score = _jaccard(anchors, photos)
                if score > best_score:
                    best_score = score
                    best_id = eid
            if best_score < OVERLAY_REMATCH_JACCARD:
                best_id = ""

        if best_id:
            if best_id != (ov["event_id"] or ""):
                rematched += 1
            conn.execute(
                "UPDATE event_overlays SET event_id = ? WHERE overlay_id = ?",
                (best_id, ov["overlay_id"]),
            )
        else:
            conn.execute(
                "UPDATE event_overlays SET event_id = '' WHERE overlay_id = ?",
                (ov["overlay_id"],),
            )
            orphaned += 1

    return rematched, orphaned


def sync_events(conn: sqlite3.Connection) -> EventSyncStats:
    """重建 events / event_photos，并重挂 overlays。

    overlays/stories 真源为 data/memory_annotations.json：
    sync 前灌库（或从库 bootstrap 文件），重建后按锚点重挂并写回文件。
    """
    from hub.shared.annotations import ensure_annotations_loaded, flush_annotations_from_db

    ann_note = ensure_annotations_loaded(conn)
    logger.info("annotations: %s", ann_note)

    points = load_photo_points(conn)
    untimed_points = load_untimed_located_points(conn)
    built = build_events_from_points(points) + build_untimed_location_events(untimed_points)

    conn.execute("DELETE FROM event_photos")
    conn.execute("DELETE FROM events")

    built_at = _now_iso()
    photo_rows: list[tuple[str, str, str]] = []
    for ev in built:
        source = (ev.source or SOURCE_AUTO).strip() or SOURCE_AUTO
        conn.execute(
            """
            INSERT INTO events (
                event_id, day, location, location_coords,
                time_start, time_end, photo_count, people_json,
                is_home, cluster_radius_m, source, built_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ev.event_id,
                ev.day,
                ev.location,
                ev.location_coords,
                ev.time_start,
                ev.time_end,
                ev.photo_count,
                json.dumps(ev.people, ensure_ascii=False),
                1 if ev.is_home else 0,
                CLUSTER_RADIUS_M,
                source,
                built_at,
            ),
        )
        for pid in ev.photo_ids:
            photo_rows.append((ev.event_id, pid, ev.photo_timestamps.get(pid, "")))

    conn.executemany(
        "INSERT INTO event_photos (event_id, photo_id, sort_ts) VALUES (?, ?, ?)",
        photo_rows,
    )

    rematched, orphaned = rematch_overlays(conn)
    conn.commit()
    flush_annotations_from_db(conn)

    in_events = len({pid for _, pid, _ in photo_rows})
    untimed_n = sum(1 for e in built if e.source == SOURCE_UNTIMED_LOC)
    dated = [e for e in built if e.source != SOURCE_UNTIMED_LOC]
    return EventSyncStats(
        events=len(built),
        event_photos=len(photo_rows),
        home_events=sum(1 for e in dated if e.is_home),
        outing_events=sum(1 for e in dated if not e.is_home),
        untimed_location_events=untimed_n,
        overlays_rematched=rematched,
        overlays_orphaned=orphaned,
        photos_with_ts=len(points),
        photos_in_events=in_events,
    )


def get_event_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    untimed_loc = conn.execute(
        "SELECT COUNT(*) FROM events WHERE source = ?",
        (SOURCE_UNTIMED_LOC,),
    ).fetchone()[0]
    home = conn.execute(
        "SELECT COUNT(*) FROM events WHERE is_home = 1 AND source != ?",
        (SOURCE_UNTIMED_LOC,),
    ).fetchone()[0]
    outing = conn.execute(
        "SELECT COUNT(*) FROM events WHERE is_home = 0 AND source != ?",
        (SOURCE_UNTIMED_LOC,),
    ).fetchone()[0]
    ep = conn.execute("SELECT COUNT(*) FROM event_photos").fetchone()[0]
    distinct_photos = conn.execute(
        "SELECT COUNT(DISTINCT photo_id) FROM event_photos"
    ).fetchone()[0]
    photos_ts = conn.execute(
        "SELECT COUNT(*) FROM photos WHERE timestamp != ''"
    ).fetchone()[0]
    untimed_located = conn.execute(
        """
        SELECT COUNT(*) FROM photos
        WHERE (timestamp = '' OR timestamp IS NULL) AND location != ''
        """
    ).fetchone()[0]
    overlays = conn.execute("SELECT COUNT(*) FROM event_overlays").fetchone()[0]
    orphan_overlays = conn.execute(
        "SELECT COUNT(*) FROM event_overlays WHERE event_id = '' OR event_id IS NULL"
    ).fetchone()[0]
    stories = conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
    return {
        "events": total,
        "outing_events": outing,
        "home_events": home,
        "untimed_location_events": untimed_loc,
        "event_photos": ep,
        "photos_in_events": distinct_photos,
        "photos_with_timestamp": photos_ts,
        "untimed_located_photos": untimed_located,
        "coverage_pct": (
            round(100.0 * distinct_photos / (photos_ts + untimed_located), 1)
            if (photos_ts + untimed_located)
            else 0.0
        ),
        "overlays": overlays,
        "orphan_overlays": orphan_overlays,
        "stories": stories,
    }


def _day_filter_clause(alias: str, day: str) -> tuple[str, list[Any]]:
    """day 支持 YYYY / YYYY-MM / YYYY-MM-DD（前缀匹配）。"""
    d = day.strip()
    if not d:
        return "", []
    col = f"{alias}.day" if alias else "day"
    if len(d) >= 10:
        return f"{col} = ?", [d[:10]]
    return f"{col} LIKE ?", [f"{d}%"]


def _keyword_event_clause(pattern: str) -> tuple[str, list[Any]]:
    """事件内任意照片的 scene / photo_terms，或地点 / 备注命中。"""
    return (
        """(
            e.location LIKE ?
            OR IFNULL(o.title, '') LIKE ?
            OR IFNULL(o.body, '') LIKE ?
            OR EXISTS (
                SELECT 1 FROM event_photos ep
                JOIN photos p ON p.photo_id = ep.photo_id
                WHERE ep.event_id = e.event_id
                  AND (
                    p.scene LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM photo_terms t
                        WHERE t.photo_id = ep.photo_id AND t.term LIKE ?
                    )
                  )
            )
        )""",
        [pattern, pattern, pattern, pattern, pattern],
    )


def _event_list_clauses(
    *,
    day: str = "",
    include_home: bool = False,
    location: str = "",
    person: str = "",
    keyword: str = "",
    months: list[int] | tuple[int, ...] | None = None,
    time_scope: str = "all",
) -> tuple[str, list[Any]]:
    """time_scope: all | dated | untimed — 控制是否含无时间地点事件。"""
    clauses = ["1=1"]
    params: list[Any] = []
    scope = (time_scope or "all").strip().lower()
    if scope not in ("all", "dated", "untimed"):
        scope = "all"
    if scope == "untimed":
        clauses.append("e.source = ?")
        params.append(SOURCE_UNTIMED_LOC)
    elif scope == "dated":
        clauses.append("(e.source IS NULL OR e.source = '' OR e.source = ?)")
        params.append(SOURCE_AUTO)
    if not include_home:
        clauses.append("e.is_home = 0")
    day_sql, day_params = _day_filter_clause("e", day)
    if day_sql:
        clauses.append(day_sql)
        params.extend(day_params)
    if months:
        month_vals = sorted({int(m) for m in months if 1 <= int(m) <= 12})
        if month_vals:
            placeholders = ", ".join("?" for _ in month_vals)
            clauses.append(f"CAST(substr(e.day, 6, 2) AS INTEGER) IN ({placeholders})")
            params.extend(month_vals)
    if location:
        clauses.append("e.location = ?")
        params.append(location.strip())
    if person:
        clauses.append("e.people_json LIKE ?")
        params.append(f"%{person}%")
    kw = keyword.strip()
    if kw:
        kw_sql, kw_params = _keyword_event_clause(f"%{kw}%")
        clauses.append(kw_sql)
        params.extend(kw_params)
    return " AND ".join(clauses), params


def list_events(
    conn: sqlite3.Connection,
    *,
    day: str = "",
    include_home: bool = False,
    location: str = "",
    person: str = "",
    keyword: str = "",
    months: list[int] | tuple[int, ...] | None = None,
    time_scope: str = "all",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where, params = _event_list_clauses(
        day=day,
        include_home=include_home,
        location=location,
        person=person,
        keyword=keyword,
        months=months,
        time_scope=time_scope,
    )
    # 无时间地点事件 day 为空：排在有日期之后，再按张数
    rows = conn.execute(
        f"""
        SELECT
            e.*,
            o.overlay_id,
            o.title AS overlay_title,
            o.body AS overlay_body,
            o.tags_json AS overlay_tags_json
        FROM events e
        LEFT JOIN event_overlays o ON o.event_id = e.event_id
        WHERE {where}
        ORDER BY
            CASE WHEN e.day = '' OR e.day IS NULL THEN 1 ELSE 0 END,
            e.day DESC,
            e.photo_count DESC,
            e.time_start DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    items = [_event_row_to_dict(r) for r in rows]
    _attach_events_weather(conn, items, allow_fetch=False)
    return items


def count_events(
    conn: sqlite3.Connection,
    *,
    day: str = "",
    include_home: bool = False,
    location: str = "",
    person: str = "",
    keyword: str = "",
    months: list[int] | tuple[int, ...] | None = None,
    time_scope: str = "all",
) -> int:
    where, params = _event_list_clauses(
        day=day,
        include_home=include_home,
        location=location,
        person=person,
        keyword=keyword,
        months=months,
        time_scope=time_scope,
    )
    return conn.execute(
        f"""
        SELECT COUNT(*) FROM events e
        LEFT JOIN event_overlays o ON o.event_id = e.event_id
        WHERE {where}
        """,
        params,
    ).fetchone()[0]


def list_event_locations(
    conn: sqlite3.Connection,
    *,
    include_home: bool = True,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    clauses = ["location != ''"]
    if not include_home:
        clauses.append("is_home = 0")
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT location, COUNT(*) AS cnt
        FROM events
        WHERE {where}
        GROUP BY location
        ORDER BY cnt DESC, location ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [{"location": r["location"], "count": r["cnt"]} for r in rows]


def list_event_years(conn: sqlite3.Connection, *, include_home: bool = True) -> list[str]:
    clauses = ["day != ''"]
    if not include_home:
        clauses.append("is_home = 0")
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT DISTINCT substr(day, 1, 4) AS y
        FROM events
        WHERE {where}
        ORDER BY y DESC
        """
    ).fetchall()
    return [r["y"] for r in rows if r["y"]]


def _event_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    people: list[str] = []
    try:
        people = json.loads(row["people_json"] or "[]")
    except json.JSONDecodeError:
        people = []
    tags: list[str] = []
    keys = set(row.keys())
    if "overlay_tags_json" in keys and row["overlay_tags_json"]:
        try:
            tags = json.loads(row["overlay_tags_json"])
        except json.JSONDecodeError:
            tags = []

    overlay_title = row["overlay_title"] if "overlay_title" in keys else ""
    overlay_body = row["overlay_body"] if "overlay_body" in keys else ""
    overlay_id = row["overlay_id"] if "overlay_id" in keys else None
    day_label = (row["day"] or "").strip() or "无时间"
    display_title = overlay_title or f"{day_label} · {row['location'] or '未知地点'}"

    overlay = None
    if overlay_id:
        overlay = {
            "overlay_id": overlay_id,
            "title": overlay_title or "",
            "body": overlay_body or "",
            "tags": tags,
        }

    return {
        "event_id": row["event_id"],
        "day": row["day"],
        "location": row["location"] or "",
        "location_coords": row["location_coords"] or "",
        "time_start": row["time_start"] or "",
        "time_end": row["time_end"] or "",
        "photo_count": row["photo_count"],
        "people": people,
        "is_home": bool(row["is_home"]),
        "cluster_radius_m": row["cluster_radius_m"],
        "source": row["source"],
        "built_at": row["built_at"],
        "display_title": display_title,
        "overlay": overlay,
        "weather": None,
        "weather_label": "",
    }


def _weather_payload_from_weather(weather: dict[str, Any]) -> dict[str, Any]:
    from hub.shared.weather import format_weather_label

    condition = str(weather.get("condition") or "").strip()
    temp_min = weather.get("temp_min_c")
    temp_max = weather.get("temp_max_c")
    temp_mean = weather.get("temp_mean_c")
    label = format_weather_label(
        condition,
        temp_min_c=float(temp_min) if temp_min is not None else None,
        temp_max_c=float(temp_max) if temp_max is not None else None,
        temp_mean_c=float(temp_mean) if temp_mean is not None else None,
    )
    return {
        "condition": condition,
        "temp_min_c": temp_min,
        "temp_max_c": temp_max,
        "temp_mean_c": temp_mean,
        "label": label,
    }


def _event_day_coords(
    conn: sqlite3.Connection, event_ids: list[str]
) -> dict[str, str]:
    """event_id → 代表坐标（事件自身或任一张有 GPS 的成员照片）。"""
    if not event_ids:
        return {}
    placeholders = ",".join("?" for _ in event_ids)
    out: dict[str, str] = {}
    rows = conn.execute(
        f"""
        SELECT e.event_id, e.location_coords
        FROM events e
        WHERE e.event_id IN ({placeholders})
        """,
        event_ids,
    ).fetchall()
    for row in rows:
        coords = str(row["location_coords"] or "").strip()
        if coords:
            out[row["event_id"]] = coords
    missing = [eid for eid in event_ids if eid not in out]
    if missing:
        ph = ",".join("?" for _ in missing)
        photo_rows = conn.execute(
            f"""
            SELECT ep.event_id, p.location_coords
            FROM event_photos ep
            JOIN photos p ON p.photo_id = ep.photo_id
            WHERE ep.event_id IN ({ph})
              AND IFNULL(p.location_coords, '') != ''
            ORDER BY ep.event_id, ep.sort_ts
            """,
            missing,
        ).fetchall()
        for row in photo_rows:
            eid = row["event_id"]
            if eid not in out:
                out[eid] = str(row["location_coords"]).strip()
    return out


def _attach_photo_weather_fallback(
    conn: sqlite3.Connection, events: list[dict[str, Any]]
) -> None:
    """Open-Meteo 缓存没有时，用照片上已写入的 weather 凑一列，避免列表再打网。"""
    missing = [
        e
        for e in events
        if e.get("event_id") and not str((e.get("weather") or {}).get("condition") or "").strip()
    ]
    if not missing:
        return
    ids = [e["event_id"] for e in missing]
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT
            ep.event_id,
            p.weather_condition,
            p.weather_temp_min_c,
            p.weather_temp_max_c,
            p.weather_temp_mean_c
        FROM event_photos ep
        JOIN photos p ON p.photo_id = ep.photo_id
        WHERE ep.event_id IN ({placeholders})
          AND p.weather_condition IS NOT NULL
          AND TRIM(p.weather_condition) != ''
        """,
        ids,
    ).fetchall()
    by_event: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_event.setdefault(str(row["event_id"]), []).append(row)

    for event in missing:
        samples = by_event.get(event["event_id"]) or []
        if not samples:
            continue
        conditions = [str(r["weather_condition"]).strip() for r in samples]
        condition = Counter(conditions).most_common(1)[0][0]
        sample = next(r for r in samples if str(r["weather_condition"]).strip() == condition)
        payload = _weather_payload_from_weather(
            {
                "condition": condition,
                "temp_min_c": sample["weather_temp_min_c"],
                "temp_max_c": sample["weather_temp_max_c"],
                "temp_mean_c": sample["weather_temp_mean_c"],
            }
        )
        event["weather"] = payload
        event["weather_label"] = payload["label"]


def _attach_events_weather(
    conn: sqlite3.Connection,
    events: list[dict[str, Any]],
    *,
    allow_fetch: bool = False,
) -> None:
    """事件天气：优先读缓存；列表默认不打 Open-Meteo，避免事件页卡住。"""
    if not events:
        return
    from hub.shared.weather import (
        load_weather_cache,
        resolve_daytime_weather,
        save_weather_cache,
    )

    ids = [e["event_id"] for e in events if e.get("event_id")]
    if not ids:
        return

    coords_by_event = _event_day_coords(conn, ids)
    # 同一天共用一条白天天气（取当天任一可用坐标）
    day_coords: dict[str, str] = {}
    for event in events:
        day = str(event.get("day") or "").strip()
        if not day or day in day_coords:
            continue
        coords = coords_by_event.get(event["event_id"], "")
        if coords:
            day_coords[day] = coords

    cache = load_weather_cache() if allow_fetch else None
    day_weather: dict[str, dict[str, Any]] = {}
    try:
        for day, coords in day_coords.items():
            weather = resolve_daytime_weather(
                coords,
                day,
                cache=cache,
                persist_cache=False,
                allow_fetch=allow_fetch,
            )
            if weather:
                day_weather[day] = _weather_payload_from_weather(dict(weather))
    finally:
        if allow_fetch and cache is not None:
            save_weather_cache(cache)

    for event in events:
        day = str(event.get("day") or "").strip()
        payload = day_weather.get(day)
        if not payload:
            continue
        event["weather"] = payload
        event["weather_label"] = payload["label"]

    _attach_photo_weather_fallback(conn, events)


def get_event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            e.*,
            o.overlay_id,
            o.title AS overlay_title,
            o.body AS overlay_body,
            o.tags_json AS overlay_tags_json
        FROM events e
        LEFT JOIN event_overlays o ON o.event_id = e.event_id
        WHERE e.event_id = ?
        """,
        (event_id,),
    ).fetchone()
    if not row:
        return None
    data = _event_row_to_dict(row)
    photos = conn.execute(
        """
        SELECT
            ep.photo_id,
            ep.sort_ts,
            p.timestamp,
            p.location,
            p.scene,
            p.source_path,
            IFNULL(p.media_type, 'photo') AS media_type,
            p.weather_condition,
            p.weather_temp_min_c,
            p.weather_temp_max_c,
            p.weather_temp_mean_c
        FROM event_photos ep
        JOIN photos p ON p.photo_id = ep.photo_id
        WHERE ep.event_id = ?
        ORDER BY ep.sort_ts ASC, ep.photo_id ASC
        """,
        (event_id,),
    ).fetchall()
    data["photos"] = [dict(p) for p in photos]
    _attach_events_weather(conn, [data])
    return data


def list_orphan_overlays(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM event_overlays
        WHERE event_id = '' OR event_id IS NULL
        ORDER BY updated_at DESC
        """
    ).fetchall()
    out = []
    for r in rows:
        try:
            anchors = json.loads(r["anchor_photo_ids"] or "[]")
        except json.JSONDecodeError:
            anchors = []
        try:
            tags = json.loads(r["tags_json"] or "[]")
        except json.JSONDecodeError:
            tags = []
        out.append(
            {
                "overlay_id": r["overlay_id"],
                "event_id": r["event_id"] or "",
                "title": r["title"] or "",
                "body": r["body"] or "",
                "tags": tags,
                "anchor_photo_ids": anchors,
                "updated_at": r["updated_at"],
            }
        )
    return out


def upsert_event_overlay(
    conn: sqlite3.Connection,
    event_id: str,
    *,
    title: str = "",
    body: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    ev = conn.execute(
        "SELECT event_id FROM events WHERE event_id = ?", (event_id,)
    ).fetchone()
    if not ev:
        raise KeyError(f"event not found: {event_id}")

    photo_ids = [
        r["photo_id"]
        for r in conn.execute(
            "SELECT photo_id FROM event_photos WHERE event_id = ? ORDER BY sort_ts, photo_id",
            (event_id,),
        )
    ]
    # 锚点：全员（稳定重挂）；过大时仍可接受
    anchors = photo_ids
    tags = tags or []
    now = _now_iso()

    existing = conn.execute(
        "SELECT overlay_id FROM event_overlays WHERE event_id = ?", (event_id,)
    ).fetchone()
    if existing:
        overlay_id = existing["overlay_id"]
        conn.execute(
            """
            UPDATE event_overlays
            SET title = ?, body = ?, tags_json = ?, anchor_photo_ids = ?,
                manual = 1, updated_at = ?
            WHERE overlay_id = ?
            """,
            (
                title.strip(),
                body,
                json.dumps(tags, ensure_ascii=False),
                json.dumps(anchors, ensure_ascii=False),
                now,
                overlay_id,
            ),
        )
    else:
        overlay_id = "ovl_" + uuid.uuid4().hex[:12]
        conn.execute(
            """
            INSERT INTO event_overlays (
                overlay_id, event_id, anchor_photo_ids, title, body,
                tags_json, manual, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                overlay_id,
                event_id,
                json.dumps(anchors, ensure_ascii=False),
                title.strip(),
                body,
                json.dumps(tags, ensure_ascii=False),
                now,
            ),
        )
    conn.commit()
    from hub.shared.annotations import flush_annotations_from_db

    flush_annotations_from_db(conn)
    return {
        "overlay_id": overlay_id,
        "event_id": event_id,
        "title": title.strip(),
        "body": body,
        "tags": tags,
        "anchor_photo_ids": anchors,
        "updated_at": now,
    }


def delete_event_overlay(conn: sqlite3.Connection, event_id: str) -> bool:
    cur = conn.execute("DELETE FROM event_overlays WHERE event_id = ?", (event_id,))
    conn.commit()
    if cur.rowcount > 0:
        from hub.shared.annotations import flush_annotations_from_db

        flush_annotations_from_db(conn)
    return cur.rowcount > 0


# ---------- Stories ----------


def list_stories(conn: sqlite3.Connection, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.*,
               (SELECT COUNT(*) FROM story_links sl WHERE sl.story_id = s.story_id) AS link_count
        FROM stories s
        ORDER BY COALESCE(s.time_start, s.updated_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_story_row(r) for r in rows]


def _story_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        people = json.loads(row["people_json"] or "[]")
    except json.JSONDecodeError:
        people = []
    data = {
        "story_id": row["story_id"],
        "title": row["title"] or "",
        "body": row["body"] or "",
        "time_start": row["time_start"] or "",
        "time_end": row["time_end"] or "",
        "people": people,
        "updated_at": row["updated_at"],
    }
    if "link_count" in row.keys():
        data["link_count"] = row["link_count"]
    return data


def get_story(conn: sqlite3.Connection, story_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM stories WHERE story_id = ?", (story_id,)
    ).fetchone()
    if not row:
        return None
    data = _story_row(row)
    links = conn.execute(
        """
        SELECT link_type, link_id, sort_order
        FROM story_links
        WHERE story_id = ?
        ORDER BY sort_order ASC, link_type, link_id
        """,
        (story_id,),
    ).fetchall()
    data["links"] = [dict(l) for l in links]
    return data


def create_story(
    conn: sqlite3.Connection,
    *,
    title: str,
    body: str = "",
    time_start: str = "",
    time_end: str = "",
    people: list[str] | None = None,
    links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    story_id = "sty_" + uuid.uuid4().hex[:12]
    now = _now_iso()
    people = people or []
    conn.execute(
        """
        INSERT INTO stories (
            story_id, title, body, time_start, time_end, people_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            story_id,
            title.strip(),
            body,
            time_start,
            time_end,
            json.dumps(people, ensure_ascii=False),
            now,
        ),
    )
    _replace_story_links(conn, story_id, links or [])
    conn.commit()
    from hub.shared.annotations import flush_annotations_from_db

    flush_annotations_from_db(conn)
    result = get_story(conn, story_id)
    assert result is not None
    return result


def update_story(
    conn: sqlite3.Connection,
    story_id: str,
    *,
    title: str | None = None,
    body: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    people: list[str] | None = None,
    links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    existing = get_story(conn, story_id)
    if existing is None:
        raise KeyError(f"story not found: {story_id}")
    now = _now_iso()
    new_title = title if title is not None else existing["title"]
    new_body = body if body is not None else existing["body"]
    new_start = time_start if time_start is not None else existing["time_start"]
    new_end = time_end if time_end is not None else existing["time_end"]
    new_people = people if people is not None else existing["people"]
    conn.execute(
        """
        UPDATE stories
        SET title = ?, body = ?, time_start = ?, time_end = ?,
            people_json = ?, updated_at = ?
        WHERE story_id = ?
        """,
        (
            new_title.strip() if isinstance(new_title, str) else new_title,
            new_body,
            new_start,
            new_end,
            json.dumps(new_people, ensure_ascii=False),
            now,
            story_id,
        ),
    )
    if links is not None:
        _replace_story_links(conn, story_id, links)
    conn.commit()
    from hub.shared.annotations import flush_annotations_from_db

    flush_annotations_from_db(conn)
    result = get_story(conn, story_id)
    assert result is not None
    return result


def _replace_story_links(
    conn: sqlite3.Connection,
    story_id: str,
    links: list[dict[str, Any]],
) -> None:
    conn.execute("DELETE FROM story_links WHERE story_id = ?", (story_id,))
    rows = []
    for i, link in enumerate(links):
        link_type = str(link.get("link_type") or "").strip()
        link_id = str(link.get("link_id") or "").strip()
        if link_type not in ("event", "photo") or not link_id:
            continue
        sort_order = int(link.get("sort_order", i))
        rows.append((story_id, link_type, link_id, sort_order))
    if rows:
        conn.executemany(
            """
            INSERT INTO story_links (story_id, link_type, link_id, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )


def delete_story(conn: sqlite3.Connection, story_id: str) -> bool:
    conn.execute("DELETE FROM story_links WHERE story_id = ?", (story_id,))
    cur = conn.execute("DELETE FROM stories WHERE story_id = ?", (story_id,))
    conn.commit()
    if cur.rowcount > 0:
        from hub.shared.annotations import flush_annotations_from_db

        flush_annotations_from_db(conn)
    return cur.rowcount > 0


def search_stories(conn: sqlite3.Connection, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return list_stories(conn, limit=limit)
    pattern = f"%{q}%"
    rows = conn.execute(
        """
        SELECT s.*,
               (SELECT COUNT(*) FROM story_links sl WHERE sl.story_id = s.story_id) AS link_count
        FROM stories s
        WHERE s.title LIKE ? OR s.body LIKE ?
        ORDER BY s.updated_at DESC
        LIMIT ?
        """,
        (pattern, pattern, limit),
    ).fetchall()
    return [_story_row(r) for r in rows]
