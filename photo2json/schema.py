"""Family Memory 固定 JSON Schema 定义与组装逻辑。

字段名称与结构不可随意修改，所有 Analyzer 实现必须兼容此协议。
"""

from __future__ import annotations

from typing import Any, TypedDict


class Person(TypedDict):
    id: str
    name: str
    confidence: float


class Quality(TypedDict):
    blur: bool
    face_detected: bool


class Source(TypedDict):
    path: str
    width: int
    height: int


class PhotoJson(TypedDict):
    photo_id: str
    timestamp: str
    people: list[Person]
    scene: str
    location: str
    objects: list[str]
    actions: list[str]
    emotion: list[str]
    tags: list[str]
    quality: Quality
    source: Source


# Analyzer 应返回的 AI 分析字段（不含 photo_id / timestamp / source）
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


def build_photo_json(
    photo_id: str,
    timestamp: str,
    source: Source,
    analysis: AnalysisResult,
) -> PhotoJson:
    """将元数据与 AI 分析结果合并为完整 JSON 对象。"""
    return PhotoJson(
        photo_id=photo_id,
        timestamp=timestamp,
        people=analysis["people"],
        scene=analysis["scene"],
        location=analysis["location"],
        objects=analysis["objects"],
        actions=analysis["actions"],
        emotion=analysis["emotion"],
        tags=analysis["tags"],
        quality=analysis["quality"],
        source=source,
    )


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
