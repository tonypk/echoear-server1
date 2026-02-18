"""Tests for app/tools/registry.py — tool registration and lookup."""
from app.tools.registry import (
    register_tool,
    get_tool,
    all_tools,
    tool_descriptions_for_llm,
    ToolParam,
    ToolResult,
    ToolDef,
)


class TestToolResult:
    def test_tts_result(self):
        r = ToolResult(type="tts", text="hello")
        assert r.type == "tts"
        assert r.text == "hello"
        assert r.data == {}

    def test_error_result(self):
        r = ToolResult(type="error", text="failed")
        assert r.type == "error"

    def test_result_with_data(self):
        r = ToolResult(type="music", text="playing", data={"title": "Song"})
        assert r.data["title"] == "Song"


class TestToolParam:
    def test_defaults(self):
        p = ToolParam(name="query")
        assert p.type == "string"
        assert p.required is True
        assert p.default is None

    def test_optional_param(self):
        p = ToolParam(name="label", required=False, default="default")
        assert p.required is False
        assert p.default == "default"


class TestToolRegistry:
    def test_builtin_tools_registered(self):
        """All expected builtin tools should be registered after import."""
        tools = all_tools()
        expected = [
            "youtube.play", "player.pause", "player.resume", "player.stop",
            "weather.query", "timer.set", "timer.cancel",
            "web.search", "conversation.reset", "note.save",
            "alarm.set", "alarm.list", "alarm.cancel",
            "briefing.daily", "meeting.start", "meeting.end", "meeting.transcribe",
            "reminder.set", "reminder.list", "reminder.cancel",
            "volume.set", "volume.up", "volume.down",
        ]
        for name in expected:
            assert name in tools, f"Tool '{name}' not registered"

    def test_get_tool_exists(self):
        tool = get_tool("player.pause")
        assert tool is not None
        assert isinstance(tool, ToolDef)
        assert tool.name == "player.pause"

    def test_get_tool_not_exists(self):
        assert get_tool("nonexistent.tool") is None

    def test_tool_has_handler(self):
        tool = get_tool("player.pause")
        assert callable(tool.handler)

    def test_tool_descriptions_for_llm(self):
        desc = tool_descriptions_for_llm()
        assert isinstance(desc, str)
        assert "youtube.play" in desc
        assert "player.pause" in desc
        assert "weather.query" in desc

    def test_tool_descriptions_params(self):
        desc = tool_descriptions_for_llm()
        # youtube.play has a "query" param
        assert "query" in desc
