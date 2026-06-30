"""CLIP 衣着向量：脸认出后缓存当日穿搭，脸不清时兜底比对。"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from hub.shared.config import (
    CLIP_ENABLED,
    CLIP_MODEL_NAME,
    CLIP_PRETRAINED,
    OUTFIT_CACHE_DIR,
    OUTFIT_MATCH_THRESHOLD,
    OUTFIT_MAX_CONFIDENCE,
)
from hub.shared.family import load_family_members
from hub.shared.face import expand_face_bbox_to_body, load_image_bgr
from hub.shared.schema import Person

logger = logging.getLogger(__name__)

_CLIP_MODEL: Any | None = None
_CLIP_PREPROCESS: Any | None = None
_CLIP_DEVICE: str = "cpu"
_CLIP_UNAVAILABLE = False


def _photo_day(timestamp: str) -> str:
    if not timestamp.strip():
        return ""
    try:
        if "T" in timestamp:
            return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d")
        return datetime.strptime(timestamp.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _day_cache_path(day: str) -> Path:
    return OUTFIT_CACHE_DIR / f"{day}.json"


def _load_day_cache(day: str) -> dict[str, Any]:
    path = _day_cache_path(day)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取衣着缓存失败 %s: %s", path, exc)
        return {}


def _save_day_cache(day: str, cache: dict[str, Any]) -> None:
    OUTFIT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _day_cache_path(day).write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_clip() -> tuple[Any, Any] | None:
    global _CLIP_MODEL, _CLIP_PREPROCESS, _CLIP_DEVICE, _CLIP_UNAVAILABLE

    if _CLIP_UNAVAILABLE or not CLIP_ENABLED:
        return None
    if _CLIP_MODEL is not None and _CLIP_PREPROCESS is not None:
        return _CLIP_MODEL, _CLIP_PREPROCESS

    try:
        import open_clip
        import torch
    except ImportError:
        logger.warning(
            "未安装 open-clip-torch，衣着兜底已跳过。请执行: pip install -r requirements.txt"
        )
        _CLIP_UNAVAILABLE = True
        return None

    try:
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        local_weights = Path(CLIP_PRETRAINED).expanduser()
        if local_weights.is_file():
            pretrained_arg: str | Path = local_weights
            logger.info("从本地加载 CLIP 权重: %s", local_weights)
        else:
            pretrained_arg = CLIP_PRETRAINED
            mirror = os.environ.get("HF_ENDPOINT", "")
            logger.info(
                "正在下载/加载 CLIP 权重 %s/%s（首次约 300MB，可能需数分钟；"
                "不是卡死）。国内可设 HF_ENDPOINT=https://hf-mirror.com",
                CLIP_MODEL_NAME,
                CLIP_PRETRAINED,
            )
            if mirror:
                logger.info("HF_ENDPOINT=%s", mirror)

        t0 = time.perf_counter()
        model, _, preprocess = open_clip.create_model_and_transforms(
            CLIP_MODEL_NAME,
            pretrained=pretrained_arg,
        )
        logger.info("CLIP 权重就绪，耗时 %.1fs", time.perf_counter() - t0)
        model.eval()
        model.to(device)
        _CLIP_MODEL = model
        _CLIP_PREPROCESS = preprocess
        _CLIP_DEVICE = device
        logger.info("CLIP 模型已加载 (%s/%s, device=%s)", CLIP_MODEL_NAME, CLIP_PRETRAINED, device)
        return model, preprocess
    except Exception as exc:
        logger.warning("CLIP 模型加载失败，衣着兜底已跳过: %s", exc)
        _CLIP_UNAVAILABLE = True
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    try:
        import numpy as np
    except ImportError:
        return 0.0
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def encode_outfit_crop(bgr_crop: Any) -> list[float] | None:
    """将人体/衣着裁剪区域编码为 CLIP 向量。"""
    clip = _get_clip()
    if clip is None or bgr_crop is None or bgr_crop.size == 0:
        return None

    try:
        import cv2
        import torch
        from PIL import Image
    except ImportError:
        return None

    model, preprocess = clip
    rgb = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    tensor = preprocess(pil).unsqueeze(0).to(_CLIP_DEVICE)

    with torch.no_grad():
        features = model.encode_image(tensor)
        features = features / features.norm(dim=-1, keepdim=True)

    return features.squeeze(0).cpu().float().tolist()


def encode_outfit_from_bbox(
    image_path: str | Path,
    bbox: tuple[float, float, float, float],
) -> list[float] | None:
    """从人脸框扩展出人体区域并编码衣着向量。"""
    bgr = load_image_bgr(Path(image_path))
    if bgr is None:
        return None

    h, w = bgr.shape[:2]
    x1, y1, x2, y2 = expand_face_bbox_to_body(bbox, h, w)
    crop = bgr[y1:y2, x1:x2]
    return encode_outfit_crop(crop)


def cache_outfit_for_person(
    day: str,
    person_id: str,
    embedding: list[float],
    *,
    photo_id: str = "",
    name: str = "",
) -> None:
    """缓存某人当天的衣着向量（脸认出后调用）。"""
    if not day or not person_id:
        return

    cache = _load_day_cache(day)
    cache[person_id] = {
        "name": name,
        "photo_id": photo_id,
        "embedding": embedding,
    }
    _save_day_cache(day, cache)
    logger.info("已缓存当日衣着: day=%s person=%s", day, person_id)


def match_outfit_against_day(
    embedding: list[float],
    day: str,
) -> Person | None:
    """将衣着向量与当日缓存比对，返回最佳匹配。"""
    if not day:
        return None

    cache = _load_day_cache(day)
    if not cache:
        return None

    members = load_family_members()
    best_id = ""
    best_name = ""
    best_score = 0.0

    for person_id, item in cache.items():
        cached_emb = item.get("embedding", [])
        score = _cosine_similarity(embedding, cached_emb)
        if score > best_score:
            best_score = score
            best_id = person_id
            member = members.get(person_id)
            best_name = item.get("name") or (member.name if member else person_id)

    if best_score < OUTFIT_MATCH_THRESHOLD:
        return None

    display = best_name
    member = members.get(best_id)
    if member is not None:
        display = member.name

    confidence = min(round(best_score * OUTFIT_MAX_CONFIDENCE, 4), OUTFIT_MAX_CONFIDENCE)
    return Person(
        id=best_id,
        name=display,
        confidence=confidence,
        match_method="outfit",
    )


def apply_outfit_fallback(
    image_path: str | Path,
    *,
    timestamp: str,
    photo_id: str,
    face_people: list[Person],
    unmatched_bboxes: list[tuple[float, float, float, float]],
) -> list[Person]:
    """脸优先；脸不清时用当日衣着缓存兜底。已有的人不会重复添加。"""
    if not CLIP_ENABLED:
        return face_people

    day = _photo_day(timestamp)
    if not day:
        return face_people

    result: dict[str, Person] = {
        p["id"]: dict(p, match_method=p.get("match_method", "face")) for p in face_people
    }

    # 脸认出 → 缓存当日衣着
    for person in face_people:
        if person.get("match_method", "face") != "face":
            continue
        bbox = person.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        embedding = encode_outfit_from_bbox(image_path, tuple(bbox))  # type: ignore[arg-type]
        if embedding is None:
            continue
        cache_outfit_for_person(
            day,
            person["id"],
            embedding,
            photo_id=photo_id,
            name=person["name"],
        )

    # 去掉内部字段 bbox 再返回
    for person in face_people:
        person.pop("bbox", None)

    # 未匹配人脸 → 衣着比对
    for bbox in unmatched_bboxes:
        embedding = encode_outfit_from_bbox(image_path, bbox)
        if embedding is None:
            continue
        matched = match_outfit_against_day(embedding, day)
        if matched is None:
            continue
        existing = result.get(matched["id"])
        if existing is None or matched["confidence"] > existing.get("confidence", 0):
            result[matched["id"]] = matched
            logger.info(
                "衣着兜底识别: %s (confidence=%.3f)",
                matched["name"],
                matched["confidence"],
            )

    cleaned: list[Person] = []
    for person in result.values():
        p = dict(person)
        p.pop("bbox", None)
        cleaned.append(Person(**p))
    return cleaned
