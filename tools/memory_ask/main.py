"""记忆问答 CLI：用现有 JSON 索引回答简单问题。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.agent import ask
from hub.shared.config import MEMORY_DB


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="基于 memorygraph.db 回答简单记忆问题",
        epilog="示例：\n"
        '  python tools/memory_ask/main.py "最近的照片"\n'
        '  python tools/memory_ask/main.py "面面几岁了"\n'
        '  python tools/memory_ask/main.py "面面最近在哪里玩"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("question", help="自然语言问题")
    parser.add_argument(
        "--db",
        type=Path,
        default=MEMORY_DB,
        help=f"SQLite 路径（默认: {MEMORY_DB}）",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="打印 intent 与原始 facts",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    result = ask(args.question, db_path=args.db)

    if args.debug:
        print(f"[intent={result.intent}, llm={result.used_llm}]")
        print(result.facts)
        print("---")

    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
