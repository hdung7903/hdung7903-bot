"""
calendar_sync.py – Đồng bộ lịch học lên Google Calendar, bao gồm link Teams.
"""
import logging
import os
from config import (
    GOOGLE_CALENDAR_ENABLED, GOOGLE_CALENDAR_ID, GOOGLE_CALENDAR_SCOPES,
    GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, GOOGLE_CREDENTIALS_JSON,
    GOOGLE_TOKEN_JSON, GOOGLE_ALLOW_LOCAL_OAUTH, TIMEZONE,
)

logger = logging.getLogger(__name__)

_GCAL_SERVICE = None
_GCAL_UNAVAILABLE_REASON = None
_GCAL_CALENDAR_VALIDATED = False
_GCAL_AUTH_ERROR = False          # True khi lỗi invalid_grant → cần token mới


def _write_secret_json_if_needed(path: str, value: str, label: str) -> bool:
    """
    Ghi env var value ra file path.
    - Nếu value rỗng và file đã có → dùng file cũ (không làm gì).
    - Nếu value có giá trị → luôn ghi đè để env var mới có hiệu lực
      (quan trọng khi token hết hạn và được cập nhật qua Coolify env).
    """
    global _GCAL_UNAVAILABLE_REASON
    if not value:
        # Không có env var → dùng file sẵn có nếu có
        return True
    # Có env var → ghi đè (kể cả khi file đã tồn tại)
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # Chỉ ghi nếu nội dung thực sự khác (tránh I/O thừa)
        new_content = value.strip()
        existing_content = ""
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    existing_content = f.read().strip()
            except OSError:
                pass
        if new_content != existing_content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            logger.info("Google Calendar %s updated from environment variable.", label)
        else:
            logger.debug("Google Calendar %s: env var matches file, no write needed.", label)
        return True
    except OSError as e:
        _GCAL_UNAVAILABLE_REASON = f"cannot write {label} to {path}: {e}"
        logger.error("Google Calendar disabled: %s", _GCAL_UNAVAILABLE_REASON)
        return False


def _materialize_google_secrets() -> bool:
    credentials_ok = _write_secret_json_if_needed(
        GOOGLE_CREDENTIALS_FILE,
        GOOGLE_CREDENTIALS_JSON,
        "credentials",
    )
    token_ok = _write_secret_json_if_needed(
        GOOGLE_TOKEN_FILE,
        GOOGLE_TOKEN_JSON,
        "token",
    )
    # Nếu token file vừa được cập nhật → reset service cache để dùng token mới
    if token_ok:
        global _GCAL_SERVICE, _GCAL_UNAVAILABLE_REASON
        _GCAL_SERVICE = None
        _GCAL_UNAVAILABLE_REASON = None
    return credentials_ok and token_ok


