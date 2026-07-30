"""
database.py – Lưu lịch học và trạng thái đã thông báo vào SQLite.
"""
import sqlite3
import json
import os
import logging
from datetime import datetime
from config import DATABASE_PATH

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Tạo bảng nếu chưa tồn tại, tự động migrate nếu thiếu cột."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schedule_events (
                id              TEXT PRIMARY KEY,
                class_id        TEXT NOT NULL,
                subject         TEXT,
                teacher         TEXT,
                room            TEXT,
                session         TEXT,
                date            TEXT,
                start_time      TEXT,
                end_time        TEXT,
                link            TEXT,
                is_approximate  INTEGER DEFAULT 0,
                date_range_end  TEXT,
                time_raw        TEXT,
                raw_data        TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS notifications_sent (
                event_id        TEXT NOT NULL,
                notif_type      TEXT NOT NULL,
                sent_at         TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (event_id, notif_type)
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                synced_at       TEXT DEFAULT (datetime('now')),
                class_id        TEXT,
                events_found    INTEGER,
                events_new      INTEGER,
                events_changed  INTEGER,
                status          TEXT
            );

            CREATE TABLE IF NOT EXISTS bot_users (
                chat_id         TEXT PRIMARY KEY,
                username        TEXT,
                is_admin        INTEGER DEFAULT 0,
                subscribed      INTEGER DEFAULT 1,
                added_at        TEXT DEFAULT (datetime('now'))
            );
        """)
        # Auto-migrate: thêm cột mới nếu DB cũ chưa có
        _migrate(conn)
    logger.info("Database initialized at %s", DATABASE_PATH)


def _migrate(conn: sqlite3.Connection) -> None:
    """Thêm các cột mới vào bảng nếu chưa tồn tại (backward-compatible)."""
    new_columns = [
        ("schedule_events", "link",           "TEXT DEFAULT ''"),
        ("schedule_events", "is_approximate", "INTEGER DEFAULT 0"),
        ("schedule_events", "date_range_end",  "TEXT"),
        ("schedule_events", "time_raw",        "TEXT"),
        ("bot_users", "is_admin", "INTEGER DEFAULT 0"),
        ("bot_users", "subscribed", "INTEGER DEFAULT 1"),
    ]
    for table, col, col_def in new_columns:
        existing = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            logger.info("Migrated DB: added column %s.%s", table, col)


# ── Events ────────────────────────────────────────────────────────────────────

def upsert_event(event: dict) -> tuple[bool, dict]:
    """
    Upsert một sự kiện. Trả về (is_new, changes_dict).
    changes_dict: {field: (old_val, new_val)} – rỗng nếu không có thay đổi.
    So sánh các trường quan trọng: subject, teacher, room, date, start_time, link.
    """
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM schedule_events WHERE id = ?", (event["id"],)
        ).fetchone()
        if existing is None:
            existing = _find_legacy_event(conn, event)

        now = datetime.now().isoformat()

        if existing is None:
            conn.execute(
                """INSERT INTO schedule_events
                   (id, class_id, subject, teacher, room, session, date,
                    start_time, end_time, link, is_approximate, date_range_end,
                    time_raw, raw_data, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event["id"], event["class_id"],
                    event.get("subject"), event.get("teacher"),
                    event.get("room"), event.get("session"),
                    event.get("date"), event.get("start_time"), event.get("end_time"),
                    event.get("link", ""),
                    int(event.get("is_approximate", False)),
                    event.get("date_range_end"),
                    event.get("time_raw", ""),
                    json.dumps(event.get("raw_data", {}), ensure_ascii=False),
                    now,
                ),
            )
            return True, {}

        # ── Kiểm tra thay đổi trên các trường quan trọng ─────────────────────
        changes = _detect_change(existing, event)

        if changes:
            conn.execute(
                """UPDATE schedule_events
                   SET subject=?, teacher=?, room=?, session=?, date=?,
                       start_time=?, end_time=?, link=?, is_approximate=?,
                       date_range_end=?, time_raw=?, raw_data=?, updated_at=?
                   WHERE id=?""",
                (
                    event.get("subject"), event.get("teacher"),
                    event.get("room"), event.get("session"),
                    event.get("date"), event.get("start_time"), event.get("end_time"),
                    event.get("link", ""),
                    int(event.get("is_approximate", False)),
                    event.get("date_range_end"),
                    event.get("time_raw", ""),
                    json.dumps(event.get("raw_data", {}), ensure_ascii=False),
                    now,
                    event["id"],
                ),
            )
            # Nếu ngày hoặc buổi thay đổi → xóa reminder cũ để gửi lại
            if "date" in changes or "session" in changes:
                conn.execute(
                    "DELETE FROM notifications_sent WHERE event_id=? AND notif_type='reminder'",
                    (event["id"],),
                )
                logger.info(
                    "Reset reminder cho event %s do lịch đổi ngày/buổi: %s",
                    event["id"],
                    {k: v for k, v in changes.items() if k in ("date", "session")},
                )
        return False, changes


