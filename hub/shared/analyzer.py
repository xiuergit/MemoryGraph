"""图片分析入口。

整个工程唯一的 AI 分析接口：analyze_image()。
替换模型时只需修改环境变量 OLLAMA_VISION_MODEL，或调整 hub/shared/vision.py。
"""

from __future__ import annotations

from hub.shared.face import recognize_people
from hub.shared.schema import AnalysisResult, Person, Quality, empty_analysis
from hub.shared.vision import analyze_image_ollama


def _merge_analysis(
    vision: AnalysisResult,
    people: list[Person],
    face_detected: bool,
) -> AnalysisResult:
    """合并 Ollama 视觉结果与人脸识别结果。"""
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


def analyze_image(image_path: str) -> dict:
    """分析单张图片，返回符合 Schema 的 AI 字段。

    - 场景语义：本地 Ollama 视觉模型（OLLAMA_VISION_MODEL）
    - 人物识别：InsightFace 人脸库（需先 face_enroll）
    - location 在 processor 中还会用 EXIF GPS / 高德补充
    """
    vision = analyze_image_ollama(image_path)
    people, face_detected = recognize_people(image_path)
    result = _merge_analysis(vision, people, face_detected)
    return dict(result)
