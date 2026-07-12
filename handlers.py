"""
handlers.py – Tất cả Telegram command handlers.
"""
import logging
import asyncio
import re
from functools import wraps
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

import database as db
from config import CLASS_IDS, TELEGRAM_OWNER_USERNAME, WC_ENABLED
from notifier import build_schedule_message, build_sync_report
from error_reporter import refresh_error_reporting

logger = logging.getLogger(__name__)

MAX_TELEGRAM_MESSAGE = 3900
HANDLER_TIMEOUT_SECONDS = 25
QR_MESSAGE_TTL_SECONDS = 5 * 60

# ── Helpers ───────────────────────────────────────────────────────────────────

PRIVATE_BOT_MESSAGE = (
    "Bot này đang chạy ở chế độ cá nhân và không mở quyền sử dụng công khai."
)

QR_BANKS = {
    "vcb": {
        "name": "Vietcombank",
        "code": "VCB",
        "account": "1014937124",
        "aliases": {"vietcombank", "vcb"},
    },
    "tech": {
        "name": "Techcombank",
        "code": "TCB",
        "account": "19072571890013",
        "aliases": {"techcombank", "tech", "tcb"},
    },
    "mb": {
        "name": "MB Bank",
        "code": "MB",
        "account": "00134070903",
        "aliases": {"mbbank", "mb"},
    },
}


def _username(update: Update) -> str:
    user = update.effective_user
    return (user.username or "").lstrip("@") if user else ""


def _display_name(update: Update) -> str:
    user = update.effective_user
    if not user:
        return ""
    return user.username or user.full_name or ""


def _register_user(update: Update, is_owner: bool = False) -> None:
    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    db.upsert_user(chat_id, _display_name(update), is_admin=is_owner)


def _can_claim_owner(update: Update) -> bool:
    if not TELEGRAM_OWNER_USERNAME:
        return True
    return _username(update).lower() == TELEGRAM_OWNER_USERNAME.lower()


async def _deny(update: Update) -> None:
    if update.callback_query:
        await update.callback_query.answer(PRIVATE_BOT_MESSAGE, show_alert=True)
    elif update.message:
        await update.message.reply_text(PRIVATE_BOT_MESSAGE)


def owner_required(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        if not db.is_owner(chat_id):
            logger.warning(
                "Rejected command from unauthorized user chat_id=%s username=%s",
                chat_id,
                _username(update) or "-",
            )
            await _deny(update)
            return
        _register_user(update, is_owner=True)
        await _notify_if_update_was_delayed(update, context)
        try:
            return await asyncio.wait_for(
                func(update, context),
                timeout=HANDLER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.exception("Command timed out: %s", update.effective_message.text if update.effective_message else "-")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "Bot đang xử lý quá lâu hoặc service bên ngoài phản hồi chậm. Thử lại sau vài giây."
                )

    return wrapper


async def _notify_if_update_was_delayed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    started_at = context.application.bot_data.get("started_at")
    if not message or not started_at or context.user_data.get("delayed_update_notified"):
        return

    message_date = message.date
    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)

    if message_date < started_at - timedelta(seconds=5):
        context.user_data["delayed_update_notified"] = True
        await message.reply_text(
            "Bot vừa khởi động lại sau deploy/offline nên phản hồi hơi trễ. Mình đang xử lý lệnh của bạn ngay bây giờ."
        )


