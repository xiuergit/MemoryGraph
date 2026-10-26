"""Family Memory 固定 JSON Schema 定义与组装逻辑。

字段名称与结构以 schemas/photo.v1.json 为准，所有端（iOS / Mac）必须兼容此协议。
"""

from __future__ import annotations

import sys
from typing import Any, TypedDict

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    from typing_extensions import NotRequired

from hub.shared.config import SCHEMA_VERSION, VIDEO_SCHEMA_VERSION


class AgeAtPhoto(TypedDict):
    years: int
    months: int
    days: int
    total_days: int
    label: str


class Person(TypedDict, total=False):
    id: str
    name: str
    confidence: float
    role: str
    age_at_photo: AgeAtPhoto
    match_method: str
    bbox: list[float]


class Quality(TypedDict):
    blur: bool
    face_detected: bool


class Transcript(TypedDict):
    text: str
    language: str
    source: str
    # draft | confirmed；缺省按 draft（不进问答）
    status: NotRequired[str]


def transcript_status(transcript: dict[str, Any] | None) -> str:
    """缺 status 或非法值一律 draft。"""
    if not isinstance(transcript, dict):
        return "draft"
    status = str(transcript.get("status") or "").strip().lower()
    return "confirmed" if status == "confirmed" else "draft"


def is_transcript_confirmed(data: dict[str, Any]) -> bool:
    tr = data.get("transcript")
    return transcript_status(tr if isinstance(tr, dict) else None) == "confirmed"


def make_transcript(
    text: str,
    *,
    language: str = "",
    source: str = "whisper",
    status: str = "draft",
) -> Transcript:
    st = "confirmed" if str(status).strip().lower() == "confirmed" else "draft"
    return Transcript(
        text=str(text or "").strip(),
        language=str(language or ""),
        source=str(source or "whisper"),
        status=st,
    )


class Source(TypedDict):
    path: str
    width: int
    height: int


class VideoSource(TypedDict, total=False):
    path: str
    width: int
    height: int
    duration_s: float
    fps: float | None
    container: str


class RelatedId(TypedDict):
    id: str
    media_type: str
    relation: str


class LocationAdmin(TypedDict):
    province: str
    city: str
    district: str
    formatted_address: str


def empty_location_admin() -> LocationAdmin:
    return LocationAdmin(
        province="",
        city="",
        district="",
        formatted_address="",
    )


def location_admin_from_dict(raw: dict[str, Any] | None) -> LocationAdmin:
    base = empty_location_admin()
    if not raw:
        return base
    return LocationAdmin(
        province=str(raw.get("province", "")),
        city=str(raw.get("city", "")),
        district=str(raw.get("district", "")),
        formatted_address=str(raw.get("formatted_address", "")),
    )


class Weather(TypedDict):
    date: str
    code: int
    condition: str
    temp_max_c: float | None
    temp_min_c: float | None
    temp_mean_c: float | None
    precipitation_mm: float | None
    source: str
    timezone: str


class PhotoJson(TypedDict, total=False):
    schema_version: str
    photo_id: str
    timestamp: str
    device_id: str
    people: list[Person]
    scene: str
    location: str
    location_coords: str
    location_admin: LocationAdmin
    objects: list[str]
    actions: list[str]
    emotion: list[str]
    tags: list[str]
    quality: Quality
    source: Source
    weather: Weather
    user_note: str
    manual_edit: bool
    manual_location: bool
    manual_people: bool
    manual_vision: bool
    manual_note: bool


def refresh_manual_edit_flag(data: dict[str, Any]) -> None:
    """用分项锁同步兼容字段 manual_edit（仅作展示/汇总，跳过逻辑看分项）。"""
    any_manual = bool(
        data.get("manual_location")
        or data.get("manual_people")
        or data.get("manual_vision")
        or data.get("manual_transcript")
        or data.get("manual_note")
    )
    if any_manual:
        data["manual_edit"] = True
    else:
        data.pop("manual_edit", None)


def is_manual_people(data: dict[str, Any]) -> bool:
    return bool(data.get("manual_people"))


def is_manual_vision(data: dict[str, Any]) -> bool:
    return bool(data.get("manual_vision"))


def is_manual_location(data: dict[str, Any]) -> bool:
    return bool(data.get("manual_location"))


def is_manual_transcript(data: dict[str, Any]) -> bool:
    return bool(data.get("manual_transcript"))


def is_manual_note(data: dict[str, Any]) -> bool:
    return bool(data.get("manual_note"))


