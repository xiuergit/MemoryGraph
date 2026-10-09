"""把已选记忆照片推到剪纸台「排版打印」作业篮（只拷候选，不共享全库）。"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image, ImageOps

from hub.shared.config import (
    MEMORY_DIR,
    PAPER_CUT_ROOT,
    PAPER_CUT_STUDIO_URL,
    SUPPORTED_EXTENSIONS,
)
from hub.shared.photo_links import resolve_photo_path

logger = logging.getLogger(__name__)

_PRINTABLE = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_HEIC = {".heic", ".heif"}
_JOB_PREFIX = "_mg_"
_MAX_PHOTOS = 24
_JOB_ID_RE = re.compile(r"^_mg_\d{8}_\d{6}(_[a-z0-9]+)?$")


@dataclass
class OutboxItem:
    photo_id: str
    file: str
    caption: str = ""
    timestamp: str = ""
    location: str = ""


@dataclass
class OutboxResult:
    job_id: str
    theme: str
    folder: str
    studio_url: str
    copied: list[OutboxItem] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    pruned: int = 0


def paper_cut_src_root() -> Path:
    root = Path(PAPER_CUT_ROOT).expanduser().resolve()
    return root / "原图"


def _new_job_id() -> str:
    return f"{_JOB_PREFIX}{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _load_memory(photo_id: str) -> dict[str, Any]:
    path = MEMORY_DIR / f"{photo_id}.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _default_caption(data: dict[str, Any]) -> str:
    location = str(data.get("location") or "").strip()
    ts = str(data.get("timestamp") or "").strip()
    day = ts[:10] if len(ts) >= 10 else ""
    scene = str(data.get("scene") or "").strip()
    parts = [p for p in (day, location or scene) if p]
    return " · ".join(parts)


def _safe_stem(photo_id: str) -> str:
    stem = re.sub(r"[^\w.\-]+", "_", photo_id, flags=re.UNICODE).strip("._")
    return (stem or "photo")[:80]


def _copy_as_printable(src: Path, dest_dir: Path, photo_id: str) -> Path:
    """拷到作业目录；HEIC 转 JPEG，其余可打印格式原样复制。"""
    suffix = src.suffix.lower()
    stem = _safe_stem(photo_id)
    if suffix in _HEIC or suffix not in _PRINTABLE:
        dest = dest_dir / f"{stem}.jpg"
        with Image.open(src) as img:
            rgb = ImageOps.exif_transpose(img)
            if rgb.mode not in ("RGB", "L"):
                rgb = rgb.convert("RGB")
            elif rgb.mode == "L":
                rgb = rgb.convert("RGB")
            rgb.save(dest, format="JPEG", quality=92, optimize=True)
        return dest

    dest = dest_dir / f"{stem}{suffix}"
    if dest.exists():
        dest = dest_dir / f"{stem}_{src.stem[:8]}{suffix}"
    shutil.copy2(src, dest)
    return dest


def prune_old_jobs(*, keep_days: int = 7) -> int:
    """删除过期的 _mg_* 作业主题目录。"""
    src_root = paper_cut_src_root()
    if not src_root.is_dir() or keep_days < 0:
        return 0
    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    for folder in src_root.iterdir():
        if not folder.is_dir() or not folder.name.startswith(_JOB_PREFIX):
            continue
        if not _JOB_ID_RE.match(folder.name):
            continue
        try:
            mtime = datetime.fromtimestamp(folder.stat().st_mtime)
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        try:
            shutil.rmtree(folder)
            removed += 1
        except OSError as exc:
            logger.warning("清理打印作业失败 %s: %s", folder, exc)
    return removed


def create_print_outbox(
    photo_ids: list[str],
    *,
    captions: dict[str, str] | None = None,
    open_select_all: bool = True,
    prune_days: int = 7,
) -> OutboxResult:
    """
    将 photo_ids 拷入 剪纸/原图/_mg_<job>/，写 manifest，返回剪纸排版深链。
    """
    ids = [str(pid).strip() for pid in photo_ids if str(pid).strip()]
    # 保序去重
    seen: set[str] = set()
    ordered: list[str] = []
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        ordered.append(pid)

    if not ordered:
        raise ValueError("请至少选择一张照片")
    if len(ordered) > _MAX_PHOTOS:
        raise ValueError(f"一次最多 {_MAX_PHOTOS} 张，请缩小选择")

    src_root = paper_cut_src_root()
    if not PAPER_CUT_ROOT or not Path(PAPER_CUT_ROOT).expanduser().is_dir():
        raise FileNotFoundError(
            f"未找到剪纸仓库：{PAPER_CUT_ROOT}。"
            "请在 .env 设置 PAPER_CUT_ROOT（指向含「原图」目录的剪纸根路径）"
        )
    src_root.mkdir(parents=True, exist_ok=True)

    pruned = prune_old_jobs(keep_days=prune_days) if prune_days > 0 else 0

    job_id = _new_job_id()
    # 同秒冲突时加后缀
    folder = src_root / job_id
    if folder.exists():
        job_id = f"{job_id}_{datetime.now().strftime('%f')[:4]}"
        folder = src_root / job_id
    folder.mkdir(parents=True, exist_ok=False)

    caption_map = {str(k).strip(): str(v).strip() for k, v in (captions or {}).items()}
    copied: list[OutboxItem] = []
    failed: list[dict[str, str]] = []

    for pid in ordered:
        data = _load_memory(pid)
        src = resolve_photo_path(pid)
        if src is None or not src.is_file():
            failed.append({"photo_id": pid, "error": "找不到原图"})
            continue
        if src.suffix.lower() not in SUPPORTED_EXTENSIONS and src.suffix.lower() not in _PRINTABLE:
            failed.append({"photo_id": pid, "error": f"不支持的格式 {src.suffix}"})
            continue
        try:
            dest = _copy_as_printable(src, folder, pid)
        except Exception as exc:  # noqa: BLE001 — 单张失败不中断
            logger.warning("拷贝打印原图失败 %s: %s", pid, exc)
            failed.append({"photo_id": pid, "error": str(exc)})
            continue

        cap = caption_map.get(pid) or _default_caption(data)
        copied.append(
            OutboxItem(
                photo_id=pid,
                file=dest.name,
                caption=cap,
                timestamp=str(data.get("timestamp") or ""),
                location=str(data.get("location") or ""),
            )
        )

    if not copied:
        try:
            shutil.rmtree(folder)
        except OSError:
            pass
        raise ValueError("没有成功拷贝任何照片：" + "; ".join(
            f"{f['photo_id']}: {f['error']}" for f in failed
        ))

    manifest = {
        "job_id": job_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "MemoryGraph",
        "items": [asdict(item) for item in copied],
        "failed": failed,
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    base = PAPER_CUT_STUDIO_URL.rstrip("/")
    theme_q = quote(job_id, safe="")
    select = "all" if open_select_all else ""
    studio_url = (
        f"{base}/print/{theme_q}?source={quote('原图')}"
        f"{'&select=all' if select else ''}&per_page=4"
    )

    return OutboxResult(
        job_id=job_id,
        theme=job_id,
        folder=str(folder),
        studio_url=studio_url,
        copied=copied,
        failed=failed,
        pruned=pruned,
    )
