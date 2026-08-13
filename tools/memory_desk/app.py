"""MemoryGraph 本地 Web 小工具：文件搜索 + 记忆问答。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from typing import Any, List, Optional
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from jsonschema import validate as jsonschema_validate, ValidationError
from PIL import Image, ImageOps

from hub.shared.agent import ask as memory_ask
from hub.shared.config import (
    DATA_DIR,
    FACES_DIR,
    MEMORY_DB,
    MEMORY_DIR,
    PHOTOS_DIR,
    PROJECT_ROOT,
    SUPPORTED_VIDEO_EXTENSIONS,
    VIDEO_FRAME_CACHE_DIR,
)
from hub.shared.backfill import backfill_folder
from hub.shared.face import build_face_index, load_face_index, save_face_index
from hub.shared.index_db import (
    connect,
    init_db,
    list_timeline,
    memory_identity,
    search_photos,
    sync_memory_dir,
)
from hub.shared.location_cluster import regeocode_locations_from_memory
from hub.shared.family import person_search_tokens, resolve_person
from hub.shared.file_search import memory_json_for_photo, search_files
from hub.shared.memory_edit import (
    MemoryEditError,
    batch_apply_location,
    batch_apply_people,
    batch_apply_timestamp,
    update_photo_fields,
)
from hub.shared.memory_stats import (
    collect_memory_stats,
    collect_face_registry_stats,
    collect_sqlite_stats,
)
from hub.shared.photo_delete import (
    BatchDeleteResult,
    DeletePhotoResult,
    PhotoDeleteError,
    batch_delete_photo_records,
    delete_photo_record,
)
from hub.shared.photo_links import enrich_photo_dict
from hub.shared.geocode import (
    GEOCODE_CACHE_FILE,
    cache_version,
    delete_geocode_cache_coords,
    geocode_cache_stats,
    list_geocode_cache_grouped,
    list_geocode_cache_regions,
    list_geocode_cache_rows,
    update_geocode_cache_by_location,
    update_geocode_cache_coords,
    sample_photos_for_geocode_cache,
)
from hub.shared.face_enroll import (
    detect_faces_in_photo,
    enroll_photo_face,
    list_registry_people,
)
from hub.shared.face_registry_manage import (
    delete_face_reference,
    get_face_person,
    list_face_people,
    rebuild_face_index,
    update_face_person,
)

app = FastAPI(title="MemoryGraph Desk", version="0.1.0")

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heif", ".heic"}
_VIDEO_EXTS = set(SUPPORTED_VIDEO_EXTENSIONS)
_THUMB_DIR = DATA_DIR / "cache" / "thumbs"


def _resolve_under_data(path_str: str) -> Path:
    raw = Path(path_str).expanduser()
    if not raw.is_absolute():
        raw = (PROJECT_ROOT / raw).resolve()
    else:
        raw = raw.resolve()
    data_root = DATA_DIR.resolve()
    if raw == data_root or str(raw).startswith(str(data_root) + "/"):
        return raw
    raise HTTPException(status_code=403, detail="路径必须在 data/ 下")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


@app.get("/api/search")
def api_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(40, ge=1, le=200),
    photos: bool = True,
    memory: bool = True,
    faces: bool = True,
) -> dict[str, Any]:
    roots: list[tuple[str, Path]] = []
    if photos:
        roots.append(("photos", PHOTOS_DIR))
    if memory:
        roots.append(("memory", MEMORY_DIR))
    if faces:
        roots.append(("faces", FACES_DIR))
    hits = search_files(q, roots=roots, limit=limit)
    items: list[dict[str, Any]] = []
    for hit in hits:
        rel = _rel(hit.path)
        item: dict[str, Any] = {
            "label": hit.root_label,
            "name": hit.path.name,
            "path": str(hit.path),
            "rel": rel,
            "is_image": hit.path.suffix.lower() in _IMAGE_EXTS,
        }
        if hit.root_label == "photos":
            mem = memory_json_for_photo(hit.path)
            if mem:
                item["memory_rel"] = _rel(mem)
                item["memory_path"] = str(mem)
                try:
                    data = json.loads(mem.read_text(encoding="utf-8"))
                    item["photo_id"] = str(data.get("photo_id") or mem.stem)
                except (json.JSONDecodeError, OSError):
                    item["photo_id"] = mem.stem
        elif hit.root_label == "memory":
            item["memory_path"] = str(hit.path)
            item["photo_id"] = hit.path.stem
        item["deletable"] = hit.root_label in {"photos", "memory"}
        items.append(item)
    return {"query": q, "count": len(items), "items": items}


def _item_from_photo_record(photo: dict[str, Any]) -> dict[str, Any]:
    enriched = enrich_photo_dict(photo)
    source = str(enriched.get("source_path") or "")
    photo_path = Path(source) if source else None
    has_file = bool(photo_path and photo_path.is_file())
    pid = str(enriched.get("photo_id") or "")
    memory_path = MEMORY_DIR / f"{pid}.json"
    has_memory = memory_path.is_file()
    return {
        "label": "person",
        "name": pid,
        "path": source if has_file else "",
        "rel": _rel(photo_path) if has_file else pid,
        "is_image": has_file,
        "photo_id": pid,
        "timestamp": enriched.get("timestamp") or "",
        "location": enriched.get("location") or "",
        "people": enriched.get("people") or "",
        "scene": enriched.get("scene") or "",
        "memory_path": str(memory_path) if has_memory else "",
        "memory_rel": _rel(memory_path) if has_memory else "",
        "deletable": True,
    }


@app.get("/api/search-person")
def api_search_person(
    q: str = Query(..., min_length=1),
    limit: int = Query(40, ge=1, le=200),
) -> dict[str, Any]:
    """按 JSON / 索引里的人物名搜索照片（需 memory_index sync）。"""
    name = q.strip()
    resolved = resolve_person(name)
    conn = connect(MEMORY_DB)
    init_db(conn)
    photos = search_photos(conn, person=name, limit=limit)
    conn.close()
    items = [_item_from_photo_record(p) for p in photos]
    return {
        "query": name,
        "resolved": resolved.name if resolved else "",
        "person_id": resolved.person_id if resolved else "",
        "count": len(items),
        "items": items,
    }


def _poster_for_video(video_path: Path) -> Path:
    """视频预览：优先 cache/video_frames/{video_id}.jpg，否则现场抽帧。"""
    from hub.shared.video_meta import extract_keyframe, get_video_id

    video_id = get_video_id(video_path, root=PHOTOS_DIR)
    cached = VIDEO_FRAME_CACHE_DIR / f"{video_id}.jpg"
    if cached.is_file():
        return cached
    return extract_keyframe(video_path, video_id=video_id)


@app.get("/api/preview")
def api_preview(
    path: str = Query(...),
    size: int = Query(0, ge=0, le=1024, description=">0 时返回最长边不超过 size 的 JPEG 缩略图"),
) -> FileResponse:
    target = _resolve_under_data(path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    suffix = target.suffix.lower()
    if suffix in _VIDEO_EXTS:
        try:
            target = _poster_for_video(target)
        except Exception as exc:
            raise HTTPException(
                status_code=415, detail=f"视频预览失败: {exc}"
            ) from exc
    elif suffix not in _IMAGE_EXTS:
        raise HTTPException(status_code=415, detail="仅支持图片或视频预览")
    if size <= 0:
        return FileResponse(target)

    try:
        digest = hashlib.sha1(
            f"{target}:{target.stat().st_mtime_ns}:{size}".encode("utf-8")
        ).hexdigest()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc

    cache_path = _THUMB_DIR / f"{digest}.jpg"
    if not cache_path.is_file():
        try:
            _THUMB_DIR.mkdir(parents=True, exist_ok=True)
            with Image.open(target) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((size, size), Image.Resampling.LANCZOS)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=90, optimize=True)
                cache_path.write_bytes(buf.getvalue())
        except Exception:
            # HEIC 等 Pillow 打不开时回退原图
            return FileResponse(target)

    return FileResponse(cache_path, media_type="image/jpeg")


class OpenRequest(BaseModel):
    path: str
    reveal: bool = False


@app.post("/api/open")
def api_open(body: OpenRequest) -> dict[str, str]:
    target = _resolve_under_data(body.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    opener = "open"
    cmd = [opener, "-R", str(target)] if body.reveal else [opener, str(target)]
    subprocess.run(cmd, check=False)
    return {"status": "ok", "path": str(target)}


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)


@app.post("/api/ask")
def api_ask(body: AskRequest) -> dict[str, Any]:
    """记忆问答：返回模板/LLM 短答 + 结构化 facts（供 Vue 证据区渲染）。"""
    result = memory_ask(body.question.strip(), photo_links=False)
    facts = dict(result.facts)
    facts.pop("_photo_links", None)
    return {
        "intent": result.intent,
        "answer": result.answer,
        "used_llm": result.used_llm,
        "facts": facts,
    }


@app.get("/api/memory/artwork")
def api_memory_artwork(
    person: str = Query(..., min_length=1, description="中文名或 person_id，如 面面"),
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=200),
    works_only: bool = Query(
        True,
        description="True=偏画作特写；False=含正在画画等过程照",
    ),
) -> dict[str, Any]:
    """某人相关画作集：同事件关联，不要求画作照片上标人物。"""
    from hub.shared.query import get_person_artwork

    conn = connect(MEMORY_DB)
    init_db(conn)
    # 多取一点再分页：count 已在结果里；这里直接按 limit 取前 N
    limit = page * page_size
    result = get_person_artwork(
        conn,
        person=person.strip(),
        limit=limit,
        works_only=works_only,
    )
    conn.close()
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=f"未找到成员：{person}")
    photos = result.get("photos") or []
    start = (page - 1) * page_size
    page_items = photos[start : start + page_size]
    return {
        "person": result["person"],
        "works_only": works_only,
        "total": int(result.get("photo_count") or 0),
        "page": page,
        "page_size": page_size,
        "items": page_items,
    }


# ---------- Events / Stories ----------


class EventOverlayBody(BaseModel):
    title: str = ""
    body: str = ""
    tags: list[str] = Field(default_factory=list)


class StoryLinkBody(BaseModel):
    link_type: str
    link_id: str
    sort_order: int = 0


class StoryBody(BaseModel):
    title: str = Field(..., min_length=1)
    body: str = ""
    time_start: str = ""
    time_end: str = ""
    people: list[str] = Field(default_factory=list)
    links: list[StoryLinkBody] = Field(default_factory=list)


class StoryUpdateBody(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    people: Optional[List[str]] = None
    links: Optional[List[StoryLinkBody]] = None


StoryLinkBody.model_rebuild()
StoryBody.model_rebuild()
StoryUpdateBody.model_rebuild()


@app.post("/api/events/sync")
def api_events_sync() -> dict[str, Any]:
    from hub.shared.events import sync_events

    conn = connect(MEMORY_DB)
    init_db(conn)
    stats = sync_events(conn)
    conn.close()
    return {
        "status": "ok",
        "outing_events": stats.outing_events,
        "home_events": stats.home_events,
        "untimed_location_events": stats.untimed_location_events,
        "events": stats.events,
        "photos_in_events": stats.photos_in_events,
        "photos_with_ts": stats.photos_with_ts,
        "overlays_rematched": stats.overlays_rematched,
        "overlays_orphaned": stats.overlays_orphaned,
    }


@app.get("/api/events/stats")
def api_events_stats() -> dict[str, Any]:
    from hub.shared.events import get_event_stats

    conn = connect(MEMORY_DB)
    init_db(conn)
    stats = get_event_stats(conn)
    conn.close()
    return stats


@app.get("/api/events")
def api_events_list(
    day: str = "",
    location: str = "",
    person: str = "",
    keyword: str = "",
    include_home: bool = False,
    time_scope: str = Query(
        "all",
        description="all | dated | untimed（无时间按地点聚合）",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    from hub.shared.events import count_events, list_events, list_orphan_overlays

    scope = (time_scope or "all").strip().lower()
    if scope not in ("all", "dated", "untimed"):
        raise HTTPException(status_code=400, detail="time_scope 须为 all / dated / untimed")

    conn = connect(MEMORY_DB)
    init_db(conn)
    items = list_events(
        conn,
        day=day.strip(),
        location=location.strip(),
        person=person.strip(),
        keyword=keyword.strip(),
        include_home=include_home,
        time_scope=scope,
        limit=limit,
        offset=offset,
    )
    total = count_events(
        conn,
        day=day.strip(),
        location=location.strip(),
        person=person.strip(),
        keyword=keyword.strip(),
        include_home=include_home,
        time_scope=scope,
    )
    orphans = list_orphan_overlays(conn)
    conn.close()
    return {
        "total": total,
        "items": items,
        "offset": offset,
        "limit": limit,
        "orphan_overlays": orphans,
    }


@app.get("/api/events/locations")
def api_events_locations(include_home: bool = True) -> dict[str, Any]:
    from hub.shared.events import list_event_locations

    conn = connect(MEMORY_DB)
    init_db(conn)
    items = list_event_locations(conn, include_home=include_home)
    conn.close()
    return {"items": items, "count": len(items)}


@app.get("/api/events/years")
def api_events_years(include_home: bool = True) -> dict[str, Any]:
    from hub.shared.events import list_event_years

    conn = connect(MEMORY_DB)
    init_db(conn)
    years = list_event_years(conn, include_home=include_home)
    conn.close()
    return {"years": years}


@app.get("/api/events/{event_id}")
def api_event_detail(event_id: str) -> dict[str, Any]:
    from hub.shared.events import get_event
    from hub.shared.photo_links import enrich_photo_dict

    conn = connect(MEMORY_DB)
    init_db(conn)
    data = get_event(conn, event_id)
    conn.close()
    if data is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    photos = [enrich_photo_dict(p) for p in data.get("photos") or []]
    data["photos"] = photos
    return data


@app.get("/api/events/{event_id}/overlay")
def api_event_overlay_get(event_id: str) -> dict[str, Any]:
    from hub.shared.events import get_event

    conn = connect(MEMORY_DB)
    init_db(conn)
    data = get_event(conn, event_id)
    conn.close()
    if data is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    return {"event_id": event_id, "overlay": data.get("overlay")}


@app.put("/api/events/{event_id}/overlay")
def api_event_overlay_put(event_id: str, body: EventOverlayBody) -> dict[str, Any]:
    from hub.shared.events import upsert_event_overlay

    conn = connect(MEMORY_DB)
    init_db(conn)
    try:
        overlay = upsert_event_overlay(
            conn,
            event_id,
            title=body.title,
            body=body.body,
            tags=body.tags,
        )
    except KeyError as exc:
        conn.close()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    conn.close()
    return {"status": "ok", "overlay": overlay}


@app.delete("/api/events/{event_id}/overlay")
def api_event_overlay_delete(event_id: str) -> dict[str, Any]:
    from hub.shared.events import delete_event_overlay

    conn = connect(MEMORY_DB)
    init_db(conn)
    ok = delete_event_overlay(conn, event_id)
    conn.close()
    if not ok:
        raise HTTPException(status_code=404, detail="无备注可删")
    return {"status": "ok"}


@app.get("/api/stories")
def api_stories_list(
    q: str = "",
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    from hub.shared.events import list_stories, search_stories

    conn = connect(MEMORY_DB)
    init_db(conn)
    items = search_stories(conn, q, limit=limit) if q.strip() else list_stories(conn, limit=limit)
    conn.close()
    return {"items": items, "count": len(items)}


@app.post("/api/stories")
def api_stories_create(body: StoryBody) -> dict[str, Any]:
    from hub.shared.events import create_story

    conn = connect(MEMORY_DB)
    init_db(conn)
    try:
        story = create_story(
            conn,
            title=body.title,
            body=body.body,
            time_start=body.time_start,
            time_end=body.time_end,
            people=body.people,
            links=[link.model_dump() for link in body.links],
        )
    except Exception as exc:
        conn.close()
        raise HTTPException(status_code=500, detail=f"创建故事失败: {exc}") from exc
    conn.close()
    return {"status": "ok", "story": story}


@app.get("/api/stories/{story_id}")
def api_story_detail(story_id: str) -> dict[str, Any]:
    from hub.shared.events import get_story

    conn = connect(MEMORY_DB)
    init_db(conn)
    story = get_story(conn, story_id)
    conn.close()
    if story is None:
        raise HTTPException(status_code=404, detail="故事不存在")
    return story


@app.put("/api/stories/{story_id}")
def api_story_update(story_id: str, body: StoryUpdateBody) -> dict[str, Any]:
    from hub.shared.events import update_story

    conn = connect(MEMORY_DB)
    init_db(conn)
    try:
        story = update_story(
            conn,
            story_id,
            title=body.title,
            body=body.body,
            time_start=body.time_start,
            time_end=body.time_end,
            people=body.people,
            links=[link.model_dump() for link in body.links] if body.links is not None else None,
        )
    except KeyError as exc:
        conn.close()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    conn.close()
    return {"status": "ok", "story": story}


@app.delete("/api/stories/{story_id}")
def api_story_delete(story_id: str) -> dict[str, Any]:
    from hub.shared.events import delete_story

    conn = connect(MEMORY_DB)
    init_db(conn)
    ok = delete_story(conn, story_id)
    conn.close()
    if not ok:
        raise HTTPException(status_code=404, detail="故事不存在")
    return {"status": "ok"}


class DeleteRequest(BaseModel):
    photo_id: str = ""
    path: str = ""
    memory_path: str = ""


class BatchDeleteRequest(BaseModel):
    photo_ids: list[str] = Field(..., min_length=1)


def _delete_result_payload(result: DeletePhotoResult) -> dict[str, Any]:
    return {
        "status": "ok",
        "photo_id": result.photo_id,
        "photo_trashed": result.photo_trashed,
        "memory_trashed": result.memory_trashed,
        "index_removed": result.index_removed,
    }


@app.post("/api/delete")
def api_delete(body: DeleteRequest) -> dict[str, Any]:
    if not body.photo_id and not body.path and not body.memory_path:
        raise HTTPException(status_code=400, detail="需要 photo_id、path 或 memory_path")
    try:
        result = delete_photo_record(
            photo_id=body.photo_id.strip(),
            photo_path=body.path.strip(),
            memory_path=body.memory_path.strip(),
        )
    except PhotoDeleteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _delete_result_payload(result)


def _batch_delete_payload(result: BatchDeleteResult) -> dict[str, Any]:
    return {
        "deleted_count": len(result.deleted),
        "failed_count": len(result.failed),
        "deleted": [_delete_result_payload(item) for item in result.deleted],
        "failed": [
            {"photo_id": photo_id, "error": error}
            for photo_id, error in result.failed
        ],
    }


@app.post("/api/delete/batch")
def api_delete_batch(body: BatchDeleteRequest) -> dict[str, Any]:
    photo_ids = [item.strip() for item in body.photo_ids if item.strip()]
    if not photo_ids:
        raise HTTPException(status_code=400, detail="photo_ids 不能为空")
    return _batch_delete_payload(batch_delete_photo_records(photo_ids))


@app.get("/api/dedup/report")
def api_dedup_report(
    year: str = Query("", description="年份前缀，如 2024；空=全库"),
    kind: str = Query("all", description="all | hash | burst"),
    burst_seconds: int = Query(3, ge=0, le=60),
    limit: int = Query(50, ge=0, le=500, description="最多返回组数；0=不截断"),
    score_quality: bool = Query(
        True,
        description="连拍/近相似组内计算清晰度/曝光，KEEP 优先更清晰",
    ),
    near_hamming: int = Query(10, ge=0, le=32, description="无时间近哈希最大汉明距离"),
) -> dict[str, Any]:
    """去重候选报告（只扫描，不删除）。"""
    from hub.shared.dedup import build_dedup_report, report_to_dict

    kind_norm = (kind or "all").strip().lower()
    if kind_norm not in ("all", "hash", "burst"):
        raise HTTPException(status_code=400, detail="kind 须为 all / hash / burst")
    report = build_dedup_report(
        year=year.strip(),
        burst_seconds=burst_seconds,
        include_hash=kind_norm in ("all", "hash"),
        include_burst=kind_norm in ("all", "burst"),
        limit_groups=limit,
        score_quality=score_quality,
        near_hamming=near_hamming,
        include_near=True,
    )
    payload = report_to_dict(report)
    payload["status"] = "ok"
    payload["kind"] = kind_norm
    payload["score_quality"] = score_quality
    return payload


@app.get("/api/memory/locations")
def api_memory_locations() -> dict[str, Any]:
    """短地名列表，并附带库内最常见的省市区与缓存中的详细地址。按照片数降序。"""
    conn = connect(MEMORY_DB)
    init_db(conn)
    rows = conn.execute(
        """
        SELECT
            location,
            location_province AS province,
            location_city AS city,
            location_district AS district,
            COUNT(*) AS cnt
        FROM photos
        WHERE location != ''
        GROUP BY location, location_province, location_city, location_district
        """
    ).fetchall()
    conn.close()

    best: dict[str, dict[str, Any]] = {}
    location_counts: dict[str, int] = {}
    for row in rows:
        loc = str(row["location"] or "").strip()
        if not loc:
            continue
        cnt = int(row["cnt"] or 0)
        location_counts[loc] = location_counts.get(loc, 0) + cnt
        province = str(row["province"] or "")
        city = str(row["city"] or "")
        district = str(row["district"] or "")
        admin_score = (
            (1 if province else 0) + (1 if city else 0) + (1 if district else 0)
        )
        score = admin_score * 1_000_000 + cnt
        prev = best.get(loc)
        if prev is None or score > int(prev.get("_score", 0)):
            best[loc] = {
                "location": loc,
                "province": province,
                "city": city,
                "district": district,
                "formatted_address": "",
                "_score": score,
            }

    try:
        from hub.shared.geocode import list_geocode_cache_grouped

        for item in list_geocode_cache_grouped():
            loc = str(item.get("location") or "").strip()
            if not loc or loc not in best:
                continue
            entry = best[loc]
            fa = str(item.get("formatted_address") or "").strip()
            if fa and not entry["formatted_address"]:
                entry["formatted_address"] = fa
            if not entry["province"] and item.get("province"):
                entry["province"] = str(item.get("province") or "")
            if not entry["city"] and item.get("city"):
                entry["city"] = str(item.get("city") or "")
            if not entry["district"] and item.get("district"):
                entry["district"] = str(item.get("district") or "")
    except Exception:
        pass

    items = []
    for loc, entry in best.items():
        entry.pop("_score", None)
        entry["count"] = location_counts.get(loc, 0)
        if not entry["formatted_address"]:
            entry["formatted_address"] = loc
        items.append(entry)
    items.sort(key=lambda item: (-int(item.get("count") or 0), item["location"]))

    return {
        "locations": [item["location"] for item in items],
        "items": items,
    }


def _folder_from_source_path(source: str) -> str:
    """data/photos/ 下的相对目录，如 2026/5-8；找不到则空串。"""
    if not source:
        return ""
    norm = source.replace("\\", "/")
    if "/photos/" not in norm:
        return ""
    rel = norm.split("/photos/", 1)[1]
    parent = str(Path(rel).parent)
    if not parent or parent == ".":
        return ""
    return parent


@app.get("/api/memory/years")
def api_memory_years() -> dict[str, Any]:
    """从 timestamp 提取有数据的年份（倒序）。"""
    conn = connect(MEMORY_DB)
    init_db(conn)
    rows = conn.execute(
        """
        SELECT DISTINCT substr(timestamp, 1, 4) AS year
        FROM photos
        WHERE length(timestamp) >= 4
          AND substr(timestamp, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'
        ORDER BY year DESC
        """
    ).fetchall()
    conn.close()
    years = [row["year"] for row in rows]
    return {"years": years}


@app.get("/api/memory/folders")
def api_memory_folders() -> dict[str, Any]:
    """列出 photos/ 下出现过的相对文件夹（含中间层，如 2026、2026/5-8）。"""
    conn = connect(MEMORY_DB)
    init_db(conn)
    rows = conn.execute(
        """
        SELECT source_path FROM photos
        WHERE source_path IS NOT NULL AND source_path != ''
        """
    ).fetchall()
    conn.close()

    folders: set[str] = set()
    for row in rows:
        folder = _folder_from_source_path(str(row["source_path"] or ""))
        if not folder:
            continue
        parts = Path(folder).parts
        for i in range(1, len(parts) + 1):
            folders.add(str(Path(*parts[:i])))

    ordered = sorted(
        folders,
        key=lambda f: (f.split("/")[0], f.count("/"), f),
        reverse=True,
    )
    return {"folders": ordered, "total": len(ordered)}


@app.get("/api/memory/list")
def api_memory_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    search: str = Query("", description="搜索 photo_id/timestamp/location/people/scene/路径"),
    location: str = Query("", description="按地址筛选"),
    date_from: str = Query("", description="起始日期 YYYY-MM-DD"),
    date_to: str = Query("", description="结束日期 YYYY-MM-DD"),
    year: str = Query("", description="按年筛选，如 2024"),
    folder: str = Query("", description="按 photos/ 下相对文件夹筛选，如 2026/5-8"),
    sort: str = Query("desc", description="排序: desc|asc|folder"),
    person: str = Query("", description="按人物筛选（中文名或 person_id）；__EMPTY__ 表示无人物"),
    face: str = Query("", description="人脸筛选: yes|no|needs_faces"),
    people_count: str = Query(
        "",
        description="人物数量筛选：1=仅单人照（排除合照）",
    ),
    timestamp: str = Query("", description="时间筛选: empty=无时间"),
    media_type: str = Query(
        "",
        description="媒体类型: photo|video|audio；空=全部",
    ),
    context_neighbors: bool = Query(
        False,
        description="与 timestamp=empty 联用：按文件夹顺序插入前后有时间的邻居，便于对照",
    ),
) -> dict[str, Any]:
    conn = connect(MEMORY_DB)
    init_db(conn)
    offset = (page - 1) * page_size

    clauses = ["1=1"]
    params: list[Any] = []

    media_type_filter = media_type.strip().lower()
    if media_type_filter in ("photo", "video", "audio"):
        clauses.append("IFNULL(p.media_type, 'photo') = ?")
        params.append(media_type_filter)

    if location:
        if location == "__EMPTY__":
            clauses.append("(p.location = '' OR p.location IS NULL)")
        else:
            clauses.append("p.location = ?")
            params.append(location)

    year = year.strip()
    if year and year.isdigit() and len(year) == 4:
        clauses.append("substr(p.timestamp, 1, 4) = ?")
        params.append(year)

    folder = folder.strip().strip("/").replace("\\", "/")
    if folder:
        # 匹配 …/photos/{folder}/… 或恰好落在该目录（容错）
        clauses.append(
            """
            (
                replace(p.source_path, '\\', '/') LIKE ?
                OR replace(p.source_path, '\\', '/') LIKE ?
            )
            """
        )
        params.extend(
            [
                f"%/photos/{folder}/%",
                f"%/photos/{folder}",
            ]
        )

    if date_from:
        clauses.append("p.timestamp >= ?")
        params.append(f"{date_from} 00:00:00")
    if date_to:
        clauses.append("p.timestamp <= ?")
        params.append(f"{date_to} 23:59:59")

    person = person.strip()
    if person == "__EMPTY__":
        clauses.append(
            """
            NOT EXISTS (
                SELECT 1 FROM photo_people pp_filter
                WHERE pp_filter.photo_id = p.photo_id
            )
            """
        )
    elif person:
        tokens = person_search_tokens(person)
        if not tokens:
            tokens = [person]
        token_clauses: list[str] = []
        for token in tokens:
            token_clauses.append("(pp_filter.person_name LIKE ? OR pp_filter.person_id LIKE ?)")
            pattern = f"%{token}%"
            params.extend([pattern, pattern])
        clauses.append(
            f"""
            EXISTS (
                SELECT 1 FROM photo_people pp_filter
                WHERE pp_filter.photo_id = p.photo_id
                  AND ({' OR '.join(token_clauses)})
            )
            """
        )

    people_count = people_count.strip()
    if people_count == "1":
        # 按不同 person_id 计数；同一人多行不会误伤，多人合照必排除
        clauses.append(
            """
            (
                SELECT COUNT(DISTINCT CASE
                    WHEN IFNULL(ppc.person_id, '') != '' THEN ppc.person_id
                    ELSE ppc.person_name
                END)
                FROM photo_people ppc
                WHERE ppc.photo_id = p.photo_id
                  AND (IFNULL(ppc.person_id, '') != '' OR IFNULL(ppc.person_name, '') != '')
            ) = 1
            """
        )

    face = face.strip().lower()
    if face == "yes":
        clauses.append("p.face_detected = 1")
    elif face == "no":
        clauses.append("p.face_detected = 0")
    elif face == "needs_faces":
        clauses.append("p.face_detected = 1")
        clauses.append(
            """
            NOT EXISTS (
                SELECT 1 FROM photo_people pp_nf
                WHERE pp_nf.photo_id = p.photo_id
            )
            """
        )

    timestamp_filter = timestamp.strip().lower()
    empty_clause = "(p.timestamp = '' OR p.timestamp IS NULL)"
    if timestamp_filter == "empty" and not context_neighbors:
        clauses.append(empty_clause)

    if search:
        pattern = f"%{search}%"
        clauses.append(
            """
            (
                p.photo_id LIKE ?
                OR p.timestamp LIKE ?
                OR p.location LIKE ?
                OR p.scene LIKE ?
                OR p.source_path LIKE ?
                OR EXISTS (
                    SELECT 1 FROM photo_people pp
                    WHERE pp.photo_id = p.photo_id AND pp.person_name LIKE ?
                )
            )
            """
        )
        params.extend([pattern, pattern, pattern, pattern, pattern, pattern])

    def _row_to_item(row_dict: dict[str, Any], *, is_context: bool = False) -> dict[str, Any]:
        photo_path = Path(row_dict.get("source_path", "") or "")
        has_file = photo_path.is_file()
        source = str(row_dict.get("source_path") or "")
        item_folder = _folder_from_source_path(source)
        if not item_folder and source:
            item_folder = str(Path(source).parent.name)
        return {
            "photo_id": row_dict["photo_id"],
            "media_type": row_dict.get("media_type") or "photo",
            "timestamp": row_dict["timestamp"] or "",
            "scene": row_dict["scene"],
            "location": row_dict["location"],
            "location_province": row_dict["location_province"] or "",
            "location_city": row_dict["location_city"] or "",
            "location_district": row_dict["location_district"] or "",
            "people": row_dict["people"] or "",
            "face_detected": bool(row_dict["face_detected"]),
            "weather_condition": row_dict.get("weather_condition") or "",
            "weather_temp_mean_c": row_dict.get("weather_temp_mean_c"),
            "weather_temp_min_c": row_dict.get("weather_temp_min_c"),
            "weather_temp_max_c": row_dict.get("weather_temp_max_c"),
            "has_file": has_file,
            "source_path": str(photo_path) if has_file else "",
            "folder": item_folder,
            "is_context": is_context,
        }

    select_sql = f"""
        SELECT
            p.photo_id,
            IFNULL(p.media_type, 'photo') AS media_type,
            p.timestamp,
            p.scene,
            p.location,
            p.location_province,
            p.location_city,
            p.location_district,
            p.source_path,
            p.face_detected,
            p.weather_condition,
            p.weather_temp_mean_c,
            p.weather_temp_min_c,
            p.weather_temp_max_c,
            GROUP_CONCAT(DISTINCT pp.person_name) AS people
        FROM photos p
        LEFT JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE {{where}}
        GROUP BY p.photo_id
    """

    sort_key = sort.strip().lower()
    if context_neighbors and timestamp_filter == "empty":
        # 同筛选条件、不限空时间：按路径排序后，给每张空时间照片夹入前后邻居
        where = " AND ".join(clauses)
        rows = conn.execute(select_sql.format(where=where), params).fetchall()
        conn.close()
        ordered = sorted(
            (dict(r) for r in rows),
            key=lambda r: ((r.get("source_path") or ""), r["photo_id"]),
        )
        by_folder: dict[str, list[dict[str, Any]]] = {}
        for row in ordered:
            item = _row_to_item(row)
            by_folder.setdefault(item["folder"] or "(unknown)", []).append(
                {**row, "_item": item}
            )

        expanded: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _folder, group in sorted(by_folder.items(), key=lambda kv: kv[0]):
            for i, row in enumerate(group):
                ts = (row.get("timestamp") or "").strip()
                if ts:
                    continue
                indices = {i}
                if i > 0:
                    indices.add(i - 1)
                if i + 1 < len(group):
                    indices.add(i + 1)
                # 若邻居仍为空，再向外扩一格有时间的（最多各找 1 个有时间）
                for j in range(i - 1, -1, -1):
                    indices.add(j)
                    if (group[j].get("timestamp") or "").strip():
                        break
                for j in range(i + 1, len(group)):
                    indices.add(j)
                    if (group[j].get("timestamp") or "").strip():
                        break
                for j in sorted(indices):
                    pid = group[j]["photo_id"]
                    if pid in seen:
                        continue
                    seen.add(pid)
                    is_empty = not (group[j].get("timestamp") or "").strip()
                    expanded.append(_row_to_item(group[j], is_context=not is_empty))

        total = len(expanded)
        page_rows = expanded[offset : offset + page_size]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": page_rows,
        }

    total_sql = f"SELECT COUNT(DISTINCT p.photo_id) FROM photos p WHERE {' AND '.join(clauses)}"
    total = conn.execute(total_sql, params).fetchone()[0]

    if sort_key == "folder":
        order_sql = "p.source_path ASC, p.photo_id ASC"
    elif sort_key == "asc":
        order_sql = (
            "CASE WHEN p.timestamp = '' OR p.timestamp IS NULL THEN 1 ELSE 0 END, "
            "p.timestamp ASC"
        )
    else:
        order_sql = (
            "CASE WHEN p.timestamp = '' OR p.timestamp IS NULL THEN 1 ELSE 0 END, "
            "p.timestamp DESC"
        )

    sql = select_sql.format(where=" AND ".join(clauses)) + f"""
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(sql, [*params, page_size, offset]).fetchall()
    conn.close()

    items = [_row_to_item(dict(row)) for row in rows]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@app.get("/api/memory/dates")
def api_memory_dates() -> dict[str, Any]:
    conn = connect(MEMORY_DB)
    init_db(conn)
    rows = conn.execute(
        "SELECT DISTINCT DATE(timestamp) as date FROM photos WHERE timestamp != '' ORDER BY date DESC"
    ).fetchall()
    conn.close()
    dates = [row["date"] for row in rows]
    return {"dates": dates}


@app.post("/api/memory/batch-update-location")
def api_batch_update_location(
    date_from: str = Body(None, description="起始日期 YYYY-MM-DD"),
    date_to: str = Body(None, description="结束日期 YYYY-MM-DD"),
    old_location: str = Body(None, description="原地址"),
    new_location: str = Body(..., description="新地址"),
    province: str = Body("", description="省"),
    city: str = Body("", description="市"),
    district: str = Body("", description="区"),
    formatted_address: str = Body("", description="详细地址"),
) -> dict[str, Any]:
    clauses = []
    params = []

    if date_from:
        clauses.append("timestamp >= ?")
        params.append(f"{date_from} 00:00:00")
    if date_to:
        clauses.append("timestamp <= ?")
        params.append(f"{date_to} 23:59:59")
    if old_location:
        if old_location == "__EMPTY__":
            clauses.append("(location = '' OR location IS NULL)")
        else:
            clauses.append("location = ?")
            params.append(old_location)

    if not clauses:
        raise HTTPException(status_code=400, detail="请至少选择一个筛选条件")

    if not new_location.strip():
        raise HTTPException(status_code=400, detail="新地址不能为空")

    conn = connect(MEMORY_DB)
    init_db(conn)

    where_clause = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT photo_id FROM photos WHERE {where_clause}", params
    ).fetchall()
    photo_ids = [row["photo_id"] for row in rows]
    conn.close()

    if not photo_ids:
        return {"updated": 0, "photo_ids": [], "failed": [], "message": "没有匹配的记录"}

    # 走 memory_edit：写 JSON + 正确同步 SQLite（province/city/district 列）
    try:
        result = batch_apply_location(
            photo_ids,
            new_location,
            province=province,
            city=city,
            district=district,
            formatted_address=formatted_address,
        )
    except MemoryEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "updated": len(result.updated),
        "failed": [f"{pid}: {err}" for pid, err in result.failed],
        "photo_ids": result.updated,
        "message": f"成功更新 {len(result.updated)} 条记录",
    }