def _schema_version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(version or "").strip().split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def bump_schema_for_user_note(data: dict[str, Any]) -> None:
    """写入旁白时升到支持 user_note / manual_note 的协议版本。

    photo → 至少 1.4；video / audio → 至少 1.1。已更高则不动。
    """
    current = str(data.get("schema_version") or "").strip()
    if data.get("video_id"):
        target = "1.1"
    elif data.get("audio_id"):
        target = "1.1"
    else:
        target = "1.4"
    if _schema_version_tuple(current) < _schema_version_tuple(target):
        data["schema_version"] = target


# Analyzer 应返回的 AI 分析字段（不含 photo_id / timestamp / source / device_id）
class AnalysisResult(TypedDict):
    people: list[Person]
    scene: str
    location: str
    objects: list[str]
    actions: list[str]
    emotion: list[str]
    tags: list[str]
    quality: Quality


def empty_analysis() -> AnalysisResult:
    """返回空分析结果，供 Mock Analyzer 或识别失败时使用。"""
    return AnalysisResult(
        people=[],
        scene="",
        location="",
        objects=[],
        actions=[],
        emotion=[],
        tags=[],
        quality=Quality(blur=False, face_detected=False),
    )


def build_video_json(
    video_id: str,
    timestamp: str,
    source: VideoSource,
    analysis: AnalysisResult,
    *,
    device_id: str = "",
    location_coords: str = "",
    location_admin: LocationAdmin | None = None,
    weather: Weather | None = None,
    related_ids: list[RelatedId] | None = None,
) -> dict[str, Any]:
    """将元数据与分析结果合并为 video.v1 JSON 对象。"""
    admin = location_admin if location_admin is not None else empty_location_admin()
    out: dict[str, Any] = {
        "schema_version": VIDEO_SCHEMA_VERSION,
        "video_id": video_id,
        "timestamp": timestamp,
        "device_id": device_id,
        "people": analysis["people"],
        "scene": analysis["scene"],
        "location": analysis["location"],
        "location_coords": location_coords,
        "location_admin": admin,
        "objects": analysis["objects"],
        "actions": analysis["actions"],
        "emotion": analysis["emotion"],
        "tags": analysis["tags"],
        "quality": analysis["quality"],
        "source": {
            "path": source["path"],
            "width": int(source["width"]),
            "height": int(source["height"]),
            "duration_s": float(source["duration_s"]),
        },
    }
    if source.get("fps") is not None:
        out["source"]["fps"] = source["fps"]
    if source.get("container"):
        out["source"]["container"] = source["container"]
    if related_ids:
        out["related_ids"] = related_ids
    if weather is not None:
        out["weather"] = weather
    return out


def build_photo_json(
    photo_id: str,
    timestamp: str,
    source: Source,
    analysis: AnalysisResult,
    *,
    device_id: str = "",
    location_coords: str = "",
    location_admin: LocationAdmin | None = None,
    weather: Weather | None = None,
) -> PhotoJson:
    """将元数据与 AI 分析结果合并为完整 JSON 对象。"""
    admin = location_admin if location_admin is not None else empty_location_admin()
    out = PhotoJson(
        schema_version=SCHEMA_VERSION,
        photo_id=photo_id,
        timestamp=timestamp,
        device_id=device_id,
        people=analysis["people"],
        scene=analysis["scene"],
        location=analysis["location"],
        location_coords=location_coords,
        location_admin=admin,
        objects=analysis["objects"],
        actions=analysis["actions"],
        emotion=analysis["emotion"],
        tags=analysis["tags"],
        quality=analysis["quality"],
        source=source,
    )
    if weather is not None:
        out["weather"] = weather
    return out


def analysis_from_dict(data: dict[str, Any]) -> AnalysisResult:
    """将任意 dict 规范化为 AnalysisResult，缺失字段使用默认值。"""
    default = empty_analysis()
    quality_raw = data.get("quality", {})
    return AnalysisResult(
        people=data.get("people", default["people"]),
        scene=data.get("scene", default["scene"]),
        location=data.get("location", default["location"]),
        objects=data.get("objects", default["objects"]),
        actions=data.get("actions", default["actions"]),
        emotion=data.get("emotion", default["emotion"]),
        tags=data.get("tags", default["tags"]),
        quality=Quality(
            blur=bool(quality_raw.get("blur", False)),
            face_detected=bool(quality_raw.get("face_detected", False)),
        ),
    )
