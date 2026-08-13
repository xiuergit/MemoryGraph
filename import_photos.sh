#!/usr/bin/env bash
# 新导入照片后一键：分析 / 补 vision → memory_index sync → memory_events sync
#
# 默认不跑 Ollama（快出 JSON）。vision 另开，每次一批：
#   ./import_photos.sh --input data/photos/2026   # ① 新图快出 JSON（默认关 Ollama）
#   ./import_photos.sh --vision                   # ② 补 scene/tags，默认每次 1000 张
#   ./import_photos.sh --vision                   # ③ 再跑一次继续下一批

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

INPUT=""
# 默认快模式：不跑 Ollama。--full 才开完整视觉。
FULL=0
FORCE=0
SKIP_EVENTS=0
STATS=0
DRY_RUN=0
INDEX_ONLY=0
VISION=0
LIMIT=""
YEAR=""
HAS_PEOPLE=1
PHOTO2JSON_EXTRA=()

DEFAULT_VISION_LIMIT=1000

usage() {
  cat <<'EOF'
新导入照片后一键：分析 / 补 vision → 索引 sync → 事件 sync

默认不跑 Ollama。推荐：
  ./import_photos.sh --input data/photos/2026     # ① 快出 JSON（只扫该目录；id 仍相对 photos/）
  ./import_photos.sh --vision                     # ② 补 vision，默认每次 1000 张
  ./import_photos.sh --vision                     #    反复执行直到补完

其它：
  ./import_photos.sh --full --input data/photos/2026   # 入库时就跑 Ollama（慢）
  ./import_photos.sh --vision --limit 500              # 每批 500 张
  ./import_photos.sh --vision --year 2026 --limit 0    # 某年全部（0=不限量）
  ./import_photos.sh --vision --year 2026              # 只补某年
  ./import_photos.sh --vision --all-photos             # 不限「有人物」
  ./import_photos.sh --force                           # 强制重跑已有 JSON
  ./import_photos.sh --skip-events / --stats / --index-only / --dry-run
  ./import_photos.sh --fast ...                        # 兼容旧写法（与默认相同）
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --input)
      INPUT="${2:-}"
      if [[ -z "$INPUT" ]]; then
        echo "错误: --input 需要目录路径" >&2
        exit 1
      fi
      shift 2
      ;;
    --limit)
      LIMIT="${2:-}"
      if [[ -z "$LIMIT" || ! "$LIMIT" =~ ^[0-9]+$ ]]; then
        echo "错误: --limit 需要非负整数（0=不限量）" >&2
        exit 1
      fi
      shift 2
      ;;
    --year)
      YEAR="${2:-}"
      if [[ -z "$YEAR" ]]; then
        echo "错误: --year 需要年份，如 2026" >&2
        exit 1
      fi
      shift 2
      ;;
    --fast) FULL=0; shift ;;  # 兼容旧写法：显式快模式 = 默认
    --full) FULL=1; shift ;;
    --vision) VISION=1; shift ;;
    --all-photos) HAS_PEOPLE=0; shift ;;
    --force) FORCE=1; shift ;;
    --skip-events) SKIP_EVENTS=1; shift ;;
    --stats) STATS=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --index-only) INDEX_ONLY=1; shift ;;
    --)
      shift
      PHOTO2JSON_EXTRA+=("$@")
      break
      ;;
    *)
      echo "未知参数: $1（用 --help 查看用法）" >&2
      exit 1
      ;;
  esac
done

if [[ "$VISION" -eq 1 && "$FULL" -eq 1 ]]; then
  echo "错误: --vision 与 --full 不能同时用（先默认入库，再单独 --vision）" >&2
  exit 1
fi
if [[ "$VISION" -eq 1 && "$INDEX_ONLY" -eq 1 ]]; then
  echo "错误: --vision 与 --index-only 不能同时用" >&2
  exit 1
fi
if [[ "$VISION" -eq 1 && "$FORCE" -eq 1 ]]; then
  echo "错误: --vision 是补空字段；强制重跑请用: python tools/photo2json/main.py --backfill vision --refill" >&2
  exit 1
