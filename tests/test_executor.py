"""Tests for app/tools/executor.py — tool dispatch and validation."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.executor import execute_tool, _execute_with_keepalive, SILENCE_BLOB
from app.tools.registry import ToolResult, ToolDef, ToolParam


class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self, mock_session):
        result = await execute_tool("nonexistent.tool", {}, mock_session)
        assert result.type == "error"
        assert "Unknown tool" in result.text

    @pytest.mark.asyncio
    async def test_missing_required_param(self, mock_session):
        result = await execute_tool("youtube.play", {}, mock_session)
        assert result.type == "ask_user"
        assert "missing_param" in result.data

    @pytest.mark.asyncio
    async def test_player_pause_no_music(self, mock_session):
        mock_session.music_playing = False
        result = await execute_tool("player.pause", {}, mock_session)
        assert result.type == "tts"
        assert "没有" in result.text

    @pytest.mark.asyncio
    async def test_player_pause_with_music(self, playing_session):
        result = await execute_tool("player.pause", {}, playing_session)
        assert result.type == "tts"
        assert "暂停" in result.text

    @pytest.mark.asyncio
    async def test_player_resume_paused(self, paused_session):
        result = await execute_tool("player.resume", {}, paused_session)
        assert result.type == "tts"
        assert "继续" in result.text

    @pytest.mark.asyncio
    async def test_player_stop(self, playing_session):
        result = await execute_tool("player.stop", {}, playing_session)
        assert result.type == "tts"
        assert "停止" in result.text
        assert playing_session.music_abort is True

    @pytest.mark.asyncio
    async def test_session_injected(self, mock_session):
        mock_session.music_playing = False
        result = await execute_tool("player.pause", {}, mock_session)
        assert result.type == "tts"

    @pytest.mark.asyncio
    async def test_conversation_reset(self, mock_session):
        with patch("app.llm.reset_conversation") as mock_reset, \
             patch("app.database.async_session_factory") as mock_db:
            mock_db_ctx = AsyncMock()
            mock_db.return_value = mock_db_ctx
            mock_db_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_db_ctx.__aexit__ = AsyncMock(return_value=None)

            result = await execute_tool("conversation.reset", {}, mock_session)
            assert result.type == "tts"
            assert "清空" in result.text

    @pytest.mark.asyncio
    async def test_tool_handler_exception(self, mock_session):
        """Handler exception should return error result."""
        async def failing_handler(**kwargs):
            raise RuntimeError("boom")

        with patch("app.tools.executor.get_tool") as mock_get:
            mock_get.return_value = ToolDef(
                name="test.fail", description="", params=[], handler=failing_handler
            )
            result = await execute_tool("test.fail", {}, mock_session)
            assert result.type == "error"
            assert "boom" in result.text


class TestSilenceBlob:
    def test_silence_blob_exists(self):
        assert isinstance(SILENCE_BLOB, bytes)
        assert len(SILENCE_BLOB) > 2

    def test_silence_blob_has_length_prefix(self):
        import struct
        length = struct.unpack('>H', SILENCE_BLOB[:2])[0]
        assert length == len(SILENCE_BLOB) - 2


class TestExecuteWithKeepalive:
    @pytest.mark.asyncio
    async def test_abort_cancels_task(self, mock_session):
        """Should cancel task when tts_abort is True."""
        mock_session.tts_abort = True

        async def slow_handler(**kwargs):
            import asyncio
            await asyncio.sleep(10)
            return ToolResult(type="tts", text="done")

        tool = ToolDef(
            name="test.slow", description="", params=[],
            handler=slow_handler, long_running=True,
        )
        ws = MagicMock()
        ws.closed = False
        ws_send_fn = AsyncMock()

        result = await _execute_with_keepalive(tool, {"session": mock_session}, mock_session, ws, ws_send_fn)
        assert result.type == "silent"
