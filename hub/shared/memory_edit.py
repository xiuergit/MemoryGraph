"""手改 memory JSON（人物 / 地址 / 语义字段）并同步 SQLite。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from hub.shared.config import JSON_INDENT, MEMORY_DB, MEMORY_DIR
from hub.shared.family import enrich_people_with_age, load_family_members
from hub.shared.index_db import sync_json_file
from hub.shared.schema import (
    Person,
    empty_location_admin,
    location_admin_from_dict,
    refresh_manual_edit_flag,
)

logger = logging.getLogger(__name__)

PeopleMode = Literal["append", "replace"]


class MemoryEditError(ValueError):
    """手改被拒绝或失败。"""


@dataclass
class MemoryEditResult:
    photo_id: str
    updated: bool = False
    error: str = ""


@dataclass
class BatchMemoryEditResult:
    updated: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _json_path(photo_id: str, memory_dir: Path | None = None) -> Path:
    return Path(memory_dir or MEMORY_DIR) / f"{photo_id}.json"


def _load_photo_json(photo_id: str, memory_dir: Path | None = None) -> tuple[Path, dict[str, Any]]:
    path = _json_path(photo_id, memory_dir)
    if not path.is_file():
        raise MemoryEditError(f"未找到 memory JSON: {photo_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise MemoryEditError(f"无法读取 JSON: {photo_id}") from exc
    return path, data


def _write_photo_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=JSON_INDENT) + "\n",
        encoding="utf-8",
    )


def _save_and_sync(
    path: Path,
    data: dict[str, Any],
    *,
    db_path: Path | None = None,
) -> None:
    _write_photo_json(path, data)
    if not sync_json_file(path, db_path or MEMORY_DB):
        raise MemoryEditError(f"写入成功但同步索引失败: {path.stem}")


def build_manual_people(
    person_ids: list[str],
    *,
    timestamp: str = "",
) -> list[Person]:
    """从 registry 构造手标 people；未知 id 报错。"""
    members = load_family_members()
    people: list[Person] = []
    seen: set[str] = set()
    for raw in person_ids:
        pid = raw.strip()
        if not pid or pid in seen:
            continue
        member = members.get(pid)
        if member is None:
            raise MemoryEditError(f"人脸库中不存在: {pid}")
        seen.add(pid)
        people.append(
            Person(
                id=pid,
                name=member.name or pid,
                confidence=1.0,
                role=member.role or "",
                match_method="manual",
            )
        )
    return enrich_people_with_age(people, timestamp)


def merge_people(
    existing: list[dict[str, Any]],
    incoming: list[Person],
    *,
    mode: PeopleMode,
) -> list[Person]:
    if mode == "replace":
        return list(incoming)

    by_id: dict[str, Person] = {}
    for person in existing:
        pid = str(person.get("id") or "").strip()
        if pid:
            by_id[pid] = Person(**dict(person))
    for person in incoming:
        by_id[person["id"]] = person
    return list(by_id.values())


def apply_people_to_photo(
    photo_id: str,
    person_ids: list[str],
    *,
    mode: PeopleMode = "append",
    memory_dir: Path | None = None,
    db_path: Path | None = None,
) -> MemoryEditResult:
    path, data = _load_photo_json(photo_id, memory_dir)
    timestamp = str(data.get("timestamp") or "")
    incoming = build_manual_people(person_ids, timestamp=timestamp)
    existing = list(data.get("people") or [])
    data["people"] = merge_people(existing, incoming, mode=mode)
    data["manual_people"] = True
    refresh_manual_edit_flag(data)
    _save_and_sync(path, data, db_path=db_path)
    return MemoryEditResult(photo_id=photo_id, updated=True)


def apply_location_to_photo(
    photo_id: str,
    location: str,
    *,
    province: str = "",
    city: str = "",
    district: str = "",
    formatted_address: str = "",
    memory_dir: Path | None = None,
    db_path: Path | None = None,
) -> MemoryEditResult:
    loc = location.strip()
    if not loc:
        raise MemoryEditError("地址不能为空")

    path, data = _load_photo_json(photo_id, memory_dir)
    admin = location_admin_from_dict(data.get("location_admin"))
    data["location"] = loc
    data["location_admin"] = {
        "province": province.strip() or admin["province"],
        "city": city.strip() or admin["city"],
        "district": district.strip() or admin["district"],
        "formatted_address": (
            formatted_address.strip()
            or admin["formatted_address"]
            or loc
        ),
    }
    data["manual_location"] = True
    refresh_manual_edit_flag(data)
    _save_and_sync(path, data, db_path=db_path)
    return MemoryEditResult(photo_id=photo_id, updated=True)


def update_photo_fields(
    photo_id: str,
    *,
    person_ids: list[str] | None = None,
    location: str | None = None,
    province: str = "",
    city: str = "",
    district: str = "",
    formatted_address: str = "",
    scene: str | None = None,
    objects: list[str] | None = None,
    actions: list[str] | None = None,
    emotion: list[str] | None = None,
    tags: list[str] | None = None,
    memory_dir: Path | None = None,
    db_path: Path | None = None,
) -> MemoryEditResult:
    """详情页保存：人物为 replace；地址与语义字段按传入覆盖。"""
    path, data = _load_photo_json(photo_id, memory_dir)
    changed = False

    if person_ids is not None:
        timestamp = str(data.get("timestamp") or "")
        data["people"] = build_manual_people(person_ids, timestamp=timestamp)
        data["manual_people"] = True
        changed = True

    if location is not None:
        loc = location.strip()
        admin = empty_location_admin()
        data["location"] = loc
        data["location_admin"] = {
            "province": province.strip(),
            "city": city.strip(),
            "district": district.strip(),
            "formatted_address": formatted_address.strip() or loc,
        }
        if not loc:
            data["location_admin"] = dict(admin)
        data["manual_location"] = True
        changed = True

    vision_touched = False
    for key, value in (
        ("scene", scene),
        ("objects", objects),
        ("actions", actions),
        ("emotion", emotion),
        ("tags", tags),
    ):
        if value is not None:
            data[key] = value
            vision_touched = True
            changed = True
    if vision_touched:
        data["manual_vision"] = True

    if not changed:
        raise MemoryEditError("没有要更新的字段")

    refresh_manual_edit_flag(data)
    _save_and_sync(path, data, db_path=db_path)
    return MemoryEditResult(photo_id=photo_id, updated=True)


def batch_apply_people(
    photo_ids: list[str],
    person_ids: list[str],
    *,
    mode: PeopleMode = "append",
    memory_dir: Path | None = None,
    db_path: Path | None = None,
) -> BatchMemoryEditResult:
    result = BatchMemoryEditResult()
    # 预校验 person_ids，避免半批成功
    build_manual_people(person_ids, timestamp="")
    seen: set[str] = set()
    for raw in photo_ids:
        pid = raw.strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        try:
            apply_people_to_photo(
                pid,
                person_ids,
                mode=mode,
                memory_dir=memory_dir,
                db_path=db_path,
            )
            result.updated.append(pid)
        except MemoryEditError as exc:
            result.failed.append((pid, str(exc)))
            logger.warning("批量标人物失败 %s: %s", pid, exc)
    return result


def batch_apply_location(
    photo_ids: list[str],
    location: str,
    *,
    province: str = "",
    city: str = "",
    district: str = "",
    formatted_address: str = "",
    memory_dir: Path | None = None,
    db_path: Path | None = None,
) -> BatchMemoryEditResult:
    result = BatchMemoryEditResult()
    if not location.strip():
        raise MemoryEditError("地址不能为空")
    seen: set[str] = set()
    for raw in photo_ids:
        pid = raw.strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        try:
            apply_location_to_photo(
                pid,
                location,
                province=province,
                city=city,
                district=district,
                formatted_address=formatted_address,
                memory_dir=memory_dir,
                db_path=db_path,
            )
            result.updated.append(pid)
        except MemoryEditError as exc:
            result.failed.append((pid, str(exc)))
            logger.warning("批量标地址失败 %s: %s", pid, exc)
    return result
