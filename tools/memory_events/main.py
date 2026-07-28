"""Outing 事件聚合：sync / stats / list。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.config import MEMORY_DB
from hub.shared.events import get_event_stats, list_events, list_orphan_overlays, sync_events
from hub.shared.index_db import connect, init_db


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_sync(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    stats = sync_events(conn)
    conn.close()
    print(
        f"事件同步完成: outing {stats.outing_events}, 家 {stats.home_events}, "
        f"合计 {stats.events} 条 · 照片 {stats.photos_in_events}/{stats.photos_with_ts} "
        f"· overlay 重挂 {stats.overlays_rematched}, 待认领 {stats.overlays_orphaned}"
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    stats = get_event_stats(conn)
    conn.close()
    print(f"事件总数: {stats['events']}（outing {stats['outing_events']} / 家 {stats['home_events']}）")
    print(f"事件照片行: {stats['event_photos']} · 去重照片: {stats['photos_in_events']}")
    print(f"有时间戳照片: {stats['photos_with_timestamp']} · 覆盖率: {stats['coverage_pct']}%")
    print(f"overlays: {stats['overlays']} · 待认领: {stats['orphan_overlays']}")
    print(f"stories: {stats['stories']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    rows = list_events(
        conn,
        day=args.day or "",
        include_home=args.include_home,
        location=args.location or "",
        keyword=getattr(args, "keyword", "") or "",
        limit=args.limit,
    )
    orphans = list_orphan_overlays(conn) if args.orphans else []
    conn.close()
    if not rows:
        print("(无事件)")
    for row in rows:
        home = " [家]" if row["is_home"] else ""
        title = row.get("display_title") or ""
        people = ",".join(row.get("people") or []) or "-"
        print(
            f"{row['event_id']}\t{row['day']}\t{row['photo_count']}张\t"
            f"{row['location'] or '-'}{home}\t{people}\t{title}"
        )
    if args.orphans:
        print(f"\n待认领 overlays: {len(orphans)}")
        for ov in orphans:
            print(f"  {ov['overlay_id']}\t{ov['title'] or '(无标题)'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MemoryGraph 事件聚合")
    parser.add_argument(
        "--db",
        type=Path,
        default=MEMORY_DB,
        help=f"SQLite 路径（默认 {MEMORY_DB}）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="重建 events / event_photos 并重挂 overlays")
    p_sync.set_defaults(func=cmd_sync)

    p_stats = sub.add_parser("stats", help="事件统计")
    p_stats.set_defaults(func=cmd_stats)

    p_list = sub.add_parser("list", help="列出事件")
    p_list.add_argument("--day", default="", help="日期前缀：YYYY / YYYY-MM / YYYY-MM-DD")
    p_list.add_argument("--location", default="", help="地点精确匹配")
    p_list.add_argument("--keyword", default="", help="场景/动作/物体/备注关键词")
    p_list.add_argument("--include-home", action="store_true", help="包含家/常驻簇")
    p_list.add_argument("--orphans", action="store_true", help="同时列出待认领 overlay")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
