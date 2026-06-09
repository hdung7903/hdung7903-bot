"""
api_client.py – Parse đúng format thực tế từ API VinhUni.

Format thực tế:
[
  {
    "duration": "",
    "link": "https://teams.microsoft.com/meet/...",
    "subject": "BB1. Sinh lý học trẻ em",
    "teacher": "PGS.TS. Nguyễn Thị Giang An,  ĐT: 0917113270",
    "time": "Tối 22,23/05/2026 (Thứ 6, 7)"
  },
  ...
]
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import httpx

from config import CLASS_IDS, DEFAULT_SESSION_TIMES, SCHEDULE_API_URL

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_event_id(class_id: str, date: str, subject: str, session: str) -> str:
    """Hash ổn định để detect thay đổi."""
    raw = f"{class_id}|{date}|{subject.strip()}|{session}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _apply_default_times(session: str, start_override: str = None) -> tuple[str, str]:
    """Trả về (start_time, end_time) mặc định theo buổi."""
    cfg = DEFAULT_SESSION_TIMES.get(session, DEFAULT_SESSION_TIMES["sang"])
    start = start_override or cfg["start"]
    end_dt = datetime.strptime(start, "%H:%M") + timedelta(hours=cfg["duration_hours"])
    return start, end_dt.strftime("%H:%M")


def _extract_link(item: dict) -> str:
    """Lấy link Teams/meeting từ API dù field bị đổi tên."""
    preferred_keys = (
        "link", "url", "meeting_url", "teams_url", "teams_link",
        "join_url", "joinUrl", "onlineMeetingUrl",
    )
    for key in preferred_keys:
        value = (item.get(key) or "").strip() if isinstance(item.get(key), str) else ""
        if value.startswith(("http://", "https://")):
            return value

    for value in item.values():
        if not isinstance(value, str):
            continue
        match = re.search(r'https?://[^\s<>"\']+', value)
        if match:
            return match.group(0).rstrip(".,);")
    return ""


# ─────────────────────────────────────────────────────────────────────────────
#  Parser cho field "time"
# ─────────────────────────────────────────────────────────────────────────────

def _detect_sessions(text: str) -> list[str]:
    """Phát hiện 1 hoặc nhiều buổi trong chuỗi time."""
    t = text.lower()
    sessions = []
    # Thứ tự quan trọng: kiểm tra "sáng" trước "chiều" trước "tối"
    if re.search(r's[áa]ng', t):
        sessions.append("sang")
    if re.search(r'chi[eề]u', t):
        sessions.append("chieu")
    if re.search(r't[oố]i', t):
        sessions.append("toi")
    return sessions or ["sang"]


def _parse_approx_date(text: str) -> Optional[str]:
    """
    Xử lý ngày dự kiến dạng 'Tháng 10/2026' hoặc 'DK: tháng 10/2026'.
    Trả về ngày đầu tháng dạng YYYY-MM-DD, hoặc None nếu không parse được.
    """
    m = re.search(r't[hh]áng\s+(\d{1,2})/(\d{4})', text, re.IGNORECASE)
    if m:
        try:
            month, year = int(m.group(1)), int(m.group(2))
            return datetime(year, month, 1).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _parse_date_range(text: str) -> Optional[list[str]]:
    """
    Xử lý khoảng thời gian dạng '30/11 đến 02/01/2027'.
    Trả về [start_date, end_date] hoặc None.
    """
    m = re.search(
        r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*đến\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)',
        text, re.IGNORECASE
    )
    if not m:
        return None

    def _norm(date_frag: str, fallback_year: int) -> Optional[str]:
        parts = date_frag.strip().split("/")
        if len(parts) == 2:
            parts.append(str(fallback_year))
        if len(parts) == 3:
            try:
                return datetime(int(parts[2]), int(parts[1]), int(parts[0])).strftime("%Y-%m-%d")
            except ValueError:
                pass
        return None

    # Cố gắng lấy năm từ text gốc
    year_m = re.search(r'(\d{4})', text)
    year = int(year_m.group(1)) if year_m else datetime.now().year

    start = _norm(m.group(1), year)
    end   = _norm(m.group(2), year)
    if start and end:
        return [start, end]
    return None


def parse_time_field(time_str: str) -> list[dict]:
    """
    Parse field 'time' từ API response.

    Trả về list[dict] với keys: {session, date, is_approximate, date_range_end}

    Ví dụ:
      "Tối 08/05/2026 (Thứ 6)"          → [{session:toi, date:2026-05-08}]
      "Tối 22,23/05/2026 (Thứ 6, 7)"    → [{toi,2026-05-22}, {toi,2026-05-23}]
      "Sáng, chiều 14/06/2026 (CN)"      → [{sang,2026-06-14}, {chieu,2026-06-14}]
      "DK: tháng 10/2026"               → [{sang,2026-10-01, is_approximate:True}]
      "Tháng 9/2026"                     → [{sang,2026-09-01, is_approximate:True}]
      "30/11 đến 02/01/2027"            → [{sang,2026-11-30, date_range_end:2027-01-02}]
    """
    if not time_str or not isinstance(time_str, str):
        return []

    time_str = time_str.strip()
    results = []
    sessions = _detect_sessions(time_str)

    # ── 1. Khoảng thời gian (đến) ────────────────────────────────────────────
    date_range = _parse_date_range(time_str)
    if date_range:
        for session in sessions:
            results.append({
                "session": session,
                "date": date_range[0],
                "is_approximate": False,
                "date_range_end": date_range[1],
            })
        return results

    # ── 2. Ngày cụ thể: "22,23/05/2026" hay "08/05/2026" ────────────────────
    # Pattern: số ngày (có thể nhiều, cách nhau dấu phẩy) / tháng / năm
    month_year_match = re.search(
        r'(\d{1,2}(?:\s*,\s*\d{1,2})*)\s*/\s*(\d{1,2})\s*/?\s*(\d{4})',
        time_str
    )
    if month_year_match:
        days_str = month_year_match.group(1)
        month    = int(month_year_match.group(2))
        year     = int(month_year_match.group(3))
        days     = [int(d.strip()) for d in days_str.split(",") if d.strip()]

        for day in days:
            try:
                date = datetime(year, month, day).strftime("%Y-%m-%d")
                for session in sessions:
                    results.append({
                        "session": session,
                        "date": date,
                        "is_approximate": False,
                        "date_range_end": None,
                    })
            except ValueError:
                logger.warning("Invalid date: day=%d month=%d year=%d", day, month, year)
        return results

    # ── 3. Ngày dự kiến: "Tháng 10/2026", "DK: tháng 10/2026" ──────────────
    approx_date = _parse_approx_date(time_str)
    if approx_date:
        for session in sessions:
            results.append({
                "session": session,
                "date": approx_date,
                "is_approximate": True,
                "date_range_end": None,
            })
        return results

    logger.warning("Could not parse time field: %r", time_str)
    return []


# ─────────────────────────────────────────────────────────────────────────────
#  Main parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_schedule_response(class_id: str, data) -> list[dict]:
    """
    Chuyển đổi response API thành danh sách events chuẩn.

    Mỗi item trong API có thể tạo ra NHIỀU events (khi có nhiều ngày/buổi).
    """
    events: list[dict] = []

    # Response là array trực tiếp
    items: list = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # Thử tìm list trong dict
        for key in ("data", "lich_hoc", "result", "results", "schedules", "items"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
        if not items:
            for v in data.values():
                if isinstance(v, list):
                    items = v
                    break

    seen_ids: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        subject  = (item.get("subject") or item.get("ten_mon") or "Không rõ môn").strip()
        teacher  = (item.get("teacher") or item.get("giang_vien") or "").strip()
        link     = _extract_link(item)
        duration = (item.get("duration") or "").strip()
        time_raw = (item.get("time") or item.get("thoi_gian") or "").strip()

        # Parse time field → 1 hoặc nhiều (session, date)
        parsed_times = parse_time_field(time_raw)

        if not parsed_times:
            # Không parse được ngày → vẫn lưu nhưng mark approximate
            event_id = _make_event_id(class_id, "unknown", subject, "sang")
            if event_id not in seen_ids:
                seen_ids.add(event_id)
                events.append({
                    "id": event_id,
                    "class_id": class_id,
                    "subject": subject,
                    "teacher": teacher,
                    "room": "",
                    "session": "sang",
                    "date": None,
                    "start_time": None,
                    "end_time": None,
                    "link": link,
                    "is_approximate": True,
                    "date_range_end": None,
                    "time_raw": time_raw,
                    "raw_data": item,
                })
            continue

        for pt in parsed_times:
            session       = pt["session"]
            date          = pt["date"]
            is_approximate = pt["is_approximate"]
            date_range_end = pt.get("date_range_end")

            start_time, end_time = _apply_default_times(session)

            event_id = _make_event_id(class_id, date or "unknown", subject, session)
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)

            events.append({
                "id": event_id,
                "class_id": class_id,
                "subject": subject,
                "teacher": teacher,
                "room": "",
                "session": session,
                "date": date,
                "start_time": start_time if not is_approximate else None,
                "end_time": end_time if not is_approximate else None,
                "link": link,
                "is_approximate": is_approximate,
                "date_range_end": date_range_end,
                "time_raw": time_raw,
                "raw_data": item,
            })

    logger.info("Parsed %d events for class_id=%s", len(events), class_id)
    return events


# ─────────────────────────────────────────────────────────────────────────────
#  Fetch functions
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_schedule(class_id: str) -> list[dict]:
    """Gọi API và trả về danh sách events đã parse."""
    payload = {"class_id": class_id}
    logger.info("Fetching schedule for class_id=%s", class_id)
    try:
        async with httpx.AsyncClient(timeout=30, verify=False) as client:
            response = await client.post(
                SCHEDULE_API_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "TelegramScheduleBot/1.0",
                },
            )
            response.raise_for_status()
            data = response.json()
            logger.debug("Raw response for %s: %s", class_id, str(data)[:300])
            return parse_schedule_response(class_id, data)
    except Exception as e:
        logger.exception("Error fetching schedule for %s: %s", class_id, e)
    return []


async def fetch_all_schedules() -> list[dict]:
    """Fetch lịch học cho tất cả class_id, deduplicate theo event id."""
    import asyncio
    tasks = [fetch_schedule(cid) for cid in CLASS_IDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_events: list[dict] = []
    for cid, result in zip(CLASS_IDS, results):
        if isinstance(result, Exception):
            logger.error("Error fetching %s: %s", cid, result)
        else:
            all_events.extend(result)

    seen: set[str] = set()
    unique = []
    for e in all_events:
        if e["id"] not in seen:
            seen.add(e["id"])
            unique.append(e)
    return unique
