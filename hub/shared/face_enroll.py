"""人脸库维护：sync-registry、从照片入库、未知人脸聚类。"""

from __future__ import annotations

import gc
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hub.shared.config import (
    FACE_ENROLL_DET_SCORE_MIN,
    FACE_ENROLL_MIN_SIDE,
    FACE_MATCH_THRESHOLD,
    FACE_REGISTRY_FILE,
    FACES_DIR,
    JSON_INDENT,
    MEMORY_DIR,
    PHOTOS_DIR,
    SUPPORTED_EXTENSIONS,
)
from hub.shared.face import (
    _cosine_similarity,
    _match_embedding,
    build_face_index,
    detect_faces,
    extract_face_embedding,
    face_match_threshold,
    iter_reference_images,
    load_face_index,
    load_image_bgr,
    save_face_crop,
    save_face_index,
)
from hub.shared.utils import json_matches_year

logger = logging.getLogger(__name__)

_DEFAULT_ROLE = "other"
_PERSON_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _face_box_side(bbox: tuple[float, float, float, float] | list[float]) -> float:
    return min(float(bbox[2]) - float(bbox[0]), float(bbox[3]) - float(bbox[1]))


def enrollability_for_face(face: dict[str, Any]) -> tuple[bool, str]:
    """判断检测结果是否适合作为参考照入库。"""
    det_score = float(face.get("det_score") or 0.0)
    if det_score < FACE_ENROLL_DET_SCORE_MIN:
        return (
            False,
            f"检测分过低（{det_score:.2f} < {FACE_ENROLL_DET_SCORE_MIN:.2f}），请换更清晰的正脸",
        )
    side = _face_box_side(face["bbox"])
    if side < FACE_ENROLL_MIN_SIDE:
        return (
            False,
            f"人脸过小（最短边 {side:.0f}px < {FACE_ENROLL_MIN_SIDE}px），裁切后难以识别",
        )
    return True, ""


@dataclass(frozen=True)
class FaceObservation:
    photo_id: str
    image_path: Path
    face_index: int
    bbox: tuple[float, float, float, float]
    embedding: list[float]


@dataclass(frozen=True)
class UnknownFaceCluster:
    cluster_id: int
    count: int
    photo_ids: list[str]
    sample_photo_id: str
    sample_image_path: Path
    sample_bbox: tuple[float, float, float, float]
    sample_face_index: int


def load_registry_data(registry_file: Path | None = None) -> dict[str, Any]:
    path = registry_file or FACE_REGISTRY_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 registry.json 失败: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_registry_data(data: dict[str, Any], registry_file: Path | None = None) -> Path:
    path = registry_file or FACE_REGISTRY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=JSON_INDENT) + "\n",
        encoding="utf-8",
    )
    return path


def _dir_has_reference_images(person_dir: Path) -> bool:
    return bool(iter_reference_images(person_dir))


def list_face_dirs(faces_dir: Path | None = None) -> list[Path]:
    root = faces_dir or FACES_DIR
    if not root.is_dir():
        return []
    dirs: list[Path] = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and not path.name.startswith("."):
            dirs.append(path)
    return dirs


