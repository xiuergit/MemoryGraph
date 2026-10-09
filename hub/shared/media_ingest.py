"""手机 Outbox media.ingest：原图落盘 + SHA-256 去重 + 回执。

合同：docs/mobile-outbox.md §5–§6。分析异步排队，不阻塞 HTTP。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hub.shared.config import (
    INGEST_REGISTRY_FILE,
    MEMORY_DIR,
    PHOTOS_DIR,
    SUPPORTED_EXTENSIONS,
)
from hub.shared.schema import build_photo_json, empty_analysis
from hub.shared.utils import build_source_info, extract_exif_timestamp, get_photo_id

logger = logging.getLogger(__name__)

DEFAULT_TZ = ZoneInfo("Asia/Shanghai")
HASH_CHUNK = 1024 * 1024
_REGISTRY_LOCK = threading.Lock()
_ANALYZE_LOCK = threading.Lock()
_ANALYZE_QUEUE: list[tuple[Path, str]] = []
_ANALYZE_WORKER_STARTED = False

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")
_STEM_SAFE_RE = re.compile(r"[^\w.\-]+", re.UNICODE)


@dataclass
class IngestReceipt:
    """media.ingest 回执。"""

    status: str  # accepted | duplicate | conflict
    local_id: str
    photo_id: str = ""
    relative_path: str = ""
    content_hash: str = ""
    mutation_id: str = ""
    device_id: str = ""
    analyze_queued: bool = False
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class IngestError(ValueError):
    """请求不合法（由 Desk 映射为 400）。"""


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _empty_registry() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "by_hash": {},
        "by_mutation_id": {},
        "by_local_id": {},
    }


def _load_registry(path: Path | None = None) -> dict[str, Any]:
    reg_path = Path(path or INGEST_REGISTRY_FILE)
    if not reg_path.is_file():
        return _empty_registry()
    try:
        data = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("ingest registry 损坏，重建空表: %s", exc)
        return _empty_registry()
    if not isinstance(data, dict):
        return _empty_registry()
    data.setdefault("schema_version", 1)
    data.setdefault("by_hash", {})
    data.setdefault("by_mutation_id", {})
    data.setdefault("by_local_id", {})
    return data


def _save_registry(data: dict[str, Any], path: Path | None = None) -> None:
    reg_path = Path(path or INGEST_REGISTRY_FILE)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = reg_path.with_suffix(reg_path.suffix + ".tmp")
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(reg_path)


def _sanitize_local_id(local_id: str) -> str:
    raw = (local_id or "").strip()
    if not raw:
        raise IngestError("local_id 不能为空")
    cleaned = _SAFE_ID_RE.sub("", raw)
    if len(cleaned) < 4:
        raise IngestError("local_id 有效字符过少（至少 4 位字母数字/_/-）")
    return cleaned


def _short_local_id(local_id: str) -> str:
    return local_id[:8].lower()


def _sanitize_stem(filename: str | None) -> str:
    name = Path(filename or "photo").name
    stem = Path(name).stem or "photo"
    stem = _STEM_SAFE_RE.sub("_", stem).strip("._") or "photo"
    return stem[:80]


def _normalize_ext(filename: str | None, content_type: str = "") -> str:
    ext = Path(filename or "").suffix.lower()
    if not ext and content_type:
        ct = content_type.split(";")[0].strip().lower()
        guess = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/heic": ".heic",
            "image/heif": ".heif",
        }.get(ct, "")
        ext = guess
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in SUPPORTED_EXTENSIONS:
        raise IngestError(
            f"不支持的图片格式: {ext or '(无扩展名)'}；"
            f"允许 {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return ext


def _parse_year_month(
    *,
    captured_at: str = "",
    exif_timestamp: str = "",
    now: datetime | None = None,
) -> tuple[str, str]:
    """返回 (YYYY, MM)。优先 EXIF → captured_at → 当前 Asia/Shanghai。"""
    for raw in (exif_timestamp, captured_at):
        text = (raw or "").strip()
        if not text:
            continue
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=DEFAULT_TZ)
            else:
                dt = dt.astimezone(DEFAULT_TZ)
            return f"{dt.year:04d}", f"{dt.month:02d}"
        except ValueError:
            # EXIF 已是 iso 时通常可解析；再试 YYYY-MM-DD / YYYY:MM:DD
            for fmt in ("%Y-%m-%d", "%Y:%m:%d", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(text[:19], fmt)
                    return f"{dt.year:04d}", f"{dt.month:02d}"
                except ValueError:
                    continue
    dt = now or datetime.now(DEFAULT_TZ)
    return f"{dt.year:04d}", f"{dt.month:02d}"


def _exif_timestamp_from_bytes(data: bytes, suffix: str) -> str:
    """写临时文件读 EXIF；失败返回 \"\"。不落盘到 photos/。"""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            return extract_exif_timestamp(Path(tmp.name))
    except OSError as exc:
        logger.debug("临时写 EXIF 失败: %s", exc)
        return ""


