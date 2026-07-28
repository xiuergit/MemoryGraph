"""memory JSON / 人脸库 / SQLite 数据健康统计。"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hub.shared.config import FACES_DIR, MEMORY_DB, MEMORY_DIR
from hub.shared.utils import json_matches_year

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


@dataclass
class MemoryStatsReport:
    total: int = 0
    bad_json: int = 0
    face_detected: int = 0
    people_nonempty: int = 0
    needs_faces: int = 0
    has_location: int = 0
    vision_filled: int = 0
    vision_empty: int = 0
    no_timestamp: int = 0
    manual_edit: int = 0
    manual_location: int = 0
    manual_people: int = 0
    manual_vision: int = 0
    people_ids: Counter[str] = field(default_factory=Counter)
    unk_in_people: int = 0
    by_year: Counter[str] = field(default_factory=Counter)
    vision_empty_by_year: Counter[str] = field(default_factory=Counter)
    needs_faces_by_year: Counter[str] = field(default_factory=Counter)


@dataclass
class FaceRegistryReport:
    registry_count: int = 0
    folder_count: int = 0
    registry_no_folder: list[tuple[str, str]] = field(default_factory=list)
    folder_no_registry: list[tuple[str, int]] = field(default_factory=list)
    empty_folders: list[str] = field(default_factory=list)
    total_ref_images: int = 0


@dataclass
class SqliteReport:
    exists: bool = False
    photos: int = 0
    distinct_people: int = 0
    with_face: int = 0
    top_people: list[tuple[str, int]] = field(default_factory=list)


def _year_key(data: dict[str, Any], json_file: Path) -> str:
    ts = str(data.get("timestamp", ""))
    if len(ts) >= 4 and ts[:4].isdigit():
        return ts[:4]
    for y in ("2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019"):
        if json_matches_year(data, json_file, y):
            return y
    return "?"


def _vision_filled(data: dict[str, Any]) -> bool:
    return bool(
        (data.get("scene") or "").strip()
        or data.get("tags")
        or data.get("objects")
        or data.get("actions")
        or data.get("emotion")
    )


def collect_memory_stats(memory_dir: Path | None = None) -> MemoryStatsReport:
    memory_path = Path(memory_dir or MEMORY_DIR)
    report = MemoryStatsReport()

    for json_file in sorted(memory_path.glob("*.json")):
        report.total += 1
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            report.bad_json += 1
            continue

        year = _year_key(data, json_file)
        report.by_year[year] += 1

        quality = data.get("quality") or {}
        if quality.get("face_detected"):
            report.face_detected += 1

        people = data.get("people") or []
        if people:
            report.people_nonempty += 1
            for person in people:
                pid = str(person.get("id") or person.get("person_id") or "?")
                report.people_ids[pid] += 1
                if pid.startswith("unk_"):
                    report.unk_in_people += 1

        if quality.get("face_detected") and not people:
            report.needs_faces += 1
            report.needs_faces_by_year[year] += 1

        if (data.get("location") or "").strip():
            report.has_location += 1

        if _vision_filled(data):
            report.vision_filled += 1
        else:
            report.vision_empty += 1
            report.vision_empty_by_year[year] += 1

        if not str(data.get("timestamp", "")).strip():
            report.no_timestamp += 1

        if data.get("manual_edit"):
            report.manual_edit += 1

        if data.get("manual_location"):
            report.manual_location += 1

        if data.get("manual_people"):
            report.manual_people += 1

        if data.get("manual_vision"):
            report.manual_vision += 1

    return report


def collect_face_registry_stats(faces_dir: Path | None = None) -> FaceRegistryReport:
    faces_path = Path(faces_dir or FACES_DIR)
    registry_path = faces_path / "registry.json"
    report = FaceRegistryReport()

    registry: dict[str, Any] = {}
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    report.registry_count = len(registry)

    dirs: dict[str, Path] = {}
    for d in faces_path.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            dirs[d.name] = d
    report.folder_count = len(dirs)

    for uid, meta in sorted(registry.items()):
        if uid not in dirs:
            report.registry_no_folder.append((uid, str(meta.get("name", ""))))

    for uid, d in sorted(dirs.items()):
        images = [
            f
            for f in d.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS and not f.name.startswith(".")
        ]
        report.total_ref_images += len(images)
        if not images:
            report.empty_folders.append(uid)
        if uid not in registry:
            report.folder_no_registry.append((uid, len(images)))

    return report


def collect_sqlite_stats(db_path: Path | None = None) -> SqliteReport:
    db = Path(db_path or MEMORY_DB)
    report = SqliteReport()
    if not db.is_file():
        return report

    report.exists = True
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    report.photos = cur.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    report.with_face = cur.execute(
        "SELECT COUNT(*) FROM photos WHERE face_detected = 1"
    ).fetchone()[0]
    report.distinct_people = cur.execute(
        "SELECT COUNT(DISTINCT person_id) FROM photo_people"
    ).fetchone()[0]
    report.top_people = cur.execute(
        "SELECT person_id, COUNT(*) c FROM photo_people "
        "GROUP BY person_id ORDER BY c DESC LIMIT 15"
    ).fetchall()
    conn.close()
    return report


def _pct(n: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{100 * n / total:.1f}%"


def format_memory_stats_report(
    *,
    memory_dir: Path | None = None,
    faces_dir: Path | None = None,
    db_path: Path | None = None,
    year: str = "",
) -> str:
    mem = collect_memory_stats(memory_dir)
    faces = collect_face_registry_stats(faces_dir)
    db = collect_sqlite_stats(db_path)

    lines: list[str] = []
    lines.append("=" * 56)
    lines.append("MemoryGraph 数据健康报告")
    lines.append("=" * 56)

    lines.append("\n## Memory JSON")
    lines.append(f"  总数:           {mem.total}")
    if mem.bad_json:
        lines.append(f"  损坏 JSON:      {mem.bad_json}")
    lines.append(
        f"  face_detected:  {mem.face_detected} ({_pct(mem.face_detected, mem.total)})"
    )
    lines.append(
        f"  people 非空:    {mem.people_nonempty} ({_pct(mem.people_nonempty, mem.total)})"
    )
    lines.append(
        f"  有脸未识别:     {mem.needs_faces} ({_pct(mem.needs_faces, mem.total)})"
    )
    lines.append(
        f"  location:       {mem.has_location} ({_pct(mem.has_location, mem.total)})"
    )
    lines.append(
        f"  vision 已补:    {mem.vision_filled} ({_pct(mem.vision_filled, mem.total)})"
    )
    lines.append(
        f"  vision 待补:    {mem.vision_empty} ({_pct(mem.vision_empty, mem.total)})"
    )
    lines.append(
        f"  无 timestamp:   {mem.no_timestamp} ({_pct(mem.no_timestamp, mem.total)})"
    )
    if mem.manual_edit:
        lines.append(f"  manual_edit:    {mem.manual_edit}")
    if mem.manual_location:
        lines.append(f"  manual_location: {mem.manual_location}")
    if mem.manual_people:
        lines.append(f"  manual_people:  {mem.manual_people}")
    if mem.manual_vision:
        lines.append(f"  manual_vision:  {mem.manual_vision}")
    if mem.unk_in_people:
        lines.append(f"  unk_* 人次:     {mem.unk_in_people}")

    lines.append("\n  按年分布:")
    for y, c in mem.by_year.most_common():
        nf = mem.needs_faces_by_year.get(y, 0)
        ve = mem.vision_empty_by_year.get(y, 0)
        lines.append(f"    {y}: {c} 张 | vision 待补 {ve} | 有脸未识别 {nf}")

    lines.append("\n  people 排名 (前 15):")
    for pid, c in mem.people_ids.most_common(15):
        lines.append(f"    {pid}: {c}")

    lines.append("\n## 人脸库 data/faces")
    lines.append(f"  registry 条目:  {faces.registry_count}")
    lines.append(f"  文件夹:         {faces.folder_count}")
    lines.append(f"  参考照合计:     {faces.total_ref_images} 张")
    if faces.registry_no_folder:
        lines.append(f"\n  registry 无文件夹 ({len(faces.registry_no_folder)}):")
        for uid, name in faces.registry_no_folder[:20]:
            lines.append(f"    {uid} → {name}")
        if len(faces.registry_no_folder) > 20:
            lines.append(f"    … 还有 {len(faces.registry_no_folder) - 20} 条")
    if faces.folder_no_registry:
        lines.append(f"\n  文件夹无 registry ({len(faces.folder_no_registry)}):")
        for uid, n in faces.folder_no_registry:
            lines.append(f"    {uid} ({n} 张)")
    if faces.empty_folders:
        lines.append(f"\n  空文件夹 ({len(faces.empty_folders)}): {', '.join(faces.empty_folders)}")

    lines.append("\n## SQLite 索引")
    if not db.exists:
        lines.append("  (未找到 memorygraph.db，请先 memory_index sync)")
    else:
        lines.append(f"  photos:         {db.photos}")
        lines.append(f"  人物 id 数:     {db.distinct_people}")
        lines.append(f"  face_detected:  {db.with_face}")
        if db.top_people:
            lines.append("  索引 people 排名:")
            for pid, c in db.top_people:
                lines.append(f"    {pid}: {c}")

    if year:
        lines.append(f"\n## {year} 年 vision 续跑提示")
        pending = mem.vision_empty_by_year.get(year, 0)
        lines.append(f"  vision 待补:    {pending} 张")
        lines.append("  命令:")
        lines.append(
            f"    python tools/photo2json/main.py --backfill vision --year {year} --resume"
        )
        lines.append(
            f"    python tools/photo2json/main.py --backfill vision --year {year} "
            f"--has-people --resume --limit 20 --sleep 10"
        )

    lines.append("")
    return "\n".join(lines)