async def _reply_html_chunks(update: Update, text: str) -> None:
    """Send long HTML safely without splitting in the middle of a tag line."""
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > MAX_TELEGRAM_MESSAGE and current:
            await update.message.reply_text(current, parse_mode="HTML")
            current = ""
        current += line
    if current:
        await update.message.reply_text(current, parse_mode="HTML")


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if _can_claim_owner(update):
        db.set_owner(chat_id, _display_name(update))
        logger.info(
            "Owner verified from TELEGRAM_OWNER_USERNAME: chat_id=%s username=%s",
            chat_id,
            _username(update) or "-",
        )
    elif not db.is_owner(chat_id):
        logger.warning(
            "Rejected /start from unauthorized user chat_id=%s username=%s owner_username=%s",
            chat_id,
            _username(update) or "-",
            TELEGRAM_OWNER_USERNAME or "-",
        )
        await _deny(update)
        return

    _register_user(update, is_owner=True)
    await _notify_if_update_was_delayed(update, context)

    name = update.effective_user.first_name or "bạn"
    wc_commands = ""
    if WC_ENABLED:
        wc_commands = (
            "\n\n"
            "<b>⚽ World Cup 2026:</b>\n"
            "/wc – Lịch trận hôm nay\n"
            "/wc live – Trận đang diễn ra\n"
            "/wc ket_qua – Kết quả hôm nay\n"
            "/wc 12-06 – Lịch theo ngày Việt Nam\n"
            "/wc bang – Bảng xếp hạng\n"
            "/wchelp – Trợ giúp World Cup"
        )
    text = (
        f"👋 Xin chào <b>{name}</b>!\n\n"
        "🤖 Đây là <b>bot cá nhân</b> của bạn.\n"
        "Bot tự động đồng bộ lịch học, nhắc lịch và đã sẵn sàng để tích hợp thêm service sau này.\n\n"
        "<b>📋 Các lệnh có sẵn:</b>\n"
        "/lich – Xem lịch học 7 ngày tới\n"
        "/lich_thang – Xem lịch học tháng này\n"
        "/hom_nay – Xem lịch học hôm nay\n"
        "/ngay_mai – Xem lịch học ngày mai\n"
        "/sync – Đồng bộ lịch ngay bây giờ\n"
        "/status – Xem trạng thái bot\n"
        "/gcal_status – Kiểm tra Google Calendar\n"
        "/dang_ky – Đăng ký nhận thông báo\n"
        "/huy – Hủy đăng ký thông báo\n"
        "/qrbank – QR chuyển khoản ngân hàng\n"
        "/qrzalo – QR kết bạn Zalo\n"
        "/qrfacebook – QR Facebook profile\n"
        "/qrgithub – QR GitHub profile\n"
        "/help – Trợ giúp"
        f"{wc_commands}\n\n"
        f"📚 Đang theo dõi lớp: <code>{', '.join(CLASS_IDS)}</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


@owner_required
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


@owner_required
async def cmd_lich(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loading = await update.message.reply_text("⏳ Đang lấy lịch học...", parse_mode="HTML")
    events = db.get_upcoming_events(days=7)
    msg = build_schedule_message(events, "📅 Lịch học 7 ngày tới")
    try:
        await loading.delete()
    except Exception:
        pass
    await update.message.reply_text(msg, parse_mode="HTML")


@owner_required
async def cmd_lich_thang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loading = await update.message.reply_text("⏳ Đang lấy lịch học...", parse_mode="HTML")
    events = db.get_upcoming_events(days=31)
    msg = build_schedule_message(events, "📅 Lịch học tháng này")
    try:
        await loading.delete()
    except Exception:
        pass
    await _reply_html_chunks(update, msg)


@owner_required
async def cmd_hom_nay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    events = db.get_events_for_date(today)
    msg = build_schedule_message(events, "📅 Lịch học hôm nay")
    await update.message.reply_text(msg, parse_mode="HTML")


@owner_required
async def cmd_ngay_mai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    events = db.get_events_for_date(tomorrow)
    msg = build_schedule_message(events, "📅 Lịch học ngày mai")
    await update.message.reply_text(msg, parse_mode="HTML")


@owner_required
async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loading = await update.message.reply_text("🔄 Đang đồng bộ lịch học...", parse_mode="HTML")
    from sync_service import run_sync
    result = await run_sync(bot=context.bot, notify_changes=False)
    msg = build_sync_report(result["new"], result["changed"], result["total"])
    try:
        await loading.delete()
    except Exception:
        pass
    await update.message.reply_text(msg, parse_mode="HTML")


@owner_required
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    last_sync = db.get_last_sync()
    users = db.get_subscribed_users()
    total_events = len(db.get_all_events())
    upcoming = len(db.get_upcoming_events(days=7))

    sync_info = "Chưa đồng bộ lần nào"
    if last_sync:
        sync_info = f"{last_sync['synced_at']} (tìm thấy {last_sync['events_found']} buổi)"

    text = (
        "📊 <b>Trạng thái Bot</b>\n\n"
        f"👥 Người dùng đăng ký: <b>{len(users)}</b>\n"
        f"📚 Tổng buổi học trong DB: <b>{total_events}</b>\n"
        f"📅 Buổi học 7 ngày tới: <b>{upcoming}</b>\n"
        f"🔄 Lần đồng bộ cuối: <b>{sync_info}</b>\n"
        f"⏰ Lịch đồng bộ: <b>0h, 7h, 12h, 17h</b> hàng ngày\n"
        f"🔔 Nhắc nhở: <b>24h trước lịch học</b>\n"
        f"📚 Lớp đang theo dõi:\n"
        + "\n".join(f"  • <code>{cid}</code>" for cid in CLASS_IDS)
    )
    await update.message.reply_text(text, parse_mode="HTML")


@owner_required
async def cmd_gcal_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from calendar_sync import get_gcal_status

    status = get_gcal_status(check_service=True)
    enabled = "bật" if status["enabled"] else "tắt"
    credentials = "có" if status["credentials_exists"] else "thiếu"
    token = "có" if status["token_exists"] else "thiếu"
    available = "có vẻ sẵn sàng" if status["available"] else "chưa sẵn sàng"

    text = (
        "📅 <b>Google Calendar Status</b>\n\n"
        f"Enabled: <b>{enabled}</b>\n"
        f"Calendar ID: <code>{status['calendar_id']}</code>\n"
        f"Credentials: <b>{credentials}</b> <code>{status['credentials_file']}</code>\n"
        f"Token: <b>{token}</b> <code>{status['token_file']}</code>\n"
        f"Local OAuth: <b>{status['allow_local_oauth']}</b>\n"
        f"State: <b>{available}</b>\n"
        f"Reason: <code>{status['reason']}</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


@owner_required
async def cmd_dang_ky(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db.set_user_subscription(chat_id, True)
    # Cập nhật danh sách nhận error alert
    refresh_error_reporting([u["chat_id"] for u in db.get_subscribed_users()])
    await update.message.reply_text(
        "✅ Bạn đã <b>đăng ký</b> nhận thông báo lịch học!\n"
        "Bot sẽ nhắc nhở bạn trước 24h khi có lịch học.",
        parse_mode="HTML",
    )


@owner_required
async def cmd_huy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db.set_user_subscription(chat_id, False)
    # Cập nhật danh sách nhận error alert
    refresh_error_reporting([u["chat_id"] for u in db.get_subscribed_users()])
    await update.message.reply_text(
        "🔕 Bạn đã <b>hủy đăng ký</b> nhận thông báo.\n"
        "Dùng /dang_ky để đăng ký lại.",
        parse_mode="HTML",
    )


def _find_qr_bank(raw: str) -> dict | None:
    keys = [part for part in re.split(r"[\s,;/]+", raw.strip().lower().replace("@", "")) if part]
    for bank in QR_BANKS.values():
        if any(key in bank["aliases"] for key in keys):
            return bank
    return None


def _find_qr_bank_key(bank: dict) -> str:
    for key, item in QR_BANKS.items():
        if item is bank:
            return key
    return ""


def _parse_qr_amount(raw: str) -> int | None:
    normalized = (raw or "").strip().lower()
    unit_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(k|nghìn|ngan|tr|triệu|trieu)", normalized)
    if unit_match:
        number = float(unit_match.group(1).replace(",", "."))
        unit = unit_match.group(2)
        multiplier = 1_000_000 if unit in {"tr", "triệu", "trieu"} else 1_000
        amount = int(number * multiplier)
        return amount if amount >= 2000 else None

    cleaned = re.sub(r"[^\d]", "", normalized)
    if not cleaned:
        return None
    amount = int(cleaned)
    return amount if amount >= 2000 else None


def _extract_qr_amount(args: list[str]) -> int | None:
    for arg in args:
        amount = _parse_qr_amount(arg)
        if amount is not None:
            return amount
    return None


def _has_amount_arg(args: list[str]) -> bool:
    return any(re.search(r"\d", arg or "") for arg in args)


def _format_vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "đ"


def _qr_url(bank: dict, amount: int | None = None) -> str:
    url = f"https://img.vietqr.io/image/{bank['code']}-{bank['account']}-compact2.png"
    if amount is not None:
        url += f"?amount={amount}"
    return url


async def _delete_message_later(message, seconds: int) -> None:
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except Exception as e:
        logger.warning("Could not delete expiring QR message: %s", e)


async def _send_qr_bank(update: Update, bank: dict, amount: int | None = None) -> None:
    amount_line = (
        f"Số tiền: <b>{_format_vnd(amount)}</b>"
        if amount is not None
        else "Số tiền: tự nhập khi chuyển khoản"
    )
    caption = (
        f"🏦 <b>{bank['name']}</b>\n"
        f"STK: <code>{bank['account']}</code>\n"
        f"{amount_line}\n\n"
        "Quét QR để chuyển khoản.\n"
        "QR này sẽ tự xóa sau 5 phút."
    )
    if update.callback_query:
        await update.callback_query.answer()
        sent = await update.callback_query.message.reply_photo(
            photo=_qr_url(bank, amount),
            caption=caption,
            parse_mode="HTML",
        )
    else:
        sent = await update.message.reply_photo(
            photo=_qr_url(bank, amount),
            caption=caption,
            parse_mode="HTML",
        )
    asyncio.create_task(_delete_message_later(sent, QR_MESSAGE_TTL_SECONDS))


async def _show_qr_amount_options(update: Update, bank: dict) -> None:
    key = _find_qr_bank_key(bank)
    keyboard = [
        [InlineKeyboardButton("Nhập số tiền", callback_data=f"qrbank:amount:{key}")],
        [InlineKeyboardButton("Lấy QR không số tiền", callback_data=f"qrbank:noamount:{key}")],
    ]
    text = (
        f"Đã chọn <b>{bank['name']}</b>.\n"
        "Bạn muốn tạo QR với số tiền cụ thể hay lấy QR để tự nhập số tiền?"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


@owner_required
async def cmd_qrbank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        bank = _find_qr_bank(" ".join(context.args))
        if bank:
            amount = _extract_qr_amount(context.args)
            if amount is not None:
                await _send_qr_bank(update, bank, amount)
            elif _has_amount_arg(context.args):
                await update.message.reply_text(
                    "Số tiền không hợp lệ. Số tiền chuyển khoản tối thiểu là 2.000đ.",
                )
            else:
                await _show_qr_amount_options(update, bank)
            return
        await update.message.reply_text(
            "Không tìm thấy ngân hàng. Dùng: /qrbank vcb, /qrbank tech hoặc /qrbank mb. Có thể thêm số tiền, ví dụ /qrbank vcb 50000.",
            parse_mode="HTML",
        )
        return

    keyboard = [
        [InlineKeyboardButton("Vietcombank", callback_data="qrbank:select:vcb")],
        [InlineKeyboardButton("Techcombank", callback_data="qrbank:select:tech")],
        [InlineKeyboardButton("MB Bank", callback_data="qrbank:select:mb")],
    ]
    await update.message.reply_text(
        "Chọn ngân hàng để lấy QR chuyển khoản:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@owner_required
async def cb_qrbank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = update.callback_query.data or ""
    parts = data.split(":")
    action = parts[1] if len(parts) >= 3 else "select"
    key = parts[2] if len(parts) >= 3 else (parts[1] if len(parts) >= 2 else "")
    bank = QR_BANKS.get(key)
    if not bank:
        await update.callback_query.answer("Ngân hàng không hợp lệ.", show_alert=True)
        return

    if action == "amount":
        context.user_data["qrbank_pending_bank"] = key
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "Nhập số tiền cần chuyển khoản, tối thiểu 2.000đ. Ví dụ: 50000",
        )
        return

    if action == "noamount":
        context.user_data.pop("qrbank_pending_bank", None)
        await _send_qr_bank(update, bank)
        return

    await _show_qr_amount_options(update, bank)


async def _handle_pending_qr_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    key = context.user_data.get("qrbank_pending_bank")
    if not key:
        return False

    bank = QR_BANKS.get(key)
    amount = _parse_qr_amount(update.message.text or "")
    if not bank:
        context.user_data.pop("qrbank_pending_bank", None)
        await update.message.reply_text("Phiên tạo QR đã hết hạn. Dùng lại /qrbank.")
        return True
    if amount is None:
        await update.message.reply_text(
            "Số tiền không hợp lệ. Nhập số từ 2.000đ trở lên, hoặc dùng /qrbank để chọn lại."
        )
        return True

    context.user_data.pop("qrbank_pending_bank", None)
    await _send_qr_bank(update, bank, amount)
    return True


@owner_required
async def cmd_qrzalo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    phone = "0395081725"
    caption = (
        "📱 <b>Kết bạn Zalo</b>\n\n"
        f"SĐT: <code>{phone}</code>\n\n"
        "Quét QR hoặc tìm bằng số điện thoại để kết bạn Zalo."
    )
    # Zalo QR code URL - using a QR generator for the phone number
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={phone}"
    await update.message.reply_photo(
        photo=qr_url,
        caption=caption,
        parse_mode="HTML",
    )


@owner_required
async def cmd_qrfacebook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    fb_url = "https://www.facebook.com/hdung7903"
    caption = (
        "📘 <b>Facebook Profile</b>\n\n"
        "Quét QR hoặc nhấn link để truy cập Facebook."
    )
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={fb_url}"
    await update.message.reply_photo(
        photo=qr_url,
        caption=caption,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Mở Facebook", url=fb_url)]
        ]),
    )


@owner_required
async def cmd_qrgithub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    gh_url = "https://github.com/hdung7903"
    caption = (
        "💻 <b>GitHub Profile</b>\n\n"
        "Quét QR hoặc nhấn link để truy cập GitHub."
    )
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={gh_url}"
    await update.message.reply_photo(
        photo=qr_url,
        caption=caption,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Mở GitHub", url=gh_url)]
        ]),
    )


@owner_required
async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "❓ Lệnh không hợp lệ. Dùng /help để xem danh sách lệnh.",
        parse_mode="HTML",
    )