def sync_registry(
    faces_dir: Path | None = None,
    *,
    registry_file: Path | None = None,
    default_role: str = _DEFAULT_ROLE,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """为有参考照的目录补 registry 占位条目。返回 (新增数, 新增 id 列表)。"""
    root = faces_dir or FACES_DIR
    registry_path = registry_file or (root / "registry.json")
    data = load_registry_data(registry_path)
    added: list[str] = []

    for person_dir in list_face_dirs(root):
        dir_id = person_dir.name
        if dir_id in data:
            continue
        if not _dir_has_reference_images(person_dir):
            continue
        data[dir_id] = {
            "name": dir_id,
            "birth_date": "",
            "role": default_role,
        }
        added.append(dir_id)
        logger.info("registry 新增: %s（请编辑 name / role / birth_date）", dir_id)

    if added and not dry_run:
        save_registry_data(data, registry_path)
    return len(added), added


def resolve_photo_image(
    photo_id: str,
    *,
    memory_dir: Path | None = None,
    photos_dir: Path | None = None,
) -> Path | None:
    """由 photo_id 定位原图路径。"""
    memory_path = memory_dir or MEMORY_DIR
    json_path = memory_path / f"{photo_id}.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            source_path = str((data.get("source") or {}).get("path", "")).strip()
            if source_path:
                candidate = Path(source_path)
                if candidate.is_file():
                    return candidate
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("读取 memory JSON 失败 %s: %s", json_path, exc)

    photos_root = photos_dir or PHOTOS_DIR
    if not photos_root.is_dir():
        return None

    stem = photo_id.rsplit("_", 1)[-1] if "_" in photo_id else photo_id
    for ext in SUPPORTED_EXTENSIONS:
        matches = list(photos_root.rglob(f"{stem}{ext}"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            for match in matches:
                if photo_id.endswith(match.stem) or match.stem in photo_id:
                    return match
            return matches[0]
    return None


def _normalize_person_id(person_id: str) -> str:
    pid = person_id.strip().lower().replace("-", "_")
    if not _PERSON_ID_RE.match(pid):
        raise ValueError(
            f"person_id 格式无效: {person_id!r}（小写字母开头，仅 a-z0-9_，最长 32）"
        )
    return pid


def _parse_match_threshold(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value > 1:
        raise ValueError(f"match_threshold 须在 (0, 1] 之间，收到: {raw!r}")
    return round(value, 4)


def upsert_registry_person(
    person_id: str,
    *,
    name: str | None = None,
    role: str = _DEFAULT_ROLE,
    birth_date: str = "",
    match_threshold: Any = ...,  # type: ignore[assignment]
    registry_file: Path | None = None,
) -> None:
    pid = _normalize_person_id(person_id)
    data = load_registry_data(registry_file)
    raw = data.get(pid)
    if isinstance(raw, dict) and str(raw.get("alias", "")).strip():
        raise ValueError(f"{pid} 是 alias 目录条目，请指定 canonical person_id")

    entry = dict(raw) if isinstance(raw, dict) else {}
    entry["name"] = name or entry.get("name") or pid
    entry["birth_date"] = birth_date if birth_date != "" else str(entry.get("birth_date", ""))
    entry["role"] = role or str(entry.get("role", _DEFAULT_ROLE))
    if match_threshold is not ...:
        if match_threshold is None or match_threshold == "":
            entry.pop("match_threshold", None)
        else:
            entry["match_threshold"] = _parse_match_threshold(match_threshold)
    entry.pop("alias", None)
    data[pid] = entry
    save_registry_data(data, registry_file)


def enroll_from_photo(
    photo_id: str,
    person_id: str,
    *,
    name: str | None = None,
    role: str = _DEFAULT_ROLE,
    birth_date: str = "",
    match_threshold: Any = ...,  # type: ignore[assignment]
    face_index: int = 0,
    faces_dir: Path | None = None,
    memory_dir: Path | None = None,
    photos_dir: Path | None = None,
    registry_file: Path | None = None,
    rebuild_index: bool = True,
) -> Path:
    """从相册照片裁剪人脸，写入 data/faces/{person_id}/ 并更新 registry/index。"""
    pid = _normalize_person_id(person_id)
    image_path = resolve_photo_image(photo_id, memory_dir=memory_dir, photos_dir=photos_dir)
    if image_path is None:
        raise FileNotFoundError(f"找不到 photo_id={photo_id} 对应的原图")

    faces = detect_faces(image_path)
    if not faces:
        raise RuntimeError(f"照片中未检测到人脸: {image_path}")

    if face_index == -1:
        target = max(
            faces,
            key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]),
        )
        picked_index = faces.index(target)
    else:
        if face_index < 0 or face_index >= len(faces):
            raise IndexError(
                f"face_index={face_index} 越界（该图共 {len(faces)} 张脸，可用 0..{len(faces)-1} 或 -1 取最大）"
            )
        picked_index = face_index
        target = faces[picked_index]

    ok, reason = enrollability_for_face(target)
    if not ok:
        raise RuntimeError(reason)

    root = faces_dir or FACES_DIR
    registry_path = registry_file or (root / "registry.json")
    person_dir = root / pid
    person_dir.mkdir(parents=True, exist_ok=True)
    safe_photo_id = re.sub(r"[^\w\-]+", "_", photo_id)[:80]
    output_name = f"from_{safe_photo_id}_f{picked_index}.jpg"
    output_path = person_dir / output_name

    # 偏紧裁切易导致二次检测失败；先 0.5，不行再放大到 0.8
    saved = False
    for pad in (0.5, 0.8):
        if not save_face_crop(image_path, target["bbox"], output_path, padding=pad):
            continue
        if extract_face_embedding(output_path, largest_only=True):
            saved = True
            if pad > 0.5:
                logger.info("入库裁切使用更大边距 padding=%.1f: %s", pad, output_path.name)
            break
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass

    if not saved:
        raise RuntimeError(
            "裁切后无法再次检测到人脸，未写入参考库。请换一张更大、更清晰的正脸再试。"
        )

    upsert_registry_person(
        pid,
        name=name,
        role=role,
        birth_date=birth_date,
        match_threshold=match_threshold,
        registry_file=registry_path,
    )
    logger.info(
        "已入库参考照: %s → %s (%s)",
        photo_id,
        pid,
        output_path.relative_to(root),
    )

    if rebuild_index:
        index = build_face_index(root)
        if not index.get("people"):
            raise RuntimeError("重建 index.json 失败：人脸库为空")
        save_face_index(index, root)

    return output_path


def list_registry_people(registry_file: Path | None = None) -> list[dict[str, Any]]:
    """返回 registry 成员列表（供 UI 选择已有 person_id）。"""
    data = load_registry_data(registry_file)
    items: list[dict[str, Any]] = []
    for person_id in sorted(data.keys()):
        raw = data.get(person_id)
        if not isinstance(raw, dict):
            continue
        if str(raw.get("alias", "")).strip():
            continue
        threshold = _parse_match_threshold(raw.get("match_threshold"))
        items.append(
            {
                "person_id": person_id,
                "name": str(raw.get("name") or person_id),
                "role": str(raw.get("role") or _DEFAULT_ROLE),
                "birth_date": str(raw.get("birth_date") or ""),
                "match_threshold": threshold,
                "effective_threshold": threshold if threshold is not None else FACE_MATCH_THRESHOLD,
            }
        )
    return items


def detect_faces_in_photo(
    photo_id: str,
    *,
    memory_dir: Path | None = None,
    photos_dir: Path | None = None,
) -> dict[str, Any]:
    """检测照片中的所有人脸，并尝试匹配现有人脸库。"""
    image_path = resolve_photo_image(photo_id, memory_dir=memory_dir, photos_dir=photos_dir)
    if image_path is None:
        raise FileNotFoundError(f"找不到 photo_id={photo_id} 对应的原图")

    bgr = load_image_bgr(image_path)
    if bgr is None:
        raise RuntimeError(f"无法读取图片: {image_path}")
    img_h, img_w = bgr.shape[:2]
    del bgr

    faces = detect_faces(image_path)
    index = load_face_index()
    items: list[dict[str, Any]] = []
    for i, face in enumerate(faces):
        matched: dict[str, Any] | None = None
        if index:
            person = _match_embedding(face["embedding"], index)
            if person is not None:
                matched = dict(person)
        bbox = face["bbox"]
        enrollable, enroll_skip_reason = enrollability_for_face(face)
        items.append(
            {
                "index": i,
                "bbox": [round(float(v), 1) for v in bbox],
                "det_score": round(float(face.get("det_score") or 0.0), 3),
                "enrollable": enrollable,
                "enroll_skip_reason": enroll_skip_reason,
                "matched": matched,
            }
        )

    return {
        "photo_id": photo_id,
        "source_path": str(image_path),
        "image_width": img_w,
        "image_height": img_h,
        "face_count": len(items),
        "faces": items,
        "enroll_det_score_min": FACE_ENROLL_DET_SCORE_MIN,
        "enroll_min_side": FACE_ENROLL_MIN_SIDE,
    }


def enroll_photo_face(
    photo_id: str,
    person_id: str,
    *,
    name: str | None = None,
    role: str = _DEFAULT_ROLE,
    birth_date: str = "",
    match_threshold: Any = ...,  # type: ignore[assignment]
    face_index: int = 0,
    faces_dir: Path | None = None,
    memory_dir: Path | None = None,
    photos_dir: Path | None = None,
    registry_file: Path | None = None,
    reidentify_photo: bool = True,
) -> dict[str, Any]:
    """从照片裁剪人脸入库，并可选重识别该张照片。"""
    pid = _normalize_person_id(person_id)
    if birth_date.strip() or match_threshold is not ...:
        upsert_registry_person(
            pid,
            name=name,
            role=role,
            birth_date=birth_date.strip(),
            match_threshold=match_threshold,
            registry_file=registry_file,
        )

    output = enroll_from_photo(
        photo_id,
        pid,
        name=name,
        role=role,
        birth_date=birth_date.strip(),
        match_threshold=match_threshold,
        face_index=face_index,
        faces_dir=faces_dir,
        memory_dir=memory_dir,
        photos_dir=photos_dir,
        registry_file=registry_file,
        rebuild_index=True,
    )

    root = faces_dir or FACES_DIR
    try:
        ref_rel = str(output.relative_to(root))
    except ValueError:
        ref_rel = str(output)

    result: dict[str, Any] = {
        "photo_id": photo_id,
        "person_id": pid,
        "name": name or pid,
        "ref_image": ref_rel,
        "index_rebuilt": True,
        "photo_reidentified": False,
    }

    if not reidentify_photo:
        return result

    from hub.shared.backfill import backfill_json_file
    from hub.shared.config import MEMORY_DB
    from hub.shared.index_db import sync_json_file

    mem_root = memory_dir or MEMORY_DIR
    json_path = mem_root / f"{photo_id}.json"
    if not json_path.is_file():
        return result

    status = backfill_json_file(
        json_path,
        mode="faces",
        photos_dir=photos_dir or PHOTOS_DIR,
        only_empty=False,
    )
    if status == "updated":
        sync_json_file(json_path, MEMORY_DB)
        result["photo_reidentified"] = True
    return result


@dataclass
class _RunningCluster:
    cluster_id: int
    count: int
    representative: list[float]
    photo_ids: set[str]
    sample_photo_id: str
    sample_image_path: Path
    sample_bbox: tuple[float, float, float, float]
    sample_face_index: int


def _list_face_json_candidates(
    memory_path: Path,
    limit: int,
    *,
    year: str = "",
    needs_faces: bool = False,
) -> list[Path]:
    """列出待扫描的 memory JSON（不加载原图）。

    needs_faces: 仅 face_detected 且 people 为空（库中未识别的有脸照片）
    否则: 含 face_detected 的照片
    """
    candidates: list[Path] = []
    for json_file in sorted(memory_path.glob("*.json")):
        if limit > 0 and len(candidates) >= limit:
            break
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if year and not json_matches_year(data, json_file, year):
            continue
        if needs_faces:
            if not (data.get("quality") or {}).get("face_detected"):
                continue
            if data.get("people"):
                continue
        elif not (data.get("quality") or {}).get("face_detected"):
            continue
        candidates.append(json_file)
    return candidates


def _assign_unknown_face(
    running: list[_RunningCluster],
    *,
    embedding: list[float],
    photo_id: str,
    image_path: Path,
    bbox: tuple[float, float, float, float],
    face_idx: int,
    cluster_threshold: float,
) -> None:
    for cluster in running:
        if _cosine_similarity(embedding, cluster.representative) >= cluster_threshold:
            cluster.count += 1
            cluster.photo_ids.add(photo_id)
            return
    running.append(
        _RunningCluster(
            cluster_id=len(running),
            count=1,
            representative=embedding,
            photo_ids={photo_id},
            sample_photo_id=photo_id,
            sample_image_path=image_path,
            sample_bbox=bbox,
            sample_face_index=face_idx,
        )
    )


def _scan_json_files_into_clusters(
    json_files: list[Path],
    *,
    memory_path: Path,
    photos_dir: Path,
    face_index: dict[str, Any],
    match_threshold: float,
    cluster_threshold: float,
    max_side: int,
    running: list[_RunningCluster] | None = None,
    progress_label: str = "",
) -> tuple[list[_RunningCluster], int, int]:
    """扫描一批 JSON，把未匹配人脸并入 running 聚类。返回 (running, 浏览数, 未匹配人脸数)。"""
    clusters = running if running is not None else []
    scanned = 0
    unknown_faces = 0

    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        photo_id = str(data.get("photo_id") or json_file.stem)
        image_path = resolve_photo_image(
            photo_id,
            memory_dir=memory_path,
            photos_dir=photos_dir,
        )
        if image_path is None:
            continue

        faces = detect_faces(image_path, max_side=max_side)
        if not faces:
            gc.collect()
            continue

        scanned += 1
        if progress_label and scanned % 50 == 0:
            logger.info(
                "%s: %d 张，%d 未匹配，%d 聚类",
                progress_label,
                scanned,
                unknown_faces,
                len(clusters),
            )

        for face_idx, face in enumerate(faces):
            embedding = face["embedding"]
            if _match_embedding(embedding, face_index) is not None:
                continue
            unknown_faces += 1
            _assign_unknown_face(
                clusters,
                embedding=embedding,
                photo_id=photo_id,
                image_path=image_path,
                bbox=face["bbox"],
                face_idx=face_idx,
                cluster_threshold=cluster_threshold,
            )

        del faces
        gc.collect()

    return clusters, scanned, unknown_faces


def _serialize_running_cluster(cluster: _RunningCluster) -> dict[str, Any]:
    return {
        "count": cluster.count,
        "representative": cluster.representative,
        "photo_ids": sorted(cluster.photo_ids),
        "sample_photo_id": cluster.sample_photo_id,
        "sample_image_path": str(cluster.sample_image_path),
        "sample_bbox": list(cluster.sample_bbox),
        "sample_face_index": cluster.sample_face_index,
    }


def _deserialize_running_cluster(data: dict[str, Any], cluster_id: int) -> _RunningCluster:
    return _RunningCluster(
        cluster_id=cluster_id,
        count=int(data["count"]),
        representative=list(data["representative"]),
        photo_ids=set(data.get("photo_ids") or []),
        sample_photo_id=str(data["sample_photo_id"]),
        sample_image_path=Path(str(data["sample_image_path"])),
        sample_bbox=tuple(float(v) for v in data["sample_bbox"]),
        sample_face_index=int(data["sample_face_index"]),
    )


def _merge_partial_clusters(
    running: list[_RunningCluster],
    partial: list[dict[str, Any]],
    *,
    cluster_threshold: float,
) -> None:
    for raw in partial:
        emb = raw["representative"]
        merged = False
        for cluster in running:
            if _cosine_similarity(emb, cluster.representative) >= cluster_threshold:
                cluster.count += int(raw["count"])
                cluster.photo_ids.update(raw.get("photo_ids") or [])
                merged = True
                break
        if not merged:
            running.append(_deserialize_running_cluster(raw, len(running)))


def _scan_batch_subprocess(
    json_paths: list[Path],
    *,
    memory_path: Path,
    photos_dir: Path,
    face_index: dict[str, Any],
    match_threshold: float,
    cluster_threshold: float,
    max_side: int,
) -> list[dict[str, Any]]:
    """子进程扫描一批照片，结束后释放 InsightFace 内存。"""
    out_fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    payload = {
        "json_paths": [str(p) for p in json_paths],
        "memory_dir": str(memory_path),
        "photos_dir": str(photos_dir),
        "face_index": face_index,
        "match_threshold": match_threshold,
        "cluster_threshold": cluster_threshold,
        "max_side": max_side,
        "out_path": out_path,
    }
    script = """
import json, sys
from pathlib import Path
from hub.shared.face_enroll import _scan_json_files_into_clusters, _serialize_running_cluster

payload = json.loads(sys.stdin.read())
paths = [Path(p) for p in payload["json_paths"]]
clusters, _, _ = _scan_json_files_into_clusters(
    paths,
    memory_path=Path(payload["memory_dir"]),
    photos_dir=Path(payload["photos_dir"]),
    face_index=payload["face_index"],
    match_threshold=payload["match_threshold"],
    cluster_threshold=payload["cluster_threshold"],
    max_side=payload["max_side"],
)
Path(payload["out_path"]).write_text(
    json.dumps([_serialize_running_cluster(c) for c in clusters], ensure_ascii=False),
    encoding="utf-8",
)
"""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    try:
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"分块扫描子进程失败: {err[:500]}")
        raw = Path(out_path).read_text(encoding="utf-8").strip()
        if not raw:
            return []
        return json.loads(raw)
    finally:
        Path(out_path).unlink(missing_ok=True)


def _clusters_to_results(
    running: list[_RunningCluster],
    min_count: int,
) -> list[UnknownFaceCluster]:
    results: list[UnknownFaceCluster] = []
    for cluster in running:
        if cluster.count < min_count:
            continue
        results.append(
            UnknownFaceCluster(
                cluster_id=cluster.cluster_id,
                count=cluster.count,
                photo_ids=sorted(cluster.photo_ids),
                sample_photo_id=cluster.sample_photo_id,
                sample_image_path=cluster.sample_image_path,
                sample_bbox=cluster.sample_bbox,
                sample_face_index=cluster.sample_face_index,
            )
        )
    results.sort(key=lambda item: item.count, reverse=True)
    return results


def scan_unknown_face_clusters(
    *,
    memory_dir: Path | None = None,
    photos_dir: Path | None = None,
    limit: int = 500,
    index: dict[str, Any] | None = None,
    cluster_threshold: float = 0.55,
    min_count: int = 6,
    max_side: int = 1280,
    chunk_size: int = 200,
    year: str = "",
    needs_faces: bool = False,
) -> list[UnknownFaceCluster]:
    """流式扫描 + 在线聚类；大批量自动分块子进程，避免 InsightFace 内存累积。"""
    face_index = index or load_face_index()
    if face_index is None:
        raise RuntimeError("index.json 不存在，请先运行 python tools/face_enroll/main.py build")

    memory_path = memory_dir or MEMORY_DIR
    photos_path = photos_dir or PHOTOS_DIR
    match_threshold = float(face_index.get("threshold", FACE_MATCH_THRESHOLD))

    candidates = _list_face_json_candidates(
        memory_path, limit, year=year, needs_faces=needs_faces
    )
    if not candidates:
        if needs_faces:
            logger.info("没有找到「有脸但 people 为空、库中未识别」的照片")
        elif year:
            logger.info("没有找到 %s 年含 face_detected 的照片 JSON", year)
        else:
            logger.info("没有找到含 face_detected 的照片 JSON")
        return []

    scope = (
        "有脸未识别"
        if needs_faces
        else (f"{year} 年" if year else "不限年份")
    )
    use_chunks = chunk_size > 0 and len(candidates) > chunk_size
    running: list[_RunningCluster] = []
    total_scanned = 0
    total_unknown = 0

    if use_chunks:
        total_chunks = (len(candidates) + chunk_size - 1) // chunk_size
        logger.info(
            "分 %d 块扫描 %d 张（%s，每块 %d 张，子进程释放内存）",
            total_chunks,
            len(candidates),
            scope,
            chunk_size,
        )
        for chunk_idx in range(total_chunks):
            start = chunk_idx * chunk_size
            batch = candidates[start : start + chunk_size]
            label = f"块 {chunk_idx + 1}/{total_chunks}"
            logger.info("%s: 开始（%d 张）", label, len(batch))
            partial = _scan_batch_subprocess(
                batch,
                memory_path=memory_path,
                photos_dir=photos_path,
                face_index=face_index,
                match_threshold=match_threshold,
                cluster_threshold=cluster_threshold,
                max_side=max_side,
            )
            _merge_partial_clusters(running, partial, cluster_threshold=cluster_threshold)
            total_scanned += len(batch)
            logger.info(
                "%s: 完成，累计 %d 张，当前 %d 个聚类",
                label,
                total_scanned,
                len(running),
            )
            gc.collect()
    else:
        if needs_faces:
            logger.info("扫描 %d 张有脸未识别照片", len(candidates))
        running, total_scanned, total_unknown = _scan_json_files_into_clusters(
            candidates,
            memory_path=memory_path,
            photos_dir=photos_path,
            face_index=face_index,
            match_threshold=match_threshold,
            cluster_threshold=cluster_threshold,
            max_side=max_side,
            progress_label="扫描进度",
        )

    logger.info(
        "未知人脸扫描完成：浏览 %d 张含脸照片，%d 个聚类（出现≥%d 次的有 %d 个）",
        total_scanned,
        len(running),
        min_count,
        sum(1 for c in running if c.count >= min_count),
    )
    return _clusters_to_results(running, min_count)


def collect_unknown_faces(
    *,
    memory_dir: Path | None = None,
    photos_dir: Path | None = None,
    limit: int = 500,
    index: dict[str, Any] | None = None,
    max_side: int = 1600,
) -> list[FaceObservation]:
    """扫描 memory JSON，收集未匹配到人脸库的 embedding（小批量用）。"""
    face_index = index or load_face_index()
    if face_index is None:
        raise RuntimeError("index.json 不存在，请先运行 python tools/face_enroll/main.py build")

    memory_path = memory_dir or MEMORY_DIR
    threshold = float(face_index.get("threshold", FACE_MATCH_THRESHOLD))
    observations: list[FaceObservation] = []
    scanned = 0

    for json_file in sorted(memory_path.glob("*.json")):
        if limit > 0 and scanned >= limit:
            break
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        quality = data.get("quality") or {}
        if not quality.get("face_detected"):
            continue

        photo_id = str(data.get("photo_id") or json_file.stem)
        image_path = resolve_photo_image(
            photo_id,
            memory_dir=memory_path,
            photos_dir=photos_dir,
        )
        if image_path is None:
            continue

        faces = detect_faces(image_path, max_side=max_side)
        gc.collect()
        if not faces:
            continue

        scanned += 1
        for face_idx, face in enumerate(faces):
            embedding = face["embedding"]
            if _match_embedding(embedding, face_index) is not None:
                continue
            observations.append(
                FaceObservation(
                    photo_id=photo_id,
                    image_path=image_path,
                    face_index=face_idx,
                    bbox=face["bbox"],
                    embedding=embedding,
                )
            )

    logger.info(
        "未知人脸扫描完成：浏览 %d 张含脸照片，收集 %d 个未匹配人脸",
        scanned,
        len(observations),
    )
    return observations


def cluster_unknown_faces(
    observations: list[FaceObservation],
    *,
    cluster_threshold: float = 0.55,
    min_count: int = 6,
) -> list[UnknownFaceCluster]:
    """按 embedding 相似度聚类未知人脸。"""
    if not observations:
        return []

    assigned = [-1] * len(observations)
    clusters: list[list[int]] = []
    cluster_id = 0

    for i, obs in enumerate(observations):
        if assigned[i] >= 0:
            continue
        group = [i]
        assigned[i] = cluster_id
        for j in range(i + 1, len(observations)):
            if assigned[j] >= 0:
                continue
            score = _cosine_similarity(obs.embedding, observations[j].embedding)
            if score >= cluster_threshold:
                group.append(j)
                assigned[j] = cluster_id
        clusters.append(group)
        cluster_id += 1

    results: list[UnknownFaceCluster] = []
    for cid, indices in enumerate(clusters):
        if len(indices) < min_count:
            continue
        photo_ids: list[str] = []
        seen_photos: set[str] = set()
        for idx in indices:
            pid = observations[idx].photo_id
            if pid not in seen_photos:
                seen_photos.add(pid)
                photo_ids.append(pid)
        sample_idx = indices[0]
        sample = observations[sample_idx]
        results.append(
            UnknownFaceCluster(
                cluster_id=cid,
                count=len(indices),
                photo_ids=sorted(photo_ids),
                sample_photo_id=sample.photo_id,
                sample_image_path=sample.image_path,
                sample_bbox=sample.bbox,
                sample_face_index=sample.face_index,
            )
        )

    results.sort(key=lambda item: item.count, reverse=True)
    return results


def format_cluster_report(clusters: list[UnknownFaceCluster], *, top: int = 20) -> str:
    if not clusters:
        return "没有发现达到最小出现次数的未知人脸聚类。"

    lines = [f"共 {len(clusters)} 个未知人脸聚类（展示前 {min(top, len(clusters))} 个）："]
    for cluster in clusters[:top]:
        samples = ", ".join(cluster.photo_ids[:5])
        if len(cluster.photo_ids) > 5:
            samples += f" … 等 {len(cluster.photo_ids)} 张"
        lines.append(
            f"- #{cluster.cluster_id}: 出现 {cluster.count} 次 | 示例 {samples}"
        )
    lines.append("")
    lines.append("自动入库: python tools/face_enroll/main.py cluster --auto")
    lines.append("交互确认: python tools/face_enroll/main.py cluster --apply")
    return "\n".join(lines)


def _next_auto_person_id(
    registry: dict[str, Any],
    *,
    prefix: str = "unk",
    reserved: set[str] | None = None,
) -> str:
    taken = set(registry.keys()) | (reserved or set())
    max_n = 0
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d{{3}})$")
    for key in taken:
        match = pattern.match(key)
        if match:
            max_n = max(max_n, int(match.group(1)))
    for n in range(max_n + 1, max_n + 10000):
        pid = f"{prefix}_{n:03d}"
        if pid not in taken:
            return pid
    raise RuntimeError("无法分配新的 auto person_id")


