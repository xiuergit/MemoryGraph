"""SQLite 索引：从 data/memory/*.json 同步，JSON 仍为唯一数据源。"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from hub.shared.schema import location_admin_from_dict
from hub.shared.family import person_search_tokens
from hub.shared.weather import weather_from_dict

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    photo_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL DEFAULT '',
    device_id TEXT NOT NULL DEFAULT '',
    scene TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    location_coords TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    face_detected INTEGER NOT NULL DEFAULT 0,
    manual_edit INTEGER NOT NULL DEFAULT 0,
    manual_location INTEGER NOT NULL DEFAULT 0,
    manual_people INTEGER NOT NULL DEFAULT 0,
    manual_vision INTEGER NOT NULL DEFAULT 0,
    json_path TEXT NOT NULL,
    json_mtime REAL NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photo_people (
    photo_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    person_name TEXT NOT NULL DEFAULT '',
    confidence REAL,
    role TEXT NOT NULL DEFAULT '',
    age_label TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (photo_id, person_id),
    FOREIGN KEY (photo_id) REFERENCES photos(photo_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS photo_terms (
    photo_id TEXT NOT NULL,
    term TEXT NOT NULL,
    term_type TEXT NOT NULL,
    PRIMARY KEY (photo_id, term, term_type),
    FOREIGN KEY (photo_id) REFERENCES photos(photo_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_photos_timestamp ON photos(timestamp);
CREATE INDEX IF NOT EXISTS idx_photo_people_name ON photo_people(person_name);
CREATE INDEX IF NOT EXISTS idx_photo_terms_term ON photo_terms(term);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    day TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    location_coords TEXT NOT NULL DEFAULT '',
    time_start TEXT NOT NULL DEFAULT '',
    time_end TEXT NOT NULL DEFAULT '',
    photo_count INTEGER NOT NULL DEFAULT 0,
    people_json TEXT NOT NULL DEFAULT '[]',
    is_home INTEGER NOT NULL DEFAULT 0,
    cluster_radius_m INTEGER NOT NULL DEFAULT 800,
    source TEXT NOT NULL DEFAULT 'auto',
    built_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS event_photos (
    event_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    sort_ts TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (event_id, photo_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS event_overlays (
    overlay_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL DEFAULT '',
    anchor_photo_ids TEXT NOT NULL DEFAULT '[]',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    manual INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS stories (
    story_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    time_start TEXT NOT NULL DEFAULT '',
    time_end TEXT NOT NULL DEFAULT '',
    people_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS story_links (
    story_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    link_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (story_id, link_type, link_id),
    FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_day ON events(day);
CREATE INDEX IF NOT EXISTS idx_events_is_home ON events(is_home);
CREATE INDEX IF NOT EXISTS idx_event_photos_photo ON event_photos(photo_id);
CREATE INDEX IF NOT EXISTS idx_event_overlays_event ON event_overlays(event_id);
CREATE INDEX IF NOT EXISTS idx_story_links_link ON story_links(link_type, link_id);
"""


@dataclass
class SyncStats:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    failed: int = 0


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    _ensure_column(conn, "photos", "location_coords", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "photos", "location_province", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "photos", "location_city", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "photos", "location_district", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "photos", "manual_edit", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "photos", "manual_location", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "photos", "manual_people", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "photos", "manual_vision", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "photos", "weather_date", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "photos", "weather_code", "INTEGER")
    _ensure_column(conn, "photos", "weather_condition", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "photos", "weather_temp_mean_c", "REAL")
    _ensure_column(conn, "photos", "weather_temp_min_c", "REAL")
    _ensure_column(conn, "photos", "weather_temp_max_c", "REAL")
    _ensure_column(conn, "photos", "weather_precipitation_mm", "REAL")
    # photo | video | audio；主键列仍叫 photo_id，存各协议的 *_id
    _ensure_column(conn, "photos", "media_type", "TEXT NOT NULL DEFAULT 'photo'")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_photos_media_type ON photos(media_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_photos_location_province ON photos(location_province)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_photos_location_city ON photos(location_city)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_photos_manual_edit ON photos(manual_edit)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_photos_manual_location ON photos(manual_location)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_photos_manual_people ON photos(manual_people)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_photos_manual_vision ON photos(manual_vision)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_photos_weather_condition ON photos(weather_condition)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_photos_weather_date ON photos(weather_date)"
    )
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def memory_identity(data: dict[str, Any]) -> tuple[str, str]:
    """从 JSON 得到 (索引主键, media_type)。主键列名仍为 photo_id。"""
    video_id = str(data.get("video_id") or "").strip()
    if video_id:
        return video_id, "video"
    audio_id = str(data.get("audio_id") or "").strip()
    if audio_id:
        return audio_id, "audio"
    photo_id = str(data.get("photo_id") or "").strip()
    if photo_id:
        return photo_id, "photo"
    raise KeyError("memory JSON 缺少 photo_id / video_id / audio_id")


