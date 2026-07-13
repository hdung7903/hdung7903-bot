import logging
import asyncio
from datetime import datetime

import database as db
from api_client import fetch_all_schedules
from calendar_sync import sync_all_events
from config import GOOGLE_CALENDAR_ENABLED, MANUAL_SCHEDULE_CLASS_ID

logger = logging.getLogger(__name__)


async def run_sync(bot=None, notify_changes: bool = True) -> dict:
    """
    Chạy chu trình đồng bộ đầy đủ.
    Returns: dict với thống kê kết quả.
    """
    logger.info("Starting schedule sync at %s", datetime.now().isoformat())

    # 1. Fetch từ API + lịch thủ công JSON
    events = await fetch_all_schedules()
    total = len(events)

    if total == 0:
        logger.warning("No events fetched from API.")
        db.log_sync("ALL", 0, 0, 0, "empty")
        return {"total": 0, "new": 0, "changed": 0, "status": "empty"}

    # 2. Upsert vào DB và phát hiện thay đổi
    new_events = []
    changed_events = []
    # Dedup theo (date, session, subject) để tránh thông báo 2 lần
    # khi cùng 1 buổi học tồn tại trong cả API lẫn manual_schedule.json
    _seen_new: set[tuple] = set()
    _seen_changed: set[tuple] = set()
    for event in events:
        is_new, is_changed = db.upsert_event(event)
        lesson_key = (
            event.get("date", ""),
            event.get("session", ""),
            (event.get("subject") or "").strip().lower(),
        )
        if is_new and lesson_key not in _seen_new:
            _seen_new.add(lesson_key)
            new_events.append(event)
        elif is_changed and lesson_key not in _seen_changed:
            _seen_changed.add(lesson_key)
            changed_events.append(event)

    # 2b. Reconcile lịch thủ công: xóa event cũ không còn trong JSON mới
    manual_events = [e for e in events if e.get("class_id") == MANUAL_SCHEDULE_CLASS_ID]
    if manual_events:
        current_manual_ids = {e["id"] for e in manual_events}
        deleted = db.delete_stale_events_for_class(MANUAL_SCHEDULE_CLASS_ID, current_manual_ids)
        if deleted:
            logger.info("Reconcile: đã xóa %d lịch thủ công không còn trong JSON", deleted)

    logger.info("Sync result: total=%d, new=%d, changed=%d", total, len(new_events), len(changed_events))

    # 3. Đồng bộ Google Calendar
    # Reconcile toàn bộ events mỗi lần sync để nếu trước đó GCal bị tắt/thiếu
    # credentials thì sau khi bật lại vẫn đẩy được các lịch đã tồn tại trong DB.
    gcal_success = 0
    gcal_failed = 0
    if GOOGLE_CALENDAR_ENABLED:
        gcal_success, gcal_failed = await asyncio.to_thread(sync_all_events, events)

    # 4. Gửi thông báo Telegram về kết quả sync, kể cả khi không đổi
    if bot and notify_changes:
        await _notify_sync_result(bot, new_events, changed_events, total, gcal_success, gcal_failed)

    # 5. Log sync
    db.log_sync("ALL", total, len(new_events), len(changed_events), "ok")

    return {
        "total": total,
        "new": len(new_events),
        "changed": len(changed_events),
        "gcal_synced": gcal_success,
        "gcal_failed": gcal_failed,
        "status": "ok",
    }


async def run_reminder_check(bot) -> int:
    """Kiểm tra và gửi nhắc nhở cho sự kiện sắp tới. Trả về số nhắc đã gửi."""
    from notifier import get_events_needing_reminder, build_reminder_message

    items = get_events_needing_reminder()  # list of (event, hours_left)
    sent_count = 0

    for event, hours_left in items:
        msg = build_reminder_message(event, hours_left=hours_left)
        success = await _broadcast(bot, msg)
        if success:
            db.mark_notification_sent(event["id"], "reminder")
            sent_count += 1
            logger.info("Sent reminder for event %s (%.1fh left)", event.get("id"), hours_left)

    if sent_count:
        logger.info("Sent %d reminder(s).", sent_count)
    return sent_count


async def _notify_sync_result(
    bot,
    new_events: list,
    changed_events: list,
    total: int,
    gcal_success: int = 0,
    gcal_failed: int = 0,
) -> None:
    from notifier import build_sync_notification

    msg = build_sync_notification(
        new_events,
        changed_events,
        total,
        gcal_synced=gcal_success,
        gcal_failed=gcal_failed,
    )
    await _broadcast(bot, msg)


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
