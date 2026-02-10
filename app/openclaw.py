import logging
from openai import AsyncOpenAI
from .config import settings

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
)

_conversation_history: list = []

SYSTEM_PROMPT = "你是EchoEar，一个友好的语音助手。请用与用户相同的语言简短回答问题。如果用户说中文就用中文回答，说英文就用英文回答。"


async def call_openclaw(text: str) -> str:
    """Chat with OpenAI GPT model"""
    _conversation_history.append({"role": "user", "content": text})

    # Keep last 10 messages to avoid token overflow
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _conversation_history[-10:]

    response = await _client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=messages,
        max_tokens=200,
    )

    reply = response.choices[0].message.content.strip()
    _conversation_history.append({"role": "assistant", "content": reply})

    logger.info(f"LLM: '{text}' -> '{reply}'")
    return reply
