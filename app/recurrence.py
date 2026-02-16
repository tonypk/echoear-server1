"""Recurrence rule parser and calculator for recurring reminders."""
from datetime import datetime, timedelta
import re
import logging

logger = logging.getLogger(__name__)


def calculate_next_occurrence(base_time: datetime, rule: str) -> datetime | None:
    """
    Calculate the next occurrence time based on recurrence rule.

    Supported rules:
    - "daily" / "每天" → next day, same time
    - "weekly" / "每周" → next week, same day/time
    - "monthly" / "每月" → next month, same day/time
    - "HH:MM" → daily at specific time (e.g., "08:00")
    - "weekdays" / "工作日" → next weekday (Mon-Fri)
    - Custom cron-like (future): "0 8 * * 1-5" (Mon-Fri 8am)

    Returns the next occurrence datetime, or None if rule is invalid.
    """
    rule = rule.strip().lower()

    # Daily recurrence
    if rule in ("daily", "每天"):
        return base_time + timedelta(days=1)

    # Weekly recurrence
    if rule in ("weekly", "每周"):
        return base_time + timedelta(weeks=1)

    # Monthly recurrence (approximate: +30 days, adjust if needed)
    if rule in ("monthly", "每月"):
        return base_time + timedelta(days=30)

    # Weekdays (Mon-Fri)
    if rule in ("weekdays", "工作日"):
        next_time = base_time + timedelta(days=1)
        # Skip weekends (5=Sat, 6=Sun)
        while next_time.weekday() >= 5:
            next_time += timedelta(days=1)
        return next_time

    # Daily at specific time: "08:00" or "HH:MM"
    time_match = re.match(r"^(\d{1,2}):(\d{2})$", rule)
    if time_match:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            next_time = base_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # If the time today has passed, schedule for tomorrow
            if next_time <= base_time:
                next_time += timedelta(days=1)
            return next_time

    logger.warning(f"Unsupported recurrence rule: {rule}")
    return None


def parse_recurrence_from_text(text: str) -> str | None:
    """
    Extract recurrence rule from natural language text.

    Examples:
    - "每天8点提醒我吃药" → "08:00"
    - "每周一早上9点开会" → "weekly" (simplified for now)
    - "每天提醒我喝水" → "daily"
    - "工作日早上提醒我" → "weekdays"

    Returns the recurrence rule string, or None if not recurring.
    """
    text = text.lower()

    # Daily patterns
    if re.search(r"每天|每日|daily", text):
        # Try to extract specific time: "每天8点" or "每天早上8点"
        time_match = re.search(r"(\d{1,2})\s*[点時时](?:\d{1,2}\s*分)?", text)
        if time_match:
            hour = int(time_match.group(1))
            return f"{hour:02d}:00"
        return "daily"

    # Weekly patterns
    if re.search(r"每周|每週|每星期|weekly", text):
        return "weekly"

    # Monthly patterns
    if re.search(r"每月|每个月|monthly", text):
        return "monthly"

    # Weekdays pattern
    if re.search(r"工作日|weekdays?", text):
        return "weekdays"

    return None
