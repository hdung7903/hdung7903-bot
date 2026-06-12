"""
wc_db.py – Lưu cache trận đấu WC để detect kết quả mới.
"""
import json
import logging
import sqlite3
from datetime import datetime

from config import DATABASE_PATH
from database import get_connection

logger = logging.getLogger(__name__)


def init_wc_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS wc_matches (
                id              INTEGER PRIMARY KEY,
                utc_date        TEXT,
                vn_date         TEXT,
                vn_time         TEXT,
                status          TEXT,
                stage           TEXT,
                grp             TEXT,
                matchday        INTEGER,
                home_team       TEXT,
                home_team_tla   TEXT,
                away_team       TEXT,
                away_team_tla   TEXT,
                home_score      INTEGER,
                away_score      INTEGER,
                ht_home         INTEGER,
                ht_away         INTEGER,
                winner          TEXT,
                goals_json      TEXT,
                yellow_cards_json TEXT,
                red_cards_json  TEXT,
                notified_result INTEGER DEFAULT 0,
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS wc_notifications (
                match_id        INTEGER NOT NULL,
                notif_type      TEXT NOT NULL,
                sent_at         TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (match_id, notif_type)
            );
        """)
        # Migration: thêm cột mới nếu chưa có (cho DB cũ)
        for col, col_type in [
            ("yellow_cards_json", "TEXT"),
            ("red_cards_json",    "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE wc_matches ADD COLUMN {col} {col_type}")
            except Exception:
                pass  # cột đã tồn tại
    logger.debug("WC tables initialized.")


def upsert_match(match: dict) -> tuple[bool, bool]:
    """
    Upsert match. Trả về (is_new, score_changed).
    """
    mid = match["id"]
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM wc_matches WHERE id = ?", (mid,)
        ).fetchone()

        now = datetime.now().isoformat()
        goals_json        = json.dumps(match.get("goals", []),        ensure_ascii=False)
        yellow_cards_json = json.dumps(match.get("yellow_cards", []), ensure_ascii=False)
        red_cards_json    = json.dumps(match.get("red_cards", []),    ensure_ascii=False)

        if existing is None:
            conn.execute(
                """INSERT INTO wc_matches
                   (id, utc_date, vn_date, vn_time, status, stage, grp, matchday,
                    home_team, home_team_tla, away_team, away_team_tla,
                    home_score, away_score, ht_home, ht_away, winner,
                    goals_json, yellow_cards_json, red_cards_json, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    mid, match["utc_date"], match["vn_date"], match["vn_time"],
                    match["status"], match["stage"], match["group"], match["matchday"],
                    match["home_team"], match["home_team_tla"],
                    match["away_team"], match["away_team_tla"],
                    match["home_score"], match["away_score"],
                    match["ht_home"], match["ht_away"],
                    match["winner"], goals_json, yellow_cards_json, red_cards_json, now,
                ),
            )
            return True, False

        # Phát hiện thay đổi tỉ số
        old_status = existing["status"]
        new_status = match["status"]
        old_home   = existing["home_score"]
        old_away   = existing["away_score"]
        new_home   = match["home_score"]
        new_away   = match["away_score"]

        score_changed = (
            old_status != new_status or
            old_home != new_home or
            old_away != new_away
        )

        if score_changed:
            conn.execute(
                """UPDATE wc_matches SET
                   status=?, home_score=?, away_score=?, ht_home=?, ht_away=?,
                   winner=?, goals_json=?, yellow_cards_json=?, red_cards_json=?, updated_at=?
                   WHERE id=?""",
                (
                    new_status, new_home, new_away,
                    match["ht_home"], match["ht_away"],
                    match["winner"], goals_json, yellow_cards_json, red_cards_json, now,
                    mid,
                ),
            )

        return False, score_changed


def get_matches_by_date(vn_date: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM wc_matches WHERE vn_date = ? ORDER BY vn_time",
            (vn_date,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_matches_by_team(team_search: str) -> list[dict]:
    s = f"%{team_search.lower()}%"
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM wc_matches
               WHERE lower(home_team) LIKE ? OR lower(away_team) LIKE ?
               ORDER BY vn_date, vn_time""",
            (s, s),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_finished_matches_date(vn_date: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM wc_matches WHERE vn_date = ? AND status = 'FINISHED' ORDER BY vn_time",
            (vn_date,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def is_wc_notified(match_id: int, notif_type: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM wc_notifications WHERE match_id=? AND notif_type=?",
            (match_id, notif_type),
        ).fetchone()
    return row is not None


def mark_wc_notified(match_id: int, notif_type: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO wc_notifications (match_id, notif_type) VALUES (?,?)",
            (match_id, notif_type),
        )


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["goals"] = json.loads(d.get("goals_json") or "[]")
    except Exception:
        d["goals"] = []
    try:
        d["yellow_cards"] = json.loads(d.get("yellow_cards_json") or "[]")
    except Exception:
        d["yellow_cards"] = []
    try:
        d["red_cards"] = json.loads(d.get("red_cards_json") or "[]")
    except Exception:
        d["red_cards"] = []
    return d
