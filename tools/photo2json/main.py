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
from hub.shared.location_cluster import (
    apply_location_normalization,
    regeocode_locations_from_memory,
)
from hub.shared.backfill import backfill_folder
from hub.shared.people_cleanup import (
    strip_low_confidence_people_from_memory,
    strip_outfit_people_from_memory,
)
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
        "--regeocode-locations",
        action="store_true",
        help="按 JSON 的 location_coords 重新逆地理并覆盖 location（不需原图）",
    )
    parser.add_argument(
        "--no-normalize-after",
        action="store_true",
        help="与 --regeocode-locations 联用：重算后不跑同日地点归一",
    )
    parser.add_argument(
        "--backfill",
        choices=["vision", "faces", "all", "weather"],
        help="在已有 JSON 上增量补全：vision/faces/all=AI；weather=日天气（Open-Meteo，不需原图）",
    )
    parser.add_argument(
        "--has-people",
        action="store_true",
        help="与 --backfill 联用：只处理 people 非空的照片",
    )
    parser.add_argument(
        "--needs-faces",
        action="store_true",
        help="与 --backfill faces 联用：只处理 face_detected 且 people 为空的照片",
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
    parser.add_argument(
        "--year",
        default="",
        help="与 --backfill 联用：只处理某年的 JSON（timestamp / photos/2025/ / 文件名）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="与 --backfill 联用：续跑模式，跳过已有内容（与 --refill 互斥）",
    )
    parser.add_argument(
        "--fill-timestamps",
        action="store_true",
        help="补全空 timestamp：按同文件夹文件名顺序，前后邻居同日则写入该日（YYYY-MM-DD）",
    )
    parser.add_argument(
        "--fill-mode",
        choices=["neighbors-same-day"],
        default="neighbors-same-day",
        help="与 --fill-timestamps 联用（默认 neighbors-same-day）",
    )
    parser.add_argument(
        "--strip-outfit-matches",
        action="store_true",
        help="移除 JSON 中 match_method=outfit 的人物，并清空 data/cache/outfit/",
    )
    parser.add_argument(
        "--strip-low-confidence",
        action="store_true",
        help="移除 JSON 中 confidence 低于阈值的 people 条目（清理遗留旧识别）",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.55,
        metavar="T",
        help="与 --strip-low-confidence 联用：低于 T 的条目删除（默认 0.55）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="与 --strip-outfit-matches / --strip-low-confidence / --fill-timestamps 联用：只统计不写文件",
    )
    args = parser.parse_args()

    setup_logging()
    if args.fill_timestamps:
        from hub.shared.timestamp_fill import fill_timestamps_from_neighbors

        stats = fill_timestamps_from_neighbors(
            mode=args.fill_mode,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        return 1 if stats.failed > 0 else 0

    if args.strip_outfit_matches:
        stats = strip_outfit_people_from_memory(
            MEMORY_DIR,
            year=args.year.strip(),
            dry_run=args.dry_run,
        )
        return 1 if stats.failed > 0 else 0

    if args.strip_low_confidence:
        stats = strip_low_confidence_people_from_memory(
            MEMORY_DIR,
            min_confidence=args.min_confidence,
            year=args.year.strip(),
            dry_run=args.dry_run,
        )
        return 1 if stats.failed > 0 else 0

    if args.regeocode_locations:
        stats = regeocode_locations_from_memory(
            MEMORY_DIR,
            limit=args.limit,
            normalize_after=not args.no_normalize_after,
        )
        return 1 if stats.failed > 0 else 0

    if args.normalize_locations:
        changed = apply_location_normalization(MEMORY_DIR)
        return 0 if changed >= 0 else 1

    if args.backfill:
        if args.resume and args.refill:
            parser.error("--resume 与 --refill 不能同时使用")
        if args.backfill == "weather":
            from hub.shared.weather import backfill_weather_folder

            if args.has_people or args.needs_faces:
                parser.error("--backfill weather 不支持 --has-people / --needs-faces")
            stats = backfill_weather_folder(
                MEMORY_DIR,
                only_empty=not args.refill,
                limit=args.limit,
                year=args.year.strip(),
            )
            return 1 if stats.failed > 0 else 0

        stats = backfill_folder(
            photos_dir=args.input,
            mode=args.backfill,
            only_empty=not args.refill,
            has_people=args.has_people,
            needs_faces=args.needs_faces,
            limit=args.limit,
            sleep_sec=args.sleep,
            batch_size=args.batch_size,
            batch_rest_sec=args.batch_rest,
            year=args.year.strip(),
            resume=args.resume,
        )
        if args.backfill in ("vision", "all"):
            apply_location_normalization(MEMORY_DIR)
        return 1 if stats.failed > 0 else 0

    stats = process_folder(args.input, skip_existing=not args.force)
    return 1 if stats.failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
