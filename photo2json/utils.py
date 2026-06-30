"""图片元数据读取、文件过滤等工具函数。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PIL import Image, ExifTags

from photo2json.config import SUPPORTED_EXTENSIONS
from photo2json.schema import Source

logger = logging.getLogger(__name__)

# 注册 HEIC/HEIF 解码器（若已安装 pillow-heif）
try:
    import pillow_heif  # type: ignore[import-untyped]

    pillow_heif.register_heif_opener()
except ImportError:
    logger.debug("pillow-heif 未安装，HEIC/HEIF 格式将不可用")


def is_image_file(path: Path) -> bool:
    """判断文件是否为支持的图片格式。"""
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def iter_image_files(input_dir: Path) -> list[Path]:
    """遍历目录，返回排序后的图片文件列表。"""
    if not input_dir.is_dir():
        raise NotADirectoryError(f"输入目录不存在或不是目录: {input_dir}")

    files = [p for p in input_dir.iterdir() if is_image_file(p)]
    return sorted(files, key=lambda p: p.name.lower())


def get_photo_id(image_path: Path) -> str:
    """以文件名（不含扩展名）作为 photo_id。"""
    return image_path.stem


def _parse_exif_datetime(value: str) -> str:
    """将 EXIF 日期字符串转为 ISO 8601 格式。"""
    # 常见 EXIF 格式: "2024:03:15 14:30:00"
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
        sub = exif.get_ifd(0x8769)  # Exif IFD
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
