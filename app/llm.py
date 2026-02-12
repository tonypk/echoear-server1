"""Two-stage LLM orchestrator: OpenAI intent planning + OpenClaw execution"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from openai import AsyncOpenAI
from .config import settings
from .session import Session
from .openclaw import execute_task, is_configured as openclaw_configured

logger = logging.getLogger(__name__)

# Per-session conversation history
_conversations: Dict[str, List[dict]] = {}

INTENT_PROMPT = """You are HiTony, a smart voice assistant. Analyze the user's request and respond in JSON.
Today's date/time: {current_datetime}

Modes:
1. CHAT — questions, conversations, information you can answer directly
2. EXECUTE — tasks needing real-world action (send messages, browse web, control devices, etc.)
3. MUSIC — user wants to play/listen to music, songs, or audio content
4. MUSIC_STOP — user wants to stop currently playing music
5. MUSIC_PAUSE — user wants to pause currently playing music
6. REMIND — user wants to set a reminder for a specific date/time

Response format:
- Chat: {"action": "chat", "response": "your answer"}
- Execute: {"action": "execute", "task": "specific task description for the execution agent", "reply_hint": "brief status phrase"}
- Music: {"action": "music", "query": "YouTube search query", "reply_hint": "正在播放..."}
- Music stop: {"action": "music_stop", "response": "已停止播放"}
- Music pause: {"action": "music_pause", "response": "已暂停"}
- Remind: {"action": "remind", "datetime": "YYYY-MM-DDTHH:MM:SS", "message": "reminder text", "response": "confirmation message"}

Music rules:
- Any request to play, listen to, or put on music/songs MUST use action "music"
- Common Chinese triggers: 播放/放/来一首/我想听/放首歌/听歌/放个歌/放音乐
- Common English triggers: play/put on/listen to
- The "query" field should be a good YouTube search query (include artist/song/genre keywords)

Reminder rules:
- Parse the date/time relative to today. If no time specified, default to 09:00.
- "datetime" must be ISO format: "2026-02-15T09:00:00"

Examples:
- "播放音乐" → {"action": "music", "query": "热门中文歌曲", "reply_hint": "正在播放音乐"}
- "放首歌" → {"action": "music", "query": "热门歌曲", "reply_hint": "正在为你播放歌曲"}
- "播放一首轻音乐" → {"action": "music", "query": "轻音乐 放松 纯音乐", "reply_hint": "正在播放轻音乐"}
- "来一首周杰伦的歌" → {"action": "music", "query": "周杰伦 热门歌曲", "reply_hint": "正在播放周杰伦的歌"}
- "我想听歌" → {"action": "music", "query": "热门中文歌曲 2024", "reply_hint": "正在为你播放音乐"}
- "Play Bohemian Rhapsody" → {"action": "music", "query": "Bohemian Rhapsody Queen official", "reply_hint": "Playing Bohemian Rhapsody"}
- "Play some jazz" → {"action": "music", "query": "jazz music relaxing", "reply_hint": "Playing some jazz"}
- "停止播放" → {"action": "music_stop", "response": "已停止播放"}
- "停/暂停/别放了" → {"action": "music_pause", "response": "已暂停"}
- "Send John a WhatsApp message saying I'll be late" → {"action": "execute", "task": "Send a WhatsApp message to contact 'John' with text: 'I'll be late'", "reply_hint": "Sending message to John"}
- "提醒我2月15号有面试" → {"action": "remind", "datetime": "2026-02-15T09:00:00", "message": "你有面试", "response": "好的，已设置2月15号早上9点提醒你有面试。"}
- "Remind me to call mom tomorrow at 3pm" → {"action": "remind", "datetime": "2026-02-12T15:00:00", "message": "Call mom", "response": "Got it, I'll remind you tomorrow at 3 PM to call mom."}
- "5分钟后提醒我吃药" → {"action": "remind", "datetime": "2026-02-11T14:35:00", "message": "吃药", "response": "好的，5分钟后提醒你吃药。"}
- "今天天气怎么样" → {"action": "chat", "response": "抱歉，我目前没有实时天气数据，你可以查看天气应用。"}
- "Hi, how are you?" → {"action": "chat", "response": "Hi! I'm doing great, how can I help you today?"}

IMPORTANT: Always respond with valid JSON only. No markdown, no code blocks. Respond in the same language as the user."""

# Fallback prompt when OpenClaw is not configured (simple chat mode)
CHAT_PROMPT = "You are HiTony, a helpful voice assistant. Keep responses concise and conversational."


def reset_conversation(session_id: str):
    """Clear conversation history for a session"""
    if session_id in _conversations:
        del _conversations[session_id]
        logger.info(f"[{session_id}] Conversation history cleared")


async def plan_intent(text: str, session_id: str, session: Optional[Session] = None) -> dict:
    """Stage 1: Use OpenAI to analyze user intent and return structured action"""
    if session and session.config.openai_api_key:
        client = AsyncOpenAI(
            api_key=session.config.openai_api_key,
            base_url=session.config.get("openai_base_url", settings.openai_base_url),
        )
    else:
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

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")
    system_prompt = INTENT_PROMPT.replace("{current_datetime}", now_str)
    messages = [{"role": "system", "content": system_prompt}] + history

    chat_model = (session.config.get("openai_chat_model", settings.intent_model)
                  if session else settings.intent_model)

    response = await client.chat.completions.create(
        model=chat_model,
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


async def call_llm_chat(text: str, session_id: str, session: Optional[Session] = None) -> str:
    """Fallback: simple chat mode when OpenClaw is not configured"""
    if session and session.config.openai_api_key:
        client = AsyncOpenAI(
            api_key=session.config.openai_api_key,
            base_url=session.config.get("openai_base_url", settings.openai_base_url),
        )
    else:
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

    chat_model = (session.config.get("openai_chat_model", settings.intent_model)
                  if session else settings.intent_model)

    response = await client.chat.completions.create(
        model=chat_model,
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
