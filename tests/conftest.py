"""Shared test fixtures for HiTony server tests."""
import asyncio
import sys
from unittest.mock import MagicMock

import pytest

# Mock opuslib before any app module imports it
_mock_opuslib = MagicMock()
_mock_encoder = MagicMock()
_mock_encoder.encode.return_value = b"\x00" * 20
_mock_opuslib.Encoder.return_value = _mock_encoder
_mock_opuslib.APPLICATION_VOIP = 2048
sys.modules["opuslib"] = _mock_opuslib


@pytest.fixture
def mock_session():
    """Create a mock Session for tool tests (avoids asyncio.Event in dataclass)."""
    from app.session import UserConfig

    session = MagicMock()
    session.device_id = "test-device-001"
    session.session_id = "test-sess"
    session.opus_packets = []
    session.listening = False
    session.tts_abort = False
    session.processing = False
    session.music_playing = False
    session.music_paused = False
    session.music_abort = False
    session.music_title = ""
    session.meeting_active = False
    session._meeting_audio_buffer = bytearray()
    session.config = UserConfig(user_id=1)
    session.volume = 60
    return session


@pytest.fixture
def playing_session(mock_session):
    """Session with music currently playing."""
    mock_session.music_playing = True
    mock_session.music_paused = False
    mock_session._music_pause_event = asyncio.Event()
    mock_session._music_pause_event.set()
    return mock_session


@pytest.fixture
def paused_session(mock_session):
    """Session with music paused."""
    mock_session.music_playing = True
    mock_session.music_paused = True
    mock_session._music_pause_event = asyncio.Event()
    # Event is cleared (paused)
    return mock_session
