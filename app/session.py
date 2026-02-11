"""Session state management for WebSocket connections."""
import asyncio
import time
import uuid
from typing import Optional, List


class Session:
    """Per-connection session state, extracted from ws_server.ConnState."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.session_id = str(uuid.uuid4())[:8]
        self.opus_packets: List[bytes] = []
        self.listening = False
        self.tts_abort = False
        self.processing = False
        self.listen_mode: Optional[str] = None
        self.protocol_version: int = 1
        self._process_task: Optional[asyncio.Task] = None

        # Activity tracking (xiaozhi pattern)
        now = time.monotonic()
        self.first_activity_time = now
        self.last_activity_time = now

    def touch(self):
        """Update last activity timestamp."""
        self.last_activity_time = time.monotonic()

    def idle_seconds(self) -> float:
        """Seconds since last activity."""
        return time.monotonic() - self.last_activity_time
