"""YouTube music tool — wraps existing music.search_and_stream()."""
from ..registry import register_tool, ToolResult, ToolParam


@register_tool(
    "youtube.play",
    description="Search YouTube and play a song or video",
    params=[ToolParam("query", description="search query or URL")],
    category="music",
)
async def youtube_play(query: str, session=None, **kwargs) -> ToolResult:
    from ...music import search_and_stream

    youtube_api_key = ""
    if session and hasattr(session, "config"):
        youtube_api_key = session.config.youtube_api_key or ""

    try:
        title, generator = await search_and_stream(query, youtube_api_key=youtube_api_key)
        return ToolResult(
            type="music",
            text=f"正在播放: {title}",
            data={"title": title, "generator": generator},
        )
    except Exception as e:
        return ToolResult(type="error", text=f"找不到音乐: {e}")