fi

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  echo "未找到 .venv，请先: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# 入库默认关 Ollama；--vision / --full 才打开
if [[ "$VISION" -eq 1 ]]; then
  export OLLAMA_VISION_ENABLED=true
  if [[ -z "$LIMIT" ]]; then
    LIMIT="$DEFAULT_VISION_LIMIT"
  fi
elif [[ "$FULL" -eq 1 ]]; then
  export OLLAMA_VISION_ENABLED=true
else
  export OLLAMA_VISION_ENABLED=false
fi

run() {
  echo ""
  echo "▶ $*"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  "$@"
}

step() {
  echo ""
  echo "════════════════════════════════════════"
  echo " $1"
  echo "════════════════════════════════════════"
}

# --- 1. photo2json / backfill vision ---
if [[ "$INDEX_ONLY" -eq 1 ]]; then
  step "跳过分析（--index-only）"
elif [[ "$VISION" -eq 1 ]]; then
  if [[ "$LIMIT" == "0" ]]; then
    step "1/3  补 vision（不限量，可中断后反复执行续补）"
    P2J_ARGS=(--backfill vision)
  else
    step "1/3  补 vision（本次最多 ${LIMIT} 张，可反复执行续补）"
    P2J_ARGS=(--backfill vision --limit "$LIMIT")
  fi
  if [[ "$HAS_PEOPLE" -eq 1 ]]; then
    P2J_ARGS+=(--has-people)
    echo "（默认只补 people 非空；全量加 --all-photos）"
  fi
  if [[ -n "$YEAR" ]]; then
    P2J_ARGS+=(--year "$YEAR")
  fi
  if [[ -n "$INPUT" ]]; then
    P2J_ARGS+=(--input "$INPUT")
  fi
  if [[ ${#PHOTO2JSON_EXTRA[@]} -gt 0 ]]; then
    P2J_ARGS+=("${PHOTO2JSON_EXTRA[@]}")
  fi
  run "$PYTHON" tools/photo2json/main.py "${P2J_ARGS[@]}"
else
  step "1/3  分析原图 → data/memory/*.json"
  if [[ "$FULL" -eq 1 ]]; then
    echo "（--full：入库时跑 Ollama，较慢）"
    if [[ -n "$LIMIT" ]]; then
      echo "提示: --full 暂不支持 --limit；请用默认入库再 --vision --limit N" >&2
    fi
  else
    echo "（默认关闭 Ollama；之后用 ./import_photos.sh --vision 分批补）"
  fi

  P2J_ARGS=()
  if [[ -n "$INPUT" ]]; then
    P2J_ARGS+=(--input "$INPUT")
  fi
  if [[ "$FORCE" -eq 1 ]]; then
    P2J_ARGS+=(--force)
  fi
  if [[ ${#PHOTO2JSON_EXTRA[@]} -gt 0 ]]; then
    P2J_ARGS+=("${PHOTO2JSON_EXTRA[@]}")
  fi
  run "$PYTHON" tools/photo2json/main.py "${P2J_ARGS[@]}"
fi

# --- 2. memory_index sync ---
step "2/3  同步 SQLite 索引"
run "$PYTHON" tools/memory_index/main.py sync

# --- 3. memory_events sync ---
if [[ "$SKIP_EVENTS" -eq 0 ]]; then
  step "3/3  聚合出门/家事件"
  run "$PYTHON" tools/memory_events/main.py sync
else
  step "跳过事件聚合（--skip-events）"
fi

if [[ "$STATS" -eq 1 ]]; then
  step "数据健康报告"
  run "$PYTHON" tools/memory_stats/main.py
fi

echo ""
echo "✓ 完成。"
echo "  问答 CLI:  python tools/memory_ask/main.py \"面面最近去哪了\""
echo "  Web UI:    ./dev.sh"
if [[ "$VISION" -eq 0 && "$FULL" -eq 0 && "$INDEX_ONLY" -eq 0 ]]; then
  echo "  下一步:    ./import_photos.sh --vision          # 默认每次 ${DEFAULT_VISION_LIMIT} 张"
fi
if [[ "$VISION" -eq 1 ]]; then
  echo "  续补:      再跑一次 ./import_photos.sh --vision 即可（已补过的会跳过）"
fi
echo ""