class BatchPeopleByIdsRequest(BaseModel):
    photo_ids: list[str] = Field(..., min_length=1)
    person_ids: list[str] = Field(..., min_length=1)
    mode: str = Field("append", description="append|replace")


class BatchLocationByIdsRequest(BaseModel):
    photo_ids: list[str] = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    province: str = ""
    city: str = ""
    district: str = ""
    formatted_address: str = ""


class BatchTimestampByIdsRequest(BaseModel):
    photo_ids: list[str] = Field(..., min_length=1)
    timestamp: str = Field(..., min_length=1, description="YYYY-MM-DD 或完整 ISO 时间")
    only_if_empty: bool = False


class MemoryUpdateRequest(BaseModel):
    photo_id: str = Field(..., min_length=1)
    person_ids: Optional[List[str]] = None
    location: Optional[str] = None
    province: str = ""
    city: str = ""
    district: str = ""
    formatted_address: str = ""
    scene: Optional[str] = None
    objects: Optional[List[str]] = None
    actions: Optional[List[str]] = None
    emotion: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    timestamp: Optional[str] = None


def _batch_edit_payload(updated: list[str], failed: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "updated": len(updated),
        "failed_count": len(failed),
        "photo_ids": updated,
        "failed": [{"photo_id": pid, "error": err} for pid, err in failed],
        "message": f"成功更新 {len(updated)} 条",
    }


