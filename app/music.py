"""Music streaming: yt-dlp fetch -> ffmpeg -> Opus encode -> async generator."""
import asyncio
import json
import logging
from typing import AsyncGenerator, Tuple

import opuslib

logger = logging.getLogger(__name__)

FRAME_SAMPLES = 960       # 60ms @ 16kHz
FRAME_BYTES = FRAME_SAMPLES * 2  # 960 samples * 2 bytes (int16)
READ_CHUNK = FRAME_BYTES * 4     # Read ~240ms at a time


async def search_and_stream(query: str) -> Tuple[str, AsyncGenerator[bytes, None]]:
    """Search YouTube and stream audio as Opus packets.

    Returns (title, async_generator_of_opus_packets).
    The generator yields one Opus packet (~60ms) at a time.
    """
    # Step 1: Get metadata (title) via yt-dlp --dump-json
    search_query = query if query.startswith("http") else f"ytsearch:{query}"

    logger.info(f"Music: fetching metadata for '{search_query}'")
    meta_proc = await asyncio.create_subprocess_exec(
        "yt-dlp", "--dump-json", "--no-download", search_query,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    meta_stdout, meta_stderr = await meta_proc.communicate()

    if meta_proc.returncode != 0:
        err = meta_stderr.decode(errors="replace")[:200]
        raise RuntimeError(f"yt-dlp metadata failed: {err}")

    info = json.loads(meta_stdout)
    title = info.get("title", "Unknown")
    url = info.get("webpage_url", search_query)
    duration = info.get("duration", 0)
    logger.info(f"Music: '{title}' ({duration}s) url={url}")

    # Step 2: Stream audio via yt-dlp | ffmpeg pipe (16kHz mono PCM16)
    cmd = (
        f'yt-dlp -f bestaudio --no-warnings -o - "{url}" | '
        f'ffmpeg -hide_banner -loglevel error -i pipe:0 '
        f'-f s16le -ar 16000 -ac 1 pipe:1'
    )
    audio_proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def opus_generator() -> AsyncGenerator[bytes, None]:
        encoder = opuslib.Encoder(16000, 1, opuslib.APPLICATION_AUDIO)
        encoder.bitrate = 24000
        buffer = b""

        try:
            while True:
                chunk = await audio_proc.stdout.read(READ_CHUNK)
                if not chunk:
                    break
                buffer += chunk
                while len(buffer) >= FRAME_BYTES:
                    frame = buffer[:FRAME_BYTES]
                    buffer = buffer[FRAME_BYTES:]
                    yield encoder.encode(frame, FRAME_SAMPLES)

            # Encode remaining (pad with silence)
            if buffer:
                frame = buffer + b'\x00' * (FRAME_BYTES - len(buffer))
                yield encoder.encode(frame, FRAME_SAMPLES)
        finally:
            # Clean up subprocess
            try:
                audio_proc.terminate()
                await asyncio.wait_for(audio_proc.wait(), timeout=3.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    audio_proc.kill()
                except ProcessLookupError:
                    pass
            logger.info(f"Music: audio process terminated for '{title}'")

    return title, opus_generator()
