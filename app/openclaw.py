"""OpenClaw execution client — sends tasks to OpenClaw agent via Responses API"""
import logging
from openai import AsyncOpenAI
from .config import settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """Check if OpenClaw is configured"""
    return bool(settings.openclaw_base_url and settings.openclaw_token)


async def execute_task(task: str) -> str:
    """Execute a task via OpenClaw Responses API.

    OpenClaw Gateway runs the full agent loop internally (tool calls, etc.)
    and returns the final result text.
    """
    if not is_configured():
        raise RuntimeError("OpenClaw not configured (OPENCLAW_URL / OPENCLAW_TOKEN missing)")

    logger.info(f"OpenClaw: executing task: {task[:100]}...")

    client = AsyncOpenAI(
        api_key=settings.openclaw_token,
        base_url=settings.openclaw_base_url,
        timeout=settings.openclaw_timeout,
    )

    response = await client.responses.create(
        model=settings.openclaw_model,
        input=task,
        instructions="Execute this task and report the result concisely. Focus on what was accomplished.",
    )

    result = response.output_text.strip()
    logger.info(f"OpenClaw: result: {result[:100]}...")
    return result
