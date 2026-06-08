"""
sync_service.py – Orchestrate: fetch API → save DB → sync GCal → notify Telegram.
"""
import logging
from datetime import datetime

import database as db
from api_client import fetch_all_schedules
from calendar_sync import sync_all_events
from config import GOOGLE_CALENDAR_ENABLED

logger = logging.getLogger(__name__)


async def run_sync(bot=None, notify_changes: bool = True) -> dict:
    """
    Chạy chu trình đồng bộ đầy đủ.
    Returns: dict với thống kê kết quả.
    """
    logger.info("Starting schedule sync at %s", datetime.now().isoformat())

    # 1. Fetch từ API
    events = await fetch_all_schedules()
    total = len(events)

    if total == 0:
        logger.warning("No events fetched from API.")
        db.log_sync("ALL", 0, 0, 0, "empty")
        return {"total": 0, "new": 0, "changed": 0, "status": "empty"}

    # 2. Upsert vào DB và phát hiện thay đổi
    new_events = []
    changed_events = []
    for event in events:
        is_new, is_changed = db.upsert_event(event)
        if is_new:
            new_events.append(event)
        elif is_changed:
            changed_events.append(event)

    logger.info("Sync result: total=%d, new=%d, changed=%d", total, len(new_events), len(changed_events))

    # 3. Đồng bộ Google Calendar
    gcal_success = 0
    if GOOGLE_CALENDAR_ENABLED and (new_events or changed_events):
        gcal_success, _ = sync_all_events(new_events + changed_events)

    # 4. Gửi thông báo Telegram về sự kiện mới/thay đổi
    if bot and notify_changes:
        await _notify_changes(bot, new_events, changed_events)

    # 5. Log sync
    db.log_sync("ALL", total, len(new_events), len(changed_events), "ok")

    return {
        "total": total,
        "new": len(new_events),
        "changed": len(changed_events),
        "gcal_synced": gcal_success,
        "status": "ok",
    }


async def run_reminder_check(bot) -> int:
    """Kiểm tra và gửi nhắc nhở cho sự kiện ngày mai. Trả về số nhắc đã gửi."""
    from notifier import get_events_needing_reminder, build_reminder_message

    events = get_events_needing_reminder()
    sent_count = 0

    for event in events:
        msg = build_reminder_message(event)
        success = await _broadcast(bot, msg)
        if success:
            db.mark_notification_sent(event["id"], "reminder")
            sent_count += 1

    if sent_count:
        logger.info("Sent %d reminder(s).", sent_count)
    return sent_count


async def _notify_changes(bot, new_events: list, changed_events: list) -> None:
    from notifier import build_new_event_message, build_changed_event_message

    for event in new_events:
        if not db.is_notification_sent(event["id"], "new"):
            msg = build_new_event_message(event)
            await _broadcast(bot, msg)
            db.mark_notification_sent(event["id"], "new")

    for event in changed_events:
        if not db.is_notification_sent(event["id"], "changed"):
            msg = build_changed_event_message(event)
            await _broadcast(bot, msg)
            db.mark_notification_sent(event["id"], "changed")


async def _broadcast(bot, message: str) -> bool:
    """Gửi tin nhắn đến tất cả user đã đăng ký."""
    users = db.get_subscribed_users()
    if not users:
        logger.warning("No subscribed users to notify.")
        return False

    success = False
    for user in users:
        try:
            await bot.send_message(
                chat_id=user["chat_id"],
                text=message,
                parse_mode="HTML",
            )
            success = True
        except Exception as e:
            logger.error("Failed to send message to %s: %s", user["chat_id"], e)
    return success
