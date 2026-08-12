"""
notifier.py – Format thông báo Telegram, hỗ trợ link Teams.
"""
import logging
from html import escape
from datetime import datetime, timedelta, timezone

import database as db
from config import NOTIFY_BEFORE_HOURS

logger = logging.getLogger(__name__)

WEEKDAY_VN = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
SESSION_LABEL = {"sang": "☀️ Sáng", "chieu": "🌤 Chiều", "toi": "🌙 Tối"}


def _fmt_date(date_str: str) -> str:
    if not date_str:
        return "Chưa xác định"
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{WEEKDAY_VN[d.weekday()]}, {d.strftime('%d/%m/%Y')}"
    except Exception:
        return date_str


def format_event(event: dict, show_link: bool = True) -> str:
    session_lbl  = SESSION_LABEL.get(event.get("session", "sang"), "📅")
    is_approx    = bool(event.get("is_approximate"))

    date_display = _fmt_date(event.get("date"))
    if is_approx:
        date_display += " <i>(dự kiến)</i>"

    time_str = ""
    if not is_approx and event.get("start_time"):
        if event.get("end_time"):
            time_str = f"\n  🕐 <b>{event['start_time']} – {event['end_time']}</b>"
        else:
            time_str = f"\n  🕐 <b>{event['start_time']}</b>"

    range_str = ""
    if event.get("date_range_end"):
        range_str = f" → {_fmt_date(event['date_range_end'])}"

    subject = escape((event.get("subject") or "Môn học").strip())
    teacher = escape((event.get("teacher") or "").strip())
    link    = escape((event.get("link") or "").strip(), quote=True)
    class_id = escape((event.get("class_id") or "").strip())

    lines = [
        f"📚 <b>{subject}</b>",
        f"  {session_lbl}  |  {date_display}{range_str}{time_str}",
    ]
    if teacher:
        lines.append(f"  👨‍🏫 {teacher}")
    if show_link and link:
        lines.append(f"  🔗 <a href='{link}'>Tham gia Teams</a>")
    lines.append(f"  🆔 <code>{class_id}</code>")

    return "\n".join(lines)


def build_schedule_message(events: list[dict], title: str = "📅 Lịch học") -> str:
    if not events:
        return f"{title}\n\n<i>Không có lịch học nào.</i>"

    by_date: dict[str, list] = {}
    for e in events:
        key = e.get("date") or "unknown"
        by_date.setdefault(key, []).append(e)

    parts = [f"<b>{title}</b>"]
    for date_str in sorted(by_date.keys()):
        parts.append(f"\n📆 <b>{_fmt_date(date_str)}</b>")
        for event in sorted(by_date[date_str], key=lambda x: x.get("start_time") or ""):
            parts.append(format_event(event))
            parts.append("─" * 28)

    return "\n".join(parts)


def build_reminder_message(event: dict, hours_left: float | None = None) -> str:
    if hours_left is not None:
        if hours_left < 1:
            time_label = f"{int(hours_left * 60)} phút nữa"
        else:
            time_label = f"{hours_left:.0f}h nữa"
    else:
        time_label = f"{NOTIFY_BEFORE_HOURS}h"
    return (
        f"⏰ <b>Nhắc nhở: Lịch học sắp tới!</b>\n\n"
        f"{format_event(event, show_link=True)}\n\n"
        f"<i>⏳ Còn {time_label}</i>"
    )


def build_new_event_message(event: dict) -> str:
    return f"🆕 <b>Lịch học mới được thêm!</b>\n\n{format_event(event)}"


_FIELD_LABEL = {
    "date":       "📅 Ngày",
    "session":    "⏰ Buổi",
    "start_time": "🕐 Giờ bắt đầu",
    "end_time":   "🕐 Giờ kết thúc",
    "teacher":    "👨‍🏫 Giảng viên",
    "room":       "🏫 Phòng",
    "link":       "🔗 Link",
    "subject":    "📚 Môn học",
}
_SESSION_LABEL_VN = {"sang": "Sáng", "chieu": "Chiều", "toi": "Tối"}


def _fmt_change_val(field: str, val: str) -> str:
    """Format giá trị thay đổi để hiển thị thân thiện hơn."""
    if not val:
        return "<i>(trống)</i>"
    if field == "date":
        return _fmt_date(val)
    if field == "session":
        return _SESSION_LABEL_VN.get(val, val)
    return escape(val)


