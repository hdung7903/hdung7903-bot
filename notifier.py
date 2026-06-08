"""
notifier.py – Format thông báo Telegram, hỗ trợ link Teams.
"""
import logging
from datetime import datetime, timedelta

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

    teacher = (event.get("teacher") or "").strip()
    link    = (event.get("link") or "").strip()

    lines = [
        f"📚 <b>{event.get('subject', 'Môn học')}</b>",
        f"  {session_lbl}  |  {date_display}{range_str}{time_str}",
    ]
    if teacher:
        lines.append(f"  👨‍🏫 {teacher}")
    if show_link and link:
        lines.append(f"  🔗 <a href='{link}'>Tham gia Teams</a>")
    lines.append(f"  🆔 <code>{event.get('class_id', '')}</code>")

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


def build_reminder_message(event: dict) -> str:
    return (
        f"⏰ <b>Nhắc nhở: Lịch học ngày mai!</b>\n\n"
        f"{format_event(event, show_link=True)}\n\n"
        f"<i>Nhắc trước {NOTIFY_BEFORE_HOURS}h</i>"
    )


def build_new_event_message(event: dict) -> str:
    return f"🆕 <b>Lịch học mới được thêm!</b>\n\n{format_event(event)}"


def build_changed_event_message(event: dict) -> str:
    return f"✏️ <b>Lịch học vừa được cập nhật!</b>\n\n{format_event(event)}"


def build_sync_report(new_count: int, changed_count: int, total: int) -> str:
    if new_count == 0 and changed_count == 0:
        return f"✅ Đồng bộ xong. Tổng <b>{total}</b> buổi học. Không có thay đổi."
    parts = [f"🔄 <b>Đồng bộ lịch học hoàn tất!</b>", f"📊 Tổng: <b>{total}</b> buổi"]
    if new_count:
        parts.append(f"🆕 Mới: <b>{new_count}</b> buổi")
    if changed_count:
        parts.append(f"✏️ Thay đổi: <b>{changed_count}</b> buổi")
    return "\n".join(parts)


def get_events_needing_reminder() -> list[dict]:
    """Trả về events cần nhắc nhở (trong vòng ~24h tới, chưa gửi)."""
    now = datetime.now()
    target_date = (now + timedelta(hours=NOTIFY_BEFORE_HOURS)).strftime("%Y-%m-%d")
    events = db.get_events_for_date(target_date)

    result = []
    for event in events:
        if db.is_notification_sent(event["id"], "reminder"):
            continue
        if event.get("start_time"):
            try:
                event_dt = datetime.strptime(
                    f"{event['date']} {event['start_time']}", "%Y-%m-%d %H:%M"
                )
                diff_h = (event_dt - now).total_seconds() / 3600
                # Chỉ gửi nếu còn trong cửa sổ 0–(NOTIFY_BEFORE_HOURS+1) giờ
                if 0 < diff_h <= NOTIFY_BEFORE_HOURS + 1:
                    result.append(event)
            except ValueError:
                result.append(event)
        else:
            result.append(event)

    return result
