"""Tests for app/asr.py — ASR, hallucination filter, PCM→WAV."""
import struct
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.asr import pcm_to_wav, _HALLUCINATIONS, _HALLUCINATION_SUBSTRINGS, transcribe_pcm


class TestPcmToWav:
    def test_wav_header(self):
        pcm = b"\x00" * 640  # 320 samples mono 16bit
        wav = pcm_to_wav(pcm)

        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert wav[12:16] == b"fmt "
        assert wav[36:40] == b"data"

    def test_wav_size(self):
        pcm = b"\x00" * 640
        wav = pcm_to_wav(pcm)
        # RIFF size = 36 + data_size
        riff_size = struct.unpack("<I", wav[4:8])[0]
        assert riff_size == 36 + 640

    def test_wav_data_section(self):
        pcm = b"\x01\x02" * 320
        wav = pcm_to_wav(pcm)
        data_size = struct.unpack("<I", wav[40:44])[0]
        assert data_size == 640
        # Data follows header
        assert wav[44:46] == b"\x01\x02"

    def test_wav_sample_rate(self):
        pcm = b"\x00" * 640
        wav = pcm_to_wav(pcm)
        # Sample rate at offset 24
        sample_rate = struct.unpack("<I", wav[24:28])[0]
        assert sample_rate == 16000

    def test_empty_pcm(self):
        wav = pcm_to_wav(b"")
        # Should still produce valid header
        assert wav[:4] == b"RIFF"
        data_size = struct.unpack("<I", wav[40:44])[0]
        assert data_size == 0


class TestHallucinationFilters:
    def test_known_hallucinations_exist(self):
        assert "thank you" in _HALLUCINATIONS
        assert "谢谢观看" in _HALLUCINATIONS
        assert "subscribe" in _HALLUCINATIONS

    def test_hallucination_substrings_exist(self):
        assert "点赞" in _HALLUCINATION_SUBSTRINGS
        assert "订阅" in _HALLUCINATION_SUBSTRINGS
        assert "thank you for watching" in _HALLUCINATION_SUBSTRINGS


class TestTranscribePcm:
    @pytest.mark.asyncio
    async def test_short_audio_filtered(self):
        """Audio < 0.5s should return empty string."""
        # 0.3s of audio = 16000 * 0.3 * 2 bytes = 9600 bytes
        short_pcm = b"\x00" * 9600
        result = await transcribe_pcm(short_pcm)
        assert result == ""

    @pytest.mark.asyncio
    async def test_very_short_audio(self):
        """Extremely short audio should return empty."""
        result = await transcribe_pcm(b"\x00" * 100)
        assert result == ""

    @pytest.mark.asyncio
    async def test_hallucination_exact_filtered(self):
        """Known hallucination phrases should be filtered."""
        # 1s of audio
        pcm = b"\x00" * 32000

        mock_transcript = MagicMock()
        mock_transcript.text = "Thank you for watching"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_transcript)

        with patch("app.asr._get_client", return_value=mock_client):
            result = await transcribe_pcm(pcm)
            assert result == ""

    @pytest.mark.asyncio
    async def test_hallucination_substring_filtered(self):
        """Substring hallucinations should be filtered."""
        pcm = b"\x00" * 32000

        mock_transcript = MagicMock()
        mock_transcript.text = "感谢大家点赞订阅"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_transcript)

        with patch("app.asr._get_client", return_value=mock_client):
            result = await transcribe_pcm(pcm)
            assert result == ""

    @pytest.mark.asyncio
    async def test_valid_transcription_passes(self):
        """Normal speech should pass through."""
        pcm = b"\x00" * 32000

        mock_transcript = MagicMock()
        mock_transcript.text = "播放周杰伦的歌"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_transcript)

        with patch("app.asr._get_client", return_value=mock_client):
            result = await transcribe_pcm(pcm)
            assert result == "播放周杰伦的歌"
