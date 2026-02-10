"""WebSocket server using websockets library (xiaozhi-compatible)"""
import asyncio
import json
import logging
from typing import Optional, List
import websockets
from websockets.server import WebSocketServerProtocol
import opuslib

from .config import settings
from .protocol import AsrText, TtsStart, TtsEnd, ErrorMsg
from .registry import registry
from .asr import transcribe_pcm
from .tts import synthesize_tts
from .openclaw import call_openclaw

logger = logging.getLogger(__name__)

class ConnState:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.opus_packets: List[bytes] = []  # Store individual Opus packets
        self.listening = False

async def handle_text_message(ws: WebSocketServerProtocol, state: ConnState, text: str):
    """Handle text JSON messages from device"""
    try:
        payload = json.loads(text)
    except Exception:
        await ws.send(json.dumps({"type": "error", "message": "invalid json"}))
        return

    mtype = payload.get("type")
    logger.info(f"Device {state.device_id} text message: {mtype}")

    if mtype == "hello":
        # Acknowledge hello
        return
    elif mtype == "wake":
        # Device woke up
        return
    elif mtype == "audio_start":
        state.opus_packets = []
        state.listening = True
        return
    elif mtype == "audio_end":
        state.listening = False
        await process_audio(ws, state)
        return

async def handle_binary_message(ws: WebSocketServerProtocol, state: ConnState, chunk: bytes):
    """Accumulate Opus audio packets"""
    if not state.listening:
        return
    state.opus_packets.append(bytes(chunk))

async def process_audio(ws: WebSocketServerProtocol, state: ConnState):
    """Process accumulated audio: Opus decode -> ASR -> LLM -> TTS"""
    if not state.opus_packets:
        await ws.send(json.dumps({"type": "error", "message": "empty audio"}))
        return

    # Decode Opus packets to raw PCM
    try:
        decoder = opuslib.Decoder(settings.pcm_sample_rate, settings.pcm_channels)
        pcm_frames = []
        for packet in state.opus_packets:
            pcm_frame = decoder.decode(packet, 960)  # 960 samples = 60ms @ 16kHz
            pcm_frames.append(pcm_frame)
        pcm = b''.join(pcm_frames)
        logger.info(f"Decoded {len(state.opus_packets)} Opus packets to {len(pcm)} bytes PCM")
    except Exception as e:
        logger.error(f"Opus decode failed: {e}")
        await ws.send(json.dumps({"type": "error", "message": f"Opus decode failed: {e}"}))
        return

    # ASR
    try:
        text = await transcribe_pcm(pcm)
        logger.info(f"ASR result: {text}")
    except Exception as e:
        logger.error(f"ASR failed: {e}")
        await ws.send(json.dumps({"type": "error", "message": f"ASR failed: {e}"}))
        return

    await ws.send(json.dumps({"type": "asr_text", "text": text}))

    # LLM via OpenClaw (with fallback for testing)
    try:
        reply = await call_openclaw(text)
        logger.info(f"LLM reply: {reply}")
    except Exception as e:
        logger.warning(f"OpenClaw failed: {e}, using test response")
        # Fallback: return a test response (English for better TTS quality)
        reply = "OK, I got it"

    # TTS - now returns Opus packets
    try:
        opus_packets = await synthesize_tts(reply)
        packet_sizes = [len(p) for p in opus_packets[:10]]
        logger.info(f"TTS synthesized {len(opus_packets)} Opus packets, first 10 sizes: {packet_sizes}")
    except Exception as e:
        logger.error(f"TTS failed: {e}")
        await ws.send(json.dumps({"type": "error", "message": f"TTS failed: {e}"}))
        return

    await ws.send(json.dumps({"type": "tts_start"}))

    # Stream Opus packets (each packet is 60ms frame)
    for packet in opus_packets:
        await ws.send(packet)
        await asyncio.sleep(0.02)  # Small delay to pace transmission

    await ws.send(json.dumps({"type": "tts_end"}))

async def handle_client(ws: WebSocketServerProtocol, path: str):
    """Main WebSocket connection handler"""
    # Extract device_id and token from headers
    device_id = ws.request_headers.get("x-device-id")
    token = ws.request_headers.get("x-device-token")

    # Log all headers for debugging
    logger.info(f"New connection from {ws.remote_address}")
    logger.info(f"Path: {path}")
    logger.info(f"Headers: {dict(ws.request_headers)}")
    logger.info(f"Extracted: device_id={device_id}, token={token}")

    if not device_id or not token:
        logger.warning(f"Missing credentials from {ws.remote_address}")
        await ws.send(json.dumps({"type": "error", "message": "missing device_id/token"}))
        await ws.close(code=4401, reason="missing credentials")
        return

    if not registry.is_valid(device_id, token):
        logger.warning(f"Invalid token for device {device_id}")
        await ws.send(json.dumps({"type": "error", "message": "invalid token"}))
        await ws.close(code=4401, reason="invalid token")
        return

    logger.info(f"Device {device_id} authenticated successfully")
    state = ConnState(device_id)

    try:
        # Main message loop
        async for message in ws:
            if isinstance(message, str):
                await handle_text_message(ws, state, message)
            elif isinstance(message, bytes):
                await handle_binary_message(ws, state, message)
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Device {device_id} disconnected")
    except Exception as e:
        logger.error(f"Error handling device {device_id}: {e}", exc_info=True)
    finally:
        logger.info(f"Connection closed for device {device_id}")

async def start_websocket_server():
    """Start the WebSocket server on configured port"""
    logger.info(f"Starting WebSocket server on {settings.ws_host}:{settings.ws_port}")

    # websockets library automatically handles ping/pong with default 20s interval
    async with websockets.serve(
        handle_client,
        settings.ws_host,
        settings.ws_port,
        ping_interval=20,  # Send ping every 20 seconds
        ping_timeout=60,   # Wait up to 60 seconds for pong
    ):
        logger.info(f"WebSocket server listening on ws://{settings.ws_host}:{settings.ws_port}/ws")
        await asyncio.Future()  # Run forever