@owner_required
async def cmd_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _handle_pending_qr_amount(update, context):
        return
    await update.message.reply_text(
        "Mình đã nhận tin nhắn. Dùng /help để xem các lệnh đang hỗ trợ.",
        parse_mode="HTML",
    )


# ── Register handlers ─────────────────────────────────────────────────────────

def register_handlers(application) -> None:
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("lich", cmd_lich))
    application.add_handler(CommandHandler("lich_thang", cmd_lich_thang))
    application.add_handler(CommandHandler("hom_nay", cmd_hom_nay))
    application.add_handler(CommandHandler("ngay_mai", cmd_ngay_mai))
    application.add_handler(CommandHandler("sync", cmd_sync))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("gcal_status", cmd_gcal_status))
    application.add_handler(CommandHandler("dang_ky", cmd_dang_ky))
    application.add_handler(CommandHandler("huy", cmd_huy))
    application.add_handler(CommandHandler("qrbank", cmd_qrbank))
    application.add_handler(CommandHandler("qrzalo", cmd_qrzalo))
    application.add_handler(CommandHandler("qrfacebook", cmd_qrfacebook))
    application.add_handler(CommandHandler("qrgithub", cmd_qrgithub))
    application.add_handler(CallbackQueryHandler(cb_qrbank, pattern=r"^qrbank:"))


def register_fallback_handlers(application) -> None:
    application.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_text))
