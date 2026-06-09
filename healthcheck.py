"""
Container healthcheck for the Telegram bot.
"""
import os
import sqlite3
import sys

from calendar_sync import get_gcal_status
from config import (
    DATABASE_PATH,
    GOOGLE_CALENDAR_ENABLED,
    TELEGRAM_BOT_TOKEN,
    validate_telegram_token,
)


def fail(message: str) -> None:
    print(f"healthcheck failed: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    token_ok, token_message = validate_telegram_token(TELEGRAM_BOT_TOKEN)
    if not token_ok:
        fail(token_message)

    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    try:
        with sqlite3.connect(DATABASE_PATH) as conn:
            conn.execute("SELECT 1")
    except Exception as e:
        fail(f"database unavailable: {e}")

    if GOOGLE_CALENDAR_ENABLED:
        status = get_gcal_status(check_service=False)
        if not status["available"]:
            fail(f"google calendar unavailable: {status['reason']}")

    print("ok")


if __name__ == "__main__":
    main()
