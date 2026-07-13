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
import logging
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import httpx

from config import (
    CLASS_IDS, DEFAULT_SESSION_TIMES, SCHEDULE_API_URL,
    MANUAL_SCHEDULE_FILE, MANUAL_SCHEDULE_CLASS_ID,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hash_event_key(raw: str) -> str:
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _make_legacy_event_id(class_id: str, date: str, subject: str, session: str) -> str:
    """ID cũ, giữ để tìm/migrate event đã sync trước đây."""
    raw = f"{class_id}|{date}|{subject.strip()}|{session}"
    return _hash_event_key(raw)


def _make_event_id(class_id: str, subject: str, session: str, occurrence: int) -> str:
    """
    ID ổn định hơn cho cùng một buổi học.

    Không đưa ngày/link vào ID để khi lịch đổi ngày hoặc link Teams đổi thì DB và
    Google Calendar update event hiện có thay vì tạo event mới.
    """
    raw = f"{class_id}|{subject.strip()}|{session}|{occurrence}"
    return _hash_event_key(raw)


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


def _parse_approx_dates(text: str) -> list[str]:
    """
    Xử lý ngày dự kiến dạng 'Tháng 10/2026' hoặc 'Tháng 10,11 /2026'.
    Trả về danh sách ngày đầu tháng dạng YYYY-MM-DD.
    """
    m = re.search(r't[hh]áng\s+(\d{1,2}(?:\s*,\s*\d{1,2})*)\s*/\s*(\d{4})', text, re.IGNORECASE)
    if not m:
        approx_date = _parse_approx_date(text)
        return [approx_date] if approx_date else []

    year = int(m.group(2))
    dates: list[str] = []
    for raw_month in m.group(1).split(","):
        try:
            month = int(raw_month.strip())
            dates.append(datetime(year, month, 1).strftime("%Y-%m-%d"))
        except ValueError:
            logger.warning("Invalid approximate month in time field: %r", text)
    return dates


def _parse_date_range(text: str) -> Optional[list[str]]:
    """
    Xử lý khoảng thời gian có từ khóa "dến" hoặc "đến" hoặc "và".
    Trả về [start_date, end_date] hoặc None.
    VD: '30/11 đến 02/01/2027', '30/9 và 01/10/2026'
    """
    m = re.search(
        r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*(?:đến|den|và|va)\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)',
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

    year_m = re.search(r'(\d{4})', text)
    year = int(year_m.group(1)) if year_m else datetime.now().year

    start = _norm(m.group(1), year)
    end   = _norm(m.group(2), year)
    if start and end:
        return [start, end]
    return None


def _parse_hyphen_range(text: str) -> Optional[list[str]]:
    """
    Xử lý khoảng thời gian dạng 'Từ 15-20/07/2026' hoặc 'Từ 015-20/07/2026'.
    Dấu gạch ngang giữa ngày (không có từ 'đến').
    Trả về [start_date, end_date] hoặc None.
    """
    # Nhận regex: (từ\s+)? ngày1 - ngày2 / tháng / năm
    m = re.search(
        r'(?:từ\s+)?(\d{1,3})\s*-\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})',
        text, re.IGNORECASE
    )
    if not m:
        # Dạng không có năm trong pattern: 'Từ 05- 12 /10/2026'
        m = re.search(
            r'(?:từ\s+)?(\d{1,3})\s*-\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/?(\d{4})',
            text, re.IGNORECASE
        )
    if not m:
        return None

    try:
        day1  = int(m.group(1)) % 100   # Nhận typo "015" -> 15 bằng mod 100
        day2  = int(m.group(2))
        month = int(m.group(3))
        year  = int(m.group(4))
        start = datetime(year, month, day1).strftime("%Y-%m-%d")
        end   = datetime(year, month, day2).strftime("%Y-%m-%d")
        return [start, end]
    except (ValueError, IndexError):
        return None


def parse_time_field(time_str: str) -> list[dict]:
    """
    Parse field 'time' từ API response.

    Trả về list[dict] với keys: {session, date, is_approximate, date_range_end}

    Ví dụ:
      "Tối 08/05/2026 (Thứ 6)"          → [{session:toi, date:2026-05-08}]
      "Tối 22,23/05/2026 (Thứ 6, 7)"    → [{toi,2026-05-22}, {toi,2026-05-23}]
      "Tối 08,05//2026"                  → [{toi,2026-05-08}, {toi,2026-05-05}]  (// tự sửa)
      "Từ 015-20 /07/2026"              → range 2026-07-15 – 2026-07-20
      "30/9 và 01/10/2026"              → range 2026-09-30 – 2026-10-01
      "Tháng 10,11 /2026"              → [{sang,2026-10-01,approx}, {sang,2026-11-01,approx}]
    """
    if not time_str or not isinstance(time_str, str):
        return []

    # ── Tiền xử lý: chuẩn hoá một số typo phổ biến ───────────────────────────
    cleaned = time_str.strip()
    cleaned = re.sub(r'/{2,}', '/', cleaned)        # '//' → '/'
    cleaned = re.sub(r',\s*/', '/', cleaned)        # ',/' → '/'
    cleaned = re.sub(r'\s+', ' ', cleaned)          # nhiều space → 1

    results = []
    sessions = _detect_sessions(cleaned)

    # ── 1. Khoảng có dấu gạch ngang ("Từ 15-20/07/2026") ────────────────────
    hyphen_range = _parse_hyphen_range(cleaned)
    if hyphen_range:
        for session in sessions:
            results.append({
                "session": session,
                "date": hyphen_range[0],
                "is_approximate": False,
                "date_range_end": hyphen_range[1],
            })
        return results

    # ── 2. Khoảng có "đến" / "và" ("30/9 và 01/10/2026") ────────────────────
    date_range = _parse_date_range(cleaned)
    if date_range:
        for session in sessions:
            results.append({
                "session": session,
                "date": date_range[0],
                "is_approximate": False,
                "date_range_end": date_range[1],
            })
        return results

    # ── 3. Ngày cụ thể: "22,23/05/2026" hay "08/05/2026" ────────────────────
    # Pattern: số ngày (có thể nhiều, cách nhau dấu phẩy) / tháng / năm
    month_year_match = re.search(
        r'(\d{1,2}(?:\s*,\s*\d{1,2})*)\s*,?\s*/\s*(\d{1,2})\s*/?\s*(\d{4})',
        cleaned
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
                logger.warning("Invalid date: day=%d month=%d year=%d in %r", day, month, year, time_str)
        if results:
            return results

    # ── 3b. Ngày thiếu tháng: "08,05/2026" (do typo "08,05//2026") ────────────
    # Khi `//` đã được rút thành `/`, dẫn đến pattern DD,DD/YYYY (không có tháng rõ ràng)
    # Xử lý: dùng số cuối cùng trong dãy ngày làm tháng (dãy ngày bị cắt bớt 1 phần tử)
    # Guard: không áp dụng nếu có từ "tháng" vì sẽ conflict với "Tháng 10,11/2026"
    if not re.search(r't[hh][áa]ng', cleaned, re.IGNORECASE):
        days_year_match = re.search(
            r'(\d{1,2}(?:\s*,\s*\d{1,2})+)\s*/\s*(\d{4})(?!\d)',
            cleaned
        )
        if days_year_match:
            raw_days = [int(d.strip()) for d in days_year_match.group(1).split(",") if d.strip()]
            year     = int(days_year_match.group(2))
            # Số cuối cùng trong dãy = tháng, các số trước = ngày
            if len(raw_days) >= 2:
                month = raw_days[-1]
                days  = raw_days[:-1]
                logger.info("Recovered missing month from typo %r: days=%s month=%d year=%d",
                            time_str, days, month, year)
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
                        logger.warning("Invalid date (recovered): day=%d month=%d year=%d in %r",
                                       day, month, year, time_str)
                if results:
                    return results


    # ── 4. Ngày dự kiến: "Tháng 10/2026", "DK: tháng 10/2026" ──────────────
    approx_dates = _parse_approx_dates(cleaned)
    if approx_dates:
        for approx_date in approx_dates:
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
    occurrence_by_key: dict[tuple[str, str], int] = {}

    def _next_occurrence(subject: str, session: str) -> int:
        key = (subject.strip().lower(), session)
        occurrence_by_key[key] = occurrence_by_key.get(key, 0) + 1
        return occurrence_by_key[key]

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
            occurrence = _next_occurrence(subject, "sang")
            event_id = _make_event_id(class_id, subject, "sang", occurrence)
            legacy_id = _make_legacy_event_id(class_id, "unknown", subject, "sang")
            if event_id not in seen_ids:
                seen_ids.add(event_id)
                events.append({
                    "id": event_id,
                    "legacy_ids": [legacy_id],
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

            occurrence = _next_occurrence(subject, session)
            event_id = _make_event_id(class_id, subject, session, occurrence)
            legacy_id = _make_legacy_event_id(class_id, date or "unknown", subject, session)
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)

            events.append({
                "id": event_id,
                "legacy_ids": [legacy_id],
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
    """Gọi API và trả về danh sách events đã parse. Tự động retry 2 lần nếu lỗi mạng."""
    payload = {"class_id": class_id}
    logger.info("Fetching schedule for class_id=%s", class_id)
    last_err: Exception | None = None
    for attempt in range(3):  # tối đa 3 lần (lần 1 + 2 retry)
        if attempt > 0:
            wait = 5 * (2 ** (attempt - 1))  # 5s, 10s
            logger.info("Retry %d/%d sau %ds (class_id=%s)…", attempt, 2, wait, class_id)
            await asyncio.sleep(wait)
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
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            last_err = e
            logger.warning("Lỗi mạng lần %d khi fetch %s: %s", attempt + 1, class_id, e)
            continue  # retry
        except httpx.HTTPStatusError as e:
            logger.error("API lịch học HTTP %s cho %s: %s", e.response.status_code, class_id, e)
            break  # HTTP error → không retry
        except Exception as e:
            logger.exception("Lỗi không xác định khi fetch schedule cho %s: %s", class_id, e)
            break

    if last_err is not None:
        logger.error("Không kết nối được API lịch học sau 3 lần thử (class_id=%s): %s",
                     class_id, last_err)
    return []



async def fetch_all_schedules() -> list[dict]:
    """Fetch lịch học cho tất cả class_id (API + lịch thủ công JSON), deduplicate theo event id."""
    tasks = [fetch_schedule(cid) for cid in CLASS_IDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_events: list[dict] = []
    for cid, result in zip(CLASS_IDS, results):
        if isinstance(result, Exception):
            logger.error("Error fetching %s: %s", cid, result)
        else:
            all_events.extend(result)

    # Thêm lịch thủ công từ file JSON
    manual = fetch_manual_schedules()
    all_events.extend(manual)

    seen: set[str] = set()
    unique = []
    for e in all_events:
        if e["id"] not in seen:
            seen.add(e["id"])
            unique.append(e)
    return unique


def fetch_manual_schedules() -> list[dict]:
    """
    Đọc và parse lịch học từ file JSON thủ công.
    Tự động bỏ qua nếu file không tồn tại.
    Các cập nhật vào JSON sẽ được phản ánh ngay sau lần sync tiếp theo.
    """
    path = MANUAL_SCHEDULE_FILE
    if not os.path.isabs(path):
        # Đường dẫn tương đối → resolve từ thư mục chứa api_client.py
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, path)

    if not os.path.exists(path):
        logger.debug("Manual schedule file not found: %s (bỏ qua)", path)
        return []

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        events = parse_schedule_response(MANUAL_SCHEDULE_CLASS_ID, data)
        logger.info("Manual schedule: đọc %d events từ %s", len(events), path)
        return events
    except Exception as e:
        logger.error("Lỗi đọc manual_schedule.json: %s", e)
        return []