def _photo_row(
    data: dict[str, Any],
    json_path: Path,
    json_mtime: float,
    *,
    memory_id: str,
    media_type: str,
) -> tuple:
    quality = data.get("quality") or {}
    source = data.get("source") or {}
    location_coords = str(data.get("location_coords", "")).strip()
    admin = location_admin_from_dict(data.get("location_admin"))
    weather = weather_from_dict(data.get("weather") if isinstance(data.get("weather"), dict) else None)
    face_detected = 1 if quality.get("face_detected") else 0
    return (
        memory_id,
        media_type,
        data.get("timestamp", ""),
        data.get("device_id", ""),
        data.get("scene", ""),
        data.get("location", ""),
        location_coords,
        admin["province"],
        admin["city"],
        admin["district"],
        source.get("path", ""),
        face_detected,
        1 if data.get("manual_edit") else 0,
        1 if data.get("manual_location") else 0,
        1 if data.get("manual_people") else 0,
        1 if data.get("manual_vision") else 0,
        (weather or {}).get("date", "") if weather else "",
        weather["code"] if weather else None,
        (weather or {}).get("condition", "") if weather else "",
        weather["temp_mean_c"] if weather else None,
        weather["temp_min_c"] if weather else None,
        weather["temp_max_c"] if weather else None,
        weather["precipitation_mm"] if weather else None,
        str(json_path.resolve()),
        json_mtime,
        datetime.now().isoformat(timespec="seconds"),
    )


def _people_rows(photo_id: str, people: list[dict[str, Any]]) -> list[tuple]:
    rows: list[tuple] = []
    for person in people:
        age = person.get("age_at_photo") or {}
        rows.append(
            (
                photo_id,
                person.get("id", ""),
                person.get("name", ""),
                person.get("confidence"),
                person.get("role", ""),
                age.get("label", ""),
            )
        )
    return rows


def _term_rows(photo_id: str, data: dict[str, Any]) -> list[tuple]:
    rows: list[tuple] = []
    for field in ("tags", "objects", "actions", "emotion"):
        seen: set[str] = set()
        for term in data.get(field) or []:
            if not term:
                continue
            key = str(term)
            if key in seen:
                continue
            seen.add(key)
            rows.append((photo_id, key, field))
    scene = str(data.get("scene", "")).strip()
    if scene:
        rows.append((photo_id, scene, "scene"))
    user_note = str(data.get("user_note") or "").strip()
    if user_note:
        rows.append((photo_id, user_note[:8000], "user_note"))
    weather = weather_from_dict(data.get("weather") if isinstance(data.get("weather"), dict) else None)
    if weather and weather.get("condition"):
        rows.append((photo_id, weather["condition"], "weather"))
    # 仅 confirmed 字幕进索引；draft / 缺 status 不参与问答检索
    transcript = data.get("transcript")
    if isinstance(transcript, dict):
        from hub.shared.schema import transcript_status

        text = str(transcript.get("text") or "").strip()
        if text and transcript_status(transcript) == "confirmed":
            rows.append((photo_id, text[:8000], "transcript"))
    return rows


