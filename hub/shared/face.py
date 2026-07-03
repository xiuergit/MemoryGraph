"""人脸识别：参考照注册、本地比对、填充 people 字段。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hub.shared.config import (
    FACE_INDEX_FILE,
    FACE_MATCH_THRESHOLD,
    FACE_REGISTRY_FILE,
    FACES_DIR,
    INSIGHTFACE_MODEL,
    INSIGHTFACE_ROOT,
    SUPPORTED_EXTENSIONS,
)
from hub.shared.schema import Person

logger = logging.getLogger(__name__)

_FACE_APP: Any | None = None
_FACE_APP_UNAVAILABLE = False


def _get_face_app() -> Any | None:
    """懒加载 InsightFace 模型；不可用时返回 None。"""
    global _FACE_APP, _FACE_APP_UNAVAILABLE

    if _FACE_APP_UNAVAILABLE:
        return None
    if _FACE_APP is not None:
        return _FACE_APP

    try:
        from insightface.app import FaceAnalysis
    except ImportError:
        logger.warning(
            "未安装 insightface，人脸识别已跳过。请执行: pip install -r requirements.txt"
        )
        _FACE_APP_UNAVAILABLE = True
        return None

    try:
        kwargs: dict[str, Any] = {"name": INSIGHTFACE_MODEL}
        if INSIGHTFACE_ROOT.strip():
            kwargs["root"] = INSIGHTFACE_ROOT.strip()
        app = FaceAnalysis(**kwargs)
        app.prepare(ctx_id=-1, det_size=(640, 640))
        _FACE_APP = app
        root_hint = INSIGHTFACE_ROOT or "~/.insightface/models"
        logger.info(
            "InsightFace 模型已加载 (%s, root=%s)",
            INSIGHTFACE_MODEL,
            root_hint,
        )
        return _FACE_APP
    except Exception as exc:
        logger.warning("InsightFace 模型加载失败，人脸识别已跳过: %s", exc)
        _FACE_APP_UNAVAILABLE = True
        return None


def _load_image_bgr(image_path: Path) -> Any | None:
    """读取图片为 OpenCV BGR 格式，支持 HEIC。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.warning("未安装 opencv-python-headless 或 numpy")
        return None

    suffix = image_path.suffix.lower()
    if suffix in {".heic", ".heif"}:
        try:
            from PIL import Image

            import pillow_heif

            pillow_heif.register_heif_opener()
            with Image.open(image_path) as img:
                rgb = np.array(img.convert("RGB"))
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except Exception as exc:
            logger.warning("读取 HEIC 失败 %s: %s", image_path, exc)
            return None

    bgr = cv2.imread(str(image_path))
    if bgr is None:
        logger.warning("无法读取图片: %s", image_path)
    return bgr


load_image_bgr = _load_image_bgr


def _largest_face(faces: list) -> Any | None:
    if not faces:
        return None
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


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


def load_registry(registry_file: Path | None = None) -> dict[str, str]:
    """读取 id → 显示名 映射。文件不存在时返回空 dict。"""
    from hub.shared.family import load_display_names

    return load_display_names(registry_file)


