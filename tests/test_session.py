"""Tests for app/session.py — UserConfig and Session state."""
import time
from app.session import UserConfig, Session


class TestUserConfig:
    def test_defaults(self):
        cfg = UserConfig()
        assert cfg.user_id == 0
        assert cfg.openai_api_key == ""
        assert cfg.tts_provider == ""

    def test_get_with_value(self):
        cfg = UserConfig(openai_api_key="sk-test")
        assert cfg.get("openai_api_key", "fallback") == "sk-test"

    def test_get_empty_falls_back(self):
        cfg = UserConfig(openai_api_key="")
        assert cfg.get("openai_api_key", "fallback") == "fallback"

    def test_get_nonexistent_field(self):
        cfg = UserConfig()
        assert cfg.get("nonexistent_field", "default") == "default"

    def test_is_pro_mode_true(self):
        cfg = UserConfig(openai_api_key="sk-test", openai_base_url="https://custom.api")
        assert cfg.is_pro_mode is True

    def test_is_pro_mode_false_no_key(self):
        cfg = UserConfig(openai_base_url="https://custom.api")
        assert cfg.is_pro_mode is False

    def test_is_pro_mode_false_no_url(self):
        cfg = UserConfig(openai_api_key="sk-test")
        assert cfg.is_pro_mode is False

    def test_is_pro_mode_false_both_empty(self):
        cfg = UserConfig()
        assert cfg.is_pro_mode is False


class TestSession:
    def test_init_state(self):
        s = Session("dev-001")
        assert s.device_id == "dev-001"
        assert len(s.session_id) == 8
        assert s.opus_packets == []
        assert s.listening is False
        assert s.tts_abort is False
        assert s.music_playing is False
        assert s.meeting_active is False

    def test_touch_updates_time(self):
        s = Session("dev-001")
        old_time = s.last_activity_time
        time.sleep(0.01)
        s.touch()
        assert s.last_activity_time > old_time

    def test_idle_seconds(self):
        s = Session("dev-001")
        time.sleep(0.05)
        idle = s.idle_seconds()
        assert idle >= 0.04

    def test_default_config(self):
        s = Session("dev-001")
        assert isinstance(s.config, UserConfig)
        assert s.config.user_id == 0
