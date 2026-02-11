"""OpenClaw execution client — sends tasks to OpenClaw agent via Responses API"""
import logging
from typing import Optional
from openai import AsyncOpenAI
from .config import settings
from .session import Session

logger = logging.getLogger(__name__)


def is_configured(session: Optional[Session] = None) -> bool:
    """Check if OpenClaw is configured (per-user or global)."""
    if session and session.config.openclaw_url and session.config.openclaw_token:
        return True
    return bool(settings.openclaw_base_url and settings.openclaw_token)


async def execute_task(task: str, session: Optional[Session] = None) -> str:
    """Execute a task via OpenClaw Responses API.

    OpenClaw Gateway runs the full agent loop internally (tool calls, etc.)
    and returns the final result text.
    """
    # Determine per-user or global OpenClaw config
    if session and session.config.openclaw_url and session.config.openclaw_token:
        claw_url = session.config.openclaw_url
        claw_token = session.config.openclaw_token
        claw_model = session.config.get("openclaw_model", settings.openclaw_model)
    elif settings.openclaw_base_url and settings.openclaw_token:
        claw_url = settings.openclaw_base_url
        claw_token = settings.openclaw_token
        claw_model = settings.openclaw_model
    else:
        raise RuntimeError("OpenClaw not configured (OPENCLAW_URL / OPENCLAW_TOKEN missing)")

    logger.info(f"OpenClaw: executing task: {task[:100]}...")

    client = AsyncOpenAI(
        api_key=claw_token,
        base_url=claw_url,
        timeout=settings.openclaw_timeout,
    )

    response = await client.responses.create(
        model=claw_model,
        input=task,
        instructions="Execute this task and report the result concisely. Focus on what was accomplished.",
    )

    result = response.output_text.strip()
    logger.info(f"OpenClaw: result: {result[:100]}...")
    return result