def load_face_index() -> dict[str, Any] | None:
    """读取人脸特征索引；不存在或无效时返回 None。"""
    if not FACE_INDEX_FILE.exists():
        return None
    try:
        data = json.loads(FACE_INDEX_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("people"):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 index.json 失败: %s", exc)
    return None


def face_index_available() -> bool:
    return load_face_index() is not None


def iter_reference_images(person_dir: Path) -> list[Path]:
    """列出某人参考照目录下的图片（含子目录，便于按年龄段分组）。"""
    if not person_dir.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(person_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        rel_parts = path.relative_to(person_dir).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        files.append(path)
    return files


def extract_face_embedding(image_path: Path, *, largest_only: bool = True) -> list[list[float]]:
    """从图片提取人脸 embedding；参考照默认只取最大的一张脸。"""
    app = _get_face_app()
    if app is None:
        return []

    bgr = _load_image_bgr(image_path)
    if bgr is None:
        return []

    try:
        faces = app.get(bgr)
    except Exception as exc:
        logger.warning("人脸检测失败 %s: %s", image_path, exc)
        return []

    if not faces:
        return []

    if largest_only:
        face = _largest_face(faces)
        if face is None:
            return []
        return [face.embedding.astype(float).tolist()]

    return [f.embedding.astype(float).tolist() for f in faces]


def load_face_aliases(registry_file: Path | None = None) -> dict[str, str]:
    """读取参考照目录 id → 合并到的 canonical person_id（registry 里 alias 字段）。"""
    from hub.shared.family import load_family_members

    path = registry_file or FACE_REGISTRY_FILE
    members = load_family_members(path)
    aliases: dict[str, str] = {}
    if not path.exists():
        return aliases

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return aliases

    if not isinstance(data, dict):
        return aliases

    for dir_id, raw in data.items():
        if not isinstance(raw, dict):
            continue
        alias = str(raw.get("alias", "")).strip()
        if alias and alias in members:
            aliases[str(dir_id)] = alias
    return aliases


def _collect_reference_samples(person_dir: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for image_path in iter_reference_images(person_dir):
        embeddings = extract_face_embedding(image_path, largest_only=True)
        if not embeddings:
            logger.warning("参考照未检测到人脸，已跳过: %s", image_path)
            continue
        rel_file = str(image_path.relative_to(person_dir))
        samples.append(
            {
                "file": rel_file,
                "embedding": embeddings[0],
            }
        )
    return samples


def build_face_index(faces_dir: Path | None = None) -> dict[str, Any]:
    """扫描 data/faces/{person_id}/ 参考照，生成 index 数据。"""
    root = faces_dir or FACES_DIR
    registry_path = root / "registry.json"
    registry = load_registry(registry_path)
    aliases = load_face_aliases(registry_path)
    people: dict[str, Any] = {}

    if not root.is_dir():
        root.mkdir(parents=True, exist_ok=True)

    for person_dir in sorted(root.iterdir()):
        if not person_dir.is_dir() or person_dir.name.startswith("."):
            continue

        dir_id = person_dir.name
        person_id = aliases.get(dir_id, dir_id)
        display_name = registry.get(person_id, registry.get(dir_id, person_id))
        samples = _collect_reference_samples(person_dir)

        if not samples:
            logger.warning("目录无有效参考照: %s", person_dir)
            continue

        if person_id in people:
            people[person_id]["samples"].extend(samples)
            logger.info(
                "已合并 %s → %s (%s): +%d 张参考照",
                dir_id,
                person_id,
                display_name,
                len(samples),
            )
        else:
            people[person_id] = {
                "name": display_name,
                "samples": samples,
            }
            if dir_id == person_id:
                logger.info("已注册 %s (%s): %d 张参考照", person_id, display_name, len(samples))
            else:
                logger.info(
                    "已注册 %s → %s (%s): %d 张参考照",
                    dir_id,
                    person_id,
                    display_name,
                    len(samples),
                )

    return {
        "version": "1.0",
        "threshold": FACE_MATCH_THRESHOLD,
        "people": people,
    }


def save_face_index(index: dict[str, Any], faces_dir: Path | None = None) -> Path:
    root = faces_dir or FACES_DIR
    root.mkdir(parents=True, exist_ok=True)
    output = root / "index.json"
    output.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output


def _match_embedding(
    embedding: list[float],
    index: dict[str, Any],
    threshold: float,
) -> Person | None:
    best_id = ""
    best_name = ""
    best_score = 0.0

    for person_id, person_data in index.get("people", {}).items():
        for sample in person_data.get("samples", []):
            score = _cosine_similarity(embedding, sample.get("embedding", []))
            if score > best_score:
                best_score = score
                best_id = person_id
                best_name = person_data.get("name", person_id)

    if best_score < threshold:
        return None

    return Person(
        id=best_id,
        name=best_name,
        confidence=round(best_score, 4),
    )


def expand_face_bbox_to_body(
    bbox: tuple[float, float, float, float],
    img_h: int,
    img_w: int,
) -> tuple[int, int, int, int]:
    """由人脸框向下扩展出粗略人体/衣着区域。"""
    x1, y1, x2, y2 = bbox
    w = max(x2 - x1, 1.0)
    h = max(y2 - y1, 1.0)
    nx1 = max(0, int(x1 - 0.25 * w))
    nx2 = min(img_w, int(x2 + 0.25 * w))
    ny1 = max(0, int(y1 - 0.15 * h))
    ny2 = min(img_h, int(y2 + 2.0 * h))
    if nx2 <= nx1 or ny2 <= ny1:
        return 0, 0, img_w, img_h
    return nx1, ny1, nx2, ny2


def scan_faces(image_path: str | Path) -> tuple[list[Person], list[tuple[float, float, float, float]], bool]:
    """扫描人脸：返回 (已识别 people, 未匹配人脸框列表, 是否检测到脸)。"""
    index = load_face_index()
    if index is None:
        return [], [], False

    app = _get_face_app()
    if app is None:
        return [], [], False

    path = Path(image_path)
    bgr = _load_image_bgr(path)
    if bgr is None:
        return [], [], False

    try:
        faces = app.get(bgr)
    except Exception as exc:
        logger.warning("人脸识别失败 %s: %s", path, exc)
        return [], [], False

    if not faces:
        return [], [], False

    threshold = float(index.get("threshold", FACE_MATCH_THRESHOLD))
    matched: dict[str, Person] = {}
    unmatched_bboxes: list[tuple[float, float, float, float]] = []

    for face in faces:
        bbox = tuple(float(v) for v in face.bbox)
        embedding = face.embedding.astype(float).tolist()
        person = _match_embedding(embedding, index, threshold)
        if person is None:
            unmatched_bboxes.append(bbox)  # type: ignore[arg-type]
            continue

        person_dict = dict(person)
        person_dict["match_method"] = "face"
        person_dict["bbox"] = list(bbox)
        existing = matched.get(person["id"])
        if existing is None or person["confidence"] > existing["confidence"]:
            matched[person["id"]] = Person(**person_dict)

    return list(matched.values()), unmatched_bboxes, True


def recognize_people(image_path: str | Path) -> tuple[list[Person], bool]:
    """识别图片中的人脸，返回 (people 列表, 是否检测到脸)。"""
    people, _, face_detected = scan_faces(image_path)
    cleaned: list[Person] = []
    for person in people:
        p = dict(person)
        p.pop("bbox", None)
        cleaned.append(Person(**p))
    return cleaned, face_detected
