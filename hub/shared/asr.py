"""语音转写唯一入口：视频/音频 → transcript 字段（本地 Whisper）。

其它模块不要直接 import whisper / faster_whisper SDK。
依赖：本机 ffmpeg（PATH）+ faster-whisper（推荐无 av 安装）。

Python 3.14 上 `pip install faster-whisper` 常因 PyAV 无 wheel 失败，请改用：

    pip install faster-whisper --no-deps
    pip install "ctranslate2>=4.0" huggingface_hub tokenizers

本模块用 ffmpeg 抽 wav + numpy 读入，不依赖 PyAV。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import types
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from hub.shared.config import (
    ASR_BEAM_SIZE,
    ASR_CACHE_DIR,
    ASR_ENABLED,
    ASR_GLOSSARY_FILE,
    ASR_INITIAL_PROMPT,
    ASR_LANGUAGE,
    ASR_MODEL,
    ASR_VAD_FILTER,
    DATA_DIR,
)
from hub.shared.schema import Transcript

logger = logging.getLogger(__name__)

_whisper_model = None
_whisper_backend: str | None = None
_glossary_cache: dict | None = None
_glossary_mtime: float | None = None

_INSTALL_HINT = (
    'pip install faster-whisper --no-deps && '
    'pip install "ctranslate2>=4.0" huggingface_hub tokenizers'
)


def _ensure_av_stub() -> None:
    """Python 3.14 常无 PyAV wheel；faster-whisper 仅 import 时需要 av。

    我们用 ffmpeg+numpy 喂波形，不会调用 decode_audio，因此注入空 stub 即可。
    """
    if "av" in sys.modules:
        return
    try:
        import av  # noqa: F401

        return
    except ImportError:
        pass
    stub = types.ModuleType("av")
    stub.__doc__ = "MemoryGraph ASR stub — real PyAV not required"
    sys.modules["av"] = stub
    logger.debug("已注入 av stub（跳过 PyAV）")


@dataclass(frozen=True)
class TranscribeResult:
    text: str
    language: str
    source: str
    skipped: bool = False
    skip_reason: str = ""

    def as_transcript(self) -> Transcript | None:
        if self.skipped and not self.text.strip():
            return None
        from hub.shared.schema import make_transcript

        return make_transcript(
            self.text.strip(),
            language=self.language or "",
            source=self.source or "whisper",
            status="draft",
        )


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def asr_available() -> tuple[bool, str]:
    """返回 (可用?, 说明)。"""
    if not ASR_ENABLED:
        return False, "ASR_ENABLED=false"
    if not find_ffmpeg():
        return False, "未找到 ffmpeg（brew install ffmpeg）"
    try:
        _ensure_av_stub()
        import ctranslate2  # noqa: F401
        import faster_whisper  # noqa: F401

        return True, "faster-whisper"
    except ImportError:
        pass
    try:
        import whisper  # noqa: F401

        return True, "openai-whisper"
    except ImportError:
        return False, f"未安装 ASR 库。推荐（避开 PyAV）：{_INSTALL_HINT}"


def extract_audio_wav(
    media_path: str | Path,
    *,
    dest_wav: Path | None = None,
    sample_rate: int = 16000,
) -> Path:
    """用 ffmpeg 抽出单声道 16k wav；失败抛 RuntimeError。"""
    src = Path(media_path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"媒体文件不存在: {src}")

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，请先安装：brew install ffmpeg")

    if dest_wav is None:
        ASR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dest_wav = ASR_CACHE_DIR / f"{src.stem}_{src.stat().st_mtime_ns}.wav"
    else:
        dest_wav = Path(dest_wav)
        dest_wav.parent.mkdir(parents=True, exist_ok=True)

    if dest_wav.is_file() and dest_wav.stat().st_size > 0:
        return dest_wav

    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(dest_wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dest_wav.is_file():
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = "\n".join(err[-8:]) if err else "unknown"
        raise RuntimeError(f"ffmpeg 抽音失败: {tail}")
    return dest_wav


def _load_wav_f32(wav_path: Path) -> np.ndarray:
    """读取 pcm_s16le wav → float32 [-1, 1]，供 faster-whisper 直接吃（不经 PyAV）。"""
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError(f"期望单声道 wav，实际 {wf.getnchannels()} 声道")
        if wf.getsampwidth() != 2:
            raise ValueError(f"期望 16-bit pcm，sampwidth={wf.getsampwidth()}")
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _load_faster_whisper():
    global _whisper_model, _whisper_backend
    if _whisper_model is not None and _whisper_backend == "faster_whisper":
        return _whisper_model
    _ensure_av_stub()
    # 再次确保（若其它库已提前 import hub，setdefault 可能已晚；进程内仍可尽量关掉）
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from faster_whisper import WhisperModel

    last_err: Exception | None = None
    for device, ctype in (("cpu", "int8"), ("cpu", "default")):
        try:
            model = WhisperModel(ASR_MODEL, device=device, compute_type=ctype)
            _whisper_model = model
            _whisper_backend = "faster_whisper"
            logger.info("已加载 faster-whisper 模型: %s (%s/%s)", ASR_MODEL, device, ctype)
            return model
        except Exception as exc:  # noqa: BLE001 — 尝试下一组 device/compute
            last_err = exc
            msg = str(exc)
            if "401" in msg or "Unauthorized" in msg or "xethub" in msg.lower() or "Xet" in msg:
                raise RuntimeError(
                    "下载 Whisper 模型失败（HuggingFace Xet/鉴权）。"
                    "请新开终端后重试（已默认 HF_HUB_DISABLE_XET=1）；"
                    "若仍失败：rm -rf ~/.cache/huggingface/hub/models--Systran--faster-whisper-base "
                    "并确认 HF_ENDPOINT=https://hf-mirror.com；"
                    "或手动下载模型后设 ASR_MODEL=/本地路径。"
                ) from exc
            logger.warning("加载模型失败 (%s/%s): %s", device, ctype, exc)
    raise RuntimeError(f"无法加载 faster-whisper 模型: {last_err}") from last_err


def _load_openai_whisper():
    global _whisper_model, _whisper_backend
    if _whisper_model is not None and _whisper_backend == "openai_whisper":
        return _whisper_model
    import whisper

    model = whisper.load_model(ASR_MODEL)
    _whisper_model = model
    _whisper_backend = "openai_whisper"
    logger.info("已加载 openai-whisper 模型: %s", ASR_MODEL)
    return model


def _join_segments(parts: list[str]) -> str:
    if not parts:
        return ""
    has_cjk = any("\u4e00" <= c <= "\u9fff" for p in parts for c in p)
    return "".join(parts) if has_cjk else " ".join(parts)


def _load_glossary() -> dict:
    """加载家庭专名提示 + 错写替换表。"""
    global _glossary_cache, _glossary_mtime
    path = Path(ASR_GLOSSARY_FILE)
    example = DATA_DIR / "asr_glossary.example.json"
    if not path.is_file() and example.is_file():
        path = example
    if not path.is_file():
        return {"prompt_names": [], "replace": {}}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {"prompt_names": [], "replace": {}}
    if _glossary_cache is not None and _glossary_mtime == mtime:
        return _glossary_cache
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 ASR 词表失败 %s: %s", path, exc)
        data = {}
    out = {
        "prompt_names": [str(x).strip() for x in (data.get("prompt_names") or []) if str(x).strip()],
        "replace": {
            str(k): str(v)
            for k, v in (data.get("replace") or {}).items()
            if str(k).strip() and str(v).strip()
        },
    }
    _glossary_cache = out
    _glossary_mtime = mtime
    return out


def _build_initial_prompt() -> str | None:
    base = (ASR_INITIAL_PROMPT or "").strip()
    names = _load_glossary().get("prompt_names") or []
    missing = [n for n in names if n and n not in base]
    if missing:
        hint = "常见人名：" + "、".join(missing) + "。"
        base = f"{base} {hint}".strip() if base else hint
    return base or None


def _apply_glossary(text: str) -> str:
    """事后替换易错专名（长 key 优先）。"""
    if not text:
        return text
    mapping = _load_glossary().get("replace") or {}
    if not mapping:
        return text
    out = text
    for wrong, right in sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True):
        if wrong in out:
            out = out.replace(wrong, right)
    return out


def _transcribe_wav(wav_path: Path, *, language: str) -> tuple[str, str, str]:
    """返回 (text, language, source_tag)。"""
    lang = (language or "").strip() or None
    try:
        model = _load_faster_whisper()
        audio = _load_wav_f32(wav_path)
        prompt = _build_initial_prompt()
        vad_params = None
        if ASR_VAD_FILTER:
            # 比默认更宽松：少切童声/混响尾音
            vad_params = {
                "min_silence_duration_ms": 800,
                "speech_pad_ms": 400,
            }
        segments, info = model.transcribe(
            audio,
            language=lang,
            beam_size=max(1, ASR_BEAM_SIZE),
            condition_on_previous_text=True,
            vad_filter=ASR_VAD_FILTER,
            vad_parameters=vad_params,
            initial_prompt=prompt,
        )
        parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
        text = _apply_glossary(_join_segments(parts))
        detected = getattr(info, "language", None) or (lang or "")
        return text.strip(), str(detected or ""), "whisper"
    except ImportError:
        pass

    try:
        model = _load_openai_whisper()
        result = model.transcribe(
            str(wav_path),
            language=lang,
            fp16=False,
            initial_prompt=_build_initial_prompt(),
        )
        text = _apply_glossary(str(result.get("text") or "").strip())
        detected = str(result.get("language") or lang or "")
        return text, detected, "whisper"
    except ImportError as exc:
        raise RuntimeError(f"未安装 ASR 库。推荐：{_INSTALL_HINT}") from exc


def transcribe_audio(
    media_path: str | Path,
    *,
    language: str | None = None,
) -> TranscribeResult:
    """
    唯一 ASR 入口：音频或视频路径 → 转写结果。

    language 覆盖默认 ASR_LANGUAGE；空文本不算失败（可能是静音）。
    """
    if not ASR_ENABLED:
        return TranscribeResult(
            text="",
            language="",
            source="omitted",
            skipped=True,
            skip_reason="ASR_ENABLED=false",
        )

    ok, reason = asr_available()
    if not ok:
        raise RuntimeError(reason)

    src = Path(media_path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"媒体文件不存在: {src}")

    lang = (language if language is not None else ASR_LANGUAGE) or ""
    tmp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if src.suffix.lower() == ".wav":
            wav = src
        else:
            tmp_dir = tempfile.TemporaryDirectory(prefix="mg_asr_")
            wav = extract_audio_wav(src, dest_wav=Path(tmp_dir.name) / "audio.wav")

        text, detected, source = _transcribe_wav(wav, language=lang)
        return TranscribeResult(
            text=text,
            language=detected or lang,
            source=source,
        )
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()
