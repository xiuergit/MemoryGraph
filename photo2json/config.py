"""项目配置：路径、支持的图片格式等。"""

from pathlib import Path

# 项目根目录（photo2json 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 默认输入/输出目录（相对于项目根目录）
INPUT_DIR = PROJECT_ROOT / "photos"
OUTPUT_DIR = PROJECT_ROOT / "output"

# 支持的图片扩展名（小写，含点号）
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".heic", ".heif"}
)

# JSON 输出缩进，便于人工查看
JSON_INDENT = 2
