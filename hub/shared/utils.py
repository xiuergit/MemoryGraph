"""图片元数据读取、文件过滤等工具函数。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PIL import Image, ExifTags

from hub.shared.config import SUPPORTED_EXTENSIONS
from hub.shared.geocode import resolve_location
from hub.shared.schema import AnalysisResult, Source

logger = logging.getLogger(__name__)

try:
    import pillow_heif  # type: ignore[import-untyped]

    pillow_heif.register_heif_opener()
except ImportError:
    logger.debug("pillow-heif 未安装，HEIC/HEIF 格式将不可用")


def is_image_file(path: Path) -> bool:
    """判断文件是否为支持的图片格式。"""
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def iter_image_files(input_dir: Path) -> list[Path]:
    """递归遍历目录，返回排序后的图片文件列表。"""
    if not input_dir.is_dir():
        raise NotADirectoryError(f"输入目录不存在或不是目录: {input_dir}")

    files = [p for p in input_dir.rglob("*") if is_image_file(p)]
    return sorted(files, key=lambda p: str(p.relative_to(input_dir)).lower())


def get_photo_id(image_path: Path, *, root: Path | None = None) -> str:
    """生成 photo_id。

    顶层文件用文件名（不含扩展名），子目录内用相对路径拼接，如 2025/IMG_3831 → 2025_IMG_3831。
    """
    if root is not None:
        rel = image_path.resolve().relative_to(root.resolve())
        if len(rel.parts) == 1:
            return rel.stem
        parent = "_".join(rel.parts[:-1])
        return f"{parent}_{rel.stem}"
    return image_path.stem


def _parse_exif_datetime(value: str) -> str:
    """将 EXIF 日期字符串转为 ISO 8601 格式。"""
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    return value


def _collect_exif_tags(exif) -> dict:
    """合并主 IFD 与 Exif 子 IFD 的标签（拍摄时间通常在子 IFD）。"""
    tags: dict = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
    try:
        sub = exif.get_ifd(0x8769)
        for k, v in sub.items():
            name = ExifTags.TAGS.get(k, k)
            if name not in tags:
                tags[name] = v
    except (KeyError, ValueError, TypeError):
        pass
    return tags


def extract_exif_timestamp(image_path: Path) -> str:
    """优先从 EXIF 读取拍摄时间，读取失败则返回空字符串。"""
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            if not exif:
                return ""

            tag_map = _collect_exif_tags(exif)

            for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                raw = tag_map.get(key)
                if raw and isinstance(raw, str):
                    return _parse_exif_datetime(raw)
    except Exception as exc:
        logger.debug("读取 EXIF 时间失败 %s: %s", image_path, exc)

    return ""


def _dms_to_decimal(dms: tuple, ref: str) -> float:
    """将 EXIF 度分秒坐标转为十进制度数。"""
    degrees, minutes, seconds = (float(v) for v in dms)
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def extract_exif_location(image_path: Path) -> str:
    """从 EXIF GPS 读取拍摄位置，返回 '纬度,经度' 字符串；无 GPS 则返回空字符串。"""
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            if not exif:
                return ""

            gps_ifd = exif.get_ifd(0x8825)
            if not gps_ifd:
                return ""

            gps_tags = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
            lat = gps_tags.get("GPSLatitude")
            lat_ref = gps_tags.get("GPSLatitudeRef")
            lon = gps_tags.get("GPSLongitude")
            lon_ref = gps_tags.get("GPSLongitudeRef")

            if not lat or not lon or not lat_ref or not lon_ref:
                return ""

            lat_dec = _dms_to_decimal(lat, str(lat_ref))
            lon_dec = _dms_to_decimal(lon, str(lon_ref))
            return f"{lat_dec:.6f},{lon_dec:.6f}"
    except Exception as exc:
        logger.debug("读取 EXIF GPS 失败 %s: %s", image_path, exc)

    return ""


def enrich_analysis_location(
    analysis: AnalysisResult,
    image_path: Path,
) -> tuple[AnalysisResult, str]:
    """用 EXIF GPS 填充 location（可读地名）与 location_coords（原始坐标）。"""
    exif_coords = extract_exif_location(image_path)
    if not exif_coords:
        return analysis, ""

    enriched = dict(analysis)
    enriched["location"] = resolve_location(exif_coords)
    return AnalysisResult(**enriched), exif_coords


def get_image_dimensions(image_path: Path) -> tuple[int, int]:
    """读取图片宽高，失败时返回 (0, 0)。"""
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            return int(width), int(height)
    except Exception as exc:
        logger.warning("读取图片尺寸失败 %s: %s", image_path, exc)
        return 0, 0


def build_source_info(image_path: Path) -> Source:
    """构建 source 字段：真实路径与尺寸。"""
    width, height = get_image_dimensions(image_path)
    return Source(
        path=str(image_path.resolve()),
        width=width,
        height=height,
    )