def _receipt_from_entry(
    *,
    status: str,
    local_id: str,
    entry: dict[str, Any],
    mutation_id: str = "",
    message: str = "",
    analyze_queued: bool = False,
) -> IngestReceipt:
    return IngestReceipt(
        status=status,
        local_id=local_id,
        photo_id=str(entry.get("photo_id") or ""),
        relative_path=str(entry.get("relative_path") or ""),
        content_hash=str(entry.get("content_hash") or ""),
        mutation_id=mutation_id or str(entry.get("mutation_id") or ""),
        device_id=str(entry.get("device_id") or ""),
        analyze_queued=analyze_queued,
        message=message,
    )


def _mutation_lookup(
    registry: dict[str, Any], mutation_id: str
) -> tuple[str, str] | None:
    """返回 (content_hash, status) 或 None。兼容旧版纯 hash 字符串。"""
    raw = registry["by_mutation_id"].get(mutation_id)
    if not raw:
        return None
    if isinstance(raw, str):
        entry = registry["by_hash"].get(raw) or {}
        return raw, str(entry.get("status") or "accepted")
    if isinstance(raw, dict):
        h = str(raw.get("content_hash") or "")
        if not h:
            return None
        st = str(raw.get("status") or "accepted")
        return h, st
    return None


def _register_entry(
    registry: dict[str, Any],
    *,
    content_hash: str,
    photo_id: str,
    relative_path: str,
    local_id: str,
    mutation_id: str,
    device_id: str,
    status: str = "accepted",
) -> dict[str, Any]:
    entry = {
        "content_hash": content_hash,
        "photo_id": photo_id,
        "relative_path": relative_path,
        "local_id": local_id,
        "mutation_id": mutation_id,
        "device_id": device_id,
        "status": status,
        "created_at": datetime.now(DEFAULT_TZ).isoformat(),
    }
    registry["by_hash"][content_hash] = entry
    registry["by_local_id"][local_id] = content_hash
    if mutation_id:
        registry["by_mutation_id"][mutation_id] = {
            "content_hash": content_hash,
            "status": status,
        }
    return entry


def _bind_mutation(
    registry: dict[str, Any],
    *,
    mutation_id: str,
    content_hash: str,
    status: str,
) -> None:
    if not mutation_id:
        return
    registry["by_mutation_id"][mutation_id] = {
        "content_hash": content_hash,
        "status": status,
    }


def ensure_memory_stub(
    photo_id: str,
    image_path: Path,
    *,
    device_id: str = "iphone",
    timestamp: str = "",
    memory_dir: Path | None = None,
    db_path: Path | None = None,
) -> bool:
    """若 memory JSON 不存在则写空壳，供 describe 立刻写旁白。

    已存在则不覆盖（可能已有 user_note）。返回是否新建 stub。
    """
    pid = (photo_id or "").strip()
    if not pid:
        return False
    mem = Path(memory_dir or MEMORY_DIR)
    out = mem / f"{pid}.json"
    if out.is_file():
        return False
    path = Path(image_path)
    if not path.is_file():
        logger.warning("ingest stub 跳过（原图不存在）: %s → %s", pid, path)
        return False
    ts = (timestamp or "").strip() or extract_exif_timestamp(path)
    try:
        source = build_source_info(path)
    except Exception as exc:
        logger.warning("ingest stub 读尺寸失败 %s: %s", path, exc)
        source = {"path": str(path.resolve()), "width": 0, "height": 0}
    photo_json = build_photo_json(
        photo_id=pid,
        timestamp=ts,
        source=source,  # type: ignore[arg-type]
        analysis=empty_analysis(),
        device_id=(device_id or "iphone").strip() or "iphone",
    )
    mem.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(photo_json), ensure_ascii=False, indent=2) + "\n"
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(out)
    logger.info("ingest stub JSON: %s", pid)
    try:
        from hub.shared.config import MEMORY_DB
        from hub.shared.index_db import sync_json_file

        sync_json_file(out, Path(db_path) if db_path else MEMORY_DB)
    except Exception as exc:
        logger.warning("ingest stub 同步索引失败 %s: %s", pid, exc)
    return True


