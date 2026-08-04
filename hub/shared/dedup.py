"""照片去重候选：字节级重复 + 连拍近邻（仅报告，不删除）。"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from hub.shared.config import MEMORY_DB
from hub.shared.index_db import connect, init_db

logger = logging.getLogger(__name__)

DEFAULT_BURST_SECONDS = 3
HASH_CHUNK = 1024 * 1024
_QUALITY_MAX_SIDE = 512
# 画质分（0–100）在 keep_score 中的权重；低于 manual_*，高于文件大小
_QUALITY_WEIGHT = 0.85
# 无时间近哈希：dHash 汉明距离 ≤ 此值视为相似（0=几乎同一张，约 8–12 为连拍级）
DEFAULT_NEAR_HAMMING = 10


@dataclass
class PhotoCand:
    photo_id: str
    timestamp: str = ""
    location: str = ""
    location_coords: str = ""
    source_path: str = ""
    resolved_path: str = ""
    file_size: int = 0
    face_detected: bool = False
    manual_edit: bool = False
    manual_location: bool = False
    manual_people: bool = False
    manual_vision: bool = False
    people_count: int = 0
    people: list[str] = field(default_factory=list)
    overlay_anchor: bool = False
    keep_score: float = 0.0
    content_hash: str = ""
    quality_score: float = 0.0  # 0–100，清晰度+曝光；未计算为 0
    sharpness: float = 0.0  # Laplacian 方差原始值
    quality_computed: bool = False
    dhash: int = 0  # 64-bit difference hash；0 且未算过时见 dhash_ok
    dhash_ok: bool = False
    near_cluster: str = ""  # 近哈希簇 id，便于列表相邻排序


@dataclass
class DupGroup:
    kind: str  # exact_hash | burst | near_hash
    group_id: str
    reason: str
    keep_photo_id: str
    candidates: list[PhotoCand]
    drop_photo_ids: list[str]


@dataclass
class DedupReport:
    scanned: int = 0
    missing_files: int = 0
    exact_groups: int = 0
    exact_extra: int = 0
    burst_groups: int = 0
    burst_extra: int = 0
    near_groups: int = 0
    near_extra: int = 0
    untimed_count: int = 0
    untimed_photos: list[PhotoCand] = field(default_factory=list)
    groups: list[DupGroup] = field(default_factory=list)
    burst_seconds: int = DEFAULT_BURST_SECONDS
    near_hamming: int = DEFAULT_NEAR_HAMMING
    year: str = ""


def _parse_ts(timestamp: str) -> float | None:
    """解析为 epoch 秒；仅接受带时刻的 ISO（含 T），纯日期不参与连拍。"""
    text = (timestamp or "").strip()
    if not text or "T" not in text:
        return None
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _read_bgr_for_quality(path: Path, *, max_side: int = _QUALITY_MAX_SIDE):
    """读取并缩小图为 BGR ndarray；失败返回 None。"""
    import cv2
    import numpy as np
    from PIL import Image

    bgr = None
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size:
            bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except OSError:
        bgr = None

    if bgr is None:
        try:
            try:
                import pillow_heif  # type: ignore[import-untyped]

                pillow_heif.register_heif_opener()
            except ImportError:
                pass
            with Image.open(path) as img:
                rgb = np.asarray(img.convert("RGB"))
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except OSError:
            return None
        except Exception as exc:  # noqa: BLE001 — 解码失败一律跳过
            logger.debug("画质读图失败 %s: %s", path, exc)
            return None

    h, w = bgr.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / float(max(h, w))
        bgr = cv2.resize(
            bgr,
            (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return bgr


def compute_image_quality(path: Path | str) -> tuple[float, float]:
    """清晰度 + 曝光启发式 → (quality 0–100, laplacian_raw)。

    清晰度：Laplacian 方差（log 映射）。
    曝光：均值过暗/过亮、高光/暗部裁切比例惩罚。
    """
    import math

    import cv2
    import numpy as np

    file_path = Path(path)
    if not file_path.is_file():
        return 0.0, 0.0

    bgr = _read_bgr_for_quality(file_path)
    if bgr is None:
        return 0.0, 0.0

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # 手机连拍常见约数十～数百；log 映射到约 0–80
    sharp_score = min(80.0, max(0.0, (math.log1p(sharp) / math.log1p(400.0)) * 80.0))

    mean = float(np.mean(gray))
    if mean < 45:
        exposure_pen = ((45.0 - mean) / 45.0) * 22.0
    elif mean > 205:
        exposure_pen = ((mean - 205.0) / 50.0) * 22.0
    else:
        exposure_pen = 0.0

    clip_hi = float(np.mean(gray >= 250))
    clip_lo = float(np.mean(gray <= 5))
    exposure_pen += min(18.0, (clip_hi + clip_lo) * 50.0)

    quality = max(0.0, min(100.0, sharp_score + 20.0 - exposure_pen))
    return quality, sharp


def _meta_keep_score(p: PhotoCand) -> float:
    score = 0.0
    if p.manual_people:
        score += 100
    if p.manual_location:
        score += 80
    if p.manual_vision:
        score += 60
    if p.manual_edit:
        score += 40
    if p.overlay_anchor:
        score += 50
    if p.people_count:
        score += 20 + min(p.people_count, 10) * 2
    if p.location_coords:
        score += 15
    if p.face_detected:
        score += 10
    if p.location:
        score += 5
    if p.timestamp:
        score += 2
    # 略偏好更大文件（画质未算时的兜底）
    score += min(p.file_size / 1_000_000.0, 30.0)
    return score


def _keep_score(p: PhotoCand) -> float:
    score = _meta_keep_score(p)
    if p.quality_computed:
        score += p.quality_score * _QUALITY_WEIGHT
    return score


def ensure_quality_scores(photos: list[PhotoCand]) -> None:
    """就地计算画质并刷新 keep_score（已有 quality_computed 则跳过）。"""
    for p in photos:
        if p.quality_computed:
            continue
        path = p.resolved_path or p.source_path
        if path:
            try:
                q, sharp = compute_image_quality(path)
            except Exception as exc:  # noqa: BLE001
                logger.debug("画质计算失败 %s: %s", p.photo_id, exc)
                q, sharp = 0.0, 0.0
        else:
            q, sharp = 0.0, 0.0
        p.quality_score = q
        p.sharpness = sharp
        p.quality_computed = True
        p.keep_score = _keep_score(p)


def compute_dhash(path: Path | str) -> int | None:
    """Difference hash（64-bit）。视觉相似则汉明距离小。"""
    import cv2

    file_path = Path(path)
    if not file_path.is_file():
        return None
    bgr = _read_bgr_for_quality(file_path, max_side=256)
    if bgr is None:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # 9x8：横向比较相邻像素 → 8*8=64 bit
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = 0
    bit_i = 0
    for row in range(8):
        for col in range(8):
            if small[row, col] > small[row, col + 1]:
                bits |= 1 << bit_i
            bit_i += 1
    return bits


def hamming64(a: int, b: int) -> int:
    return int((a ^ b).bit_count()) if hasattr(int, "bit_count") else bin(a ^ b).count("1")


def ensure_dhashes(photos: list[PhotoCand]) -> None:
    """就地计算 dHash（仅尚未计算的）。"""
    for p in photos:
        if p.dhash_ok:
            continue
        path = p.resolved_path or p.source_path
        digest = None
        if path:
            try:
                digest = compute_dhash(path)
            except Exception as exc:  # noqa: BLE001
                logger.debug("dHash 失败 %s: %s", p.photo_id, exc)
        if digest is None:
            p.dhash = 0
            p.dhash_ok = False
        else:
            p.dhash = int(digest)
            p.dhash_ok = True


def find_near_hash_groups(
    photos: list[PhotoCand],
    *,
    max_hamming: int = DEFAULT_NEAR_HAMMING,
    score_quality: bool = True,
) -> list[DupGroup]:
    """无时间照片：按 dHash 汉明距离聚类（仅 ≥2 张的簇）。"""
    pool = [p for p in photos if p.dhash_ok]
    if len(pool) < 2:
        return []

    n = len(pool)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if hamming64(pool[i].dhash, pool[j].dhash) <= max_hamming:
                union(i, j)

    buckets: dict[int, list[PhotoCand]] = defaultdict(list)
    for i, p in enumerate(pool):
        buckets[find(i)].append(p)

    groups: list[DupGroup] = []
    for root, members in buckets.items():
        if len(members) < 2:
            continue
        cluster_id = f"near_{pool[root].photo_id}"
        for p in members:
            p.near_cluster = cluster_id
        if score_quality:
            ensure_quality_scores(members)
        ranked = sorted(
            members,
            key=lambda x: (-x.keep_score, -x.quality_score, -x.file_size, x.photo_id),
        )
        keep = ranked[0]
        # 簇内两两最大距离，便于报告
        max_d = 0
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                max_d = max(max_d, hamming64(a.dhash, b.dhash))
        q_note = (
            f" · KEEP画质 {keep.quality_score:.0f}"
            if keep.quality_computed
            else ""
        )
        groups.append(
            DupGroup(
                kind="near_hash",
                group_id=cluster_id,
                reason=(
                    f"无时间近相似 · {len(members)} 张 · "
                    f"dHash≤{max_hamming}（组内最大距离 {max_d}）{q_note}"
                ),
                keep_photo_id=keep.photo_id,
                candidates=ranked,
                drop_photo_ids=[m.photo_id for m in ranked[1:]],
            )
        )

    groups.sort(key=lambda g: (-len(g.candidates), g.group_id))
    return groups


def sort_untimed_by_near(photos: list[PhotoCand]) -> list[PhotoCand]:
    """近哈希簇内相邻；大簇优先；簇外按 dHash 数值排序便于浏览补时间。"""
    in_cluster: dict[str, list[PhotoCand]] = defaultdict(list)
    singles: list[PhotoCand] = []
    for p in photos:
        if p.near_cluster:
            in_cluster[p.near_cluster].append(p)
        else:
            singles.append(p)

    ordered: list[PhotoCand] = []
    clusters = sorted(
        in_cluster.items(),
        key=lambda item: (-len(item[1]), item[0]),
    )
    for _cid, members in clusters:
        members_sorted = sorted(
            members,
            key=lambda x: (-x.keep_score, -x.quality_score, -x.file_size, x.photo_id),
        )
        ordered.extend(members_sorted)

    singles_sorted = sorted(
        singles,
        key=lambda x: (
            x.dhash if x.dhash_ok else 1 << 63,
            1 if (x.location or "").strip() else 0,
            -x.file_size,
            x.photo_id,
        ),
    )
    ordered.extend(singles_sorted)
    return ordered


def _load_overlay_anchors(conn: sqlite3.Connection) -> set[str]:
    anchors: set[str] = set()
    try:
        rows = conn.execute("SELECT anchor_photo_ids FROM event_overlays").fetchall()
    except sqlite3.OperationalError:
        return anchors
    for row in rows:
        try:
            ids = json.loads(row["anchor_photo_ids"] or "[]")
        except json.JSONDecodeError:
            continue
        if isinstance(ids, list):
            for pid in ids:
                if str(pid).strip():
                    anchors.add(str(pid).strip())
    return anchors


def _resolve_path_fast(photo_id: str, source_path: str) -> Path | None:
    """批量去重用：只信 source_path / memory JSON，不做 photos/ 全树 rglob。"""
    if source_path:
        path = Path(source_path).expanduser()
        if path.is_file():
            return path.resolve()
    pid = (photo_id or "").strip()
    if not pid:
        return None
    from hub.shared.config import MEMORY_DIR

    json_path = MEMORY_DIR / f"{pid}.json"
    if json_path.is_file():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        src = str((data.get("source") or {}).get("path", "")).strip()
        if src:
            path = Path(src).expanduser()
            if path.is_file():
                return path.resolve()
    return None


def load_photo_candidates(
    conn: sqlite3.Connection,
    *,
    year: str = "",
    include_untimed: bool = True,
) -> list[PhotoCand]:
    """从索引加载候选照片元数据（含解析路径与文件大小）。

    year 非空时：该年有时间戳的照片；include_untimed 时额外带上 timestamp 为空的
   （无论选哪一年，方便去重时顺手删或补时间/地址）。
    """
    anchors = _load_overlay_anchors(conn)
    clauses = ["1=1"]
    params: list[Any] = []
    year = (year or "").strip()
    if year:
        if include_untimed:
            clauses.append("(p.timestamp LIKE ? OR TRIM(p.timestamp) = '')")
            params.append(f"{year}%")
        else:
            clauses.append("p.timestamp LIKE ?")
            params.append(f"{year}%")

    sql = f"""
        SELECT
            p.photo_id,
            p.timestamp,
            p.location,
            p.location_coords,
            p.source_path,
            p.face_detected,
            p.manual_edit,
            p.manual_location,
            p.manual_people,
            p.manual_vision,
            GROUP_CONCAT(DISTINCT pp.person_name) AS people
        FROM photos p
        LEFT JOIN photo_people pp ON pp.photo_id = p.photo_id
        WHERE {" AND ".join(clauses)}
        GROUP BY p.photo_id
        ORDER BY p.timestamp ASC, p.photo_id ASC
    """
    out: list[PhotoCand] = []
    for row in conn.execute(sql, params):
        people_raw = row["people"] or ""
        people = [n.strip() for n in people_raw.split(",") if n and n.strip()]
        path = _resolve_path_fast(row["photo_id"], row["source_path"] or "")
        size = 0
        resolved = ""
        if path is not None and path.is_file():
            resolved = str(path)
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
        cand = PhotoCand(
            photo_id=row["photo_id"],
            timestamp=row["timestamp"] or "",
            location=row["location"] or "",
            location_coords=row["location_coords"] or "",
            source_path=row["source_path"] or "",
            resolved_path=resolved,
            file_size=size,
            face_detected=bool(row["face_detected"]),
            manual_edit=bool(row["manual_edit"]),
            manual_location=bool(row["manual_location"]),
            manual_people=bool(row["manual_people"]),
            manual_vision=bool(row["manual_vision"]),
            people_count=len(people),
            people=people,
            overlay_anchor=row["photo_id"] in anchors,
        )
        cand.keep_score = _keep_score(cand)
        out.append(cand)
    return out


def find_exact_hash_groups(photos: list[PhotoCand]) -> tuple[list[DupGroup], int]:
    """同文件大小再算 SHA-256；相同 hash 且 ≥2 张成组。返回 (groups, missing_files)。"""
    by_size: dict[int, list[PhotoCand]] = defaultdict(list)
    missing = 0
    for p in photos:
        if not p.resolved_path or p.file_size <= 0:
            missing += 1
            continue
        by_size[p.file_size].append(p)

    groups: list[DupGroup] = []
    for size, same_size in by_size.items():
        if len(same_size) < 2:
            continue
        by_hash: dict[str, list[PhotoCand]] = defaultdict(list)
        for p in same_size:
            try:
                digest = _file_sha256(Path(p.resolved_path))
            except OSError as exc:
                logger.warning("hash 失败 %s: %s", p.photo_id, exc)
                continue
            p.content_hash = digest
            by_hash[digest].append(p)

        for digest, members in by_hash.items():
            if len(members) < 2:
                continue
            ranked = sorted(
                members,
                key=lambda x: (-x.keep_score, x.timestamp or "", x.photo_id),
            )
            keep = ranked[0]
            drops = [m.photo_id for m in ranked[1:]]
            groups.append(
                DupGroup(
                    kind="exact_hash",
                    group_id=f"hash_{digest[:12]}",
                    reason=f"相同内容 SHA-256={digest[:16]}… · {size} bytes",
                    keep_photo_id=keep.photo_id,
                    candidates=ranked,
                    drop_photo_ids=drops,
                )
            )
    groups.sort(key=lambda g: (-len(g.candidates), g.group_id))
    return groups, missing


def find_burst_groups(
    photos: list[PhotoCand],
    *,
    max_gap_seconds: int = DEFAULT_BURST_SECONDS,
    score_quality: bool = True,
) -> list[DupGroup]:
    """按时间排序，相邻间隔 ≤ max_gap_seconds 连成一组（≥2 张）。

    score_quality=True 时对组内照片算清晰度/曝光，KEEP 优先更清晰的。
    """
    timed: list[tuple[float, PhotoCand]] = []
    for p in photos:
        ts = _parse_ts(p.timestamp)
        if ts is None:
            continue
        timed.append((ts, p))
    timed.sort(key=lambda item: (item[0], item[1].photo_id))

    groups: list[DupGroup] = []
    i = 0
    while i < len(timed):
        cluster = [timed[i]]
        j = i + 1
        while j < len(timed):
            gap = timed[j][0] - cluster[-1][0]
            if gap <= max_gap_seconds:
                cluster.append(timed[j])
                j += 1
            else:
                break
        if len(cluster) >= 2:
            members = [item[1] for item in cluster]
            # 排除已是「整组同 hash」的纯字节重复（留给 exact 报告）；仍保留混合组
            hashes = {m.content_hash for m in members if m.content_hash}
            if len(hashes) == 1 and len(members) >= 2 and all(m.content_hash for m in members):
                i = j
                continue
            if score_quality:
                ensure_quality_scores(members)
            ranked = sorted(
                members,
                key=lambda x: (
                    -x.keep_score,
                    -x.quality_score if score_quality else 0.0,
                    x.timestamp or "",
                    x.photo_id,
                ),
            )
            keep = ranked[0]
            t0 = members[0].timestamp
            t1 = members[-1].timestamp
            span = cluster[-1][0] - cluster[0][0]
            q_note = ""
            if score_quality and keep.quality_computed:
                q_note = f" · KEEP画质 {keep.quality_score:.0f}"
            groups.append(
                DupGroup(
                    kind="burst",
                    group_id=f"burst_{members[0].photo_id}",
                    reason=(
                        f"连拍候选 · 间隔≤{max_gap_seconds}s · "
                        f"{len(members)} 张 · 跨度 {span:.1f}s · {t0} → {t1}{q_note}"
                    ),
                    keep_photo_id=keep.photo_id,
                    candidates=ranked,
                    drop_photo_ids=[m.photo_id for m in ranked[1:]],
                )
            )
        i = j if j > i else i + 1

    groups.sort(key=lambda g: (-len(g.candidates), g.candidates[0].timestamp or ""))
    return groups


def build_dedup_report(
    *,
    db_path: Path | None = None,
    year: str = "",
    burst_seconds: int = DEFAULT_BURST_SECONDS,
    include_hash: bool = True,
    include_burst: bool = True,
    limit_groups: int = 0,
    score_quality: bool = True,
    include_untimed: bool = True,
    untimed_limit: int = 200,
    near_hamming: int = DEFAULT_NEAR_HAMMING,
    include_near: bool = True,
) -> DedupReport:
    conn = connect(db_path or MEMORY_DB)
    init_db(conn)
    photos = load_photo_candidates(
        conn,
        year=year,
        include_untimed=include_untimed,
    )
    conn.close()

    report = DedupReport(
        scanned=len(photos),
        burst_seconds=burst_seconds,
        near_hamming=near_hamming,
        year=(year or "").strip(),
    )

    untimed = [p for p in photos if not (p.timestamp or "").strip()]
    report.untimed_count = len(untimed)

    exact: list[DupGroup] = []
    if include_hash:
        exact, missing = find_exact_hash_groups(photos)
        report.missing_files = missing
        report.exact_groups = len(exact)
        report.exact_extra = sum(len(g.drop_photo_ids) for g in exact)

    burst: list[DupGroup] = []
    if include_burst:
        burst = find_burst_groups(
            photos,
            max_gap_seconds=burst_seconds,
            score_quality=score_quality,
        )
        report.burst_groups = len(burst)
        report.burst_extra = sum(len(g.drop_photo_ids) for g in burst)

    near: list[DupGroup] = []
    if include_near and include_untimed and untimed:
        exact_member_ids: set[str] = set()
        for g in exact:
            for c in g.candidates:
                exact_member_ids.add(c.photo_id)
        near_pool = [p for p in untimed if p.photo_id not in exact_member_ids]
        ensure_dhashes(near_pool)
        # 仍给已进 exact 的无时间算 dHash，便于列表排序相邻
        ensure_dhashes([p for p in untimed if p.photo_id in exact_member_ids])
        near = find_near_hash_groups(
            near_pool,
            max_hamming=near_hamming,
            score_quality=score_quality,
        )
        report.near_groups = len(near)
        report.near_extra = sum(len(g.drop_photo_ids) for g in near)

    # 无时间列表：近哈希簇相邻，方便补时间
    if untimed:
        if include_near:
            ensure_dhashes(untimed)
            # 把 near 簇标记写回（find 已写；exact 排除的无簇仍按 dhash 排序）
            for g in near:
                for c in g.candidates:
                    c.near_cluster = g.group_id
        report.untimed_photos = sort_untimed_by_near(untimed)[: max(0, untimed_limit)]
    else:
        report.untimed_photos = []

    core = exact + burst
    if limit_groups > 0:
        core = core[:limit_groups]
    # 近哈希组始终附在后面（仅无时间），不占用连拍/字节的 limit
    report.groups = core + near
    return report


def _fmt_photo_line(p: PhotoCand, *, keep: bool) -> str:
    mark = "KEEP" if keep else "drop?"
    people = ",".join(p.people) if p.people else "-"
    flags = []
    if p.manual_location:
        flags.append("manual_loc")
    if p.manual_people:
        flags.append("manual_people")
    if p.overlay_anchor:
        flags.append("overlay_anchor")
    if p.face_detected:
        flags.append("face")
    flag_s = f" [{','.join(flags)}]" if flags else ""
    size_kb = p.file_size / 1024 if p.file_size else 0
    q = (
        f"  quality={p.quality_score:.0f}"
        if p.quality_computed
        else ""
    )
    return (
        f"  [{mark}] {p.photo_id}  score={p.keep_score:.1f}{q}  "
        f"ts={p.timestamp or '-'}  loc={p.location or '-'}  "
        f"people={people}  size={size_kb:.0f}KB{flag_s}"
    )


def format_dedup_report(report: DedupReport) -> str:
    lines: list[str] = []
    lines.append("MemoryGraph 去重候选报告（只报告，不删除）")
    lines.append("=" * 48)
    scope = f"年份 {report.year}" if report.year else "全库"
    if report.year:
        scope += " + 无时间"
    lines.append(f"范围: {scope} · 扫描 {report.scanned} 张")
    lines.append(
        f"字节重复: {report.exact_groups} 组 · 可删候选 {report.exact_extra} 张"
        + (f" · 缺原图 {report.missing_files}" if report.missing_files else "")
    )
    lines.append(
        f"连拍候选: {report.burst_groups} 组 · 间隔≤{report.burst_seconds}s · "
        f"可删候选 {report.burst_extra} 张（需人工确认）"
    )
    if report.untimed_count:
        lines.append(
            f"无时间: {report.untimed_count} 张 · 近相似 {report.near_groups} 组 / "
            f"可删候选 {report.near_extra} · 列表展示 {len(report.untimed_photos)} 张（近哈希相邻）"
        )
    lines.append("")
    lines.append(
        "保留建议: 连拍/近相似优先画质；另看 manual_* / overlay 锚点 / 人物 / GPS。"
    )
    lines.append("删除请用 Desk 或 photo_delete → data/.trash/；确认后再 memory_index sync。")
    lines.append("")

    if not report.groups and not report.untimed_photos:
        lines.append("(无候选组)")
        return "\n".join(lines)

    exact = [g for g in report.groups if g.kind == "exact_hash"]
    burst = [g for g in report.groups if g.kind == "burst"]
    near = [g for g in report.groups if g.kind == "near_hash"]

    if exact:
        lines.append(f"## 字节级重复（{len(exact)}）")
        lines.append("")
        for i, g in enumerate(exact, 1):
            lines.append(f"### E{i}. {g.group_id}")
            lines.append(g.reason)
            for p in g.candidates:
                lines.append(_fmt_photo_line(p, keep=(p.photo_id == g.keep_photo_id)))
            lines.append(f"  suggested_drop: {', '.join(g.drop_photo_ids)}")
            lines.append("")

    if burst:
        lines.append(f"## 连拍近邻（{len(burst)}）")
        lines.append("")
        for i, g in enumerate(burst, 1):
            lines.append(f"### B{i}. {g.group_id}")
            lines.append(g.reason)
            for p in g.candidates:
                lines.append(_fmt_photo_line(p, keep=(p.photo_id == g.keep_photo_id)))
            lines.append(f"  suggested_drop: {', '.join(g.drop_photo_ids)}")
            lines.append("")

    if near:
        lines.append(f"## 无时间近相似（{len(near)}）")
        lines.append("")
        for i, g in enumerate(near, 1):
            lines.append(f"### N{i}. {g.group_id}")
            lines.append(g.reason)
            for p in g.candidates:
                lines.append(_fmt_photo_line(p, keep=(p.photo_id == g.keep_photo_id)))
            lines.append(f"  suggested_drop: {', '.join(g.drop_photo_ids)}")
            lines.append("")

    if report.untimed_photos:
        lines.append(
            f"## 无时间列表（近哈希相邻 · 展示 {len(report.untimed_photos)} / 共 {report.untimed_count}）"
        )
        lines.append("")
        last_c = None
        for p in report.untimed_photos:
            if p.near_cluster and p.near_cluster != last_c:
                lines.append(f"  --- 簇 {p.near_cluster} ---")
                last_c = p.near_cluster
            elif not p.near_cluster and last_c:
                lines.append("  --- 其余 ---")
                last_c = ""
            lines.append(_fmt_photo_line(p, keep=False).replace("[drop?]", "[untimed]"))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def report_to_dict(report: DedupReport) -> dict[str, Any]:
    return {
        "scanned": report.scanned,
        "missing_files": report.missing_files,
        "exact_groups": report.exact_groups,
        "exact_extra": report.exact_extra,
        "burst_groups": report.burst_groups,
        "burst_extra": report.burst_extra,
        "near_groups": report.near_groups,
        "near_extra": report.near_extra,
        "burst_seconds": report.burst_seconds,
        "near_hamming": report.near_hamming,
        "year": report.year,
        "untimed_count": report.untimed_count,
        "untimed_photos": [asdict(c) for c in report.untimed_photos],
        "groups": [
            {
                "kind": g.kind,
                "group_id": g.group_id,
                "reason": g.reason,
                "keep_photo_id": g.keep_photo_id,
                "drop_photo_ids": g.drop_photo_ids,
                "candidates": [asdict(c) for c in g.candidates],
            }
            for g in report.groups
        ],
    }
