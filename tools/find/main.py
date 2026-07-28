#!/usr/bin/env python3
"""按文件名搜索 data/ 下的照片、JSON、人脸参考照，输出可点击链接。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.config import DATA_DIR, FACES_DIR, MEMORY_DIR, PHOTOS_DIR, PROJECT_ROOT
from hub.shared.file_search import (
    FileSearchHit,
    format_path_link,
    memory_json_for_photo,
    search_files,
)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _print_hits(hits: list[FileSearchHit], *, show_json: bool) -> None:
    if not hits:
        print("(无匹配)")
        return
    for i, hit in enumerate(hits, 1):
        path = hit.path
        print(f"{i}. [{hit.root_label}] {format_path_link(path)}")
        print(f"   {_rel(path)}")
        if show_json and hit.root_label == "photos":
            mem = memory_json_for_photo(path)
            if mem:
                print(f"   memory → {format_path_link(mem, label=mem.name)}")


def _open_paths(paths: list[Path]) -> None:
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    for path in paths:
        subprocess.run([opener, str(path)], check=False)


def _build_roots(args: argparse.Namespace) -> list[tuple[str, Path]]:
    if args.all_data:
        return [("data", DATA_DIR)]
    roots: list[tuple[str, Path]] = []
    if args.photos:
        roots.append(("photos", PHOTOS_DIR))
    if args.memory:
        roots.append(("memory", MEMORY_DIR))
    if args.faces:
        roots.append(("faces", FACES_DIR))
    return roots


def _run_search(args: argparse.Namespace, query: str) -> list[FileSearchHit]:
    hits = search_files(
        query,
        roots=_build_roots(args),
        exact=args.exact,
        limit=args.limit,
    )
    _print_hits(hits, show_json=not args.no_json)
    if args.open and hits:
        _open_paths([h.path for h in hits[: args.open_count]])
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在 MemoryGraph 数据目录按文件名搜索（photos / memory / faces）",
        epilog="示例：\n"
        "  python tools/find/main.py IMG_3844\n"
        "  python tools/find/main.py IMG_3844 --open\n"
        "  python tools/find/main.py 3844 -i\n"
        "  python tools/find/main.py photo.v1 --memory --all-data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", help="文件名或片段，如 IMG_3844")
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="交互模式：反复输入文件名搜索",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="精确匹配文件名（忽略扩展名可选等同）",
    )
    parser.add_argument("--limit", type=int, default=30, help="最多显示几条（默认 30）")
    parser.add_argument(
        "--open",
        action="store_true",
        help="用系统默认程序打开匹配文件（macOS: open）",
    )
    parser.add_argument(
        "--open-count",
        type=int,
        default=1,
        metavar="N",
        help="--open 时最多打开前 N 个（默认 1）",
    )
    parser.add_argument("--no-json", action="store_true", help="不显示关联 memory JSON")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--all-data",
        action="store_true",
        help="搜索整个 data/（默认只搜 photos + memory + faces）",
    )
    parser.add_argument(
        "--photos",
        action="store_true",
        help="只搜 data/photos（可与 --memory / --faces 组合）",
    )
    parser.add_argument("--memory", action="store_true", help="只搜 data/memory")
    parser.add_argument("--faces", action="store_true", help="只搜 data/faces")
    args = parser.parse_args()

    if args.photos or args.memory or args.faces:
        pass
    elif not args.all_data:
        args.photos = True
        args.memory = True
        args.faces = True

    if args.interactive or not args.query:
        print("MemoryGraph 文件搜索（输入空行或 Ctrl-D 退出）")
        print(f"范围: {', '.join(label for label, _ in _build_roots(args))}")
        try:
            while True:
                try:
                    query = input("\n文件名> ").strip()
                except EOFError:
                    print()
                    break
                if not query:
                    break
                print()
                _run_search(args, query)
        except KeyboardInterrupt:
            print()
            return 130
        return 0

    hits = _run_search(args, args.query)
    return 0 if hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
