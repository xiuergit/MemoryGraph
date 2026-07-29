"""补全缺失 timestamp：按同文件夹文件名顺序，用前后邻居同日推断。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from hub.shared.config import JSON_INDENT, MEMORY_DB, MEMORY_DIR, PHOTOS_DIR
from hub.shared.family import enrich_people_with_age
from hub.shared.index_db import sync_json_file

logger = logging.getLogger(__name__)

FillMode = Literal["neighbors-same-day"]


@dataclass
class TimestampFillProposal:
    photo_id: str
    folder: str
    filename: str
    suggested: str  # YYYY-MM-DD
    prev_id: str
    next_id: str
    prev_ts: str
    next_ts: str


@dataclass
class TimestampFillStats:
    proposed: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    proposals: list[TimestampFillProposal] = field(default_factory=list)


_IMG_NUM = re.compile(r"^(?:IMG_|DSC_?|PHOTO_)(\d+)", re.I)


def _photos_rel(path: str) -> tuple[str, str]:
    """Return (folder_rel, filename) under photos/, else (parent, name)."""
    raw = (path or "").replace("\\", "/")
    name = Path(raw).name
    marker = "/photos/"
    if marker in raw:
        rel = raw.split(marker, 1)[1]
        return str(Path(rel).parent).replace("\\", "/"), name
    if raw:
        try:
            rel = str(Path(raw).resolve().relative_to(PHOTOS_DIR.resolve()))
            return str(Path(rel).parent).replace("\\", "/"), name
        except ValueError:
            pass
    return str(Path(raw).parent) if raw else "", name


def _sort_key(filename: str) -> tuple:
    """Prefer camera sequence numbers so IMG_10 < IMG_2 is avoided; else name."""
    stem = Path(filename).stem
    m = _IMG_NUM.match(stem)
    if m:
        return (0, int(m.group(1)), filename.lower())
    return (1, filename.lower())


def _day(ts: str) -> str:
    ts = (ts or "").strip()
    return ts[:10] if len(ts) >= 10 else ""


def iter_memory_records(
    memory_dir: Path | None = None,
) -> list[dict[str, Any]]:
    root = Path(memory_dir or MEMORY_DIR)
    records: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        source_path = str((data.get("source") or {}).get("path") or "")
        folder, filename = _photos_rel(source_path)
        records.append(
            {
                "photo_id": str(data.get("photo_id") or path.stem),
                "timestamp": str(data.get("timestamp") or "").strip(),
                "folder": folder,
                "filename": filename,
                "source_path": source_path,
                "json_path": path,
                "data": data,
            }
        )
    return records


def propose_same_day_neighbor_fills(
    memory_dir: Path | None = None,
) -> list[TimestampFillProposal]:
    """前后邻居（同文件夹、按文件名序）为同一天 → 建议补该日。"""
    by_folder: dict[str, list[dict[str, Any]]] = {}
    for rec in iter_memory_records(memory_dir):
        by_folder.setdefault(rec["folder"] or "(unknown)", []).append(rec)

    proposals: list[TimestampFillProposal] = []
    for folder, items in by_folder.items():
        items.sort(key=lambda r: _sort_key(r["filename"]))
        for i, rec in enumerate(items):
            if rec["timestamp"]:
                continue
            prev = None
            for j in range(i - 1, -1, -1):
                if items[j]["timestamp"]:
                    prev = items[j]
                    break
            nxt = None
            for j in range(i + 1, len(items)):
                if items[j]["timestamp"]:
                    nxt = items[j]
                    break
            if not prev or not nxt:
                continue
            d1, d2 = _day(prev["timestamp"]), _day(nxt["timestamp"])
            if not d1 or d1 != d2:
                continue
            proposals.append(
                TimestampFillProposal(
                    photo_id=rec["photo_id"],
                    folder=folder,
                    filename=rec["filename"],
                    suggested=d1,
                    prev_id=prev["photo_id"],
                    next_id=nxt["photo_id"],
                    prev_ts=prev["timestamp"],
                    next_ts=nxt["timestamp"],
                )
            )
    proposals.sort(key=lambda p: (p.folder, _sort_key(p.filename)))
    return proposals


def apply_timestamp_to_json(
    data: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    """写入 timestamp，刷新人物年龄，并打 manual_edit（防批处理覆盖）。"""
    ts = timestamp.strip()
    if not ts:
        raise ValueError("timestamp 不能为空")
    data["timestamp"] = ts
    people = list(data.get("people") or [])
    if people:
        data["people"] = enrich_people_with_age(people, ts)
    data["manual_edit"] = True
    return data


def apply_timestamp_fill(
    proposal: TimestampFillProposal,
    *,
    memory_dir: Path | None = None,
    db_path: Path | None = None,
) -> None:
    path = Path(memory_dir or MEMORY_DIR) / f"{proposal.photo_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"未找到 JSON: {proposal.photo_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if str(data.get("timestamp") or "").strip():
        raise ValueError(f"已有 timestamp，跳过: {proposal.photo_id}")
    apply_timestamp_to_json(data, proposal.suggested)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=JSON_INDENT) + "\n",
        encoding="utf-8",
    )
    if not sync_json_file(path, db_path or MEMORY_DB):
        raise RuntimeError(f"同步索引失败: {proposal.photo_id}")


def fill_timestamps_from_neighbors(
    *,
    mode: FillMode = "neighbors-same-day",
    dry_run: bool = False,
    memory_dir: Path | None = None,
    db_path: Path | None = None,
    limit: int | None = None,
) -> TimestampFillStats:
    if mode != "neighbors-same-day":
        raise ValueError(f"不支持的 mode: {mode}")

    proposals = propose_same_day_neighbor_fills(memory_dir)
    if limit is not None:
        proposals = proposals[: max(0, limit)]

    stats = TimestampFillStats(proposed=len(proposals), proposals=proposals)
    if dry_run:
        logger.info("dry-run：可补 %s 张（前后邻居同日）", stats.proposed)
        return stats

    for prop in proposals:
        try:
            apply_timestamp_fill(prop, memory_dir=memory_dir, db_path=db_path)
            stats.updated += 1
            logger.info(
                "补时间 %s → %s（夹在 %s / %s）",
                prop.photo_id,
                prop.suggested,
                prop.prev_id,
                prop.next_id,
            )
        except ValueError as exc:
            stats.skipped += 1
            logger.warning("%s", exc)
        except Exception as exc:  # noqa: BLE001 — 单张失败不中断
            stats.failed += 1
            logger.error("补时间失败 %s: %s", prop.photo_id, exc)

    logger.info(
        "补时间完成：更新 %s，跳过 %s，失败 %s（提案 %s）",
        stats.updated,
        stats.skipped,
        stats.failed,
        stats.proposed,
    )
    return stats
