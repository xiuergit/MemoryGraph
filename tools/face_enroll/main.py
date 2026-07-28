"""人脸库注册：扫描参考照、sync-registry、从照片入库、未知人脸聚类。"""

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
from hub.shared.face_enroll import (
    apply_cluster_enrollments,
    auto_cluster_enrollments,
    enroll_from_photo,
    format_auto_enroll_report,
    format_cluster_report,
    scan_unknown_face_clusters,
    sync_registry,
)


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_build(args: argparse.Namespace) -> int:
    if not args.faces_dir.is_dir():
        logging.error("目录不存在: %s", args.faces_dir)
        return 1

    if args.sync_registry:
        added, ids = sync_registry(args.faces_dir, dry_run=args.dry_run)
        if args.dry_run:
            logging.info("dry-run: 将新增 %d 条 registry 条目: %s", added, ", ".join(ids) or "无")
        elif added:
            logging.info("registry 已同步，新增 %d 人: %s", added, ", ".join(ids))

    index = build_face_index(args.faces_dir)
    people_count = len(index.get("people", {}))
    if people_count == 0:
        logging.error(
            "未生成任何人脸数据。请在 %s 下创建子目录并放入参考照，"
            "或使用 from-photo / cluster --apply 入库。",
            args.faces_dir,
        )
        return 1

    if args.dry_run:
        logging.info("dry-run: 将写入 index.json（%d 人）", people_count)
        return 0

    output = save_face_index(index, args.faces_dir)
    logging.info("人脸库已写入: %s（%d 人）", output.resolve(), people_count)
    return 0


def cmd_sync_registry(args: argparse.Namespace) -> int:
    added, ids = sync_registry(args.faces_dir, dry_run=args.dry_run)
    if added == 0:
        logging.info("registry 已是最新，无需补充")
        return 0
    if args.dry_run:
        logging.info("dry-run: 将新增 %d 条: %s", added, ", ".join(ids))
    else:
        logging.info("registry 已更新，新增 %d 条: %s", added, ", ".join(ids))
        logging.info("请编辑 %s 补充 name / role / birth_date", args.faces_dir / "registry.json")
    return 0


def cmd_from_photo(args: argparse.Namespace) -> int:
    try:
        output = enroll_from_photo(
            args.photo_id,
            args.person_id,
            name=args.name,
            role=args.role,
            face_index=args.face_index,
            faces_dir=args.faces_dir,
            rebuild_index=not args.no_rebuild,
        )
    except (ValueError, FileNotFoundError, RuntimeError, IndexError) as exc:
        logging.error("%s", exc)
        return 1

    logging.info("参考照已保存: %s", output)
    if args.no_rebuild:
        logging.info("未重建 index，请运行: python tools/face_enroll/main.py build")
    return 0


