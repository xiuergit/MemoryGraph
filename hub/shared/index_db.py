"""SQLite 索引：从 data/memory/*.json 同步，JSON 仍为唯一数据源。"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

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
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _photo_row(data: dict[str, Any], json_path: Path, json_mtime: float) -> tuple:
    quality = data.get("quality") or {}
    source = data.get("source") or {}
    location_coords = str(data.get("location_coords", "")).strip()
    return (
        data["photo_id"],
        data.get("timestamp", ""),
        data.get("device_id", ""),
        data.get("scene", ""),
        data.get("location", ""),
        location_coords,
        source.get("path", ""),
        1 if quality.get("face_detected") else 0,
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
        for term in data.get(field) or []:
            if term:
                rows.append((photo_id, str(term), field))
    scene = data.get("scene", "")
    if scene:
        rows.append((photo_id, scene, "scene"))
    return rows


def _upsert_photo(conn: sqlite3.Connection, data: dict[str, Any], json_path: Path) -> None:
    json_mtime = json_path.stat().st_mtime
    photo_id = data["photo_id"]

    conn.execute(
        """
        INSERT INTO photos (
            photo_id, timestamp, device_id, scene, location, location_coords,
            source_path, face_detected, json_path, json_mtime, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(photo_id) DO UPDATE SET
            timestamp = excluded.timestamp,
            device_id = excluded.device_id,
            scene = excluded.scene,
            location = excluded.location,
            location_coords = excluded.location_coords,
            source_path = excluded.source_path,
            face_detected = excluded.face_detected,
            json_path = excluded.json_path,
            json_mtime = excluded.json_mtime,
            indexed_at = excluded.indexed_at
        """,
        _photo_row(data, json_path, json_mtime),
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
            photo_id = data.get("photo_id") or json_path.stem
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
) -> list[dict[str, Any]]:
    """按人物名或关键词搜索照片，按 timestamp 倒序。"""
    clauses = ["1=1"]
    params: list[Any] = []

    if person:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM photo_people pp
                WHERE pp.photo_id = p.photo_id
                  AND (pp.person_name LIKE ? OR pp.person_id LIKE ?)
            )
            """
        )
        pattern = f"%{person}%"
        params.extend([pattern, pattern])

    if query:
        clauses.append(
            """
            (
                p.scene LIKE ?
                OR p.location LIKE ?
                OR EXISTS (
                    SELECT 1 FROM photo_terms t
                    WHERE t.photo_id = p.photo_id AND t.term LIKE ?
                )
            )
            """
        )
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern])

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


def list_timeline(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            p.photo_id,
            p.timestamp,
            p.scene,
            p.location,
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
