#!/usr/bin/env python3
"""启动 MemoryGraph 本地 Web 小工具（文件搜索 + 记忆问答）。"""

from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import sys
import webbrowser
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hub.shared.config import DATA_DIR

DESK_PORT_FILE = DATA_DIR / ".memory_desk_port"


def _write_desk_port(port: int) -> None:
    """写入当前 Desk 端口，供 web/vite 读取 proxy 目标。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DESK_PORT_FILE.write_text(str(port), encoding="utf-8")


def _load_app():
    app_path = Path(__file__).resolve().parent / "app.py"
    spec = importlib.util.spec_from_file_location("memory_desk_app", app_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {app_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True


def _find_free_port(host: str, start: int, *, tries: int = 20) -> int:
    for port in range(start, start + tries):
        if not _port_in_use(host, port):
            return port
    raise RuntimeError(f"在 {start}–{start + tries - 1} 范围内找不到可用端口")


def _is_wildcard_host(host: str) -> bool:
    return host in {"0.0.0.0", "::", "[::]"}


def _lan_ipv4() -> str | None:
    """尽量拿到局域网 IPv4，供手机/iPad 填写；失败则返回 None。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return None


def _browser_url(host: str, port: int) -> str:
    """浏览器可打开的地址：0.0.0.0 不能当 URL，改用 127.0.0.1。"""
    open_host = "127.0.0.1" if _is_wildcard_host(host) else host
    return f"http://{open_host}:{port}/"


def _print_endpoints(host: str, port: int) -> str:
    """打印本机 / 局域网访问方式，返回应自动打开的 URL。"""
    local_url = _browser_url(host, port)
    print(f"MemoryGraph Desk 监听 {host}:{port}")
    print(f"  本机浏览器: {local_url}")
    if _is_wildcard_host(host):
        lan = _lan_ipv4()
        if lan:
            print(f"  手机/iPad:  http://{lan}:{port}/  （App 设置填 {lan}）")
        else:
            print("  手机/iPad:  填 Mac 局域网 IP（系统设置 → 网络）")
    print("Ctrl+C 停止服务")
    return local_url


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MemoryGraph Desk — 本地 Web：搜文件、预览、打开、问答",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址：仅本机用 127.0.0.1；手机/iPad 访问用 0.0.0.0（本机仍可用 127.0.0.1 打开）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MEMORY_DESK_PORT", "8766")),
        help="端口（默认 8766，Mac Hub 用 8765）",
    )
    parser.add_argument(
        "--auto-port",
        action="store_true",
        help="若默认端口被占用，自动尝试下一个可用端口",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="不自动打开浏览器",
    )
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("请先安装依赖: pip install -r requirements.txt", file=sys.stderr)
        return 1

    port = args.port
    if _port_in_use(args.host, port):
        if args.auto_port:
            port = _find_free_port(args.host, port + 1)
        else:
            print(f"端口 {port} 已被占用（Desk 可能已在运行）。")
            print(f"  直接打开: {_browser_url(args.host, port)}")
            print(f"  换端口启动: python tools/memory_desk/main.py --host {args.host} --port {port + 1}")
            print(f"  查看占用: lsof -nP -iTCP:{port} -sTCP:LISTEN")
            _write_desk_port(port)
            if not args.no_browser:
                webbrowser.open(_browser_url(args.host, port))
            return 0

    url = _print_endpoints(args.host, port)
    _write_desk_port(port)

    if not args.no_browser:
        webbrowser.open(url)

    app = _load_app()
    uvicorn.run(
        app,
        host=args.host,
        port=port,
        reload=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
