"""Two-stage LLM orchestrator: OpenAI intent planning + OpenClaw execution"""
import json
import logging
from typing import Dict, List
from openai import AsyncOpenAI
from .config import settings
from .openclaw import execute_task, is_configured as openclaw_configured

logger = logging.getLogger(__name__)

# Per-session conversation history
_conversations: Dict[str, List[dict]] = {}

INTENT_PROMPT = """You are EchoEar, a smart voice assistant. Analyze the user's request and respond in JSON.

Modes:
1. CHAT — questions, conversations, information you can answer directly
2. EXECUTE — tasks needing real-world action (send messages, browse web, control devices, etc.)
3. MUSIC — user wants to play music (from YouTube or a URL)
4. MUSIC_STOP — user wants to stop currently playing music
5. MUSIC_PAUSE — user wants to pause currently playing music

Response format:
- Chat: {"action": "chat", "response": "your answer"}
- Execute: {"action": "execute", "task": "specific task description for the execution agent", "reply_hint": "brief status phrase"}
- Music: {"action": "music", "query": "search query or URL", "reply_hint": "Playing [song description]"}
- Music stop: {"action": "music_stop", "response": "Music stopped."}
- Music pause: {"action": "music_pause", "response": "Music paused."}

Examples:
- "What's the weather?" → {"action": "chat", "response": "I don't have real-time weather data, but you can check your weather app."}
- "Send John a WhatsApp message saying I'll be late" → {"action": "execute", "task": "Send a WhatsApp message to contact 'John' with text: 'I'll be late'", "reply_hint": "Sending message to John"}
- "播放一首轻音乐" → {"action": "music", "query": "relaxing light music", "reply_hint": "Playing some relaxing music"}
- "Play Bohemian Rhapsody" → {"action": "music", "query": "Bohemian Rhapsody Queen", "reply_hint": "Playing Bohemian Rhapsody"}
- "停止播放" → {"action": "music_stop", "response": "Music stopped."}
- "暂停" → {"action": "music_pause", "response": "Music paused."}
- "Hi, how are you?" → {"action": "chat", "response": "Hi! I'm doing great, how can I help you today?"}

IMPORTANT: Always respond with valid JSON only. No markdown, no code blocks."""

# Fallback prompt when OpenClaw is not configured (simple chat mode)
CHAT_PROMPT = "You are EchoEar, a helpful voice assistant. Keep responses concise and conversational."


def reset_conversation(session_id: str):
    """Clear conversation history for a session"""
    if session_id in _conversations:
        del _conversations[session_id]
        logger.info(f"[{session_id}] Conversation history cleared")


async def plan_intent(text: str, session_id: str) -> dict:
    """Stage 1: Use OpenAI to analyze user intent and return structured action"""
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )

    if session_id not in _conversations:
        _conversations[session_id] = []

    history = _conversations[session_id]
    history.append({"role": "user", "content": text})

    if len(history) > 20:
        history[:] = history[-20:]

    messages = [{"role": "system", "content": INTENT_PROMPT}] + history

    response = await client.chat.completions.create(
        model=settings.intent_model,
        messages=messages,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    logger.info(f"[{session_id}] Intent raw: {raw[:200]}")

    try:
        intent = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"[{session_id}] Intent JSON parse failed, treating as chat")
        intent = {"action": "chat", "response": raw}

    return intent


async def call_llm_chat(text: str, session_id: str) -> str:
    """Fallback: simple chat mode when OpenClaw is not configured"""
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )

    if session_id not in _conversations:
        _conversations[session_id] = []

    history = _conversations[session_id]
    history.append({"role": "user", "content": text})

    if len(history) > 20:
        history[:] = history[-20:]

    messages = [{"role": "system", "content": CHAT_PROMPT}] + history

    response = await client.chat.completions.create(
        model=settings.intent_model,
        messages=messages,
    )

    reply = response.choices[0].message.content.strip()
    history.append({"role": "assistant", "content": reply})
    return reply


async def call_llm(text: str, session_id: str = "default") -> str:
    """Main entry: two-stage LLM call (intent planning → execution/reply)"""

    # If OpenClaw not configured, use simple chat mode (backward compatible)
    if not openclaw_configured():
        logger.info(f"[{session_id}] OpenClaw not configured, using chat mode")
        return await call_llm_chat(text, session_id)

    # Stage 1: Intent Planning (OpenAI GPT)
    intent = await plan_intent(text, session_id)
    action = intent.get("action", "chat")

    if action == "execute":
        task = intent.get("task", text)
        hint = intent.get("reply_hint", "Processing...")
        logger.info(f"[{session_id}] Intent: EXECUTE — task={task[:80]}, hint={hint}")

        # Stage 2: Execute via OpenClaw
        try:
            result = await execute_task(task)
            reply = result
        except Exception as e:
            logger.error(f"[{session_id}] OpenClaw execution failed: {e}", exc_info=True)
            reply = "Sorry, I couldn't complete that task right now. Please try again later."
    else:
        reply = intent.get("response", "I'm not sure how to help with that.")
        logger.info(f"[{session_id}] Intent: CHAT — {reply[:80]}")

    # Update conversation history
    history = _conversations.get(session_id, [])
    history.append({"role": "assistant", "content": reply})

    return reply
