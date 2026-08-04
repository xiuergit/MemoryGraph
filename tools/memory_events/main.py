"""Outing 事件聚合：sync / stats / list / 标注导入导出。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.annotations import (
    annotations_path,
    flush_annotations_from_db,
    load_annotations,
    replace_annotations_in_db,
)
from hub.shared.config import MEMORY_ANNOTATIONS_FILE, MEMORY_DB
from hub.shared.events import (
    get_event_stats,
    list_events,
    list_orphan_overlays,
    rematch_overlays,
    sync_events,
)
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
        f"无时间地点 {stats.untimed_location_events}, "
        f"合计 {stats.events} 条 · 照片 {stats.photos_in_events}/{stats.photos_with_ts} "
        f"· overlay 重挂 {stats.overlays_rematched}, 待认领 {stats.overlays_orphaned}"
    )
    print(f"标注文件: {annotations_path()}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    stats = get_event_stats(conn)
    conn.close()
    print(
        f"事件总数: {stats['events']}（outing {stats['outing_events']} / "
        f"家 {stats['home_events']} / 无时间地点 {stats.get('untimed_location_events', 0)}）"
    )
    print(f"事件照片行: {stats['event_photos']} · 去重照片: {stats['photos_in_events']}")
    print(
        f"有时间戳照片: {stats['photos_with_timestamp']} · 覆盖率: {stats['coverage_pct']}% · "
        f"无时间有地址: {stats.get('untimed_located_photos', 0)}"
    )
    print(f"overlays: {stats['overlays']} · 待认领: {stats['orphan_overlays']}")
    print(f"stories: {stats['stories']}")
    ann = annotations_path()
    if ann.is_file():
        data = load_annotations(ann)
        print(
            f"标注文件: {ann} "
            f"（{len(data['overlays'])} overlays / {len(data['stories'])} stories）"
        )
    else:
        print(f"标注文件: {ann}（尚不存在，sync 或 export-annotations 会创建）")
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


def cmd_export_annotations(args: argparse.Namespace) -> int:
    """从 SQLite 导出 overlays/stories → memory_annotations.json。"""
    out = Path(args.output) if args.output else annotations_path()
    conn = connect(args.db)
    init_db(conn)
    path = flush_annotations_from_db(conn, out)
    data = load_annotations(path)
    conn.close()
    print(
        f"已导出 → {path} "
        f"（{len(data['overlays'])} overlays / {len(data['stories'])} stories）"
    )
    return 0


def cmd_import_annotations(args: argparse.Namespace) -> int:
    """从 memory_annotations.json 灌库并按锚点重挂 overlays。"""
    src = Path(args.input) if args.input else annotations_path()
    if not src.is_file():
        print(f"标注文件不存在: {src}", file=sys.stderr)
        return 1
    data = load_annotations(src)
    conn = connect(args.db)
    init_db(conn)
    n_ov, n_st = replace_annotations_in_db(conn, data, commit=False)
    rematched, orphaned = rematch_overlays(conn)
    conn.commit()
    flush_annotations_from_db(conn, src if args.input else None)
    conn.close()
    print(
        f"已导入 {src}: {n_ov} overlays / {n_st} stories · "
        f"重挂 {rematched}, 待认领 {orphaned}"
    )
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

    p_sync = sub.add_parser(
        "sync",
        help="重建 events / event_photos；从 memory_annotations.json 灌标注并重挂",
    )
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

    p_export = sub.add_parser(
        "export-annotations",
        help="从 SQLite 导出 overlays/stories 到 memory_annotations.json",
    )
    p_export.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=f"输出路径（默认 {MEMORY_ANNOTATIONS_FILE}）",
    )
    p_export.set_defaults(func=cmd_export_annotations)

    p_import = sub.add_parser(
        "import-annotations",
        help="从 memory_annotations.json 灌库并重挂 overlays",
    )
    p_import.add_argument(
        "-i",
        "--input",
        type=Path,
        default=None,
        help=f"输入路径（默认 {MEMORY_ANNOTATIONS_FILE}）",
    )
    p_import.set_defaults(func=cmd_import_annotations)

    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
