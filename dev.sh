#!/usr/bin/env bash
# 一键启动 MemoryGraph Desk（后端）+ Vue Inspector（前端）
# 用法：./dev.sh
# 停止：Ctrl+C（前后端一并退出）

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PORT_FILE="$ROOT/data/.memory_desk_port"
DESK_PID=""
WEB_PID=""

cleanup() {
  trap - EXIT INT TERM
  echo ""
  echo "正在停止前后端…"
  if [[ -n "${WEB_PID}" ]] && kill -0 "${WEB_PID}" 2>/dev/null; then
    kill "${WEB_PID}" 2>/dev/null || true
    wait "${WEB_PID}" 2>/dev/null || true
  fi
  if [[ -n "${DESK_PID}" ]] && kill -0 "${DESK_PID}" 2>/dev/null; then
    kill "${DESK_PID}" 2>/dev/null || true
    for _ in $(seq 1 12); do
      kill -0 "${DESK_PID}" 2>/dev/null || break
      sleep 0.25
    done
    if kill -0 "${DESK_PID}" 2>/dev/null; then
      echo "Desk 仍在退出（可能在跑 AI），强制结束…"
      kill -9 "${DESK_PID}" 2>/dev/null || true
    fi
    wait "${DESK_PID}" 2>/dev/null || true
  fi
  echo "已停止。"
}
trap cleanup EXIT INT TERM

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  echo "未找到 .venv，请先: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "未找到 npm，请先安装 Node.js" >&2
  exit 1
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [[ ! -d "$ROOT/web/node_modules" ]]; then
  echo "首次运行：安装前端依赖…"
  (cd "$ROOT/web" && npm install)
fi

# 局域网 IPv4，供 iOS App 设置填写（优先 en0，其次 en1）
lan_ip() {
  local ip=""
  ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
  if [[ -z "$ip" ]]; then
    ip="$(ipconfig getifaddr en1 2>/dev/null || true)"
  fi
  printf '%s' "$ip"
}

echo "启动 Desk API（--host 0.0.0.0 --auto-port --no-browser）…"
"$PYTHON" tools/memory_desk/main.py --host 0.0.0.0 --auto-port --no-browser &
DESK_PID=$!

desk_ready=0
for _ in $(seq 1 60); do
  if ! kill -0 "${DESK_PID}" 2>/dev/null; then
    echo "Desk 进程已退出，启动失败。" >&2
    exit 1
  fi
  if [[ -f "$PORT_FILE" ]]; then
    port="$(tr -d '[:space:]' < "$PORT_FILE")"
    if [[ "$port" =~ ^[0-9]+$ ]] && curl -sf "http://127.0.0.1:${port}/" >/dev/null 2>&1; then
      desk_ready=1
      break
    fi
  fi
  sleep 0.25
done

if [[ "$desk_ready" -ne 1 ]]; then
  echo "等待 Desk 就绪超时（检查端口或依赖）。" >&2
  exit 1
fi

DESK_PORT="$(tr -d '[:space:]' < "$PORT_FILE")"
LAN_IP="$(lan_ip)"
echo "Desk 已就绪 → http://127.0.0.1:${DESK_PORT}/"
if [[ -n "$LAN_IP" ]]; then
  echo "手机/iPad:  http://${LAN_IP}:${DESK_PORT}/  （App 设置填 ${LAN_IP}，端口 ${DESK_PORT}）"
else
  echo "手机/iPad:  填 Mac 局域网 IP（系统设置 → 网络）+ 端口 ${DESK_PORT}"
fi
echo "启动 Vue Inspector…"
echo "浏览器请打开 Vite 提示的地址（通常 http://127.0.0.1:5173）"
echo "Ctrl+C 停止前后端"
echo ""

(
  cd "$ROOT/web"
  npm run dev -- --host 127.0.0.1 --open
) &
WEB_PID=$!

wait "${WEB_PID}"