@app.post("/api/memory/batch-update-people")
def api_batch_update_people(body: BatchPeopleByIdsRequest) -> dict[str, Any]:
    mode = body.mode.strip().lower()
    if mode not in ("append", "replace"):
        raise HTTPException(status_code=400, detail="mode 须为 append 或 replace")
    try:
        result = batch_apply_people(body.photo_ids, body.person_ids, mode=mode)  # type: ignore[arg-type]
    except MemoryEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _batch_edit_payload(result.updated, result.failed)


@app.post("/api/memory/batch-update-location-by-ids")
def api_batch_update_location_by_ids(body: BatchLocationByIdsRequest) -> dict[str, Any]:
    try:
        result = batch_apply_location(
            body.photo_ids,
            body.location,
            province=body.province,
            city=body.city,
            district=body.district,
            formatted_address=body.formatted_address,
        )
    except MemoryEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _batch_edit_payload(result.updated, result.failed)


@app.post("/api/memory/batch-update-timestamp")
def api_batch_update_timestamp(body: BatchTimestampByIdsRequest) -> dict[str, Any]:
    try:
        result = batch_apply_timestamp(
            body.photo_ids,
            body.timestamp,
            only_if_empty=body.only_if_empty,
        )
    except MemoryEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _batch_edit_payload(result.updated, result.failed)


