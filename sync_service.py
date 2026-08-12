import logging
import asyncio
import time
from datetime import datetime

import database as db
from api_client import fetch_all_schedule_sources
from calendar_sync import sync_all_events, is_gcal_auth_error, get_gcal_user_alert
from config import GOOGLE_CALENDAR_ENABLED, MANUAL_SCHEDULE_CLASS_ID

logger = logging.getLogger(__name__)

# Rate-limit noti GCal lỗi: chỉ gửi 1 lần / 24h để không spam
_GCAL_ALERT_INTERVAL = 86400   # 24 giờ (giây)
_last_gcal_alert_at: float = 0.0


def _normalize_subject(subject: str | None) -> str:
    """Tạo khóa so sánh tên môn giữa nguồn API và lịch thủ công."""
    return " ".join((subject or "").casefold().split())


def _prefer_api_events(events: list[dict]) -> tuple[list[dict], int]:
    """Ưu tiên lịch API khi nó đã có cùng môn với một event thủ công.

    Lịch thủ công vẫn là fallback cho các môn API chưa trả về. Khi API đã có
    lịch chính thức, giữ cả hai sẽ tạo event trùng hoặc giữ lại ngày cũ.
    """
    api_events = [event for event in events if event.get("class_id") != MANUAL_SCHEDULE_CLASS_ID]
    manual_events = [event for event in events if event.get("class_id") == MANUAL_SCHEDULE_CLASS_ID]
    api_subjects = {_normalize_subject(event.get("subject")) for event in api_events}
    active_manual_events = [
        event
        for event in manual_events
        if _normalize_subject(event.get("subject")) not in api_subjects
    ]
    return api_events + active_manual_events, len(manual_events) - len(active_manual_events)


