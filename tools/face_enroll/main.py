"""人脸库注册：扫描 data/faces/ 参考照，生成 index.json。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.config import FACE_INDEX_FILE, FACES_DIR
from hub.shared.face import build_face_index, save_face_index


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从 data/faces/{person_id}/ 参考照生成 data/faces/index.json",
    )
    parser.add_argument(
        "--faces-dir",
        type=Path,
        default=FACES_DIR,
        help=f"人脸库根目录（默认: {FACES_DIR}）",
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)

    if not args.faces_dir.is_dir():
        logger.error("目录不存在: %s", args.faces_dir)
        return 1

    index = build_face_index(args.faces_dir)
    people_count = len(index.get("people", {}))
    if people_count == 0:
        logger.error(
            "未生成任何人脸数据。请在 %s 下创建子目录（如 baby/）并放入参考照。",
            args.faces_dir,
        )
        return 1

    output = save_face_index(index, args.faces_dir)
    logger.info("人脸库已写入: %s（%d 人）", output.resolve(), people_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
