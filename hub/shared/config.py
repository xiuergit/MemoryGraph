"""项目配置：路径、支持的图片格式等。"""

import os
from pathlib import Path

# 仓库根目录（hub/shared 的上两级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_dotenv() -> None:
    """读取项目根 .env（不覆盖已 export 的环境变量）。"""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return
    try:
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                continue
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    except OSError:
        pass


_load_dotenv()

# 运行时数据目录（不进 git，见 .gitignore）
DATA_DIR = PROJECT_ROOT / "data"
PHOTOS_DIR = DATA_DIR / "photos"
MEMORY_DIR = DATA_DIR / "memory"
MEMORY_DB = DATA_DIR / "memorygraph.db"

# 支持的图片扩展名（小写，含点号）
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".heic", ".heif"}
)

# JSON 输出缩进，便于人工查看
JSON_INDENT = 2

# 当前协议版本，与 schemas/photo.v1.json 一致
SCHEMA_VERSION = "1.1"

# 高德逆地理编码 Key（环境变量，勿写入代码）
# 申请：https://lbs.amap.com/ → 创建应用 → Web 服务 API
AMAP_KEY = os.environ.get("AMAP_KEY", "")

# 人脸库（参考照 + 自动生成的 index.json）
FACES_DIR = DATA_DIR / "faces"
FACE_REGISTRY_FILE = FACES_DIR / "registry.json"
FACE_INDEX_FILE = FACES_DIR / "index.json"

# 人脸匹配阈值（余弦相似度），可通过环境变量覆盖
FACE_MATCH_THRESHOLD = float(os.environ.get("FACE_MATCH_THRESHOLD", "0.45"))
# 人脸检测置信度下限（InsightFace det_score）；过低易把菜/花纹/阴影误判为人脸
FACE_DET_SCORE_MIN = float(os.environ.get("FACE_DET_SCORE_MIN", "0.70"))
# 前端/入库更严：参考照须达到该分，且裁切后仍能再次检出
FACE_ENROLL_DET_SCORE_MIN = float(os.environ.get("FACE_ENROLL_DET_SCORE_MIN", "0.70"))
# 入库人脸框最短边像素；过小裁切后常检不出
FACE_ENROLL_MIN_SIDE = int(os.environ.get("FACE_ENROLL_MIN_SIDE", "80"))

# Ollama 本地视觉模型（场景 / 物体 / 动作等）
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "qwen3-vl:30b")
OLLAMA_VISION_ENABLED = os.environ.get("OLLAMA_VISION_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "180"))

# Ollama 文本对话（Agent 问答，与视觉模型分开配置）
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "gpt-oss:20b")
OLLAMA_CHAT_ENABLED = os.environ.get("OLLAMA_CHAT_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)

# InsightFace 人脸识别
# 模型：buffalo_s（小、下载快）| buffalo_l（更准、更大）
INSIGHTFACE_MODEL = os.environ.get("INSIGHTFACE_MODEL", "buffalo_s")
# 模型目录，默认 ~/.insightface/models；可指向已手动下载的目录
INSIGHTFACE_ROOT = os.environ.get("INSIGHTFACE_ROOT", "")

# CLIP 衣着兜底（脸不清时比对当日穿搭向量）
OUTFIT_CACHE_DIR = DATA_DIR / "cache" / "outfit"
CLIP_ENABLED = os.environ.get("CLIP_ENABLED", "true").lower() in ("1", "true", "yes")
# 未匹配人脸 → 衣着比对（易误识别，默认关闭；仅脸认出后写缓存仍可用）
OUTFIT_FALLBACK_ENABLED = os.environ.get("OUTFIT_FALLBACK_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
# 仅当人脸匹配置信度 ≥ 此值时才写入当日衣着缓存
OUTFIT_CACHE_MIN_FACE_CONF = float(os.environ.get("OUTFIT_CACHE_MIN_FACE_CONF", "0.55"))
CLIP_MODEL_NAME = os.environ.get("CLIP_MODEL_NAME", "ViT-B-32")
CLIP_PRETRAINED = os.environ.get("CLIP_PRETRAINED", "openai")
OUTFIT_MATCH_THRESHOLD = float(os.environ.get("OUTFIT_MATCH_THRESHOLD", "0.88"))
OUTFIT_MAX_CONFIDENCE = float(os.environ.get("OUTFIT_MAX_CONFIDENCE", "0.72"))

# HuggingFace 镜像（CLIP 权重下载）。国内默认 hf-mirror，海外可设 HF_ENDPOINT=
_hf_endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
if _hf_endpoint:
    os.environ.setdefault("HF_ENDPOINT", _hf_endpoint)