@app.put("/api/memory/update")
def api_memory_update(body: MemoryUpdateRequest) -> dict[str, Any]:
    try:
        update_photo_fields(
            body.photo_id.strip(),
            person_ids=body.person_ids,
            location=body.location,
            province=body.province,
            city=body.city,
            district=body.district,
            formatted_address=body.formatted_address,
            scene=body.scene,
            objects=body.objects,
            actions=body.actions,
            emotion=body.emotion,
            tags=body.tags,
            timestamp=body.timestamp,
        )
    except MemoryEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    json_path = MEMORY_DIR / f"{body.photo_id.strip()}.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return {"status": "ok", "photo_id": body.photo_id.strip(), "data": data}


@app.get("/api/memory/detail")
def api_memory_detail(photo_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    json_path = MEMORY_DIR / f"{photo_id}.json"
    if not json_path.is_file():
        raise HTTPException(status_code=404, detail=f"未找到 memory JSON: {photo_id}")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"JSON 解析失败: {exc}") from exc

    try:
        _mid, media_type = memory_identity(data)
    except KeyError:
        media_type = "photo"

    source = data.get("source") or {}
    photo_path = Path(source.get("path", ""))
    has_file = photo_path.is_file()

    return {
        "photo_id": photo_id,
        "media_type": media_type,
        "json_path": str(json_path),
        "has_photo_file": has_file,
        "source_path": str(photo_path) if has_file else "",
        "data": data,
    }


