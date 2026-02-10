"""OpenAI Chat LLM integration"""
import logging
from typing import Dict, List
from openai import AsyncOpenAI
from .config import settings

logger = logging.getLogger(__name__)

# Per-session conversation history
_conversations: Dict[str, List[dict]] = {}

SYSTEM_PROMPT = "You are EchoEar, a helpful voice assistant. Keep responses concise and conversational."


def reset_conversation(session_id: str):
    """Clear conversation history for a session"""
    if session_id in _conversations:
        del _conversations[session_id]
        logger.info(f"[{session_id}] Conversation history cleared")


async def call_llm(text: str, session_id: str = "default") -> str:
    """Call OpenAI Chat API with conversation history"""
    if session_id not in _conversations:
        _conversations[session_id] = []

    history = _conversations[session_id]
    history.append({"role": "user", "content": text})

    # Keep last 20 messages to avoid token overflow
    if len(history) > 20:
        history[:] = history[-20:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )

    response = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=messages,
    )

    reply = response.choices[0].message.content.strip()
    history.append({"role": "assistant", "content": reply})

    return reply
