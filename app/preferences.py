"""Device-level user preferences — simple key-value store backed by SQLite.

Preferences are loaded into memory on WS connect and saved on WS disconnect
(same lifecycle as conversation history). Supports LLM system prompt injection
so the assistant knows about user preferences.

NOTE: set_preference() is wired but not yet called from any tool or API endpoint.
A future "preference.set" tool or LLM extraction logic will populate preferences.
The infrastructure (DB column, load/save lifecycle, prompt injection) is ready.
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# In-memory store: device_id → {key: value}
# Thread-safety: only accessed from the asyncio event loop thread (same as _conversations in llm.py)
_preferences: Dict[str, Dict[str, str]] = {}

MAX_PREF_VALUE_LEN = 200

# Known preference keys and their descriptions (for LLM prompt)
KNOWN_KEYS = {
    "preferred_city": "用户所在城市",
    "music_preference": "音乐偏好",
    "wake_greeting": "唤醒问候语",
    "nickname": "用户昵称",
    "language": "首选语言",
}


def load_preferences(device_id: str, prefs: Dict[str, str]):
    """Load preferences from DB (called on WS connect)."""
    _preferences[device_id] = dict(prefs)
    logger.info(f"[{device_id}] Loaded {len(prefs)} preferences")


def get_preferences(device_id: str) -> Dict[str, str]:
    """Get all preferences for saving to DB. Returns a copy."""
    return dict(_preferences.get(device_id, {}))


def get_preference(device_id: str, key: str) -> Optional[str]:
    """Get a single preference value."""
    return _preferences.get(device_id, {}).get(key)


def set_preference(device_id: str, key: str, value: str):
    """Set a preference. Creates device entry if needed.

    Values are sanitized: newlines stripped, length capped.
    """
    value = value.replace("\n", " ").replace("\r", " ").strip()[:MAX_PREF_VALUE_LEN]
    if device_id not in _preferences:
        _preferences[device_id] = {}
    _preferences[device_id][key] = value
    logger.info(f"[{device_id}] Preference set: {key}={value}")


def clear_preferences(device_id: str):
    """Clear in-memory preferences (called on WS disconnect)."""
    _preferences.pop(device_id, None)


def preferences_for_prompt(device_id: str) -> str:
    """Format preferences as text for injection into LLM system prompt.

    Returns empty string if no preferences are set.
    """
    prefs = _preferences.get(device_id, {})
    if not prefs:
        return ""

    lines = []
    for key, value in prefs.items():
        desc = KNOWN_KEYS.get(key, key)
        lines.append(f"- {desc}: {value}")

    return "用户偏好设置：\n" + "\n".join(lines)
