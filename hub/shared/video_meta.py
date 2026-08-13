"""视频元数据与关键帧（OpenCV + QuickTime ISO6709 + macOS mdls；不依赖 ffmpeg）。"""

from __future__ import annotations

import logging
import re
import struct
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from hub.shared.config import (
    PHOTOS_DIR,
    SUPPORTED_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    VIDEO_FRAME_CACHE_DIR,
)
from hub.shared.utils import get_photo_id

logger = logging.getLogger(__name__)

# Apple QuickTime / iPhone：+lat+lon+alt/ 或 +lat+lon/
_ISO6709_RE = re.compile(
    rb"([+-]\d{1,2}\.\d+)([+-]\d{1,3}\.\d+)(?:[+-]\d+(?:\.\d+)?)?/"
)


@dataclass
class VideoProbe:
    width: int
    height: int
    duration_s: float
    fps: float | None
    container: str
    timestamp: str
    location_coords: str


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def iter_video_files(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise NotADirectoryError(f"输入目录不存在或不是目录: {input_dir}")
    files = [p for p in input_dir.rglob("*") if is_video_file(p)]
    return sorted(files, key=lambda p: str(p.relative_to(input_dir)).lower())


def get_video_id(video_path: Path, *, root: Path | None = None) -> str:
    """相对 photos/ 的 stem + `_v`，避免与同 stem 静图 photo_id 冲突。"""
    return f"{get_photo_id(video_path, root=root or PHOTOS_DIR)}_v"


def find_live_photo_still(video_path: Path) -> Path | None:
    """同目录同 stem 的静图（Live Photo 配对）。"""
    stem_path = video_path.with_suffix("")
    for ext in sorted(SUPPORTED_EXTENSIONS):
        candidate = Path(str(stem_path) + ext)
        if candidate.is_file():
            return candidate
        # 常见大写扩展名
        upper = Path(str(stem_path) + ext.upper())
        if upper.is_file():
            return upper
    return None


def _mdls_raw(path: Path, key: str) -> str:
    try:
        out = subprocess.run(
            ["mdls", "-raw", "-name", key, str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("mdls 失败 %s %s: %s", key, path, exc)
        return ""
    text = (out.stdout or "").strip()
    if not text or text == "(null)":
        return ""
    return text


def _parse_mdls_datetime(raw: str) -> str:
    """mdls 日期 → 本地 naive ISO（与照片 EXIF 风格接近）。"""
    raw = raw.strip()
    if not raw:
        return ""
    # 例: 2026-08-02 08:06:55 +0000
    m = re.match(
        r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?: ([+-]\d{4}|[+-]\d{2}:\d{2}|Z))?",
        raw,
    )
    if not m:
        return ""
    date_s, time_s, tz_s = m.group(1), m.group(2), m.group(3)
    try:
        if not tz_s:
            return f"{date_s}T{time_s}"
        if tz_s == "Z":
            dt = datetime.fromisoformat(f"{date_s}T{time_s}+00:00")
        elif len(tz_s) == 5 and tz_s[0] in "+-":
            # +0000
            dt = datetime.strptime(f"{date_s}T{time_s}{tz_s}", "%Y-%m-%dT%H:%M:%S%z")
        else:
            dt = datetime.fromisoformat(f"{date_s}T{time_s}{tz_s}")
        local = dt.astimezone().replace(tzinfo=None)
        return local.isoformat(timespec="seconds")
    except ValueError:
        return f"{date_s}T{time_s}"


def _probe_mdls(path: Path) -> tuple[str, str, float | None]:
    """返回 (timestamp_iso, location_coords, duration_s_or_none)。"""
    created = _mdls_raw(path, "kMDItemContentCreationDate")
    if not created:
        created = _mdls_raw(path, "kMDItemDateAdded")
    timestamp = _parse_mdls_datetime(created)

    lat = _mdls_raw(path, "kMDItemLatitude")
    lon = _mdls_raw(path, "kMDItemLongitude")
    coords = ""
    try:
        if lat and lon:
            coords = f"{float(lat):.6f},{float(lon):.6f}"
    except ValueError:
        coords = ""

    duration: float | None = None
    dur_raw = _mdls_raw(path, "kMDItemDurationSeconds")
    try:
        if dur_raw:
            duration = float(dur_raw)
    except ValueError:
        duration = None

    return timestamp, coords, duration


def _parse_iso6709_to_coords(raw: str) -> str:
    """ISO 6709 字符串 → '纬度,经度'；失败返回空串。"""
    text = raw.strip().strip("\x00")
    m = re.match(
        r"^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)(?:[+-]\d+(?:\.\d+)?)?/?$",
        text,
    )
    if not m:
        return ""
    try:
        lat = float(m.group(1))
        lon = float(m.group(2))
    except ValueError:
        return ""
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return ""
    return f"{lat:.6f},{lon:.6f}"


def _iter_qt_atoms(data: bytes, start: int = 0, end: int | None = None):
    if end is None:
        end = len(data)
    pos = start
    while pos + 8 <= end:
        size = struct.unpack(">I", data[pos : pos + 4])[0]
        typ = data[pos + 4 : pos + 8]
        header = 8
        if size == 1 and pos + 16 <= end:
            size = struct.unpack(">Q", data[pos + 8 : pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            break
        yield typ, pos, size, header
        pos += size


def _extract_qt_location_from_meta(data: bytes) -> str:
    """从 moov/.../meta 的 keys+ilst 读 com.apple.quicktime.location.ISO6709。"""
    for typ, pos, size, header in _iter_qt_atoms(data):
        if typ != b"moov":
            continue
        moov_s, moov_e = pos + header, pos + size
        stack = [(moov_s, moov_e)]
        while stack:
            cur_s, cur_e = stack.pop()
            for typ2, pos2, size2, header2 in _iter_qt_atoms(data, cur_s, cur_e):
                body_s, body_e = pos2 + header2, pos2 + size2
                if typ2 in (b"udta", b"trak", b"mdia", b"minf", b"stbl"):
                    stack.append((body_s, body_e))
                elif typ2 == b"meta":
                    coords = _parse_meta_keys_ilst(data, body_s + 4, body_e)
                    if coords:
                        return coords
    return ""


def _parse_meta_keys_ilst(data: bytes, start: int, end: int) -> str:
    keys: list[str] = []
    ilst_range: tuple[int, int] | None = None
    for typ, pos, size, header in _iter_qt_atoms(data, start, end):
        body_s, body_e = pos + header, pos + size
        if typ == b"keys" and body_e - body_s >= 8:
            count = struct.unpack(">I", data[body_s + 4 : body_s + 8])[0]
            p = body_s + 8
            for _ in range(count):
                if p + 8 > body_e:
                    break
                ksize = struct.unpack(">I", data[p : p + 4])[0]
                if ksize < 8 or p + ksize > body_e:
                    break
                name = data[p + 8 : p + ksize].decode("utf-8", "replace")
                keys.append(name)
                p += ksize
        elif typ == b"ilst":
            ilst_range = (body_s, body_e)

    if not keys or not ilst_range:
        return ""

    istart, iend = ilst_range
    for typ, pos, size, header in _iter_qt_atoms(data, istart, iend):
        idx = struct.unpack(">I", typ)[0]
        if not (1 <= idx <= len(keys)):
            continue
        key = keys[idx - 1]
        if "location" not in key.lower() and "xyz" not in key.lower():
            continue
        for ctyp, cpos, csize, cheader in _iter_qt_atoms(
            data, pos + header, pos + size
        ):
            if ctyp != b"data":
                continue
            # data: 4 type + 4 locale + payload
            payload = data[cpos + cheader + 8 : cpos + csize]
            for decoder in ("utf-8", "ascii"):
                try:
                    text = payload.decode(decoder).strip("\x00").strip()
                except UnicodeDecodeError:
                    continue
                coords = _parse_iso6709_to_coords(text)
                if coords:
                    return coords
    return ""


def _extract_iso6709_coords_scan(data: bytes) -> str:
    """整文件扫描 ISO6709 字面量（keys 表之外仍常有一份）。"""
    m = _ISO6709_RE.search(data)
    if not m:
        return ""
    try:
        text = m.group(0).decode("ascii")
    except UnicodeDecodeError:
        return ""
    return _parse_iso6709_to_coords(text)


def extract_video_location_coords(path: Path) -> str:
    """从视频文件读取 GPS：mdls → QuickTime meta → ISO6709 扫描。"""
    _ts, coords_mdls, _dur = _probe_mdls(path)
    if coords_mdls:
        return coords_mdls
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.debug("读取视频失败 %s: %s", path, exc)
        return ""
    return (
        _extract_qt_location_from_meta(data)
        or _extract_iso6709_coords_scan(data)
    )


def _probe_opencv(path: Path) -> tuple[int, int, float, float | None]:
    """返回 (width, height, duration_s, fps)。"""
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {path}")
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        if fps > 1e-3 and frame_count > 0:
            duration_s = frame_count / fps
        else:
            # 部分容器 FRAME_COUNT 不可靠：读到末尾估时
            duration_s = 0.0
            if cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 1.0):
                duration_s = max(0.0, float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0)
        fps_out: float | None = fps if fps > 1e-3 else None
        return width, height, float(duration_s), fps_out
    finally:
        cap.release()


def probe_video(path: Path) -> VideoProbe:
    """读取视频宽高/时长/时间/GPS（尽力而为）。"""
    width, height, duration_cv, fps = _probe_opencv(path)
    timestamp, coords_mdls, duration_mdls = _probe_mdls(path)
    duration_s = duration_mdls if duration_mdls and duration_mdls > 0 else duration_cv
    if not timestamp:
        # 回退文件 mtime
        ts = datetime.fromtimestamp(path.stat().st_mtime)
        timestamp = ts.isoformat(timespec="seconds")
    if coords_mdls:
        coords = coords_mdls
    else:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            logger.debug("读取视频失败 %s: %s", path, exc)
            coords = ""
        else:
            coords = (
                _extract_qt_location_from_meta(raw)
                or _extract_iso6709_coords_scan(raw)
            )
    return VideoProbe(
        width=width,
        height=height,
        duration_s=round(max(0.0, duration_s), 3),
        fps=round(fps, 3) if fps is not None else None,
        container=path.suffix.lower().lstrip("."),
        timestamp=timestamp,
        location_coords=coords,
    )


def extract_keyframe(
    video_path: Path,
    *,
    video_id: str,
    at_seconds: float | None = None,
) -> Path:
    """抽出一帧 JPEG 到 cache，供 analyze_image 使用。"""
    import cv2

    probe = probe_video(video_path)
    if at_seconds is None:
        if probe.duration_s > 2.0:
            at_seconds = 1.0
        elif probe.duration_s > 0:
            at_seconds = probe.duration_s * 0.5
        else:
            at_seconds = 0.0

    VIDEO_FRAME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = VIDEO_FRAME_CACHE_DIR / f"{video_id}.jpg"

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, at_seconds) * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"无法读取关键帧: {video_path}")
        if not cv2.imwrite(str(out), frame):
            raise RuntimeError(f"写入关键帧失败: {out}")
    finally:
        cap.release()
    return out