def _load_schema() -> dict[str, Any]:
    schema_path = PROJECT_ROOT / "schemas" / "photo.v1.json"
    with schema_path.open(encoding="utf-8") as fh:
        return json.load(fh)


@app.get("/api/memory/validate")
def api_memory_validate(
    photo_id: str = Query("", description="单个 photo_id；不传则批量验证所有"),
) -> dict[str, Any]:
    schema = _load_schema()
    results = []

    if photo_id:
        json_files = [MEMORY_DIR / f"{photo_id}.json"]
    else:
        json_files = sorted(MEMORY_DIR.glob("*.json"))

    for json_path in json_files:
        item = {"photo_id": json_path.stem, "valid": True, "errors": []}
        if not json_path.is_file():
            item["valid"] = False
            item["errors"].append("文件不存在")
            results.append(item)
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            item["valid"] = False
            item["errors"].append(f"JSON 解析错误: {exc}")
            results.append(item)
            continue

        try:
            jsonschema_validate(instance=data, schema=schema)
        except ValidationError as exc:
            item["valid"] = False
            item["errors"].append(str(exc))

        results.append(item)

    valid_count = sum(1 for r in results if r["valid"])
    return {
        "total": len(results),
        "valid": valid_count,
        "invalid": len(results) - valid_count,
        "results": results,
    }