def _find_legacy_event(conn: sqlite3.Connection, event: dict):
    """Tìm event đã lưu bằng ID cũ, rồi migrate sang ID ổn định mới."""
    for legacy_id in event.get("legacy_ids") or []:
        if legacy_id == event["id"]:
            continue
        existing = conn.execute(
            "SELECT * FROM schedule_events WHERE id = ?", (legacy_id,)
        ).fetchone()
        if not existing:
            continue

        conflict = conn.execute(
            "SELECT 1 FROM schedule_events WHERE id = ?", (event["id"],)
        ).fetchone()
        if conflict:
            return None

        conn.execute(
            "UPDATE schedule_events SET id = ?, updated_at = ? WHERE id = ?",
            (event["id"], datetime.now().isoformat(), legacy_id),
        )
        conn.execute(
            "UPDATE notifications_sent SET event_id = ? WHERE event_id = ?",
            (event["id"], legacy_id),
        )
        logger.info("Migrated event id %s -> %s", legacy_id, event["id"])
        return conn.execute(
            "SELECT * FROM schedule_events WHERE id = ?", (event["id"],)
        ).fetchone()
    return None


def _detect_change(existing, new: dict) -> dict:
    """
    So sánh các trường quan trọng giữa bản ghi cũ và mới.
    Trả về dict {field: (old_val, new_val)} cho các trường thay đổi (rỗng = không đổi).
    """
    WATCH_FIELDS = ["subject", "teacher", "room", "session", "date", "start_time", "end_time", "link"]
    changes: dict[str, tuple] = {}
    for field in WATCH_FIELDS:
        old_val = str(existing[field] or "").strip()
        new_val = str(new.get(field) or "").strip()
        if old_val != new_val:
            logger.info(
                "Change detected in event %s field '%s': %r → %r",
                existing["id"], field, old_val, new_val
            )
            changes[field] = (old_val, new_val)
    return changes


def get_upcoming_events(days: int = 7, include_approximate: bool = False) -> list[dict]:
    with get_connection() as conn:
        approx_filter = "" if include_approximate else "AND is_approximate = 0"
        rows = conn.execute(
            f"""SELECT * FROM schedule_events
               WHERE date >= date('now', 'localtime')
                 AND date <= date('now', '+{days} days', 'localtime')
                 {approx_filter}
               ORDER BY date, start_time""",
        ).fetchall()
    return [dict(r) for r in rows]


