"""Background reminder scheduler — checks for due reminders and pushes TTS to devices."""
import asyncio
import json
import logging
import struct
from datetime import datetime

from sqlalchemy import select

from .database import async_session_factory
from .models import Reminder
from .tts import synthesize_tts
from .config import settings

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30  # seconds between DB checks


async def _push_tts_to_device(device_id: str, text: str) -> bool:
    """Push a TTS message to a connected device. Returns True on success."""
    from .ws_server import get_active_connection
    from .pipeline import ws_send_safe, _stream_batched

    conn = get_active_connection(device_id)
    if not conn:
        logger.info(f"Device {device_id} not connected, cannot push reminder")
        return False

    ws, session = conn

    # Don't interrupt if device is busy (recording, speaking, or playing music)
    if session.processing or session.listening or session.music_playing:
        logger.info(f"Device {device_id} busy, deferring reminder")
        return False

    try:
        opus_packets = await synthesize_tts(text, session=session)
        if not opus_packets:
            return False

        # Send TTS: tts_start → batched audio → tts_end
        ok = await ws_send_safe(
            ws, json.dumps({"type": "tts_start", "text": text}), session, "reminder_tts_start"
        )
        if not ok:
            return False

        await _stream_batched(ws, session, opus_packets)
        await ws_send_safe(ws, json.dumps({"type": "tts_end"}), session, "reminder_tts_end")

        logger.info(f"Reminder TTS pushed to {device_id}: {len(opus_packets)} packets")
        return True

    except Exception as e:
        logger.error(f"Failed to push reminder TTS to {device_id}: {e}")
        return False


async def _check_and_deliver():
    """Check DB for due reminders and deliver them."""
    now = datetime.now()

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(Reminder).where(
                    Reminder.remind_at <= now,
                    Reminder.delivered == 0,
                )
            )
            due_reminders = result.scalars().all()

            for reminder in due_reminders:
                logger.info(
                    f"Reminder #{reminder.id} due: '{reminder.message}' "
                    f"for device {reminder.device_id}"
                )

                success = await _push_tts_to_device(
                    reminder.device_id, reminder.message
                )

                if success:
                    reminder.delivered = 1
                    logger.info(f"Reminder #{reminder.id} delivered via TTS")

                    # If this is a recurring reminder, create the next occurrence
                    if reminder.is_recurring and reminder.recurrence_rule:
                        await _create_next_recurrence(db, reminder)
                else:
                    # Check if reminder is very overdue (>1 hour) — mark as failed
                    overdue_seconds = (now - reminder.remind_at).total_seconds()
                    if overdue_seconds > 3600:
                        reminder.delivered = 2  # failed
                        logger.warning(
                            f"Reminder #{reminder.id} expired after {overdue_seconds:.0f}s, "
                            f"marking as failed"
                        )
                    # else: keep as pending, will retry next cycle

            await db.commit()

    except Exception as e:
        logger.error(f"Reminder scheduler error: {e}")


async def _create_next_recurrence(db, parent_reminder: Reminder):
    """Create the next occurrence of a recurring reminder."""
    from .recurrence import calculate_next_occurrence

    next_time = calculate_next_occurrence(
        parent_reminder.remind_at,
        parent_reminder.recurrence_rule
    )

    if not next_time:
        logger.warning(
            f"Cannot calculate next occurrence for reminder #{parent_reminder.id}, "
            f"rule: {parent_reminder.recurrence_rule}"
        )
        return

    # Create a new reminder instance
    new_reminder = Reminder(
        user_id=parent_reminder.user_id,
        device_id=parent_reminder.device_id,
        remind_at=next_time,
        message=parent_reminder.message,
        delivered=0,
        is_recurring=parent_reminder.is_recurring,
        recurrence_rule=parent_reminder.recurrence_rule,
    )
    db.add(new_reminder)
    logger.info(
        f"Created recurring reminder: '{new_reminder.message}' "
        f"at {next_time.strftime('%Y-%m-%d %H:%M')}"
    )


async def start_reminder_scheduler():
    """Background loop: check for due reminders every CHECK_INTERVAL seconds."""
    logger.info(f"Reminder scheduler started (check every {CHECK_INTERVAL}s)")

    # Wait a bit for server to fully start
    await asyncio.sleep(5)

    while True:
        try:
            await _check_and_deliver()
        except Exception as e:
            logger.error(f"Reminder scheduler loop error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)
