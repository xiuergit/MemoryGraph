"""维护工具后台任务状态（单任务、进程内内存）。"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Any

_lock = threading.Lock()
_cancel = threading.Event()

_IDLE: dict[str, Any] = {
    "running": False,
    "kind": "",
    "year": "",
    "phase": "",
    "current": 0,
    "total": 0,
    "current_file": "",
    "success": 0,
    "skipped": 0,
    "failed": 0,
    "message": "",
    "error": "",
    "cancelled": False,
    "pending_at_start": 0,
    "batch_limit": None,
    "started_at": 0.0,
    "finished_at": 0.0,
    "result": None,
}

_state: dict[str, Any] = deepcopy(_IDLE)


def snapshot() -> dict[str, Any]:
    with _lock:
        return deepcopy(_state)


def is_cancelled() -> bool:
    return _cancel.is_set()


def start(
    kind: str,
    *,
    year: str = "",
    pending_at_start: int = 0,
    batch_limit: int | None = None,
) -> None:
    with _lock:
        if _state["running"]:
            raise RuntimeError(f"已有任务在运行：{_state['kind']} {_state['year']}".strip())
        _cancel.clear()
        _state.clear()
        _state.update(deepcopy(_IDLE))
        _state.update(
            {
                "running": True,
                "kind": kind,
                "year": year,
                "phase": "starting",
                "message": "准备扫描…",
                "started_at": time.time(),
                "pending_at_start": pending_at_start,
                "batch_limit": batch_limit,
            }
        )


def update(**fields: Any) -> None:
    with _lock:
        if not _state["running"]:
            return
        _state.update(fields)


def request_cancel() -> bool:
    """请求取消当前任务；下一张/下一个视频前生效。"""
    with _lock:
        if not _state["running"]:
            return False
        _cancel.set()
        _state["phase"] = "cancelling"
        _state["message"] = "正在取消（当前这张跑完后停止）…"
        return True


def finish(*, result: dict[str, Any] | None = None, error: str = "") -> None:
    with _lock:
        cancelled = _cancel.is_set()
        _state["running"] = False
        _state["finished_at"] = time.time()
        _state["cancelled"] = cancelled
        if cancelled:
            _state["phase"] = "cancelled"
            _state["error"] = ""
            _state["message"] = "已取消"
            _state["result"] = result
        elif error:
            _state["phase"] = "error"
            _state["error"] = error
            _state["message"] = error
        else:
            _state["phase"] = "done"
            _state["error"] = ""
            _state["result"] = result
            _state["message"] = "已完成"
        _cancel.clear()