def _stub_after_ingest(
    *,
    photo_id: str,
    relative_path: str,
    photos_root: Path,
    device_id: str,
    timestamp: str = "",
    memory_dir: Path | None = None,
    db_path: Path | None = None,
) -> None:
    rel = (relative_path or "").strip()
    pid = (photo_id or "").strip()
    if not pid or not rel:
        return
    ensure_memory_stub(
        pid,
        Path(photos_root) / rel,
        device_id=device_id,
        timestamp=timestamp,
        memory_dir=memory_dir,
        db_path=db_path,
    )


def enqueue_analyze(image_path: Path, device_id: str = "iphone") -> None:
    """排队异步 analyze（photo2json 单张）；不阻塞调用方。"""
    global _ANALYZE_WORKER_STARTED
    path = Path(image_path)
    with _ANALYZE_LOCK:
        _ANALYZE_QUEUE.append((path, device_id or "iphone"))
        if not _ANALYZE_WORKER_STARTED:
            _ANALYZE_WORKER_STARTED = True
            threading.Thread(target=_analyze_worker_loop, daemon=True).start()


def _analyze_worker_loop() -> None:
    global _ANALYZE_WORKER_STARTED
    while True:
        with _ANALYZE_LOCK:
            if not _ANALYZE_QUEUE:
                _ANALYZE_WORKER_STARTED = False
                return
            image_path, device_id = _ANALYZE_QUEUE.pop(0)
        try:
            _run_analyze_one(image_path, device_id=device_id)
        except Exception as exc:
            logger.exception("ingest 异步分析失败 %s: %s", image_path, exc)


def _run_analyze_one(image_path: Path, *, device_id: str) -> None:
    """调用 photo2json 单张；失败只打日志，原图仍保留。

    skip_existing=True：已分析完的跳过；ingest stub / 仅有旁白的会 merge 补 AI。
    """
    from tools.photo2json.processor import process_one_image

    if not image_path.is_file():
        logger.warning("ingest 分析跳过（文件不存在）: %s", image_path)
        return
    result = process_one_image(
        image_path,
        MEMORY_DIR,
        photos_root=PHOTOS_DIR,
        skip_existing=True,
        device_id=device_id or "iphone",
    )
    logger.info("ingest 异步分析完成 %s → %s", image_path.name, result)
    if result == "success":
        try:
            from hub.shared.config import MEMORY_DB
            from hub.shared.index_db import sync_memory_dir

            sync_memory_dir(MEMORY_DIR, MEMORY_DB)
        except Exception as exc:
            logger.warning("ingest 后 sync 索引失败（可稍后手动）: %s", exc)