def _get_calendar_service():
    global _GCAL_SERVICE, _GCAL_UNAVAILABLE_REASON, _GCAL_AUTH_ERROR
    if _GCAL_SERVICE is not None:
        return _GCAL_SERVICE
    if _GCAL_UNAVAILABLE_REASON:
        return None

    if not _materialize_google_secrets():
        return None

    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        _GCAL_UNAVAILABLE_REASON = f"credentials file not found: {GOOGLE_CREDENTIALS_FILE}"
        logger.warning("Google Calendar disabled: %s", _GCAL_UNAVAILABLE_REASON)
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if os.path.exists(GOOGLE_TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, GOOGLE_CALENDAR_SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Google Calendar: access token hết hạn, đang tự động refresh...")
                creds.refresh(Request())
                # Lưu token mới vào file để lần sau dùng
                token_dir = os.path.dirname(GOOGLE_TOKEN_FILE)
                if token_dir:
                    os.makedirs(token_dir, exist_ok=True)
                with open(GOOGLE_TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())
                logger.info("Google Calendar: token đã được refresh và lưu lại thành công.")
            else:
                if not GOOGLE_ALLOW_LOCAL_OAUTH:
                    _GCAL_UNAVAILABLE_REASON = (
                        f"token file not found or invalid: {GOOGLE_TOKEN_FILE}. "
                        "Generate token.json locally, mount it to the container, or set "
                        "GOOGLE_ALLOW_LOCAL_OAUTH=true only when running interactively."
                    )
                    logger.warning("Google Calendar disabled: %s", _GCAL_UNAVAILABLE_REASON)
                    return None
                flow = InstalledAppFlow.from_client_secrets_file(
                    GOOGLE_CREDENTIALS_FILE, GOOGLE_CALENDAR_SCOPES
                )
                creds = flow.run_local_server(port=0)
                token_dir = os.path.dirname(GOOGLE_TOKEN_FILE)
                if token_dir:
                    os.makedirs(token_dir, exist_ok=True)
                with open(GOOGLE_TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())

        _GCAL_SERVICE = build("calendar", "v3", credentials=creds)
        _GCAL_AUTH_ERROR = False   # Reset nếu trước đó có lỗi nhưng giờ OK
        return _GCAL_SERVICE
    except ImportError:
        _GCAL_UNAVAILABLE_REASON = "Google Calendar libraries not installed"
        logger.warning("Google Calendar disabled: %s", _GCAL_UNAVAILABLE_REASON)
        return None
    except Exception as e:
        _GCAL_UNAVAILABLE_REASON = str(e)
        err_str = str(e).lower()
        # invalid_grant = refresh token bị thu hồi/hết hạn → cần tạo token mới thủ công
        if any(k in err_str for k in ("invalid_grant", "token_expired", "unauthorized",
                                      "invalid_client", "bad request")):
            _GCAL_AUTH_ERROR = True
            logger.warning("Google Calendar: refresh token hết hạn hoặc bị thu hồi: %s", e)
        else:
            _GCAL_AUTH_ERROR = False
            logger.error("Google Calendar disabled: failed to get service: %s", e)
        return None


def _ensure_calendar_available(service) -> bool:
    global _GCAL_CALENDAR_VALIDATED, _GCAL_UNAVAILABLE_REASON
    if _GCAL_CALENDAR_VALIDATED:
        return True
    try:
        service.calendars().get(calendarId=GOOGLE_CALENDAR_ID).execute()
        _GCAL_CALENDAR_VALIDATED = True
        return True
    except Exception as e:
        _GCAL_UNAVAILABLE_REASON = (
            f"calendar id not found or not accessible: {GOOGLE_CALENDAR_ID}. "
            "Use GOOGLE_CALENDAR_ID=primary for your main calendar, or use the real "
            "calendar ID from Google Calendar settings."
        )
        logger.error("Google Calendar disabled: %s Original error: %s", _GCAL_UNAVAILABLE_REASON, e)
        return False


def is_gcal_auth_error() -> bool:
    """Trả True khi GCal lỗi vì token hết hạn/bị thu hồi (cần tạo token mới)."""
    return _GCAL_AUTH_ERROR


def get_gcal_user_alert() -> str:
    """
    Trả về tin nhắn Telegram thân thiện khi GCal bị lỗi auth,
    kèm hướng dẫn fix cụ thể.
    """
    return (
        "⚠️ <b>Google Calendar bị mất kết nối!</b>\n\n"
        "Token xác thực Google đã hết hạn hoặc bị thu hồi.\n"
        "Lịch học <b>vẫn đồng bộ bình thường</b> trên bot, "
        "chỉ Google Calendar không được cập nhật.\n\n"
        "<b>Cách fix (5 phút):</b>\n"
        "1. Mở PowerShell trong thư mục bot\n"
        "2. Chạy: <code>python refresh_gcal_token.py</code>\n"
        "3. Đăng nhập Google trên trình duyệt → Allow\n"
        "4. Copy JSON token mới → cập nhật biến "
        "<code>GOOGLE_TOKEN_JSON</code> trên Coolify\n"
        "5. Redeploy → gõ <code>/gcal_status</code> kiểm tra\n\n"
        "<i>Bot sẽ không báo lại lỗi này trong 24h tới.</i>"
    )


def reset_gcal_service() -> None:
    """Reset service cache (dùng khi token được cập nhật từ bên ngoài)."""
    global _GCAL_SERVICE, _GCAL_UNAVAILABLE_REASON, _GCAL_AUTH_ERROR, _GCAL_CALENDAR_VALIDATED
    _GCAL_SERVICE = None
    _GCAL_UNAVAILABLE_REASON = None
    _GCAL_AUTH_ERROR = False
    _GCAL_CALENDAR_VALIDATED = False


def get_gcal_status(check_service: bool = False) -> dict:
    materialized = _materialize_google_secrets()
    status = {
        "enabled": GOOGLE_CALENDAR_ENABLED,
        "calendar_id": GOOGLE_CALENDAR_ID,
        "credentials_file": GOOGLE_CREDENTIALS_FILE,
        "credentials_exists": os.path.exists(GOOGLE_CREDENTIALS_FILE),
        "token_file": GOOGLE_TOKEN_FILE,
        "token_exists": os.path.exists(GOOGLE_TOKEN_FILE),
        "allow_local_oauth": GOOGLE_ALLOW_LOCAL_OAUTH,
        "available": False,
        "reason": "",
    }

    if not GOOGLE_CALENDAR_ENABLED:
        status["reason"] = "GOOGLE_CALENDAR_ENABLED=false"
        return status
    if not materialized:
        status["reason"] = _GCAL_UNAVAILABLE_REASON or "failed to materialize Google secrets"
        return status
    if not status["credentials_exists"]:
        status["reason"] = f"missing credentials file: {GOOGLE_CREDENTIALS_FILE}"
        return status
    if not status["token_exists"] and not GOOGLE_ALLOW_LOCAL_OAUTH:
        status["reason"] = f"missing token file: {GOOGLE_TOKEN_FILE}"
        return status

    if check_service:
        service = _get_calendar_service()
        calendar_ok = bool(service and _ensure_calendar_available(service))
        status["available"] = calendar_ok
        status["reason"] = _GCAL_UNAVAILABLE_REASON or ("ok" if calendar_ok else "service unavailable")
    else:
        status["available"] = True
        status["reason"] = "looks configured"
    return status


def _event_to_gcal(event: dict) -> dict:
    """Chuyển event bot → Google Calendar event body."""
    date      = event.get("date") or ""
    start_t   = event.get("start_time") or "08:00"
    end_t     = event.get("end_time") or "10:00"
    session   = {"sang": "Sáng", "chieu": "Chiều", "toi": "Tối"}.get(event.get("session", "sang"), "Sáng")
    subject   = event.get("subject", "Lịch học")
    teacher   = event.get("teacher", "")
    link      = event.get("link", "")
    class_id  = event.get("class_id", "")
    is_approx = bool(event.get("is_approximate"))

    summary = f"📚 {subject} ({session})"
    if is_approx:
        summary += " [Dự kiến]"

    desc_lines = [
        f"Môn: {subject}",
        f"Buổi: {session}",
        f"Giảng viên: {teacher}" if teacher else "",
        f"Lớp: {class_id}",
        "",
        f"🔗 Link Teams: {link}" if link else "",
    ]
    description = "\n".join(l for l in desc_lines if l is not None)

    gcal = {
        "summary": summary,
        "description": description,
        "location": link if link else "",
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 60},
                {"method": "popup", "minutes": 1440},  # 24h
            ],
        },
        "extendedProperties": {
            "private": {
                "bot_event_id": event["id"],
                "class_id": class_id,
            }
        },
        "colorId": "2",  # Xanh lá
    }

    if not is_approx and date:
        gcal["start"] = {"dateTime": f"{date}T{start_t}:00", "timeZone": TIMEZONE}
        gcal["end"]   = {"dateTime": f"{date}T{end_t}:00",   "timeZone": TIMEZONE}
    elif date:
        # Sự kiện ngày (all-day) cho lịch dự kiến
        gcal["start"] = {"date": date}
        gcal["end"]   = {"date": date}

    return gcal


