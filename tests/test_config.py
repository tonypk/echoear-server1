"""Tests for app/config.py — settings and sanitization."""
from app.config import _sanitize_ascii, settings


class TestSanitizeAscii:
    def test_pure_ascii(self):
        assert _sanitize_ascii("hello") == "hello"

    def test_unicode_stripped(self):
        assert _sanitize_ascii("sk-\u200btest") == "sk-test"

    def test_chinese_stripped(self):
        assert _sanitize_ascii("sk-你好test") == "sk-test"

    def test_whitespace_stripped(self):
        assert _sanitize_ascii("  hello  ") == "hello"

    def test_empty(self):
        assert _sanitize_ascii("") == ""

    def test_all_unicode(self):
        assert _sanitize_ascii("你好世界") == ""

    def test_mixed(self):
        assert _sanitize_ascii("api-key-123\xc0") == "api-key-123"


class TestSettings:
    def test_defaults_exist(self):
        assert settings.ws_host is not None
        assert settings.ws_port > 0
        assert settings.pcm_sample_rate == 16000
        assert settings.pcm_channels == 1

    def test_model_defaults(self):
        assert settings.openai_asr_model == "whisper-1"
        assert settings.openai_tts_model == "tts-1"
        assert settings.openai_tts_voice == "alloy"

    def test_frame_duration(self):
        assert settings.frame_duration_ms == 60

    def test_music_max_duration(self):
        assert settings.music_max_duration_s == 600