def build_changed_event_message(event: dict, changes: dict | None = None) -> str:
    """
    Thông báo lịch học thay đổi, hiển thị rõ trường nào đổi và giá trị cũ → mới.
    changes: {field: (old_val, new_val)} (từ db._detect_change).
    """
    # Phân loại: đổi ngày/buổi là quan trọng nhất
    is_reschedule = changes and ("date" in changes or "session" in changes)
    icon  = "⚠️" if is_reschedule else "✏️"
    title = "⚠️ <b>Lịch học Bị ĐỔI NGÀY!</b>" if is_reschedule else "✏️ <b>Lịch học vừa được cập nhật!</b>"

    lines = [title, "", format_event(event)]

    if changes:
        lines.append("")
        lines.append("<b>Chi tiết thay đổi:</b>")
        for field, (old_val, new_val) in changes.items():
            label   = _FIELD_LABEL.get(field, field)
            old_fmt = _fmt_change_val(field, old_val)
            new_fmt = _fmt_change_val(field, new_val)
            lines.append(f"  {label}: <s>{old_fmt}</s> → <b>{new_fmt}</b>")

    return "\n".join(lines)


def build_sync_report(new_count: int, changed_count: int, total: int, deleted_count: int = 0) -> str:
    if new_count == 0 and changed_count == 0 and deleted_count == 0:
        return f"✅ Đồng bộ xong. Tổng <b>{total}</b> buổi học. Không có thay đổi."
    parts = [f"🔄 <b>Đồng bộ lịch học hoàn tất!</b>", f"📊 Tổng: <b>{total}</b> buổi"]
    if new_count:
        parts.append(f"🆕 Mới: <b>{new_count}</b> buổi")
    if changed_count:
        parts.append(f"✏️ Thay đổi: <b>{changed_count}</b> buổi")
    if deleted_count:
        parts.append(f"🗑 Đã hủy/xóa: <b>{deleted_count}</b> buổi")
    return "\n".join(parts)


def build_sync_fetch_failure_notification() -> str:
    return (
        "⚠️ <b>Chưa thể đồng bộ lịch học</b>\n\n"
        "API lịch học không trả dữ liệu. Bot giữ nguyên lịch đã lưu trước đó "
        "và sẽ tự thử lại ở lần đồng bộ tiếp theo."
    )


def build_sync_notification(
    new_events: list[dict],
    changed_events: list[tuple[dict, dict]],  # list of (event, changes_dict)
    total: int,
    deleted_events: list[dict] | None = None,
    gcal_synced: int = 0,
    gcal_failed: int = 0,
    gcal_deleted: int = 0,
    failed_classes: set[str] | None = None,
) -> str:
    deleted_events = deleted_events or []
    new_count     = len(new_events)
    changed_count = len(changed_events)
    deleted_count = len(deleted_events)

    if new_count == 0 and changed_count == 0 and deleted_count == 0:
        parts = (
            [f"Dữ liệu vừa nhận được từ các lớp khả dụng: <b>{total}</b> buổi."]
            if failed_classes
            else [
                "✅ <b>Lịch học như cũ</b>",
                f"Tổng hiện có: <b>{total}</b> buổi.",
            ]
        )
    else:
        # Kiểm tra có thay đổi ngày không
        has_reschedule = any(
            "date" in ch or "session" in ch
            for _, ch in changed_events
        )
        header = "⚠️ <b>Có lịch học Bị ĐỔI!</b>" if has_reschedule else "🔄 <b>Lịch học vừa được cập nhật</b>"
        parts = [
            header,
            f"📊 Tổng: <b>{total}</b> buổi",
        ]
        if new_count:
            parts.append(f"🆕 Mới: <b>{new_count}</b> buổi")
        if changed_count:
            parts.append(f"✏️ Thay đổi: <b>{changed_count}</b> buổi")
        if deleted_count:
            parts.append(f"🗑 Đã hủy/xóa: <b>{deleted_count}</b> buổi")

        # Chi tiết tối đa 10 thay đổi
        preview_new      = new_events[:5]
        preview_changed  = changed_events[:5]
        preview_deleted  = deleted_events[:5]
        if preview_new or preview_changed or preview_deleted:
            parts.append("\n<b>Chi tiết:</b>")
            for event in preview_new:
                parts.append(f"\n🆕 {format_event(event)}")
            for event, ch in preview_changed:
                parts.append(f"\n{build_changed_event_message(event, ch)}")
            for event in preview_deleted:
                parts.append(f"\n🗑 <b>Lịch đã bị hủy/xóa:</b>\n{format_event(event)}")
            remaining = (
                new_count + changed_count + deleted_count
                - len(preview_new) - len(preview_changed) - len(preview_deleted)
            )
            if remaining > 0:
                parts.append(f"\n... và <b>{remaining}</b> thay đổi khác.")

    if failed_classes:
        warning = (
            "⚠️ <b>Đồng bộ chưa hoàn tất</b>\n"
            "API chưa trả dữ liệu cho: <code>"
            + ", ".join(escape(class_id) for class_id in sorted(failed_classes))
            + "</code>. Không kết luận lịch như cũ."
        )
        parts.insert(0, warning)

    if gcal_synced or gcal_failed:
        parts.append(
            f"\n📅 Google Calendar: <b>{gcal_synced}</b> synced"
            + (f", <b>{gcal_failed}</b> lỗi" if gcal_failed else "")
            + (f", đã xóa <b>{gcal_deleted}</b> lịch cũ" if gcal_deleted else "")
        )

    return "\n".join(parts)


