import io
import json
import struct
import logging
import math
from collections import OrderedDict
from typing import Optional
import numpy as np
import websockets
from openai import AsyncOpenAI
from .config import settings
from .session import Session

logger = logging.getLogger(__name__)

# ============================================================================
# OpenAI Whisper client pool
# ============================================================================

_client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
)

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


# ============================================================================
# Audio utilities
# ============================================================================

def pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """Convert raw PCM16 mono 16kHz to WAV format in memory"""
    num_channels = settings.pcm_channels
    sample_rate = settings.pcm_sample_rate
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_bytes)

    buf = io.BytesIO()
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', 36 + data_size))
    buf.write(b'WAVE')
    buf.write(b'fmt ')
    buf.write(struct.pack('<I', 16))
    buf.write(struct.pack('<H', 1))
    buf.write(struct.pack('<H', num_channels))
    buf.write(struct.pack('<I', sample_rate))
    buf.write(struct.pack('<I', byte_rate))
    buf.write(struct.pack('<H', block_align))
    buf.write(struct.pack('<H', bits_per_sample))
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    buf.write(pcm_bytes)
    return buf.getvalue()


# ============================================================================
# Whisper hallucination filter
# ============================================================================

_HALLUCINATIONS = {
    "thank you", "thank you for watching", "thanks for watching",
    "thanks", "bye", "goodbye", "all right", "you", "the end",
    "subscribe", "like and subscribe", "see you next time",
    "so", "okay", "yeah", "yes", "no", "hmm", "uh",
    "谢谢观看", "感谢观看", "请订阅", "点赞", "订阅",
    "谢谢大家", "谢谢", "再见", "好的", "嗯",
    "字幕", "字幕由", "字幕提供",
}

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


def _filter_hallucination(text: str) -> str:
    """Return empty string if text matches known Whisper hallucination patterns."""
    normalized = text.lower().rstrip(".!?,。！？，")
    if normalized in _HALLUCINATIONS:
        logger.warning(f"ASR: filtered hallucination (exact): '{text}'")
        return ""
    lower_text = text.lower()
    for pattern in _HALLUCINATION_SUBSTRINGS:
        if pattern in lower_text:
            logger.warning(f"ASR: filtered hallucination (substring '{pattern}'): '{text}'")
            return ""
    return text


# ============================================================================
# PCM preprocessing
# ============================================================================

def _preprocess_pcm(pcm_bytes: bytes) -> bytes:
    """Peak normalization to -3 dBFS (mic signal is very quiet)."""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    peak = np.max(np.abs(samples))
    if peak < 100:
        return pcm_bytes

    current_peak_db = 20 * math.log10(peak / 32768)
    if current_peak_db > -6:
        logger.info(f"ASR preprocess: peak {current_peak_db:.1f} dBFS (loud enough, skip)")
        return pcm_bytes

    target_peak = 32768 * 10 ** (-3.0 / 20)
    gain = target_peak / peak
    normalized = np.clip(samples * gain, -32768, 32767).astype(np.int16)
    logger.info(f"ASR preprocess: peak {current_peak_db:.1f} dBFS → gain {gain:.1f}x")
    return normalized.tobytes()


# ============================================================================
# Provider: OpenAI Whisper
# ============================================================================

async def _transcribe_whisper(pcm_bytes: bytes, session: Optional[Session] = None) -> str:
    """Transcribe using OpenAI Whisper API."""
    wav_bytes = pcm_to_wav(pcm_bytes)
    wav_file = io.BytesIO(wav_bytes)
    wav_file.name = "audio.wav"

    client = _get_client(session)
    asr_model = (session.config.get("openai_asr_model", settings.openai_asr_model)
                 if session else settings.openai_asr_model)

    try:
        transcript = await client.audio.transcriptions.create(
            model=asr_model,
            file=wav_file,
            temperature=0,
            language="zh",
            prompt=_ASR_PROMPT,
        )
    except Exception as e:
        if session and session.config.openai_base_url:
            logger.warning(f"ASR Whisper: Pro mode failed ({e}), falling back to default API")
            wav_file.seek(0)
            transcript = await _client.audio.transcriptions.create(
                model=settings.openai_asr_model,
                file=wav_file,
                temperature=0,
                language="zh",
                prompt=_ASR_PROMPT,
            )
        else:
            raise

    text = transcript.text.strip()
    return _filter_hallucination(text)


