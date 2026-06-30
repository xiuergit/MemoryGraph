"""本地 Ollama 视觉模型：场景、物体、动作等语义字段。"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path

from hub.shared.config import (
    OLLAMA_BASE_URL,
    OLLAMA_TIMEOUT,
    OLLAMA_VISION_ENABLED,
    OLLAMA_VISION_MODEL,
    SUPPORTED_EXTENSIONS,
)
from hub.shared.schema import AnalysisResult, analysis_from_dict, empty_analysis

logger = logging.getLogger(__name__)

_VISION_PROMPT = """你是家庭照片分析助手。只描述图片中确实能看见的内容，不要猜测，不要编造。

要求：
1. 只返回 JSON，不要 markdown，不要额外说明
2. people 必须为空数组 []（人物识别由其他模块处理）
3. 看不清或不确定的字符串用 ""，数组用 []
4. 使用简体中文

JSON 格式：
{
  "people": [],
  "scene": "一句话场景描述",
  "location": "能从画面判断的地点描述，否则空字符串",
  "objects": ["可见物体"],
  "actions": ["正在发生的动作"],
  "emotion": ["可观察到的情绪"],
  "tags": ["便于检索的标签"],
  "quality": {"blur": false, "face_detected": false}
}"""


def _image_to_base64(image_path: Path) -> str | None:
    """读取图片并转为 base64；HEIC 会先转为 JPEG。"""
    if not image_path.is_file():
        logger.warning("图片不存在: %s", image_path)
        return None

    suffix = image_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        logger.warning("不支持的图片格式: %s", image_path)
        return None

    try:
        if suffix in {".heic", ".heif"}:
            from PIL import Image

            import pillow_heif

            pillow_heif.register_heif_opener()
            with Image.open(image_path) as img:
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=90)
                return base64.b64encode(buf.getvalue()).decode("ascii")

        return base64.b64encode(image_path.read_bytes()).decode("ascii")
    except Exception as exc:
        logger.warning("图片编码失败 %s: %s", image_path, exc)
        return None


def _extract_json_object(text: str) -> dict | None:
    """从模型输出中解析 JSON 对象。"""
    text = text.strip()
    if not text:
        return None

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError as exc:
        logger.warning("解析 Ollama JSON 失败: %s", exc)
        return None


def _call_ollama_chat(model: str, prompt: str, image_b64: str) -> str:
    """调用 Ollama /api/chat，返回 assistant 文本。"""
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))

    message = data.get("message") or {}
    content = message.get("content", "")
    return str(content).strip()


def analyze_image_ollama(image_path: str | Path) -> AnalysisResult:
    """调用本地 Ollama 视觉模型分析图片。失败时返回空分析结果。"""
    if not OLLAMA_VISION_ENABLED:
        logger.debug("Ollama 视觉分析已禁用 (OLLAMA_VISION_ENABLED=false)")
        return empty_analysis()

    path = Path(image_path)
    image_b64 = _image_to_base64(path)
    if image_b64 is None:
        return empty_analysis()

    try:
        logger.info(
            "Ollama 视觉分析: model=%s, image=%s",
            OLLAMA_VISION_MODEL,
            path.name,
        )
        content = _call_ollama_chat(
            OLLAMA_VISION_MODEL,
            _VISION_PROMPT,
            image_b64,
        )
    except urllib.error.URLError as exc:
        logger.warning(
            "Ollama 请求失败 (%s)。请确认 ollama serve 已启动且已 pull 模型 %s",
            exc,
            OLLAMA_VISION_MODEL,
        )
        return empty_analysis()
    except TimeoutError:
        logger.warning("Ollama 请求超时 (%ss)", OLLAMA_TIMEOUT)
        return empty_analysis()
    except Exception as exc:
        logger.warning("Ollama 视觉分析失败: %s", exc)
        return empty_analysis()

    parsed = _extract_json_object(content)
    if parsed is None:
        logger.warning("Ollama 返回内容无法解析为 JSON: %s", content[:200])
        return empty_analysis()

    # people 由人脸识别模块负责，忽略模型返回的人物信息
    parsed["people"] = []
    result = analysis_from_dict(parsed)
    logger.info("Ollama 分析完成: scene=%s", result["scene"][:50] if result["scene"] else "")
    return result