def _upsert_photo(conn: sqlite3.Connection, data: dict[str, Any], json_path: Path) -> None:
    json_mtime = json_path.stat().st_mtime
    photo_id, media_type = memory_identity(data)

    conn.execute(
        """
        INSERT INTO photos (
            photo_id, media_type, timestamp, device_id, scene, location, location_coords,
            location_province, location_city, location_district,
            source_path, face_detected, manual_edit, manual_location,
            manual_people, manual_vision,
            weather_date, weather_code, weather_condition,
            weather_temp_mean_c, weather_temp_min_c, weather_temp_max_c,
            weather_precipitation_mm,
            json_path, json_mtime, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(photo_id) DO UPDATE SET
            media_type = excluded.media_type,
            timestamp = excluded.timestamp,
            device_id = excluded.device_id,
            scene = excluded.scene,
            location = excluded.location,
            location_coords = excluded.location_coords,
            location_province = excluded.location_province,
            location_city = excluded.location_city,
            location_district = excluded.location_district,
            source_path = excluded.source_path,
            face_detected = excluded.face_detected,
            manual_edit = excluded.manual_edit,
            manual_location = excluded.manual_location,
            manual_people = excluded.manual_people,
            manual_vision = excluded.manual_vision,
            weather_date = excluded.weather_date,
            weather_code = excluded.weather_code,
            weather_condition = excluded.weather_condition,
            weather_temp_mean_c = excluded.weather_temp_mean_c,
            weather_temp_min_c = excluded.weather_temp_min_c,
            weather_temp_max_c = excluded.weather_temp_max_c,
            weather_precipitation_mm = excluded.weather_precipitation_mm,
            json_path = excluded.json_path,
            json_mtime = excluded.json_mtime,
            indexed_at = excluded.indexed_at
        """,
        _photo_row(
            data,
            json_path,
            json_mtime,
            memory_id=photo_id,
            media_type=media_type,
        ),
    )
    conn.execute("DELETE FROM photo_people WHERE photo_id = ?", (photo_id,))
    conn.execute("DELETE FROM photo_terms WHERE photo_id = ?", (photo_id,))

    conn.executemany(
        """
        INSERT INTO photo_people (
            photo_id, person_id, person_name, confidence, role, age_label
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        _people_rows(photo_id, data.get("people") or []),
    )
    conn.executemany(
        "INSERT INTO photo_terms (photo_id, term, term_type) VALUES (?, ?, ?)",
        _term_rows(photo_id, data),
    )


def _load_json(json_path: Path) -> dict[str, Any]:
    with json_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def sync_memory_dir(
    memory_dir: Path,
    db_path: Path,
    *,
    force: bool = False,
) -> SyncStats:
    """扫描 memory_dir 下 JSON，增量同步到 SQLite。"""
    stats = SyncStats()
    conn = connect(db_path)
    init_db(conn)

    existing: dict[str, float] = {}
    if not force:
        for row in conn.execute("SELECT photo_id, json_mtime FROM photos"):
            existing[row["photo_id"]] = row["json_mtime"]

    seen_ids: set[str] = set()
    json_files = sorted(memory_dir.glob("*.json"))

    for json_path in json_files:
        try:
            json_mtime = json_path.stat().st_mtime
            data = _load_json(json_path)
            photo_id, _media_type = memory_identity(data)
            seen_ids.add(photo_id)

            if not force and photo_id in existing and existing[photo_id] == json_mtime:
                stats.skipped += 1
                continue

            _upsert_photo(conn, data, json_path)
            if photo_id in existing:
                stats.updated += 1
            else:
                stats.added += 1
        except Exception as exc:
            stats.failed += 1
            logger.warning("索引失败 %s: %s", json_path.name, exc)

    if not force:
        stale = [
            row["photo_id"]
            for row in conn.execute("SELECT photo_id FROM photos")
            if row["photo_id"] not in seen_ids
        ]
        for photo_id in stale:
            conn.execute("DELETE FROM photos WHERE photo_id = ?", (photo_id,))
            stats.removed += 1

    conn.commit()
    conn.close()
    return stats


def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    photo_count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    people_count = conn.execute(
        "SELECT COUNT(DISTINCT person_name) FROM photo_people WHERE person_name != ''"
    ).fetchone()[0]
    with_face = conn.execute(
        "SELECT COUNT(*) FROM photos WHERE face_detected = 1"
    ).fetchone()[0]
    latest = conn.execute(
        "SELECT photo_id, timestamp FROM photos ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    return {
        "photos": photo_count,
        "people": people_count,
        "with_face": with_face,
        "latest": dict(latest) if latest else None,
    }


def search_photos(
    conn: sqlite3.Connection,
    *,
    person: str = "",
    query: str = "",
    limit: int = 20,
    term_types: tuple[str, ...] | None = None,
    match_scene: bool = True,
    match_location: bool = True,
) -> list[dict[str, Any]]:
    """按人物名或关键词搜索照片，按 timestamp 倒序。

    term_types: 若指定，仅匹配 photo_terms 中这些类型（如 ('actions',)）。
    match_scene / match_location: 是否用 scene、location 做 LIKE（动作检索时常关掉）。
    limit<=0：取全量（上限 5000），供问答证据图用。
    """
    if limit <= 0:
        limit = 5000

    clauses = ["1=1"]
    params: list[Any] = []

    if person:
        tokens = person_search_tokens(person)
        if not tokens:
            tokens = [person]
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

    if query:
        pattern = f"%{query}%"
        or_parts: list[str] = []
        if match_scene:
            or_parts.append("p.scene LIKE ?")
            params.append(pattern)
        if match_location:
            or_parts.append("p.location LIKE ?")
            params.append(pattern)
            or_parts.append("p.location_province LIKE ?")
            params.append(pattern)
            or_parts.append("p.location_city LIKE ?")
            params.append(pattern)
            or_parts.append("p.location_district LIKE ?")
            params.append(pattern)

        term_sql = "t.photo_id = p.photo_id AND t.term LIKE ?"
        term_params: list[Any] = [pattern]
        if term_types:
            placeholders = ",".join("?" for _ in term_types)
            term_sql += f" AND t.term_type IN ({placeholders})"
            term_params.extend(term_types)
        or_parts.append(
            f"""
            EXISTS (
                SELECT 1 FROM photo_terms t
                WHERE {term_sql}
            )
            """
        )
        params.extend(term_params)
        clauses.append(f"({' OR '.join(or_parts)})")

    sql = f"""
        SELECT
            p.photo_id,
            IFNULL(p.media_type, 'photo') AS media_type,
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


def list_timeline(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    if limit <= 0:
        limit = 5000
    rows = conn.execute(
        """
        SELECT
            p.photo_id,
            IFNULL(p.media_type, 'photo') AS media_type,
            p.timestamp,
            p.scene,
            p.location,
            p.source_path,
            GROUP_CONCAT(DISTINCT pp.person_name) AS people
        FROM photos p
        LEFT JOIN photo_people pp ON pp.photo_id = p.photo_id
        GROUP BY p.photo_id
        ORDER BY p.timestamp DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_day_media(
    conn: sqlite3.Connection,
    day: str,
    *,
    person: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """按日历日列出全部媒体（photo/video/audio），不限 outing 聚类。

    day: YYYY-MM-DD（也接受 YYYY-MM / YYYY 前缀）。
    这是 DaySlice 的媒体层；不等于 memory_events 出门事件。
    """
    day_key = str(day or "").strip()[:10]
    if not day_key:
        return []
    if limit <= 0:
        limit = 500

    clauses = ["p.timestamp != ''", "substr(p.timestamp, 1, ?) = ?"]
    params: list[Any] = [len(day_key), day_key]

    if person:
        tokens = person_search_tokens(person)
        if not tokens:
            tokens = [person]
        token_clauses: list[str] = []
        for token in tokens:
            token_clauses.append("(pp2.person_name LIKE ? OR pp2.person_id LIKE ?)")
            pattern = f"%{token}%"
            params.extend([pattern, pattern])
        clauses.append(
            f"""
            EXISTS (
                SELECT 1 FROM photo_people pp2
                WHERE pp2.photo_id = p.photo_id
                  AND ({' OR '.join(token_clauses)})
            )
            """
        )

    rows = conn.execute(
        f"""
        SELECT
            p.photo_id,
            IFNULL(p.media_type, 'photo') AS media_type,
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
        ORDER BY p.timestamp ASC, p.photo_id ASC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def sync_json_file(
    json_path: Path,
    db_path: Path | None = None,
) -> bool:
    """将单条 memory JSON 同步进 SQLite（JSON 为真源）。"""
    from hub.shared.config import MEMORY_DB

    path = Path(json_path)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("同步索引失败 %s: %s", path.name, exc)
        return False

    conn = connect(db_path or MEMORY_DB)
    init_db(conn)
    _upsert_photo(conn, data, path)
    conn.commit()
    conn.close()
    return True
