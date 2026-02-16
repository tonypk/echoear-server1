"""Volume control tool."""
from ..registry import tool, ToolResult


@tool(
    name="volume.set",
    description="Set device volume (0-100)",
    parameters={
        "level": {
            "type": "integer",
            "description": "Volume level (0=mute, 100=max)",
            "minimum": 0,
            "maximum": 100,
        }
    },
    required=["level"]
)
async def volume_set(level: int, session=None, **kwargs) -> ToolResult:
    """Set device volume to specified level."""
    if not session:
        return ToolResult(
            success=False,
            message="No active session"
        )

    # Clamp to valid range
    level = max(0, min(100, level))

    # Send volume command via WebSocket
    import json
    from ..pipeline import ws_send_safe

    ws, _ = session
    msg = json.dumps({"type": "volume", "level": level})
    await ws_send_safe(ws, msg)

    if level == 0:
        return ToolResult(success=True, message="已静音")
    elif level <= 30:
        return ToolResult(success=True, message=f"音量设为{level}%，较小")
    elif level <= 70:
        return ToolResult(success=True, message=f"音量设为{level}%")
    else:
        return ToolResult(success=True, message=f"音量设为{level}%，较大")


@tool(
    name="volume.up",
    description="Increase volume by 10%",
    parameters={}
)
async def volume_up(session=None, **kwargs) -> ToolResult:
    """Increase volume by 10%."""
    # Get current volume from session state (if tracked)
    # For now, just send a relative command
    return ToolResult(
        success=True,
        message="音量已增大",
        data={"action": "volume_up"}
    )


@tool(
    name="volume.down",
    description="Decrease volume by 10%",
    parameters={}
)
async def volume_down(session=None, **kwargs) -> ToolResult:
    """Decrease volume by 10%."""
    return ToolResult(
        success=True,
        message="音量已减小",
        data={"action": "volume_down"}
    )
