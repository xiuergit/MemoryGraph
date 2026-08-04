"""照片去重候选报告：字节重复 + 连拍近邻（不删除）。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.config import MEMORY_DB
from hub.shared.dedup import (
    DEFAULT_BURST_SECONDS,
    build_dedup_report,
    format_dedup_report,
    report_to_dict,
)


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MemoryGraph 去重候选报告（exact hash + 连拍 + 无时间近哈希；只报告不删除）",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=MEMORY_DB,
        help=f"SQLite 路径（默认 {MEMORY_DB}）",
    )
    parser.add_argument("--year", default="", help="只扫该年，如 2024")
    parser.add_argument(
        "--burst-seconds",
        type=int,
        default=DEFAULT_BURST_SECONDS,
        help=f"连拍最大间隔秒数（默认 {DEFAULT_BURST_SECONDS}）",
    )
    parser.add_argument(
        "--hash-only",
        action="store_true",
        help="只报字节级重复",
    )
    parser.add_argument(
        "--burst-only",
        action="store_true",
        help="只报连拍近邻",
    )
    parser.add_argument(
        "--no-quality",
        action="store_true",
        help="连拍/近相似不做画质评分（更快）",
    )
    parser.add_argument(
        "--near-hamming",
        type=int,
        default=10,
        help="无时间近哈希最大汉明距离（默认 10）",
    )
    parser.add_argument(
        "--no-near",
        action="store_true",
        help="不对无时间照片做近哈希聚类",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多输出多少组（0=全部；先 exact 后 burst）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="写入文本报告路径（默认打印到 stdout）",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        dest="json_out",
        help="同时写一份 JSON 报告",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    if args.hash_only and args.burst_only:
        print("不能同时指定 --hash-only 与 --burst-only", file=sys.stderr)
        return 2

    include_hash = not args.burst_only
    include_burst = not args.hash_only

    report = build_dedup_report(
        db_path=args.db,
        year=args.year.strip(),
        burst_seconds=max(0, args.burst_seconds),
        include_hash=include_hash,
        include_burst=include_burst,
        limit_groups=max(0, args.limit),
        score_quality=not args.no_quality,
        near_hamming=max(0, args.near_hamming),
        include_near=not args.no_near,
    )
    text = format_dedup_report(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"已写入 {args.output}")
        # 摘要仍打到终端
        print(
            f"扫描 {report.scanned} · exact {report.exact_groups} 组/{report.exact_extra} 张 · "
            f"burst {report.burst_groups} 组/{report.burst_extra} 张"
        )
    else:
        print(text, end="")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report_to_dict(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON → {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
