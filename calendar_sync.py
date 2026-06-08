"""
calendar_sync.py – Đồng bộ lịch học lên Google Calendar, bao gồm link Teams.
"""
import logging
import os
from config import (
    GOOGLE_CALENDAR_ENABLED, GOOGLE_CALENDAR_ID, GOOGLE_CALENDAR_SCOPES,
    GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, TIMEZONE,
)

logger = logging.getLogger(__name__)


def _get_calendar_service():
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
                flow = InstalledAppFlow.from_client_secrets_file(
                    GOOGLE_CREDENTIALS_FILE, GOOGLE_CALENDAR_SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(GOOGLE_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())

        return build("calendar", "v3", credentials=creds)
    except ImportError:
        logger.warning("Google Calendar libraries not installed.")
        return None
    except Exception as e:
        logger.error("Failed to get Google Calendar service: %s", e)
        return None


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
    success, fail = 0, 0
    for event in events:
        if sync_event_to_gcal(event):
            success += 1
        else:
            fail += 1
    return success, fail
