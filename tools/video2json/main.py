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
from hub.shared.video_transcript import backfill_transcript_folder
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
        help="重新生成已存在的 JSON（或配合 --backfill transcript 覆盖字幕）",
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
        "--backfill",
        choices=["transcript"],
        default=None,
        help="增量补全：transcript=本地 ASR 写字幕（需 ffmpeg + faster-whisper）",
    )
    parser.add_argument(
        "--year",
        default="",
        help="仅处理该年份（与 photo2json --year 同语义；backfill 时筛 JSON）",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=None,
        help="transcript backfill：短于此秒数跳过（默认读 ASR_MIN_DURATION_S，通常 3）",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="指定视频文件（可多个）；若不传则扫描 --input。backfill 时可传 video_id 或 JSON 路径",
    )
    args = parser.parse_args()
    setup_logging()

    if args.backfill == "transcript":
        video_ids: list[str] | None = None
        if args.paths:
            video_ids = []
            for p in args.paths:
                s = str(p)
                if s.endswith(".json"):
                    video_ids.append(Path(s).stem)
                else:
                    video_ids.append(Path(s).name.replace(".json", ""))
        try:
            stats = backfill_transcript_folder(
                MEMORY_DIR,
                force=args.force,
                limit=args.limit,
                year=args.year,
                min_duration_s=args.min_duration,
                video_ids=video_ids,
            )
        except RuntimeError as exc:
            logging.error("%s", exc)
            return 2
        return 1 if stats.failed else 0

    stats = process_folder(
        input_dir=args.input,
        memory_dir=MEMORY_DIR,
        skip_existing=not args.force,
        device_id=args.device_id,
        run_ai=not args.no_ai,
        limit=args.limit,
        files=list(args.paths) if args.paths else None,
        year=args.year,
    )
    if stats.failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