def ingest_photo_bytes(
    data: bytes,
    *,
    local_id: str,
    filename: str | None = None,
    content_type: str = "",
    mutation_id: str = "",
    device_id: str = "iphone",
    captured_at: str = "",
    photos_dir: Path | None = None,
    registry_path: Path | None = None,
    memory_dir: Path | None = None,
    db_path: Path | None = None,
    queue_analyze: bool = True,
) -> IngestReceipt:
    """落盘原图并回执；同时确保 memory stub JSON 存在（describe 可立刻写旁白）。

    同一字节 → duplicate；mutation/local 冲突 → conflict。
    """
    if not data:
        raise IngestError("空文件")

    safe_local = _sanitize_local_id(local_id)
    mut = (mutation_id or "").strip()
    device = (device_id or "iphone").strip() or "iphone"
    ext = _normalize_ext(filename, content_type)
    digest = sha256_bytes(data)
    photos_root = Path(photos_dir or PHOTOS_DIR).resolve()
    reg_file = Path(registry_path or INGEST_REGISTRY_FILE)
    mem_dir = Path(memory_dir) if memory_dir else None
    stub_ts = (captured_at or "").strip()

    def _ensure_stub(entry_like: dict[str, Any], *, timestamp: str = "") -> None:
        _stub_after_ingest(
            photo_id=str(entry_like.get("photo_id") or ""),
            relative_path=str(entry_like.get("relative_path") or ""),
            photos_root=photos_root,
            device_id=str(entry_like.get("device_id") or device),
            timestamp=timestamp or stub_ts,
            memory_dir=mem_dir,
            db_path=db_path,
        )

    with _REGISTRY_LOCK:
        registry = _load_registry(reg_file)

        # mutation_id 幂等 / 冲突
        if mut:
            looked = _mutation_lookup(registry, mut)
            if looked:
                prev_hash, prev_status = looked
                prev = registry["by_hash"].get(prev_hash) or {}
                if prev_hash == digest:
                    stored = prev_status if prev_status in ("accepted", "duplicate") else "accepted"
                    _ensure_stub({**prev, "content_hash": prev_hash})
                    return _receipt_from_entry(
                        status=stored,
                        local_id=safe_local,
                        entry={**prev, "content_hash": prev_hash},
                        mutation_id=mut,
                        message="mutation_id 幂等重放",
                    )
                return IngestReceipt(
                    status="conflict",
                    local_id=safe_local,
                    photo_id=str(prev.get("photo_id") or ""),
                    relative_path=str(prev.get("relative_path") or ""),
                    content_hash=prev_hash,
                    mutation_id=mut,
                    device_id=str(prev.get("device_id") or ""),
                    message="同一 mutation_id 已绑定不同内容",
                )

        # 内容去重
        existing = registry["by_hash"].get(digest)
        if existing:
            # 同 local_id 或新 local_id 指向已有图 → duplicate，复用 photo_id
            entry = dict(existing)
            entry["content_hash"] = digest
            entry["status"] = "duplicate"
            # 记录新 local_id 映射（旁白/故事可挂到已有 id）
            registry["by_local_id"][safe_local] = digest
            _bind_mutation(
                registry,
                mutation_id=mut,
                content_hash=digest,
                status="duplicate",
            )
            # 不改 by_hash 里首次 accepted 记录的 status（保留首次）
            _save_registry(registry, reg_file)
            _ensure_stub(entry)
            return _receipt_from_entry(
                status="duplicate",
                local_id=safe_local,
                entry=entry,
                mutation_id=mut,
                message="内容哈希已存在，复用 photo_id，未写入第二份文件",
            )

        # 同 local_id 曾绑定其它哈希 → conflict（防止悄悄换图）
        prev_for_local = registry["by_local_id"].get(safe_local)
        if prev_for_local and prev_for_local != digest:
            prev = registry["by_hash"].get(prev_for_local) or {}
            return IngestReceipt(
                status="conflict",
                local_id=safe_local,
                photo_id=str(prev.get("photo_id") or ""),
                relative_path=str(prev.get("relative_path") or ""),
                content_hash=prev_for_local,
                mutation_id=mut,
                device_id=str(prev.get("device_id") or ""),
                message="同一 local_id 已绑定不同内容",
            )

        exif_ts = _exif_timestamp_from_bytes(data, ext)
        year, month = _parse_year_month(
            captured_at=captured_at,
            exif_timestamp=exif_ts,
        )
        short = _short_local_id(safe_local)
        stem = _sanitize_stem(filename)
        out_name = f"ob_{short}_{stem}{ext}"
        rel = Path(year) / month / out_name
        dest = photos_root / rel
        stub_ts_resolved = stub_ts or exif_ts

        if dest.exists():
            try:
                on_disk = sha256_file(dest)
            except OSError:
                on_disk = ""
            if on_disk == digest:
                photo_id = get_photo_id(dest, root=photos_root)
                entry = _register_entry(
                    registry,
                    content_hash=digest,
                    photo_id=photo_id,
                    relative_path=str(rel).replace("\\", "/"),
                    local_id=safe_local,
                    mutation_id=mut,
                    device_id=device,
                    status="duplicate",
                )
                _save_registry(registry, reg_file)
                _ensure_stub(entry, timestamp=stub_ts_resolved)
                return _receipt_from_entry(
                    status="duplicate",
                    local_id=safe_local,
                    entry=entry,
                    mutation_id=mut,
                    message="目标路径已存在且内容相同",
                )
            return IngestReceipt(
                status="conflict",
                local_id=safe_local,
                photo_id=get_photo_id(dest, root=photos_root),
                relative_path=str(rel).replace("\\", "/"),
                content_hash=on_disk,
                mutation_id=mut,
                device_id=device,
                message="目标路径已存在且内容不同，未覆盖",
            )

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_dest = dest.with_suffix(dest.suffix + ".partial")
        try:
            tmp_dest.write_bytes(data)
            tmp_dest.replace(dest)
        except OSError as exc:
            if tmp_dest.exists():
                try:
                    tmp_dest.unlink()
                except OSError:
                    pass
            raise IngestError(f"落盘失败: {exc}") from exc

        photo_id = get_photo_id(dest, root=photos_root)
        entry = _register_entry(
            registry,
            content_hash=digest,
            photo_id=photo_id,
            relative_path=str(rel).replace("\\", "/"),
            local_id=safe_local,
            mutation_id=mut,
            device_id=device,
        )
        _save_registry(registry, reg_file)

    _ensure_stub(entry, timestamp=stub_ts_resolved)

    analyze_queued = False
    if queue_analyze:
        enqueue_analyze(dest, device_id=device)
        analyze_queued = True

    return _receipt_from_entry(
        status="accepted",
        local_id=safe_local,
        entry=entry,
        mutation_id=mut,
        analyze_queued=analyze_queued,
        message="已落盘（含 memory stub）",
    )