@app.get("/api/memory/stats")
def api_memory_stats() -> dict[str, Any]:
    mem = collect_memory_stats()
    faces = collect_face_registry_stats()
    db = collect_sqlite_stats()

    return {
        "memory": {
            "total": mem.total,
            "bad_json": mem.bad_json,
            "face_detected": mem.face_detected,
            "people_nonempty": mem.people_nonempty,
            "needs_faces": mem.needs_faces,
            "has_location": mem.has_location,
            "vision_filled": mem.vision_filled,
            "vision_empty": mem.vision_empty,
            "no_timestamp": mem.no_timestamp,
            "manual_edit": mem.manual_edit,
            "manual_location": mem.manual_location,
            "manual_people": mem.manual_people,
            "manual_vision": mem.manual_vision,
            "unk_in_people": mem.unk_in_people,
            "by_year": dict(mem.by_year),
            "vision_empty_by_year": dict(mem.vision_empty_by_year),
            "needs_faces_by_year": dict(mem.needs_faces_by_year),
            "people_ids": dict(mem.people_ids.most_common(20)),
        },
        "faces": {
            "registry_count": faces.registry_count,
            "folder_count": faces.folder_count,
            "total_ref_images": faces.total_ref_images,
            "registry_no_folder": faces.registry_no_folder,
            "folder_no_registry": faces.folder_no_registry,
            "empty_folders": faces.empty_folders,
        },
        "sqlite": {
            "exists": db.exists,
            "photos": db.photos,
            "distinct_people": db.distinct_people,
            "with_face": db.with_face,
            "top_people": [{"person_id": pid, "count": c} for pid, c in db.top_people],
        },
    }


class GeocodeCacheUpdateCoordsBody(BaseModel):
    coords: str
    location: str
    province: str = ""
    city: str = ""
    district: str = ""
    formatted_address: str = ""


class GeocodeCacheUpdateLocationBody(BaseModel):
    old_location: str
    new_location: str
    province: str = ""
    city: str = ""
    district: str = ""
    formatted_address: str = ""


@app.get("/api/geocode/cache/stats")
def api_geocode_cache_stats() -> dict[str, Any]:
    stats = geocode_cache_stats()
    return {
        "cache_file": str(GEOCODE_CACHE_FILE),
        "cache_version": cache_version(),
        **stats,
    }


@app.get("/api/geocode/cache/regions")
def api_geocode_cache_regions() -> dict[str, Any]:
    return list_geocode_cache_regions()