def auto_cluster_enrollments(
    clusters: list[UnknownFaceCluster],
    *,
    faces_dir: Path | None = None,
    registry_file: Path | None = None,
    default_role: str = _DEFAULT_ROLE,
    min_count: int = 6,
    id_prefix: str = "unk",
    max_samples: int = 1,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """自动将聚类入库：建目录、裁剪参考照、写 registry 占位（name=person_id，待人工改名）。"""
    root = faces_dir or FACES_DIR
    registry_path = registry_file or (root / "registry.json")
    registry = load_registry_data(registry_path)
    reserved: set[str] = set()
    results: list[dict[str, Any]] = []

    for cluster in clusters:
        if cluster.count < min_count:
            continue

        person_id = _next_auto_person_id(registry, prefix=id_prefix, reserved=reserved)
        reserved.add(person_id)
        photo_ids = cluster.photo_ids[: max(1, max_samples)]
        saved: list[str] = []

        if not dry_run:
            for photo_id in photo_ids:
                try:
                    output = enroll_from_photo(
                        photo_id,
                        person_id,
                        name=person_id,
                        role=default_role,
                        face_index=cluster.sample_face_index if photo_id == cluster.sample_photo_id else -1,
                        faces_dir=root,
                        registry_file=registry_path,
                        rebuild_index=False,
                    )
                    saved.append(output.name)
                except (ValueError, FileNotFoundError, RuntimeError, IndexError) as exc:
                    logger.warning("自动入库跳过 %s → %s: %s", photo_id, person_id, exc)

            if not saved:
                reserved.discard(person_id)
                continue

            registry = load_registry_data(registry_path)

        results.append(
            {
                "person_id": person_id,
                "name": person_id,
                "role": default_role,
                "count": cluster.count,
                "photo_count": len(cluster.photo_ids),
                "sample_photo_id": cluster.sample_photo_id,
                "saved_files": saved,
            }
        )
        logger.info(
            "自动入库: %s（出现 %d 次，示例 %s）→ 请编辑 registry.json 改名",
            person_id,
            cluster.count,
            cluster.sample_photo_id,
        )

    if results and not dry_run:
        index = build_face_index(root)
        save_face_index(index, root)
        logger.info("已重建 index.json（+%d 人）", len(results))

    return results


def format_auto_enroll_report(results: list[dict[str, Any]]) -> str:
    if not results:
        return "没有自动入库的新面孔。"

    lines = [
        f"已自动入库 {len(results)} 人（请在 data/faces/registry.json 里改 name / role）：",
        "",
    ]
    for item in results:
        lines.append(
            f"- {item['person_id']}: 出现 {item['count']} 次 / "
            f"{item['photo_count']} 张照片 | 示例 {item['sample_photo_id']}"
        )
    lines.extend(
        [
            "",
            "下一步：",
            "  1. 编辑 data/faces/registry.json（unk_001 → 中文名、role）",
            "  2. python tools/face_enroll/main.py build",
            "  3. python tools/photo2json/main.py --backfill faces",
        ]
    )
    return "\n".join(lines)


def apply_cluster_enrollments(
    clusters: list[UnknownFaceCluster],
    *,
    faces_dir: Path | None = None,
    default_role: str = _DEFAULT_ROLE,
    min_count: int = 6,
    interactive: bool = True,
) -> int:
    """交互式将聚类代表照片入库。"""
    enrolled = 0
    root = faces_dir or FACES_DIR

    for cluster in clusters:
        if cluster.count < min_count:
            continue
        print(
            f"\n聚类 #{cluster.cluster_id}: 出现 {cluster.count} 次，"
            f"涉及 {len(cluster.photo_ids)} 张照片"
        )
        print(f"  示例: {cluster.sample_photo_id}")
        preview = ", ".join(cluster.photo_ids[:8])
        if len(cluster.photo_ids) > 8:
            preview += " …"
        print(f"  照片: {preview}")

        if interactive:
            person_id = input("  person_id（回车跳过）: ").strip()
            if not person_id:
                print("  已跳过")
                continue
            display_name = input(f"  显示名 [{person_id}]: ").strip() or person_id
            role = input(f"  role [{default_role}]: ").strip() or default_role
        else:
            continue

        try:
            enroll_from_photo(
                cluster.sample_photo_id,
                person_id,
                name=display_name,
                role=role,
                face_index=cluster.sample_face_index,
                faces_dir=root,
                rebuild_index=False,
            )
            enrolled += 1
        except (ValueError, FileNotFoundError, RuntimeError, IndexError) as exc:
            logger.error("入库失败: %s", exc)
            print(f"  入库失败: {exc}")

    if enrolled:
        index = build_face_index(root)
        save_face_index(index, root)
        logger.info("已重建 index.json（+%d 人）", enrolled)
    return enrolled