VN_TZ = timezone(timedelta(hours=7))


def get_events_needing_reminder() -> list[tuple[dict, float]]:
    """
    Trả về list (event, hours_left) cho các buổi học:
    - Chưa gửi reminder
    - Sắp bắt đầu trong vòng NOTIFY_BEFORE_HOURS giờ (theo giờ VN)

    Dedup theo (date, session, subject) để tránh gửi 2 lần khi cùng 1 buổi
    xuất hiện trong cả API lẫn manual_schedule.json với event_id khác nhau.
    """
    now_vn = datetime.now(VN_TZ)

    # Lấy events trong hôm nay và ngày mai (giờ VN)
    today_str    = now_vn.strftime("%Y-%m-%d")
    tomorrow_str = (now_vn + timedelta(days=1)).strftime("%Y-%m-%d")

    candidates = (
        db.get_events_for_date(today_str) +
        db.get_events_for_date(tomorrow_str)
    )

    result: list[tuple[dict, float]] = []
    # Dedup key: (date, session, subject) → để tránh lặp khi cùng buổi học
    # nằm trong cả API và manual JSON với class_id khác nhau
    seen_lessons: set[tuple[str, str, str]] = set()

    for event in candidates:
        event_date = event.get("date")
        start_time = event.get("start_time")
        session    = event.get("session", "sang")
        subject    = (event.get("subject") or "").strip().lower()

        if not event_date:
            continue

        # Kiểm tra đã gửi chưa (theo event_id)
        if db.is_notification_sent(event["id"], "reminder"):
            # Đánh dấu lesson này đã handled dù bằng event_id nào
            seen_lessons.add((event_date, session, subject))
            continue

        # Dedup: nếu cùng buổi học đã được xử lý bởi event_id khác → bỏ qua
        lesson_key = (event_date, session, subject)
        if lesson_key in seen_lessons:
            # Đánh dấu event này là sent luôn để tránh gửi ở lần check sau
            db.mark_notification_sent(event["id"], "reminder")
            logger.debug("Dedup reminder: %s already queued via another event_id", event["id"])
            continue

        # Tính khoảng cách thời gian
        hours_left: float | None = None
        if start_time:
            try:
                event_dt = datetime(
                    *[int(x) for x in event_date.split("-")],
                    *[int(x) for x in start_time.split(":")],
                    tzinfo=VN_TZ,
                )
                diff_h = (event_dt - now_vn).total_seconds() / 3600
                # Gửi nếu còn trong khoảng (0, NOTIFY_BEFORE_HOURS] giờ
                if not (0 < diff_h <= NOTIFY_BEFORE_HOURS):
                    continue
                hours_left = diff_h
            except (ValueError, TypeError):
                # Không parse được giờ → gửi nếu là ngày mai
                if event_date != tomorrow_str:
                    continue
                hours_left = 24.0
        else:
            # Không có giờ cụ thể → chỉ gửi cho ngày mai
            if event_date != tomorrow_str:
                continue
            hours_left = 24.0

        seen_lessons.add(lesson_key)
        result.append((event, hours_left))

    return result