def get_events_for_date(date_str: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule_events WHERE date = ? AND is_approximate = 0 ORDER BY start_time",
            (date_str,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_events(include_approximate: bool = True) -> list[dict]:
    with get_connection() as conn:
        approx_filter = "" if include_approximate else "WHERE is_approximate = 0"
        rows = conn.execute(
            f"SELECT * FROM schedule_events {approx_filter} ORDER BY date, start_time"
        ).fetchall()
    return [dict(r) for r in rows]


def get_events_for_class(class_id: str, include_approximate: bool = True) -> list[dict]:
    """Lấy tất cả events của 1 class_id."""
    with get_connection() as conn:
        if include_approximate:
            rows = conn.execute(
                "SELECT * FROM schedule_events WHERE class_id = ? ORDER BY date, start_time",
                (class_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM schedule_events WHERE class_id = ? AND is_approximate = 0 ORDER BY date, start_time",
                (class_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_event_ids_for_class(class_id: str) -> set[str]:
    """Lấy tất cả event IDs đang có trong DB cho một class."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM schedule_events WHERE class_id = ?", (class_id,)
        ).fetchall()
    return {row["id"] for row in rows}


def delete_stale_events_for_class(class_id: str, current_ids: set[str]) -> int:
    """
    Xóa các events trong DB thuộc class_id nhưng không còn trong current_ids.
    Trả về số events đã xóa.
    Dùng cho reconcile lịch thủ công: nếu xóa 1 mục khỏi JSON → tự xóa khỏi DB.
    """
    existing = get_event_ids_for_class(class_id)
    stale = existing - current_ids
    if not stale:
        return 0
    with get_connection() as conn:
        for eid in stale:
            conn.execute("DELETE FROM schedule_events WHERE id = ?", (eid,))
            conn.execute(
                "DELETE FROM notifications_sent WHERE event_id = ?", (eid,)
            )
        conn.commit()
    logger.info("Deleted %d stale events for class_id=%s", len(stale), class_id)
    return len(stale)


# ── Notifications ─────────────────────────────────────────────────────────────

def is_notification_sent(event_id: str, notif_type: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM notifications_sent WHERE event_id=? AND notif_type=?",
            (event_id, notif_type),
        ).fetchone()
    return row is not None


def mark_notification_sent(event_id: str, notif_type: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO notifications_sent (event_id, notif_type) VALUES (?,?)",
            (event_id, notif_type),
        )


# ── Sync log ──────────────────────────────────────────────────────────────────

def log_sync(class_id: str, events_found: int, events_new: int,
             events_changed: int, status: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO sync_log
               (class_id, events_found, events_new, events_changed, status)
               VALUES (?,?,?,?,?)""",
            (class_id, events_found, events_new, events_changed, status),
        )


def get_last_sync() -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


# ── Users ─────────────────────────────────────────────────────────────────────

def upsert_user(chat_id: str, username: str = "", is_admin: bool = False) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO bot_users (chat_id, username, is_admin) VALUES (?,?,?)
               ON CONFLICT(chat_id) DO UPDATE SET
                   username=excluded.username,
                   is_admin=CASE
                       WHEN bot_users.is_admin = 1 THEN 1
                       ELSE excluded.is_admin
                   END""",
            (str(chat_id), username, int(is_admin)),
        )


def has_owner() -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM bot_users WHERE is_admin = 1 LIMIT 1"
        ).fetchone()
    return row is not None


def is_owner(chat_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM bot_users WHERE chat_id = ? AND is_admin = 1",
            (str(chat_id),),
        ).fetchone()
    return row is not None


def claim_owner(chat_id: str, username: str = "") -> bool:
    with get_connection() as conn:
        existing_owner = conn.execute(
            "SELECT chat_id FROM bot_users WHERE is_admin = 1 LIMIT 1"
        ).fetchone()
        if existing_owner and str(existing_owner["chat_id"]) != str(chat_id):
            return False
        conn.execute(
            """INSERT INTO bot_users (chat_id, username, is_admin, subscribed)
               VALUES (?, ?, 1, 1)
               ON CONFLICT(chat_id) DO UPDATE SET
                   username=excluded.username,
                   is_admin=1,
                   subscribed=1""",
            (str(chat_id), username),
        )
    return True


def set_owner(chat_id: str, username: str = "") -> None:
    """Set the single bot owner, replacing any owner claimed before."""
    with get_connection() as conn:
        conn.execute("UPDATE bot_users SET is_admin = 0")
        conn.execute(
            """INSERT INTO bot_users (chat_id, username, is_admin, subscribed)
               VALUES (?, ?, 1, 1)
               ON CONFLICT(chat_id) DO UPDATE SET
                   username=excluded.username,
                   is_admin=1,
                   subscribed=1""",
            (str(chat_id), username),
        )


def get_subscribed_users() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM bot_users WHERE subscribed = 1 AND is_admin = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def set_user_subscription(chat_id: str, subscribed: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE bot_users SET subscribed=? WHERE chat_id=?",
            (int(subscribed), str(chat_id)),
        )
