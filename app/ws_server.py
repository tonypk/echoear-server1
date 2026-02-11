"""WebSocket server — thin connection lifecycle + message routing.

All pipeline logic (ASR/LLM/TTS/rate-control) lives in pipeline.py.
Session state lives in session.py.
"""
import asyncio
import json
import logging
import traceback

import websockets
from websockets.server import WebSocketServerProtocol

from .config import settings
from .session import Session
from .pipeline import run_pipeline, ws_send_safe
from .registry import registry
from .llm import reset_conversation

logger = logging.getLogger(__name__)


async def handle_text_message(ws: WebSocketServerProtocol, session: Session, text: str):
    """Route incoming JSON messages."""
    try:
        payload = json.loads(text)
    except Exception:
        await ws_send_safe(ws, json.dumps({"type": "error", "message": "invalid json"}), session)
        return

    mtype = payload.get("type")
    session.touch()
    logger.info(f"[{session.session_id}] Device {session.device_id}: {mtype}")

    if mtype == "hello":
        listen_mode = payload.get("listen_mode")
        if listen_mode:
            session.listen_mode = listen_mode
            session.protocol_version = 2
            logger.info(f"[{session.session_id}] Xiaozhi protocol v2, listen_mode={listen_mode}")

        hello_resp = {
            "type": "hello",
            "session_id": session.session_id,
            "audio_params": {
                "sample_rate": settings.pcm_sample_rate,
                "channels": settings.pcm_channels,
                "codec": "opus",
                "frame_duration_ms": settings.frame_duration_ms,
            },
            "features": {"asr": True, "tts": True, "llm": True, "abort": True},
            "version": session.protocol_version,
        }
        await ws_send_safe(ws, json.dumps(hello_resp), session, "hello_resp")
        logger.info(f"[{session.session_id}] Hello handshake complete")

    elif mtype == "audio_start":
        session.opus_packets = []
        session.listening = True
        session.tts_abort = False

    elif mtype == "audio_end":
        session.listening = False
        _launch_pipeline(ws, session)

    elif mtype == "listen":
        listen_state = payload.get("state")
        listen_mode = payload.get("mode")

        if listen_state == "detect":
            logger.info(f"[{session.session_id}] Wake detected: text={payload.get('text')}")

        elif listen_state == "start":
            if listen_mode:
                session.listen_mode = listen_mode
            session.opus_packets = []
            session.listening = True
            session.tts_abort = False
            logger.info(f"[{session.session_id}] Listen start (mode={listen_mode})")

        elif listen_state == "stop":
            session.listening = False
            logger.info(f"[{session.session_id}] Listen stop, launching pipeline...")
            _launch_pipeline(ws, session)

    elif mtype == "abort":
        reason = payload.get("reason", "unknown")
        logger.info(f"[{session.session_id}] Abort requested (reason={reason})")
        session.tts_abort = True
        await ws_send_safe(ws, json.dumps({"type": "tts_end", "reason": "abort"}), session, "abort_ack")

    elif mtype == "ping":
        await ws_send_safe(ws, json.dumps({"type": "pong"}), session, "pong")


def _launch_pipeline(ws: WebSocketServerProtocol, session: Session):
    """Launch the ASR→LLM→TTS pipeline as a background task."""
    if session.processing:
        logger.warning(f"[{session.session_id}] Already processing, ignoring new request")
        return

    if session._process_task and not session._process_task.done():
        logger.warning(f"[{session.session_id}] Cancelling previous pipeline task")
        session._process_task.cancel()

    session._process_task = asyncio.create_task(_pipeline_wrapper(ws, session))


async def _pipeline_wrapper(ws: WebSocketServerProtocol, session: Session):
    """Wrapper to catch unhandled exceptions from the pipeline."""
    try:
        await run_pipeline(ws, session)
    except asyncio.CancelledError:
        logger.info(f"[{session.session_id}] Pipeline cancelled")
        session.processing = False
    except Exception as e:
        logger.error(f"[{session.session_id}] UNHANDLED in pipeline: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        session.processing = False
        try:
            await ws_send_safe(ws, json.dumps({"type": "error", "message": f"Internal error: {e}"}), session)
        except Exception:
            pass


async def handle_client(ws: WebSocketServerProtocol, path: str):
    """Main WebSocket connection handler — auth, message loop, cleanup."""
    device_id = ws.request_headers.get("x-device-id")
    token = ws.request_headers.get("x-device-token")

    logger.info(f"New connection from {ws.remote_address}, path: {path}")

    if not device_id or not token:
        logger.warning(f"Missing credentials from {ws.remote_address}")
        await ws_send_safe(ws, json.dumps({"type": "error", "message": "missing device_id/token"}), Session("unknown"))
        await ws.close(code=4401, reason="missing credentials")
        return

    if not registry.is_valid(device_id, token):
        logger.warning(f"Invalid token for device {device_id}")
        await ws_send_safe(ws, json.dumps({"type": "error", "message": "invalid token"}), Session("unknown"))
        await ws.close(code=4401, reason="invalid token")
        return

    session = Session(device_id)
    logger.info(f"[{session.session_id}] Device {device_id} authenticated, session started")

    try:
        async for message in ws:
            if isinstance(message, str):
                await handle_text_message(ws, session, message)
            elif isinstance(message, bytes):
                # Accumulate Opus audio packets
                if session.listening:
                    session.opus_packets.append(bytes(message))
                    session.touch()
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"[{session.session_id}] Device {device_id} disconnected")
    except Exception as e:
        logger.error(f"[{session.session_id}] Error handling device {device_id}: {e}", exc_info=True)
    finally:
        session.tts_abort = True
        if session._process_task and not session._process_task.done():
            logger.info(f"[{session.session_id}] Waiting for pipeline to finish...")
            try:
                await asyncio.wait_for(session._process_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                session._process_task.cancel()
                logger.warning(f"[{session.session_id}] Force-cancelled pipeline")
        reset_conversation(session.session_id)
        logger.info(f"[{session.session_id}] Session ended for device {device_id}")


async def start_websocket_server():
    """Start the WebSocket server."""
    logger.info(f"Starting WebSocket server on {settings.ws_host}:{settings.ws_port}")

    async with websockets.serve(
        handle_client,
        settings.ws_host,
        settings.ws_port,
        ping_interval=None,
        ping_timeout=None,
        write_limit=4096,
        max_queue=64,
    ):
        logger.info(f"WebSocket server listening on ws://{settings.ws_host}:{settings.ws_port}/ws")
        await asyncio.Future()
