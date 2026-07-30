"""
error_reporter.py – Gửi lỗi ERROR/CRITICAL lên Telegram khi xảy ra.

Tích hợp như một logging.Handler nên bắt được lỗi từ toàn bộ ứng dụng.
Rate-limited để tránh spam khi lỗi lặp lại nhiều lần.
"""
import asyncio
import hashlib
import logging
import time
import traceback
from datetime import datetime, timedelta, timezone
from html import escape

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Mỗi "dạng lỗi" (hash của message + module) chỉ gửi tối đa 1 lần / 5 phút
_RATE_LIMIT_SECONDS = 300
_last_sent: dict[str, float] = {}   # error_key → monotonic timestamp

# Lỗi mạng tạm thời → không cần alert
_SUPPRESS_PATTERNS = (
    "ConnectError",
    "TimeoutException",
    "TimedOut",
    "Timed out",           # python-telegram-bot string repr
    "Failed to send message",  # broadcast timeout trong sync_service
    "NetworkError",
    "Temporary failure in name resolution",
    "Connection refused",
    "EOF occurred in violation of protocol",
    "[Errno -3]",
    "[Errno 111]",
    "[Errno 104]",
)

MAX_MSG_LEN = 3500   # Telegram max 4096; để margin


def _should_suppress(text: str) -> bool:
    """Trả True nếu lỗi là lỗi mạng tạm thời không cần alert."""
    for pat in _SUPPRESS_PATTERNS:
        if pat in text:
            return True
    return False


def _error_key(record: logging.LogRecord) -> str:
    """Hash key để rate-limit dựa vào (module, message đầu 100 ký tự)."""
    raw = f"{record.name}:{record.getMessage()[:100]}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _is_rate_limited(key: str) -> bool:
    """Trả True nếu lỗi này vừa được gửi trong vòng RATE_LIMIT_SECONDS."""
    now = time.monotonic()
    last = _last_sent.get(key, 0.0)
    if now - last < _RATE_LIMIT_SECONDS:
        return True
    _last_sent[key] = now
    return False


def _format_alert(record: logging.LogRecord) -> str:
    """Tạo nội dung tin nhắn Telegram cho lỗi."""
    level_icon = "🔴" if record.levelno >= logging.CRITICAL else "🟠"
    level_name = record.levelname
    now_vn = datetime.now(VN_TZ).strftime("%d/%m %H:%M:%S")
    module = record.name
    message = escape(record.getMessage())

    lines = [
        f"{level_icon} <b>[{level_name}]</b> <code>{escape(module)}</code>",
        f"🕐 <i>{now_vn} (VN)</i>",
        f"",
        f"<b>Chi tiết:</b>",
        f"<pre>{message[:800]}</pre>",
    ]

    # Traceback nếu có
    if record.exc_info and record.exc_info[0] is not None:
        tb = "".join(traceback.format_exception(*record.exc_info))
        # Cắt traceback nếu quá dài
        if len(tb) > 1200:
            tb = "...(truncated)...\n" + tb[-1200:]
        lines.append(f"\n<b>Traceback:</b>\n<pre>{escape(tb)}</pre>")

    return "\n".join(lines)


class TelegramErrorHandler(logging.Handler):
    """
    logging.Handler gửi ERROR/CRITICAL lên Telegram.
    Phải được khởi tạo với bot và chat_id sau khi bot sẵn sàng.
    """

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self._bot = None
        self._chat_ids: list[int | str] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def configure(self, bot, chat_ids: list, loop: asyncio.AbstractEventLoop) -> None:
        """Gọi sau khi bot được khởi động để cung cấp bot instance và chat_ids."""
        self._bot = bot
        self._chat_ids = chat_ids
        self._loop = loop
        logger.info("TelegramErrorHandler configured for %d chat(s)", len(chat_ids))

    def emit(self, record: logging.LogRecord) -> None:
        """Được gọi mỗi khi có log ERROR hoặc CRITICAL."""
        if self._bot is None or not self._chat_ids:
            return  # Chưa configure → bỏ qua

        # Ngăn lỗi từ chính module này gây vòng lặp
        if record.name == __name__:
            return

        # Lỗi mạng tạm thời → skip
        full_text = record.getMessage()
        if record.exc_info:
            full_text += "".join(traceback.format_exception(*record.exc_info))
        if _should_suppress(full_text):
            return

        # Rate limiting
        key = _error_key(record)
        if _is_rate_limited(key):
            return

        msg = _format_alert(record)
        if len(msg) > MAX_MSG_LEN:
            msg = msg[:MAX_MSG_LEN] + "\n...<i>(cắt bớt)</i>"

        self._send_async(msg)

    def _send_async(self, msg: str) -> None:
        """Gửi non-blocking vào event loop đang chạy."""
        if self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send(msg), self._loop)
        except Exception:
            pass  # Tránh exception trong emit() gây vòng lặp

    async def _send(self, msg: str) -> None:
        for chat_id in self._chat_ids:
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=msg,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception as e:
                # Chỉ log WARNING, không raise để tránh vòng lặp
                logging.getLogger(__name__).warning(
                    "Không gửi được error alert tới %s: %s", chat_id, e
                )


# ── Singleton ─────────────────────────────────────────────────────────────────
_handler = TelegramErrorHandler()


def get_handler() -> TelegramErrorHandler:
    return _handler


def setup_error_reporting(bot, chat_ids: list, loop: asyncio.AbstractEventLoop) -> None:
    """
    Kích hoạt error reporting sau khi bot đã sẵn sàng.
    Thêm TelegramErrorHandler vào root logger để bắt lỗi từ toàn bộ app.
    """
    global _handler
    _handler.configure(bot, chat_ids, loop)

    root = logging.getLogger()
    # Tránh thêm 2 lần nếu gọi setup lại
    for h in root.handlers:
        if isinstance(h, TelegramErrorHandler):
            root.removeHandler(h)
    root.addHandler(_handler)
    logger.info("✅ Telegram error reporting enabled.")


def refresh_error_reporting(chat_ids: list) -> None:
    """Cập nhật danh sách chat_id nhận alert (gọi sau /dang_ky hoặc /huy)."""
    _handler._chat_ids = list(chat_ids)
    logger.debug("Error reporting refreshed: %d chat(s)", len(chat_ids))