@app.get("/api/geocode/cache")
def api_geocode_cache_list(
    mode: str = Query("grouped", description="grouped=按地址合并 | coords=按坐标"),
    search: str = Query("", description="搜索 location / 详细地址 / 坐标"),
    province: str = Query("", description="按省筛选"),
    city: str = Query("", description="按市筛选"),
    sort: str = Query("coord_count", description="coord_count=坐标数优先 | region=省市优先"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    region_province = province.strip()
    region_city = city.strip()
    if mode == "coords":
        rows = list_geocode_cache_rows(
            search=search.strip(),
            province=region_province,
            city=region_city,
        )
        items = [
            {
                "coords": row.coords,
                "location": row.location,
                "province": row.province,
                "city": row.city,
                "district": row.district,
                "formatted_address": row.formatted_address,
                "valid": row.valid,
                "missing_admin": not row.province.strip(),
            }
            for row in rows
        ]
    elif mode == "grouped":
        items = list_geocode_cache_grouped(
            search=search.strip(),
            province=region_province,
            city=region_city,
            sort=sort.strip() or "coord_count",
        )
    else:
        raise HTTPException(status_code=400, detail="mode 须为 grouped 或 coords")

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "mode": mode,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items[start:end],
    }


@app.get("/api/geocode/cache/samples")
def api_geocode_cache_samples(
    coords: str = Query("", description="单条坐标 lat,lon"),
    location: str = Query("", description="短地名（按地址合并模式）"),
    limit: int = Query(6, ge=1, le=20),
) -> dict[str, Any]:
    coords = coords.strip()
    location = location.strip()
    if not coords and not location:
        raise HTTPException(status_code=400, detail="请提供 coords 或 location")
    if coords and location:
        raise HTTPException(status_code=400, detail="coords 与 location 二选一")
    return sample_photos_for_geocode_cache(coords=coords, location=location, limit=limit)


@app.put("/api/geocode/cache/coords")
def api_geocode_cache_update_coords(body: GeocodeCacheUpdateCoordsBody) -> dict[str, Any]:
    try:
        ok = update_geocode_cache_coords(
            body.coords.strip(),
            location=body.location,
            province=body.province,
            city=body.city,
            district=body.district,
            formatted_address=body.formatted_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=f"未找到坐标缓存: {body.coords}")
    return {"ok": True, "coords": body.coords.strip()}


@app.put("/api/geocode/cache/location")
def api_geocode_cache_update_location(body: GeocodeCacheUpdateLocationBody) -> dict[str, Any]:
    try:
        updated = update_geocode_cache_by_location(
            body.old_location,
            new_location=body.new_location,
            province=body.province,
            city=body.city,
            district=body.district,
            formatted_address=body.formatted_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "updated": updated,
        "old_location": body.old_location.strip(),
        "new_location": body.new_location.strip(),
    }


@app.delete("/api/geocode/cache/coords")
def api_geocode_cache_delete_coords(coords: str = Query(..., min_length=3)) -> dict[str, Any]:
    ok = delete_geocode_cache_coords(coords.strip())
    if not ok:
        raise HTTPException(status_code=404, detail=f"未找到坐标缓存: {coords}")
    return {"ok": True, "coords": coords.strip(), "message": "已删除，regeocode 时会重新请求高德"}


@app.get("/api/face/registry")
def api_face_registry() -> dict[str, Any]:
    """人脸库 registry 列表（供 Vue 选择已有成员）。按照片出现次数降序。"""
    people = list_registry_people()
    counts: dict[str, int] = {}
    try:
        conn = connect(MEMORY_DB)
        init_db(conn)
        rows = conn.execute(
            """
            SELECT person_id, COUNT(DISTINCT photo_id) AS cnt
            FROM photo_people
            WHERE person_id != ''
            GROUP BY person_id
            """
        ).fetchall()
        conn.close()
        counts = {str(row["person_id"]): int(row["cnt"] or 0) for row in rows}
    except Exception:
        counts = {}
    for person in people:
        person["photo_count"] = counts.get(str(person.get("person_id") or ""), 0)
    people.sort(
        key=lambda p: (-int(p.get("photo_count") or 0), str(p.get("person_id") or ""))
    )
    return {"people": people}


@app.get("/api/face/detect")
def api_face_detect(photo_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    """检测照片中的所有人脸，并标注是否已匹配库内成员。"""
    try:
        return detect_faces_in_photo(photo_id.strip())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class FaceEnrollRequest(BaseModel):
    photo_id: str = Field(..., min_length=1)
    person_id: str = Field(..., min_length=1)
    name: str = Field("", description="中文名；新建成员必填")
    role: str = Field("other", description="child / parent / relative / sibling / friend / other")
    birth_date: str = Field("", description="YYYY-MM-DD，可选")
    match_threshold: Optional[float] = Field(
        None,
        gt=0,
        le=1,
        description="识别阈值；不传则沿用 registry 或全局默认",
    )
    face_index: int = Field(0, ge=-1, description="人脸序号，-1 表示最大脸")
    reidentify_photo: bool = Field(True, description="入库后重识别本张照片并 sync 索引")


class FacePersonUpdateBody(BaseModel):
    name: Optional[str] = Field(None, description="中文名")
    role: Optional[str] = Field(None, description="child / parent / relative / sibling / friend / other")
    birth_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    match_threshold: Optional[float] = Field(
        None,
        gt=0,
        le=1,
        description="识别阈值；传 null 清除，使用全局默认",
    )


@app.post("/api/face/enroll")
def api_face_enroll(body: FaceEnrollRequest) -> dict[str, Any]:
    """从当前照片裁剪人脸，写入 data/faces/ 并重建 index.json。"""
    name = body.name.strip()
    if not name:
        name = body.person_id.strip()
    enroll_kwargs: dict[str, Any] = {
        "name": name,
        "role": body.role.strip() or "other",
        "birth_date": body.birth_date.strip(),
        "face_index": body.face_index,
        "reidentify_photo": body.reidentify_photo,
    }
    if body.match_threshold is not None:
        enroll_kwargs["match_threshold"] = body.match_threshold
    try:
        result = enroll_photo_face(
            body.photo_id.strip(),
            body.person_id.strip(),
            **enroll_kwargs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", **result}


@app.get("/api/face/people")
def api_face_people() -> dict[str, Any]:
    """人脸库成员列表（含参考照数量、识别阈值）。"""
    return {"people": list_face_people()}


@app.get("/api/face/people/{person_id}")
def api_face_person(person_id: str) -> dict[str, Any]:
    """单个成员详情与参考照列表。"""
    try:
        return get_face_person(person_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/face/people/{person_id}")
def api_face_person_update(person_id: str, body: FacePersonUpdateBody) -> dict[str, Any]:
    """更新 registry 属性并重建 index.json。"""
    kwargs: dict[str, Any] = {}
    if body.name is not None:
        kwargs["name"] = body.name
    if body.role is not None:
        kwargs["role"] = body.role
    if body.birth_date is not None:
        kwargs["birth_date"] = body.birth_date
    if "match_threshold" in body.model_fields_set:
        kwargs["match_threshold"] = body.match_threshold
    try:
        return update_face_person(person_id.strip(), **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/face/people/{person_id}/refs")
def api_face_person_delete_ref(
    person_id: str,
    file: str = Query(..., min_length=1, description="参考照相对路径，如 ref_01.jpg"),
) -> dict[str, Any]:
    """删除某成员的参考照并重建 index.json。"""
    try:
        return delete_face_reference(person_id.strip(), file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/face/rebuild-index")
def api_face_rebuild_index() -> dict[str, Any]:
    """手动重建 index.json。"""
    try:
        return rebuild_face_index()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ToolsLimitBody(BaseModel):
    limit: Optional[int] = Field(None, ge=1, description="本次最多处理条数；不传则全库")
    sync_after: bool = Field(True, description="完成后同步 SQLite 索引")


class ToolsRegeocodeBody(ToolsLimitBody):
    normalize_after: bool = Field(False, description="家附近已拆 POI 时保持 false")


class ToolsBackfillFacesBody(ToolsLimitBody):
    year: str = Field("", description="只处理某年，如 2026")
    refill: bool = Field(True, description="强制重跑人脸（新人入库后建议开启）")


def _rebuild_pydantic_models_for_dynamic_load() -> None:
    """main.py 用 importlib 加载本模块时，需 rebuild 含 Optional 注解的模型。"""
    import typing

    ns = {
        **globals(),
        "Optional": typing.Optional,
        "List": typing.List,
    }
    for model_cls in (
        FaceEnrollRequest,
        FacePersonUpdateBody,
        MemoryUpdateRequest,
        BatchPeopleByIdsRequest,
        BatchLocationByIdsRequest,
        ToolsLimitBody,
        ToolsRegeocodeBody,
        ToolsBackfillFacesBody,
    ):
        model_cls.model_rebuild(_types_namespace=ns)


_rebuild_pydantic_models_for_dynamic_load()


@app.get("/api/tools/config")
def api_tools_config() -> dict[str, Any]:
    """当前运行时配置（便于确认 .env 是否生效）。"""
    from hub.shared.config import (
        CLIP_ENABLED,
        FACE_MATCH_THRESHOLD,
        OUTFIT_FALLBACK_ENABLED,
    )

    idx = load_face_index()
    return {
        "face_match_threshold": FACE_MATCH_THRESHOLD,
        "index_json_threshold": float(idx["threshold"]) if idx and idx.get("threshold") is not None else None,
        "clip_enabled": CLIP_ENABLED,
        "outfit_fallback_enabled": OUTFIT_FALLBACK_ENABLED,
    }


@app.post("/api/tools/sync-index")
def api_tools_sync_index(force: bool = Query(False)) -> dict[str, Any]:
    """JSON → SQLite 索引同步。"""
    stats = sync_memory_dir(MEMORY_DIR, MEMORY_DB, force=force)
    return {"status": "ok", "stats": asdict(stats)}


@app.post("/api/tools/regeocode-locations")
def api_tools_regeocode(body: ToolsRegeocodeBody) -> dict[str, Any]:
    """将 .geocode_cache.json 写回 memory JSON 的 location（不改 location_coords）。"""
    stats = regeocode_locations_from_memory(
        MEMORY_DIR,
        limit=body.limit,
        normalize_after=body.normalize_after,
    )
    result: dict[str, Any] = {"status": "ok", "regeocode": asdict(stats)}
    if body.sync_after:
        result["sync"] = asdict(sync_memory_dir(MEMORY_DIR, MEMORY_DB))
    return result


@app.post("/api/tools/rebuild-face-index")
def api_tools_rebuild_face_index() -> dict[str, Any]:
    """扫描 data/faces/ 参考照，重建 index.json。"""
    index = build_face_index(FACES_DIR)
    people_count = len(index.get("people", {}))
    if people_count == 0:
        raise HTTPException(status_code=400, detail="人脸库为空，请先添加参考照")
    output = save_face_index(index, FACES_DIR)
    return {
        "status": "ok",
        "people_count": people_count,
        "index_file": str(output),
    }


@app.post("/api/tools/backfill-faces")
def api_tools_backfill_faces(body: ToolsBackfillFacesBody) -> dict[str, Any]:
    """按原图重跑人脸识别，写回 JSON people 字段。"""
    stats = backfill_folder(
        memory_dir=MEMORY_DIR,
        photos_dir=PHOTOS_DIR,
        mode="faces",
        only_empty=not body.refill,
        year=body.year.strip(),
        limit=body.limit,
    )
    result: dict[str, Any] = {"status": "ok", "backfill": asdict(stats)}
    if body.sync_after:
        result["sync"] = asdict(sync_memory_dir(MEMORY_DIR, MEMORY_DB))
    return result


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MemoryGraph Desk</title>
  <style>
    :root {
      --bg: #0f1419;
      --panel: #1a2332;
      --border: #2d3a4f;
      --text: #e7ecf3;
      --muted: #8b9cb3;
      --accent: #5b9fd4;
      --accent-hover: #7ab3e0;
    }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      min-height: 100vh;
    }
    header {
      padding: 1.25rem 1.5rem;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
    }
    header h1 { margin: 0; font-size: 1.25rem; font-weight: 600; }
    header p { margin: 0.35rem 0 0; color: var(--muted); font-size: 0.875rem; }
    main { max-width: 960px; margin: 0 auto; padding: 1.5rem; }
    section { margin-bottom: 2rem; }
    section h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 0.75rem; }
    .search-row { display: flex; gap: 0.5rem; }
    input[type="text"], textarea {
      flex: 1;
      width: 100%;
      padding: 0.75rem 1rem;
      font-size: 1rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
    }
    input:focus, textarea:focus { outline: 2px solid var(--accent); border-color: transparent; }
    button {
      padding: 0.75rem 1.25rem;
      font-size: 0.95rem;
      border: none;
      border-radius: 8px;
      background: var(--accent);
      color: #fff;
      cursor: pointer;
      white-space: nowrap;
    }
    button:hover { background: var(--accent-hover); }
    button.secondary { background: var(--border); color: var(--text); }
    button.secondary:hover { background: #3d4f6a; }
    button.danger { background: #a94444; }
    button.danger:hover { background: #c25555; }
    .hint { color: var(--muted); font-size: 0.8rem; margin-top: 0.5rem; }
    #status { color: var(--muted); font-size: 0.875rem; margin: 0.75rem 0; min-height: 1.25rem; }
    .results { list-style: none; padding: 0; margin: 0; }
    .result {
      display: grid;
      grid-template-columns: 72px 1fr auto;
      gap: 1rem;
      align-items: center;
      padding: 0.75rem;
      border: 1px solid var(--border);
      border-radius: 10px;
      margin-bottom: 0.5rem;
      background: var(--panel);
    }
    .result img {
      width: 72px; height: 72px; object-fit: cover; border-radius: 6px; background: #000;
    }
    .result .placeholder {
      width: 72px; height: 72px; border-radius: 6px; background: var(--border);
      display: flex; align-items: center; justify-content: center; font-size: 0.7rem; color: var(--muted);
    }
    .result .name { font-weight: 600; word-break: break-all; }
    .result .meta { font-size: 0.8rem; color: var(--muted); margin-top: 0.25rem; }
    .result .actions { display: flex; flex-direction: column; gap: 0.35rem; }
    .result .actions button { padding: 0.4rem 0.65rem; font-size: 0.75rem; }
    .tag {
      display: inline-block; font-size: 0.65rem; padding: 0.15rem 0.45rem;
      border-radius: 4px; background: var(--border); color: var(--muted); margin-right: 0.35rem;
    }
    .answer-box {
      white-space: pre-wrap;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem;
      line-height: 1.55;
      min-height: 3rem;
    }
    textarea { min-height: 4rem; resize: vertical; }
  </style>
</head>
<body>
  <header>
    <h1>MemoryGraph Desk</h1>
    <p>搜文件名 · 按人物找图 · 预览 · 打开 · 记忆问答</p>
  </header>
  <main>
    <section>
      <h2>按人物搜照片</h2>
      <div class="search-row">
        <input id="personQ" type="text" placeholder="输入人物名，如 面面、笑笑、爸爸" autocomplete="off" />
        <button type="button" id="personSearchBtn">搜索</button>
      </div>
      <p class="hint">查 memory JSON 里识别到的人物 · 删除会移入 data/.trash/ 并清索引</p>
      <div id="personStatus"></div>
      <ul id="personResults" class="results"></ul>
    </section>

    <section>
      <h2>文件搜索</h2>
      <div class="search-row">
        <input id="q" type="text" placeholder="输入文件名，如 IMG_3844" autofocus autocomplete="off" />
        <button type="button" id="searchBtn">搜索</button>
      </div>
      <p class="hint">在 data/photos、memory、faces 中按文件名匹配 · Enter 搜索</p>
      <div id="status"></div>
      <ul id="results" class="results"></ul>
    </section>

    <section>
      <h2>记忆问答</h2>
      <textarea id="question" placeholder="例如：笑笑在前秦村的照片？面面最近去哪了？"></textarea>
      <div style="margin-top:0.5rem;display:flex;gap:0.5rem;">
        <button type="button" id="askBtn">提问</button>
      </div>
      <div id="answer" class="answer-box" style="margin-top:0.75rem;color:var(--muted);">回答会显示在这里</div>
    </section>
  </main>
  <script>
    const qInput = document.getElementById("q");
    const statusEl = document.getElementById("status");
    const resultsEl = document.getElementById("results");

    async function doSearch() {
      const q = qInput.value.trim();
      if (!q) return;
      statusEl.textContent = "搜索中…";
      resultsEl.innerHTML = "";
      try {
        const res = await fetch("/api/search?q=" + encodeURIComponent(q));
        const data = await res.json();
        statusEl.textContent = data.count ? `找到 ${data.count} 个结果` : "无匹配";
        resultsEl.innerHTML = data.items.map(item => renderItem(item)).join("");
      } catch (e) {
        statusEl.textContent = "搜索失败";
      }
    }

    function renderPhotoItem(item) {
      const thumb = item.is_image && item.path
        ? `<img src="/api/preview?path=${encodeURIComponent(item.path)}" alt="" loading="lazy" />`
        : `<div class="placeholder">${esc(item.label || "?")}</div>`;
      const mem = item.memory_rel
        ? `<div class="meta">JSON: ${esc(item.memory_rel)}</div>` : "";
      const meta = item.timestamp || item.location || item.people
        ? `<div class="meta">${esc([item.timestamp, item.people, item.location].filter(Boolean).join(" · "))}</div>`
        : "";
      const openBtn = item.path
        ? `<button type="button" onclick="openFile('${escAttr(item.path)}', false)">打开</button>
           <button type="button" class="secondary" onclick="openFile('${escAttr(item.path)}', true)">Finder</button>`
        : "";
      const deleteBtn = item.deletable
        ? `<button type="button" class="danger" onclick="deletePhoto(this, '${escAttr(item.photo_id || "")}', '${escAttr(item.path || "")}', '${escAttr(item.memory_path || "")}')">删除</button>`
        : "";
      return `<li class="result">
        ${thumb}
        <div>
          <span class="tag">${esc(item.label)}</span>
          <div class="name">${esc(item.name)}</div>
          ${meta}
          <div class="meta">${esc(item.rel)}</div>
          ${mem}
        </div>
        <div class="actions">
          ${openBtn}
          ${item.memory_path ? `<button type="button" class="secondary" onclick="openFile('${escAttr(item.memory_path)}', false)">JSON</button>` : ""}
          ${deleteBtn}
        </div>
      </li>`;
    }

    function renderItem(item) {
      return renderPhotoItem(item);
    }

    async function doPersonSearch() {
      const q = document.getElementById("personQ").value.trim();
      const personStatusEl = document.getElementById("personStatus");
      const personResultsEl = document.getElementById("personResults");
      if (!q) return;
      personStatusEl.textContent = "搜索中…";
      personResultsEl.innerHTML = "";
      try {
        const res = await fetch("/api/search-person?q=" + encodeURIComponent(q));
        const data = await res.json();
        const hint = data.resolved && data.resolved !== data.query
          ? `（匹配 ${data.resolved}）` : "";
        personStatusEl.textContent = data.count
          ? `找到 ${data.count} 张${hint}` : `没有找到含「${data.query}」的照片`;
        personResultsEl.innerHTML = data.items.map(item => renderPhotoItem(item)).join("");
      } catch (e) {
        personStatusEl.textContent = "搜索失败";
      }
    }

    function esc(s) {
      return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    }
    function escAttr(s) {
      return String(s).replace(/\\\\/g,"\\\\\\\\").replace(/'/g,"\\\\'");
    }

    async function openFile(path, reveal) {
      if (!path) return;
      await fetch("/api/open", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path, reveal}),
      });
    }

    async function deletePhoto(btn, photoId, path, memoryPath) {
      const label = photoId || path.split("/").pop() || "此项";
      const msg = `确定删除「${label}」？\n\n原图 + memory JSON 会移入 data/.trash/\nSQLite 索引同步清除（无需再 sync）`;
      if (!confirm(msg)) return;
      btn.disabled = true;
      btn.textContent = "…";
      try {
        const res = await fetch("/api/delete", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            photo_id: photoId || "",
            path: path || "",
            memory_path: memoryPath || "",
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "删除失败");
        const li = btn.closest("li");
        if (li) li.remove();
      } catch (e) {
        alert(e.message || "删除失败");
        btn.disabled = false;
        btn.textContent = "删除";
      }
    }

    document.getElementById("personSearchBtn").onclick = doPersonSearch;
    document.getElementById("personQ").addEventListener("keydown", e => {
      if (e.key === "Enter") doPersonSearch();
    });

    document.getElementById("searchBtn").onclick = doSearch;
    qInput.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });

    document.getElementById("askBtn").onclick = async () => {
      const question = document.getElementById("question").value.trim();
      const answerEl = document.getElementById("answer");
      if (!question) return;
      answerEl.textContent = "思考中…";
      answerEl.style.color = "var(--muted)";
      try {
        const res = await fetch("/api/ask", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({question}),
        });
        const data = await res.json();
        answerEl.style.color = "var(--text)";
        answerEl.textContent = data.answer || "(无回答)";
      } catch (e) {
        answerEl.textContent = "问答失败，请确认 Ollama 已启动";
      }
    };
  </script>
</body>
</html>
"""
