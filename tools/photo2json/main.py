"""Mac 批量 Photo2JSON 入口。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 支持 `python tools/photo2json/main.py` 直接运行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.config import MEMORY_DIR, PHOTOS_DIR
from hub.shared.location_cluster import apply_location_normalization
from tools.photo2json.processor import process_folder


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将 data/photos/ 中的图片批量转为 data/memory/*.json",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=PHOTOS_DIR,
        help=f"图片目录（默认: {PHOTOS_DIR}）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="重新生成已存在的 JSON",
    )
    parser.add_argument(
        "--normalize-locations",
        action="store_true",
        help="仅按同日相邻照片统一 location，不跑 AI 分析",
    )
    args = parser.parse_args()

    setup_logging()
    if args.normalize_locations:
        changed = apply_location_normalization(MEMORY_DIR)
        return 0 if changed >= 0 else 1

    stats = process_folder(args.input, skip_existing=not args.force)
    return 1 if stats.failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
