"""ASR → LLM → TTS pipeline with rate-controlled audio streaming."""
import asyncio
import json
import logging
import time
from typing import Optional, Tuple, List

import opuslib
from websockets.server import WebSocketServerProtocol

from .config import settings
from .session import Session
from .audio_rate_ctrl import AudioRateController
from .asr import transcribe_pcm
from .tts import synthesize_tts
from .llm import call_llm

logger = logging.getLogger(__name__)

WS_SEND_TIMEOUT = 2.0  # seconds


async def ws_send_safe(ws: WebSocketServerProtocol, data, session: Session, label: str = "") -> bool:
    """Send data via WebSocket with timeout. Returns True on success."""
    try:
        await asyncio.wait_for(ws.send(data), timeout=WS_SEND_TIMEOUT)
        return True
    except asyncio.TimeoutError:
        logger.error(f"[{session.session_id}] ws.send() timed out ({WS_SEND_TIMEOUT}s) {label}")
        return False
    except Exception as e:
        logger.warning(f"[{session.session_id}] ws.send() failed {label}: {type(e).__name__}: {e}")
        return False


async def run_pipeline(ws: WebSocketServerProtocol, session: Session):
    """Full pipeline: decode Opus → ASR → LLM → TTS → rate-controlled send.

    Runs as a background task so the WS message loop stays responsive
    for abort messages during TTS streaming.
    """
    if not session.opus_packets:
        await ws_send_safe(ws, json.dumps({"type": "error", "message": "empty audio"}), session)
        return

    session.processing = True
    pipeline_t0 = time.monotonic()

    try:
        # Start keepalive pings to keep TCP cwnd open during processing
        keepalive_task = asyncio.create_task(_keepalive_pings(ws, session))

        try:
            result = await _process_asr_llm_tts(ws, session)
        finally:
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                pass

        if result is None:
            return

        opus_packets, reply_text = result

        # Send tts_start
        ok = await ws_send_safe(ws, json.dumps({"type": "tts_start", "text": reply_text}), session, "tts_start")
        if not ok:
            logger.error(f"[{session.session_id}] Failed to send tts_start, aborting")
            return

        # Stream with rate control
        sent = await _stream_with_rate_control(ws, session, opus_packets)

        # Send tts_end
        if not session.tts_abort:
            await ws_send_safe(ws, json.dumps({"type": "tts_end"}), session, "tts_end")
            logger.info(f"[{session.session_id}] TTS complete: {sent}/{len(opus_packets)} packets")
        else:
            logger.info(f"[{session.session_id}] TTS aborted: {sent}/{len(opus_packets)} packets")

    finally:
        session.processing = False
        elapsed = time.monotonic() - pipeline_t0
        logger.info(f"[{session.session_id}] Pipeline total: {elapsed:.1f}s")


async def _keepalive_pings(ws: WebSocketServerProtocol, session: Session):
    """Send WS pings every 1s during processing to keep TCP cwnd open."""
    try:
        while True:
            await asyncio.sleep(1.0)
            if ws.closed or session.tts_abort:
                break
            try:
                await ws.ping()
                logger.debug(f"[{session.session_id}] Keepalive ping sent")
            except Exception:
                break
    except asyncio.CancelledError:
        pass


async def _process_asr_llm_tts(
    ws: WebSocketServerProtocol,
    session: Session,
) -> Optional[Tuple[List[bytes], str]]:
    """Run ASR → LLM → TTS synthesis. Returns (opus_packets, reply_text) or None."""
    sid = session.session_id

    logger.info(f"[{sid}] Pipeline start: {len(session.opus_packets)} opus packets")

    # --- Opus decode ---
    t0 = time.monotonic()
    try:
        decoder = opuslib.Decoder(settings.pcm_sample_rate, settings.pcm_channels)
        pcm_frames = []
        for packet in session.opus_packets:
            pcm_frame = decoder.decode(packet, 960)  # 960 samples = 60ms @ 16kHz
            pcm_frames.append(pcm_frame)
        pcm = b''.join(pcm_frames)
        logger.info(f"[{sid}] Opus decode: {len(session.opus_packets)} packets -> {len(pcm)} bytes ({time.monotonic()-t0:.2f}s)")
    except Exception as e:
        logger.error(f"[{sid}] Opus decode failed: {e}")
        await ws_send_safe(ws, json.dumps({"type": "error", "message": f"Opus decode failed: {e}"}), session)
        return None

    if session.tts_abort or ws.closed:
        logger.info(f"[{sid}] Aborted before ASR")
        return None

    # --- ASR ---
    t0 = time.monotonic()
    try:
        text = await transcribe_pcm(pcm)
        logger.info(f"[{sid}] ASR: '{text}' ({time.monotonic()-t0:.2f}s)")
    except Exception as e:
        logger.error(f"[{sid}] ASR failed: {e}")
        await ws_send_safe(ws, json.dumps({"type": "error", "message": f"ASR failed: {e}"}), session)
        return None

    await ws_send_safe(ws, json.dumps({"type": "asr_text", "text": text}), session, "asr_text")

    if not text or text.strip() == "":
        logger.info(f"[{sid}] ASR empty, skipping LLM+TTS")
        return None

    if session.tts_abort or ws.closed:
        logger.info(f"[{sid}] Aborted before LLM")
        return None

    # --- LLM ---
    t0 = time.monotonic()
    try:
        reply = await call_llm(text, session_id=sid)
        logger.info(f"[{sid}] LLM: '{reply}' ({time.monotonic()-t0:.2f}s)")
    except Exception as e:
        logger.error(f"[{sid}] LLM failed: {e}", exc_info=True)
        await ws_send_safe(ws, json.dumps({"type": "error", "message": f"LLM failed: {e}"}), session)
        return None

    if session.tts_abort or ws.closed:
        logger.info(f"[{sid}] Aborted before TTS")
        return None

    # --- TTS synthesis ---
    t0 = time.monotonic()
    try:
        opus_packets = await synthesize_tts(reply)
        logger.info(f"[{sid}] TTS synth: {len(opus_packets)} packets ({time.monotonic()-t0:.2f}s)")
    except Exception as e:
        logger.error(f"[{sid}] TTS synth failed: {e}")
        await ws_send_safe(ws, json.dumps({"type": "error", "message": f"TTS failed: {e}"}), session)
        return None

    if session.tts_abort or ws.closed:
        logger.info(f"[{sid}] Aborted before TTS stream")
        return None

    return (opus_packets, reply)


async def _stream_with_rate_control(
    ws: WebSocketServerProtocol,
    session: Session,
    opus_packets: List[bytes],
) -> int:
    """Send Opus packets at real-time playback rate using AudioRateController."""
    sid = session.session_id

    ctrl = AudioRateController(frame_duration_ms=settings.frame_duration_ms)
    ctrl.add_all(opus_packets)

    logger.info(f"[{sid}] TTS stream start: {len(opus_packets)} packets at {settings.frame_duration_ms}ms intervals")

    async def send_one(packet: bytes) -> bool:
        return await ws_send_safe(ws, packet, session, f"tts_pkt")

    def should_abort() -> bool:
        return session.tts_abort or ws.closed

    return await ctrl.drain(send_one, should_abort)