# ============================================================================
# Provider: FunASR (self-hosted, WebSocket protocol)
# ============================================================================

# FunASR hotwords: boost recognition of HiTony command keywords
_FUNASR_HOTWORDS = (
    "播放 音乐 暂停 继续 停止 下一首 切歌 "
    "提醒 闹钟 天气 搜索 会议 记一下 清空 你好 再见"
)


async def _transcribe_funasr(pcm_bytes: bytes, session: Optional[Session] = None) -> str:
    """Transcribe using self-hosted FunASR server (WebSocket protocol).

    Protocol:
    1. Send JSON config (text frame)
    2. Send PCM audio bytes (binary frames, chunked)
    3. Send {"is_speaking": false} (text frame)
    4. Receive JSON result with "text" field
    """
    funasr_url = settings.funasr_url

    try:
        async with websockets.connect(funasr_url, open_timeout=5, close_timeout=5) as ws:
            # Step 1: Send config
            config = {
                "mode": "offline",
                "wav_name": "hitony_audio",
                "wav_format": "pcm",
                "is_speaking": True,
                "audio_fs": settings.pcm_sample_rate,
                "itn": True,
                "hotwords": _FUNASR_HOTWORDS,
            }
            await ws.send(json.dumps(config, ensure_ascii=False))

            # Step 2: Send PCM audio in chunks (60ms = 1920 bytes at 16kHz 16bit mono)
            chunk_size = 1920 * 2  # 1920 samples * 2 bytes
            for i in range(0, len(pcm_bytes), chunk_size):
                await ws.send(pcm_bytes[i:i + chunk_size])

            # Step 3: Signal end of speech
            await ws.send(json.dumps({"is_speaking": False}))

            # Step 4: Receive result
            text = ""
            async for message in ws:
                result = json.loads(message)
                text = result.get("text", "")
                if result.get("is_final", False) or result.get("mode") == "offline":
                    break

            text = text.strip()
            if text:
                logger.info(f"ASR FunASR result: {text}")
            return text

    except Exception as e:
        logger.error(f"ASR FunASR error: {e}")
        # Fallback to Whisper on FunASR failure
        logger.warning("ASR: FunASR failed, falling back to Whisper")
        return await _transcribe_whisper(pcm_bytes, session)


# ============================================================================
# Public API: transcribe_pcm (provider router)
# ============================================================================

def _get_asr_provider(session: Optional[Session] = None) -> str:
    """Determine ASR provider: per-user config > global config > 'whisper'."""
    if session:
        provider = session.config.get("asr_provider", "")
        if provider:
            return provider
    return settings.asr_provider


async def transcribe_pcm(pcm_bytes: bytes, session: Optional[Session] = None) -> str:
    """Transcribe PCM audio using the configured ASR provider."""
    duration_s = len(pcm_bytes) / 2 / settings.pcm_sample_rate

    # Filter very short recordings (<0.5s) — usually noise/accidental triggers
    if duration_s < 0.5:
        logger.info(f"ASR: skipping short audio ({duration_s:.1f}s < 0.5s)")
        return ""

    # Peak normalization (mic signal is very quiet)
    pcm_bytes = _preprocess_pcm(pcm_bytes)

    provider = _get_asr_provider(session)
    logger.info(f"ASR: {len(pcm_bytes)} bytes PCM ({duration_s:.1f}s), provider={provider}")

    if provider == "funasr":
        return await _transcribe_funasr(pcm_bytes, session)

    # Default: Whisper
    return await _transcribe_whisper(pcm_bytes, session)
