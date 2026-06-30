"""图片分析入口。

整个工程唯一的 AI 分析接口：analyze_image()。
"""

from __future__ import annotations

from hub.shared.face import scan_faces
from hub.shared.outfit import apply_outfit_fallback
from hub.shared.schema import AnalysisResult, Person, Quality, empty_analysis
from hub.shared.vision import analyze_image_ollama


def _merge_analysis(
    vision: AnalysisResult,
    people: list[Person],
    face_detected: bool,
) -> AnalysisResult:
    quality = vision["quality"]
    return AnalysisResult(
        people=people,
        scene=vision["scene"],
        location=vision["location"],
        objects=vision["objects"],
        actions=vision["actions"],
        emotion=vision["emotion"],
        tags=vision["tags"],
        quality=Quality(
            blur=quality["blur"],
            face_detected=face_detected or quality["face_detected"],
        ),
    )


def _strip_internal_person_fields(people: list[Person]) -> list[Person]:
    cleaned: list[Person] = []
    for person in people:
        p = dict(person)
        p.pop("bbox", None)
        cleaned.append(Person(**p))
    return cleaned


def analyze_image(
    image_path: str,
    *,
    timestamp: str = "",
    photo_id: str = "",
) -> dict:
    """分析单张图片，返回符合 Schema 的 AI 字段。

    - 场景语义：Ollama 视觉模型
    - 人物识别：InsightFace 人脸库
    - 衣着兜底：CLIP 比对当日已缓存穿搭（脸不清时）
    """
    vision = analyze_image_ollama(image_path)

    face_people, unmatched_bboxes, face_detected = scan_faces(image_path)
    people = apply_outfit_fallback(
        image_path,
        timestamp=timestamp,
        photo_id=photo_id,
        face_people=face_people,
        unmatched_bboxes=unmatched_bboxes,
    )
    people = _strip_internal_person_fields(people)

    result = _merge_analysis(vision, people, face_detected)
    return dict(result)