def _find_existing_gcal_event(service, event: dict) -> str | None:
    event_ids = [event["id"], *(event.get("legacy_ids") or [])]
    seen: set[str] = set()
    for bot_event_id in event_ids:
        if not bot_event_id or bot_event_id in seen:
            continue
        seen.add(bot_event_id)
        try:
            result = service.events().list(
                calendarId=GOOGLE_CALENDAR_ID,
                privateExtendedProperty=f"bot_event_id={bot_event_id}",
                maxResults=1,
            ).execute()
            items = result.get("items", [])
            if items:
                return items[0]["id"]
        except Exception as e:
            logger.error("Error searching gcal event by bot id %s: %s", bot_event_id, e)
            return None
    return None


def sync_event_to_gcal(event: dict, service=None) -> bool:
    if not GOOGLE_CALENDAR_ENABLED:
        return False
    if not event.get("date"):
        return False  # Bỏ qua event không có ngày

    service = service or _get_calendar_service()
    if not service:
        return False

    gcal_event = _event_to_gcal(event)
    if not gcal_event.get("start"):
        return False

    existing_id = _find_existing_gcal_event(service, event)
    try:
        if existing_id:
            service.events().update(
                calendarId=GOOGLE_CALENDAR_ID,
                eventId=existing_id,
                body=gcal_event,
            ).execute()
            logger.info("Updated GCal event: %s", event["id"])
        else:
            service.events().insert(
                calendarId=GOOGLE_CALENDAR_ID,
                body=gcal_event,
            ).execute()
            logger.info("Created GCal event: %s", event["id"])
        return True
    except Exception as e:
        logger.error("Failed to sync event %s to GCal: %s", event["id"], e)
        return False


