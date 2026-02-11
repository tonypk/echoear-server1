"""Real-time audio rate controller (inspired by xiaozhi AudioRateController).

Sends TTS Opus packets at playback rate (~60ms per packet) to prevent
TCP congestion window overflow through phone hotspot connections.
"""
import asyncio
import logging
import time
from collections import deque
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class AudioRateController:
    """Pace TTS packet delivery to match real-time playback rate.

    Instead of bursting all packets at once (which overwhelms TCP cwnd
    through phone hotspot), sends one packet every frame_duration_ms.
    At 60ms/packet with ~180B Opus frames, data rate is only ~3KB/s.
    """

    def __init__(self, frame_duration_ms: int = 60):
        self.frame_duration_ms = frame_duration_ms
        self.queue: deque[bytes] = deque()
        self.start_time: float = 0.0

    def add_audio(self, opus_packet: bytes):
        """Queue an Opus packet for rate-controlled sending."""
        self.queue.append(opus_packet)

    def add_all(self, packets: list[bytes]):
        """Queue multiple Opus packets."""
        self.queue.extend(packets)

    async def drain(
        self,
        send_callback: Callable[[bytes], Awaitable[bool]],
        abort_check: Callable[[], bool],
    ) -> int:
        """Send all queued packets at real-time playback rate.

        Args:
            send_callback: async (opus_bytes) -> bool. Returns True on success.
            abort_check: () -> bool. Returns True if sending should stop.

        Returns:
            Number of packets successfully sent.
        """
        total = len(self.queue)
        if total == 0:
            return 0

        self.start_time = time.monotonic()
        sent = 0
        consecutive_errors = 0

        while self.queue:
            if abort_check():
                logger.info(f"Rate ctrl: aborted at {sent}/{total}")
                break

            # Wait until it's time to send the next packet
            target_time = self.start_time + sent * (self.frame_duration_ms / 1000.0)
            now = time.monotonic()
            if now < target_time:
                await asyncio.sleep(target_time - now)

            packet = self.queue.popleft()
            ok = await send_callback(packet)

            if ok:
                sent += 1
                consecutive_errors = 0
            else:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    logger.error(f"Rate ctrl: 3 consecutive send errors at {sent}/{total}, stopping")
                    break

        elapsed = time.monotonic() - self.start_time
        logger.info(f"Rate ctrl: sent {sent}/{total} packets in {elapsed:.1f}s "
                    f"(expected {total * self.frame_duration_ms / 1000:.1f}s)")
        return sent
