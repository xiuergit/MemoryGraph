"""Mac 批量 Video2JSON 入口（video.v1）。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.config import MEMORY_DIR, PHOTOS_DIR
from tools.video2json.processor import process_folder


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将 data/photos/ 中的视频批量转为 data/memory/*_v.json（video.v1）",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=PHOTOS_DIR,
        help=f"视频目录（默认: {PHOTOS_DIR}）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="重新生成已存在的 JSON",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="只写元数据（时长/尺寸/时间），不抽帧、不跑视觉/人脸",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="本次最多成功写入 N 条（已存在会跳过并继续往后找，与 photo2json --backfill --limit 同语义）",
    )
    parser.add_argument(
        "--device-id",
        default="iphone",
        help="写入 device_id（默认 iphone）",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="指定视频文件（可多个）；若不传则扫描 --input",
    )
    args = parser.parse_args()
    setup_logging()

    stats = process_folder(
        input_dir=args.input,
        memory_dir=MEMORY_DIR,
        skip_existing=not args.force,
        device_id=args.device_id,
        run_ai=not args.no_ai,
        limit=args.limit,
        files=list(args.paths) if args.paths else None,
    )
    if stats.failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