def _delete_stale_gcal_events(service, events: list[dict]) -> tuple[int, int]:
    """
    Xóa event cũ/duplicate do bot tạo nhưng không còn trong lịch nguồn.

    Chỉ đụng vào event mang private extended properties của bot; event do người
    dùng tự tạo trên Google Calendar không bao giờ bị ảnh hưởng.
    """
    current_ids_by_class: dict[str, set[str]] = {}
    for event in events:
        if not event.get("date"):
            continue
        current_ids_by_class.setdefault(event["class_id"], set()).add(event["id"])

    deleted = 0
    failed = 0
    for class_id, current_ids in current_ids_by_class.items():
        page_token = None
        seen_ids: set[str] = set()
        while True:
            try:
                result = service.events().list(
                    calendarId=GOOGLE_CALENDAR_ID,
                    privateExtendedProperty=f"class_id={class_id}",
                    maxResults=250,
                    pageToken=page_token,
                    fields="items(id,extendedProperties),nextPageToken",
                ).execute()
            except Exception as e:
                logger.error("Failed to list GCal events for cleanup class %s: %s", class_id, e)
                failed += 1
                break

            for gcal_event in result.get("items", []):
                props = (gcal_event.get("extendedProperties") or {}).get("private") or {}
                bot_event_id = props.get("bot_event_id")
                should_delete = not bot_event_id or bot_event_id not in current_ids
                is_duplicate = bot_event_id in seen_ids if bot_event_id else False
                if not should_delete and not is_duplicate:
                    seen_ids.add(bot_event_id)
                    continue

                try:
                    service.events().delete(
                        calendarId=GOOGLE_CALENDAR_ID,
                        eventId=gcal_event["id"],
                    ).execute()
                    deleted += 1
                    reason = "duplicate" if is_duplicate else "stale"
                    logger.info("Deleted %s GCal event %s for class %s", reason, gcal_event["id"], class_id)
                except Exception as e:
                    logger.error("Failed to delete GCal event %s: %s", gcal_event.get("id"), e)
                    failed += 1

            page_token = result.get("nextPageToken")
            if not page_token:
                break
    return deleted, failed


def sync_all_events(events: list[dict]) -> tuple[int, int, int]:
    if not GOOGLE_CALENDAR_ENABLED:
        return 0, 0, 0
    service = _get_calendar_service()
    if not service:
        return 0, 0, 0
    if not _ensure_calendar_available(service):
        return 0, len(events), 0
    success, fail = 0, 0
    for event in events:
        if not event.get("date"):
            logger.info("Skipped GCal event without parsed date: %s (%s)", event["id"], event.get("time_raw", ""))
            continue
        if sync_event_to_gcal(event, service=service):
            success += 1
        else:
            fail += 1

    if fail:
        logger.warning("Skipped GCal stale-event cleanup because %d sync operation(s) failed.", fail)
        return success, fail, 0

    deleted, cleanup_failed = _delete_stale_gcal_events(service, events)
    return success, cleanup_failed, deleted
