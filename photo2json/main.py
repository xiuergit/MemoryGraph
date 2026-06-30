"""Family Memory Photo2JSON 入口。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# 确保以 `python main.py` 或 `python -m photo2json.main` 方式运行时能正确导入
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photo2json.config import INPUT_DIR, OUTPUT_DIR
from photo2json.processor import process_folder


def setup_logging() -> None:
    """配置控制台日志格式。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    """读取 photos/ 目录，输出 JSON 到 output/。"""
    setup_logging()
    stats = process_folder(INPUT_DIR, OUTPUT_DIR)
    return 1 if stats.failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
