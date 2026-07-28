"""Memory JSON / 人脸库 / SQLite 数据健康报告。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.config import FACES_DIR, MEMORY_DB, MEMORY_DIR
from hub.shared.memory_stats import format_memory_stats_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MemoryGraph 数据健康报告（JSON / 人脸库 / SQLite）",
    )
    parser.add_argument(
        "--memory-dir",
        type=Path,
        default=MEMORY_DIR,
        help=f"memory JSON 目录（默认: {MEMORY_DIR}）",
    )
    parser.add_argument(
        "--faces-dir",
        type=Path,
        default=FACES_DIR,
        help=f"人脸库目录（默认: {FACES_DIR}）",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=MEMORY_DB,
        help=f"SQLite 索引（默认: {MEMORY_DB}）",
    )
    parser.add_argument(
        "--year",
        default="",
        help="附加显示该年的 vision 续跑命令提示，如 2025",
    )
    args = parser.parse_args()
    print(
        format_memory_stats_report(
            memory_dir=args.memory_dir,
            faces_dir=args.faces_dir,
            db_path=args.db,
            year=args.year.strip(),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
