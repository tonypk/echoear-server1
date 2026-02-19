import io
import struct
import logging
import math
from collections import OrderedDict
from typing import Optional
import numpy as np
from openai import AsyncOpenAI
from .config import settings
from .session import Session

logger = logging.getLogger(__name__)

# Global default client
_client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
)

# Per-user client cache with LRU eviction: (base_url, api_key) → AsyncOpenAI
_CLIENT_CACHE_MAX = 20
_client_cache: OrderedDict[tuple[str, str], AsyncOpenAI] = OrderedDict()


def _get_client(session: Optional[Session] = None) -> AsyncOpenAI:
    """Return cached per-user client if session has custom API key, else global."""
    if session and session.config.openai_api_key:
        base_url = session.config.get("openai_base_url", settings.openai_base_url)
        key = (base_url, session.config.openai_api_key)
        if key not in _client_cache:
            if len(_client_cache) >= _CLIENT_CACHE_MAX:
                _client_cache.popitem(last=False)
            _client_cache[key] = AsyncOpenAI(api_key=session.config.openai_api_key, base_url=base_url)
        _client_cache.move_to_end(key)
        return _client_cache[key]
    return _client

def pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """Convert raw PCM16 mono 16kHz to WAV format in memory"""
    num_channels = settings.pcm_channels
    sample_rate = settings.pcm_sample_rate
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_bytes)

    buf = io.BytesIO()
    # RIFF header
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', 36 + data_size))
    buf.write(b'WAVE')
    # fmt chunk
    buf.write(b'fmt ')
    buf.write(struct.pack('<I', 16))  # chunk size
    buf.write(struct.pack('<H', 1))   # PCM format
    buf.write(struct.pack('<H', num_channels))
    buf.write(struct.pack('<I', sample_rate))
    buf.write(struct.pack('<I', byte_rate))
    buf.write(struct.pack('<H', block_align))
    buf.write(struct.pack('<H', bits_per_sample))
    # data chunk
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    buf.write(pcm_bytes)
    return buf.getvalue()


# Whisper hallucination patterns — produced from silence/noise input
_HALLUCINATIONS = {
    # English
    "thank you", "thank you for watching", "thanks for watching",
    "thanks", "bye", "goodbye", "all right", "you", "the end",
    "subscribe", "like and subscribe", "see you next time",
    "so", "okay", "yeah", "yes", "no", "hmm", "uh",
    # Chinese
    "谢谢观看", "感谢观看", "请订阅", "点赞", "订阅",
    "谢谢大家", "谢谢", "再见", "好的", "嗯",
    "字幕", "字幕由", "字幕提供",
}

# Longer hallucination patterns — match as substrings
# NOTE: Whisper prompt must stay under ~170 chars — longer prompts cause misrecognition.
_ASR_PROMPT = (
    "HiTony语音助手。播放音乐，放首歌，下一首，切歌，暂停，继续播放，停止播放，"
    "音量大一点，音量小一点，提醒我，设置闹钟，今天天气怎么样，"
    "搜索，帮我查一下，开始会议，结束会议，记一下，清空对话，你好，谢谢，再见。"
)

_HALLUCINATION_SUBSTRINGS = [
    "点赞", "订阅", "转发", "打赏", "关注",
    "字幕由", "字幕提供", "subtitles by",
    "thank you for watching", "thanks for watching",
    "like and subscribe",
    "明镜", "栏目", "支持明镜",
    "请不吝", "视频来源",
]


def _preprocess_pcm(pcm_bytes: bytes) -> bytes:
    """Pre-process PCM audio for reliable ASR:
    Peak normalization to -3 dBFS (mic signal is very quiet, ~0.5% full scale).
    """
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    peak = np.max(np.abs(samples))
    if peak < 100:  # Near-silence, don't amplify noise
        return pcm_bytes

    current_peak_db = 20 * math.log10(peak / 32768)
    if current_peak_db > -6:  # Already loud enough
        logger.info(f"ASR preprocess: peak {current_peak_db:.1f} dBFS (loud enough, skip)")
        return pcm_bytes

    target_peak = 32768 * 10 ** (-3.0 / 20)  # -3 dBFS
    gain = target_peak / peak
    normalized = np.clip(samples * gain, -32768, 32767).astype(np.int16)
    logger.info(f"ASR preprocess: peak {current_peak_db:.1f} dBFS → gain {gain:.1f}x")
    return normalized.tobytes()


async def transcribe_pcm(pcm_bytes: bytes, session: Optional[Session] = None) -> str:
    """Transcribe PCM audio using OpenAI Whisper API"""
    duration_s = len(pcm_bytes) / 2 / settings.pcm_sample_rate

    # Peak normalization (mic signal is very quiet)
    pcm_bytes = _preprocess_pcm(pcm_bytes)

    wav_bytes = pcm_to_wav(pcm_bytes)
    logger.info(f"ASR: sending {len(pcm_bytes)} bytes PCM ({duration_s:.1f}s, {len(wav_bytes)} bytes WAV) to Whisper")

    # Filter very short recordings (<0.5s) — usually noise/accidental triggers
    if duration_s < 0.5:
        logger.info(f"ASR: skipping short audio ({duration_s:.1f}s < 0.5s)")
        return ""

    wav_file = io.BytesIO(wav_bytes)
    wav_file.name = "audio.wav"

    client = _get_client(session)
    asr_model = (session.config.get("openai_asr_model", settings.openai_asr_model)
                 if session else settings.openai_asr_model)

    # Try user's OpenClaw first (Pro mode), fallback to default if unsupported
    try:
        transcript = await client.audio.transcriptions.create(
            model=asr_model,
            file=wav_file,
            temperature=0,
            language="zh",
            # Whisper prompt: vocabulary hints for common commands
            prompt=_ASR_PROMPT,
        )
    except Exception as e:
        # Fallback to default API if user's OpenClaw doesn't support ASR
        if session and session.config.openai_base_url:
            logger.warning(f"ASR: Pro mode failed ({e}), falling back to default API")
            wav_file.seek(0)  # Reset file pointer
            transcript = await _client.audio.transcriptions.create(
                model=settings.openai_asr_model,
                file=wav_file,
                temperature=0,
                language="zh",
                prompt=_ASR_PROMPT,
            )
        else:
            raise  # Re-raise if not in Pro mode

    text = transcript.text.strip()
    logger.info(f"ASR result: {text}")

    # Filter known Whisper hallucinations (noise/silence → fake output)
    normalized = text.lower().rstrip(".!?,。！？，")
    if normalized in _HALLUCINATIONS:
        logger.warning(f"ASR: filtered hallucination (exact): '{text}'")
        return ""

    # Substring hallucination check (YouTube-style garbage)
    lower_text = text.lower()
    for pattern in _HALLUCINATION_SUBSTRINGS:
        if pattern in lower_text:
            logger.warning(f"ASR: filtered hallucination (substring '{pattern}'): '{text}'")
            return ""

    return text
