#!/usr/bin/env bash
# 手动下载 CLIP 权重（HuggingFace 超时时用）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/models/clip"
OUT_FILE="$OUT_DIR/open_clip_model.safetensors"
URL="${CLIP_URL:-https://hf-mirror.com/timm/vit_base_patch32_clip_224.openai/resolve/main/open_clip_model.safetensors}"

mkdir -p "$OUT_DIR"

if [[ -f "$OUT_FILE" ]]; then
  echo "已存在: $OUT_FILE"
  exit 0
fi

echo "下载 CLIP 权重到 $OUT_FILE"
echo "来源: $URL"
curl -L --retry 5 --retry-delay 3 -o "$OUT_FILE" "$URL"

echo ""
echo "完成。请在 .env 中设置:"
echo "CLIP_PRETRAINED=$OUT_FILE"
