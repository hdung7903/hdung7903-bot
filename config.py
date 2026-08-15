import os
import re
from datetime import date

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> None:
        return None

load_dotenv()

def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_telegram_token() -> str:
    """Read bot token from the canonical env var, with common deploy aliases."""
    for key in ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN", "TELEGRAM_TOKEN"):
        value = _env(key)
        if value:
            return value
    return ""


def validate_telegram_token(token: str) -> tuple[bool, str]:
    if not token:
        return False, "TELEGRAM_BOT_TOKEN is missing or empty"
    lowered = token.lower()
    if lowered in {"your_bot_token_here", "change_me", "changeme", "xxx"}:
        return False, "TELEGRAM_BOT_TOKEN is still a placeholder"
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
        return False, "TELEGRAM_BOT_TOKEN does not look like a Telegram BotFather token"
    return True, "ok"


# ── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = _get_telegram_token()
# Optional safety gate. Leave empty to let the first /start claim the bot.
TELEGRAM_OWNER_USERNAME = _env("TELEGRAM_OWNER_USERNAME").lstrip("@")

# ── API trường ────────────────────────────────────────────────────────────────
SCHEDULE_API_URL = "https://bd.vinhuni.edu.vn/api/lay-lich-hoc"
CLASS_IDS = [
    cid.strip()
    for cid in os.getenv(
        "CLASS_IDS",
        "TA01.NVSPTH.QY01,TA01-NVSPGVTHCS.THPT-QY01",
    ).split(",")
    if cid.strip()
]

# ── Lịch học mặc định ────────────────────────────────────────────────────────
# Nếu API không trả về giờ cụ thể, dùng giờ mặc định này
DEFAULT_SESSION_TIMES = {
    "sang":   {"start": "08:00", "duration_hours": 2},   # Sáng  8:00 – 10:00
    "chieu":  {"start": "14:00", "duration_hours": 2},   # Chiều 14:00 – 16:00
    "toi":    {"start": "19:30", "duration_hours": 2},   # Tối   19:30 – 21:30
}

# ── Google Calendar ───────────────────────────────────────────────────────────
GOOGLE_CALENDAR_ENABLED    = os.getenv("GOOGLE_CALENDAR_ENABLED", "false").lower() == "true"
GOOGLE_CREDENTIALS_FILE    = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE          = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
GOOGLE_CREDENTIALS_JSON    = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
GOOGLE_TOKEN_JSON          = os.getenv("GOOGLE_TOKEN_JSON", "")
GOOGLE_AUTH_MODE           = os.getenv("GOOGLE_AUTH_MODE", "oauth").strip().lower()
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE", "/app/data/google_service_account.json"
)
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_CALENDAR_ID         = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_CALENDAR_SCOPES     = ["https://www.googleapis.com/auth/calendar"]
GOOGLE_ALLOW_LOCAL_OAUTH   = os.getenv("GOOGLE_ALLOW_LOCAL_OAUTH", "false").lower() == "true"

# ── Cron schedule ─────────────────────────────────────────────────────────────
# Giờ chạy đồng bộ lịch (UTC+7 → server dùng giờ địa phương nếu TZ=Asia/Ho_Chi_Minh)
SYNC_HOURS = [int(h) for h in os.getenv("SYNC_HOURS", "0,5,7,12,17").split(",")]

# Nhắc nhở trước bao nhiêu giờ (mặc định 24h = 1 ngày)
NOTIFY_BEFORE_HOURS = int(os.getenv("NOTIFY_BEFORE_HOURS", "24"))

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/schedule.db")

# ── Timezone ──────────────────────────────────────────────────────────────────
TIMEZONE = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ── World Cup 2026 ───────────────────────────────────────────────────────────
WC_ENABLED          = os.getenv("WC_ENABLED", "true").lower() == "true"
WC_API_BASE_URL     = os.getenv(
    "WC_API_BASE_URL",
    "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world",
)
WC_STANDINGS_URL    = os.getenv(
    "WC_STANDINGS_URL",
    "https://site.web.api.espn.com/apis/v2/sports/soccer/fifa.world/standings",
)
# FIFA API – trả về Goals và Bookings đầy đủ trong HomeTeam/AwayTeam
WC_FIFA_API_BASE    = os.getenv("WC_FIFA_API_BASE", "https://api.fifa.com/api/v3")
WC_FIFA_COMPETITION = os.getenv("WC_FIFA_COMPETITION", "17")    # World Cup
WC_FIFA_SEASON      = os.getenv("WC_FIFA_SEASON", "285023")     # 2026
WC_FIFA_STAGE       = os.getenv("WC_FIFA_STAGE", "289273")      # First Stage (group)
WC_START_DATE       = date(2026, 6, 11)
WC_END_DATE         = date(2026, 7, 19)
# Gửi thông báo lịch WC hàng ngày lúc mấy giờ (giờ VN)
WC_DAILY_NOTIFY_HOUR = int(os.getenv("WC_DAILY_NOTIFY_HOUR", "0"))
# Kiểm tra kết quả live bao nhiêu phút 1 lần trong ngày có trận (0 = tắt)
# Mặc định 3 phút để thông báo kết quả nhanh sau khi trận kết thúc
WC_LIVE_CHECK_MINUTES = int(os.getenv("WC_LIVE_CHECK_MINUTES", "3"))

# ── Lịch học thủ công (đọc từ file JSON) ───────────────────────────────────
MANUAL_SCHEDULE_FILE     = os.getenv("MANUAL_SCHEDULE_FILE", "manual_schedule.json")
MANUAL_SCHEDULE_CLASS_ID = os.getenv("MANUAL_SCHEDULE_CLASS_ID", "MANUAL-TA01-NVSPTH")
