"""图片分析入口。

整个工程唯一的 AI 分析接口：analyze_image()。
替换模型时只需修改此文件，其它模块不应依赖具体模型实现。
"""

from __future__ import annotations

from photo2json.schema import AnalysisResult, empty_analysis


def analyze_image(image_path: str) -> dict:
    """分析单张图片，返回符合 Schema 的 AI 字段。

    Args:
        image_path: 图片文件的绝对或相对路径。

    Returns:
        包含 people / scene / location / objects / actions /
        emotion / tags / quality 的字典。

    Note:
        第一版为 Mock 实现，不调用任何 AI 模型。
        后续可替换为 Qwen2.5-VL、Gemini、GPT-4o 等实现。
    """
    # image_path 预留给未来模型调用；Mock 阶段不使用
    _ = image_path

    result: AnalysisResult = empty_analysis()
    return dict(result)