async def run_sync(bot=None, notify_changes: bool = True) -> dict:
    """
    Chạy chu trình đồng bộ đầy đủ.
    Returns: dict với thống kê kết quả.
    """
    logger.info("Starting schedule sync at %s", datetime.now().isoformat())

    # 1. Fetch từ API + lịch thủ công JSON
    fetched_events, successful_api_classes, failed_api_classes = await fetch_all_schedule_sources()
    events, overridden_manual_count = _prefer_api_events(fetched_events)
    total = len(events)

    if overridden_manual_count:
        logger.info(
            "API schedule overrides %d manual event(s) with the same subject.",
            overridden_manual_count,
        )

    if total == 0 and not successful_api_classes:
        logger.error("Schedule fetch returned no events; keeping the existing schedule unchanged.")
        db.log_sync("ALL", 0, 0, 0, "fetch_failed")
        if bot and notify_changes:
            await _notify_sync_fetch_failure(bot)
        return {"total": 0, "new": 0, "changed": 0, "status": "fetch_failed"}

    # 2. Upsert vào DB và phát hiện thay đổi
    new_events = []
    changed_events = []  # list of (event, changes_dict)
    # Dedup theo (date, session, subject) để tránh thông báo 2 lần
    # khi cùng 1 buổi học tồn tại trong cả API lẫn manual_schedule.json
    _seen_new: set[tuple] = set()
    _seen_changed: set[tuple] = set()
    for event in events:
        is_new, changes = db.upsert_event(event)
        lesson_key = (
            event.get("date", ""),
            event.get("session", ""),
            (event.get("subject") or "").strip().lower(),
        )
        if is_new and lesson_key not in _seen_new:
            _seen_new.add(lesson_key)
            new_events.append(event)
        elif changes and lesson_key not in _seen_changed:
            _seen_changed.add(lesson_key)
            changed_events.append((event, changes))

    # 2b. Reconcile snapshot từng nguồn. Chỉ dọn lớp API đã fetch thành công;
    # nếu API lỗi thì giữ nguyên lịch cũ và báo rõ, không báo "như cũ".
    deleted_events: list[dict] = []
    manual_events = [e for e in events if e.get("class_id") == MANUAL_SCHEDULE_CLASS_ID]
    current_manual_ids = {e["id"] for e in manual_events}
    deleted_events.extend(
        db.reconcile_stale_events_for_class(MANUAL_SCHEDULE_CLASS_ID, current_manual_ids)
    )
    for class_id in successful_api_classes:
        current_ids = {
            event["id"]
            for event in events
            if event.get("class_id") == class_id
        }
        deleted_events.extend(db.reconcile_stale_events_for_class(class_id, current_ids))
    if deleted_events:
        logger.info("Reconcile: đã xóa %d lịch không còn trong nguồn", len(deleted_events))
    if failed_api_classes:
        logger.warning("Schedule API unavailable for class(es): %s", sorted(failed_api_classes))

    logger.info("Sync result: total=%d, new=%d, changed=%d", total, len(new_events), len(changed_events))

    # 3. Đồng bộ Google Calendar
    # Reconcile toàn bộ events mỗi lần sync để nếu trước đó GCal bị tắt/thiếu
    # credentials thì sau khi bật lại vẫn đẩy được các lịch đã tồn tại trong DB.
    gcal_success = 0
    gcal_failed = 0
    gcal_deleted = 0
    if GOOGLE_CALENDAR_ENABLED:
        gcal_success, gcal_failed, gcal_deleted = await asyncio.to_thread(
            sync_all_events,
            events,
            cleanup_class_ids={MANUAL_SCHEDULE_CLASS_ID, *successful_api_classes},
        )
        # Kiểm tra lỗi auth sau khi sync → noti người dùng (rate-limit 24h)
        if bot and is_gcal_auth_error():
            await _notify_gcal_auth_error(bot)

    # 4. Gửi thông báo Telegram về kết quả sync, kể cả khi không đổi
    if bot and notify_changes:
        await _notify_sync_result(
            bot,
            new_events,
            changed_events,
            deleted_events,
            total,
            gcal_success,
            gcal_failed,
            gcal_deleted,
            failed_api_classes,
        )

    # 5. Log sync
    db.log_sync("ALL", total, len(new_events), len(changed_events) + len(deleted_events), "ok")

    return {
        "total": total,
        "new": len(new_events),
        "changed": len(changed_events),
        "deleted": len(deleted_events),
        "failed_classes": sorted(failed_api_classes),
        "gcal_synced": gcal_success,
        "gcal_failed": gcal_failed,
        "gcal_deleted": gcal_deleted,
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


async def _notify_gcal_auth_error(bot) -> None:
    """Gửi noti GCal token hết hạn, rate-limit 24h để không spam."""
    global _last_gcal_alert_at
    now = time.monotonic()
    if now - _last_gcal_alert_at < _GCAL_ALERT_INTERVAL:
        return  # Đã gửi trong 24h qua → bỏ qua
    _last_gcal_alert_at = now
    msg = get_gcal_user_alert()
    await _broadcast(bot, msg)
    logger.warning("Đã gửi cảnh báo GCal auth error tới người dùng.")


async def _notify_sync_result(
    bot,
    new_events: list,
    changed_events: list,
    deleted_events: list,
    total: int,
    gcal_success: int = 0,
    gcal_failed: int = 0,
    gcal_deleted: int = 0,
    failed_classes: set[str] | None = None,
) -> None:
    from notifier import build_sync_notification

    msg = build_sync_notification(
        new_events,
        changed_events,
        total=total,
        deleted_events=deleted_events,
        gcal_synced=gcal_success,
        gcal_failed=gcal_failed,
        gcal_deleted=gcal_deleted,
        failed_classes=failed_classes,
    )
    await _broadcast(bot, msg)


async def _notify_sync_fetch_failure(bot) -> None:
    """Báo rõ khi API lịch học không trả dữ liệu, thay vì im lặng."""
    from notifier import build_sync_fetch_failure_notification

    await _broadcast(bot, build_sync_fetch_failure_notification())


async def _broadcast(bot, message: str) -> bool:
    """Gửi tin nhắn đến tất cả user đã đăng ký."""
    users = db.get_subscribed_users()
    if not users:
        logger.warning("No subscribed users to notify.")
        return False

    success = False
    for user in users:
        for attempt in range(1, 4):
            try:
                await bot.send_message(
                    chat_id=user["chat_id"],
                    text=message,
                    parse_mode="HTML",
                )
                success = True
                break
            except Exception as e:
                if attempt == 3:
                    logger.error("Failed to send message to %s after 3 attempts: %s", user["chat_id"], e)
                    break
                logger.warning("Notification send attempt %d/3 failed for %s: %s", attempt, user["chat_id"], e)
                await asyncio.sleep(attempt)
    return success
