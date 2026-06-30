"""JSON 记忆库 → SQLite 索引（验证用，JSON 仍为数据源）。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.config import MEMORY_DB, MEMORY_DIR
from hub.shared.index_db import connect, get_stats, init_db, list_timeline, search_photos, sync_memory_dir


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _print_rows(rows: list[dict]) -> None:
    if not rows:
        print("(无结果)")
        return
    for row in rows:
        people = row.get("people") or "-"
        scene = row.get("scene") or "-"
        ts = row.get("timestamp") or "-"
        print(f"{row['photo_id']}\t{ts}\t{people}\t{scene}")


def cmd_sync(args: argparse.Namespace) -> int:
    stats = sync_memory_dir(args.input, args.db, force=args.force)
    print(
        f"同步完成: 新增 {stats.added}, 更新 {stats.updated}, "
        f"跳过 {stats.skipped}, 删除 {stats.removed}, 失败 {stats.failed}"
    )
    return 1 if stats.failed > 0 else 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    stats = get_stats(conn)
    conn.close()
    print(f"照片: {stats['photos']}")
    print(f"人物: {stats['people']}")
    print(f"检测到人脸: {stats['with_face']}")
    if stats["latest"]:
        latest = stats["latest"]
        print(f"最近一张: {latest['photo_id']} ({latest['timestamp']})")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    rows = search_photos(
        conn,
        person=args.person or "",
        query=args.query or "",
        limit=args.limit,
    )
    conn.close()
    _print_rows(rows)
    return 0


def cmd_timeline(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    rows = list_timeline(conn, limit=args.limit)
    conn.close()
    _print_rows(rows)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将 data/memory/*.json 索引到 SQLite，便于检索验证",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=MEMORY_DB,
        help=f"SQLite 路径（默认: {MEMORY_DB}）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sync_parser = sub.add_parser("sync", help="扫描 JSON 并同步索引")
    sync_parser.add_argument(
        "--input",
        type=Path,
        default=MEMORY_DIR,
        help=f"JSON 目录（默认: {MEMORY_DIR}）",
    )
    sync_parser.add_argument(
        "--force",
        action="store_true",
        help="忽略 mtime，全量重建索引",
    )
    sync_parser.set_defaults(func=cmd_sync)

    stats_parser = sub.add_parser("stats", help="查看索引统计")
    stats_parser.set_defaults(func=cmd_stats)

    search_parser = sub.add_parser("search", help="按人物或关键词搜索")
    search_parser.add_argument("--person", help="人物名或 id，如 面面 / baby")
    search_parser.add_argument("--query", "-q", help="搜索 scene / location / tags 等")
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.set_defaults(func=cmd_search)

    timeline_parser = sub.add_parser("timeline", help="按时间倒序列出照片")
    timeline_parser.add_argument("--limit", type=int, default=20)
    timeline_parser.set_defaults(func=cmd_timeline)

    args = parser.parse_args()
    setup_logging()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
