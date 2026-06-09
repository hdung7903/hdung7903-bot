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


def _write_secret_json_if_needed(path: str, value: str, label: str) -> None:
    if not value or os.path.exists(path):
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(value.strip())
    logger.info("Google Calendar %s materialized from environment.", label)


def _materialize_google_secrets() -> None:
    _write_secret_json_if_needed(
        GOOGLE_CREDENTIALS_FILE,
        GOOGLE_CREDENTIALS_JSON,
        "credentials",
    )
    _write_secret_json_if_needed(
        GOOGLE_TOKEN_FILE,
        GOOGLE_TOKEN_JSON,
        "token",
    )


def _get_calendar_service():
    global _GCAL_SERVICE, _GCAL_UNAVAILABLE_REASON
    if _GCAL_SERVICE is not None:
        return _GCAL_SERVICE
    if _GCAL_UNAVAILABLE_REASON:
        return None

    _materialize_google_secrets()

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
                creds.refresh(Request())
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
        return _GCAL_SERVICE
    except ImportError:
        _GCAL_UNAVAILABLE_REASON = "Google Calendar libraries not installed"
        logger.warning("Google Calendar disabled: %s", _GCAL_UNAVAILABLE_REASON)
        return None
    except Exception as e:
        _GCAL_UNAVAILABLE_REASON = str(e)
        logger.error("Google Calendar disabled: failed to get service: %s", e)
        return None


def get_gcal_status(check_service: bool = False) -> dict:
    _materialize_google_secrets()
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
    if not status["credentials_exists"]:
        status["reason"] = f"missing credentials file: {GOOGLE_CREDENTIALS_FILE}"
        return status
    if not status["token_exists"] and not GOOGLE_ALLOW_LOCAL_OAUTH:
        status["reason"] = f"missing token file: {GOOGLE_TOKEN_FILE}"
        return status

    if check_service:
        service = _get_calendar_service()
        status["available"] = service is not None
        status["reason"] = _GCAL_UNAVAILABLE_REASON or ("ok" if service else "service unavailable")
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


def _find_existing_gcal_event(service, bot_event_id: str) -> str | None:
    try:
        result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            privateExtendedProperty=f"bot_event_id={bot_event_id}",
            maxResults=1,
        ).execute()
        items = result.get("items", [])
        return items[0]["id"] if items else None
    except Exception as e:
        logger.error("Error searching gcal event: %s", e)
        return None


def sync_event_to_gcal(event: dict) -> bool:
    if not GOOGLE_CALENDAR_ENABLED:
        return False
    if not event.get("date"):
        return False  # Bỏ qua event không có ngày

    service = _get_calendar_service()
    if not service:
        return False

    gcal_event = _event_to_gcal(event)
    if not gcal_event.get("start"):
        return False

    existing_id = _find_existing_gcal_event(service, event["id"])
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


def sync_all_events(events: list[dict]) -> tuple[int, int]:
    if not GOOGLE_CALENDAR_ENABLED:
        return 0, 0
    if not _get_calendar_service():
        return 0, 0
    success, fail = 0, 0
    for event in events:
        if sync_event_to_gcal(event):
            success += 1
        else:
            fail += 1
    return success, fail
