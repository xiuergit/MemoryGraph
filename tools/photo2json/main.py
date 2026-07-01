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
from hub.shared.backfill import backfill_folder
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
    parser.add_argument(
        "--backfill",
        choices=["vision", "faces", "all"],
        help="在已有 JSON 上增量补全：vision=Ollama 场景/tags，faces=人脸，all=全部 AI",
    )
    parser.add_argument(
        "--has-people",
        action="store_true",
        help="与 --backfill 联用：只处理 JSON 里已识别到人脸/人物的照片",
    )
    parser.add_argument(
        "--refill",
        action="store_true",
        help="与 --backfill 联用：即使字段已有内容也重跑（默认只补空字段）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="与 --backfill 联用：本次最多更新 N 张（分批跑 Ollama）",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        metavar="SEC",
        help="与 --backfill 联用：每更新一张后暂停 SEC 秒（默认 0）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        metavar="N",
        help="与 --backfill 联用：每更新 N 张后额外休息（配合 --batch-rest）",
    )
    parser.add_argument(
        "--batch-rest",
        type=float,
        default=0.0,
        metavar="SEC",
        help="与 --backfill 联用：每 batch-size 张后额外休息 SEC 秒",
    )
    args = parser.parse_args()

    setup_logging()
    if args.normalize_locations:
        changed = apply_location_normalization(MEMORY_DIR)
        return 0 if changed >= 0 else 1

    if args.backfill:
        stats = backfill_folder(
            photos_dir=args.input,
            mode=args.backfill,
            only_empty=not args.refill,
            has_people=args.has_people,
            limit=args.limit,
            sleep_sec=args.sleep,
            batch_size=args.batch_size,
            batch_rest_sec=args.batch_rest,
        )
        if args.backfill in ("vision", "all"):
            apply_location_normalization(MEMORY_DIR)
        return 1 if stats.failed > 0 else 0

    stats = process_folder(args.input, skip_existing=not args.force)
    return 1 if stats.failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