def cmd_cluster(args: argparse.Namespace) -> int:
    try:
        clusters = scan_unknown_face_clusters(
            limit=args.limit,
            cluster_threshold=args.threshold,
            min_count=args.min_count,
            max_side=args.max_side,
            chunk_size=args.chunk_size,
            year=args.year or "",
            needs_faces=args.needs_faces,
        )
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1
    print(format_cluster_report(clusters, top=args.top))

    if args.apply and args.auto:
        logging.error("--apply 与 --auto 不能同时使用")
        return 1

    if args.auto:
        results = auto_cluster_enrollments(
            clusters,
            faces_dir=args.faces_dir,
            default_role=args.role,
            min_count=args.min_count,
            id_prefix=args.id_prefix,
            max_samples=args.max_samples,
            dry_run=getattr(args, "dry_run", False),
        )
        if args.dry_run:
            logging.info("dry-run: 将自动入库 %d 人", len(results))
            for item in results:
                logging.info("  %s ← %s", item["person_id"], item["sample_photo_id"])
        else:
            print(format_auto_enroll_report(results))
        return 0

    if args.apply:
        if not clusters:
            return 0
        print("\n交互式入库（每个聚类可命名 person_id；回车跳过）")
        enrolled = apply_cluster_enrollments(
            clusters,
            faces_dir=args.faces_dir,
            default_role=args.role,
            min_count=args.min_count,
            interactive=True,
        )
        logging.info("本次新入库 %d 人", enrolled)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="人脸库：build / sync-registry / from-photo / cluster",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python tools/face_enroll/main.py build\n"
            "  python tools/face_enroll/main.py build --sync-registry\n"
            "  python tools/face_enroll/main.py sync-registry\n"
            "  python tools/face_enroll/main.py from-photo 2021_2021年10月_IMG_4816 chuchu --name 初初 --role friend\n"
            "  python tools/face_enroll/main.py cluster --limit 500\n"
            "  python tools/face_enroll/main.py cluster --auto\n"
            "  python tools/face_enroll/main.py cluster --apply\n"
        ),
    )
    parser.add_argument("--faces-dir", type=Path, default=FACES_DIR, help=f"人脸库根目录（默认: {FACES_DIR}）")
    parser.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写入文件")

    sub = parser.add_subparsers(dest="command")

    p_build = sub.add_parser("build", help="扫描参考照生成 index.json（默认命令）")
    p_build.add_argument(
        "--sync-registry",
        action="store_true",
        help="build 前自动为有参考照的目录补 registry 占位",
    )
    p_build.set_defaults(func=cmd_build)

    p_sync = sub.add_parser("sync-registry", help="为有参考照的目录补 registry.json 占位条目")
    p_sync.set_defaults(func=cmd_sync_registry)

    p_photo = sub.add_parser("from-photo", help="从相册照片裁剪人脸写入参考库")
    p_photo.add_argument("photo_id", help="memory JSON 的 photo_id")
    p_photo.add_argument("person_id", help="人脸库目录 id（小写拼音，如 chuchu）")
    p_photo.add_argument("--name", help="registry 显示名（默认与 person_id 相同）")
    p_photo.add_argument("--role", default="other", help="registry role（默认 other）")
    p_photo.add_argument(
        "--face-index",
        type=int,
        default=-1,
        help="取第几张脸（0 起；默认 -1 为最大的一张）",
    )
    p_photo.add_argument("--no-rebuild", action="store_true", help="不立即重建 index.json")
    p_photo.set_defaults(func=cmd_from_photo)

    p_cluster = sub.add_parser("cluster", help="扫描未知人脸并聚类，可选交互入库")
    p_cluster.add_argument("--limit", type=int, default=500, help="最多扫描多少张含脸照片（0=不限）")
    p_cluster.add_argument(
        "--year",
        default="",
        help="只扫某年的照片（匹配 timestamp / photos/2025/ 路径 / 文件名前缀）",
    )
    p_cluster.add_argument(
        "--needs-faces",
        action="store_true",
        help="只扫 face_detected 且 people 为空的照片（库中没有的人，先 cluster 发现）",
    )
    p_cluster.add_argument("--min-count", type=int, default=6, help="聚类最少出现次数（默认 6）")
    p_cluster.add_argument("--threshold", type=float, default=0.55, help="聚类相似度阈值")
    p_cluster.add_argument(
        "--max-side",
        type=int,
        default=1280,
        help="检测前缩小图片长边（默认 1280，省内存；0 表示原图）",
    )
    p_cluster.add_argument(
        "--chunk-size",
        type=int,
        default=200,
        help="每块扫描张数，超过则启子进程释放内存（默认 200；0 表示不分块）",
    )
    p_cluster.add_argument("--top", type=int, default=20, help="报告展示前 N 个聚类")
    p_cluster.add_argument("--role", default="other", help="入库时的默认 role")
    p_cluster.add_argument(
        "--auto",
        action="store_true",
        help="自动入库：建 unk_XXX 目录 + 参考照 + registry 占位（再去 JSON 改名）",
    )
    p_cluster.add_argument(
        "--id-prefix",
        default="unk",
        help="自动入库 person_id 前缀（默认 unk → unk_001）",
    )
    p_cluster.add_argument(
        "--max-samples",
        type=int,
        default=1,
        help="每个聚类最多裁剪几张参考照（默认 1）",
    )
    p_cluster.add_argument("--apply", action="store_true", help="交互式命名并入库（适合少量新人）")
    p_cluster.set_defaults(func=cmd_cluster)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command is None:
        args.command = "build"
        args.sync_registry = False
        args.func = cmd_build

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
