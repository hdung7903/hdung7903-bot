"""
handlers.py – Tất cả Telegram command handlers.
"""
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import database as db
from config import CLASS_IDS, TIMEZONE
from notifier import build_schedule_message, build_sync_report, format_event

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_registered(chat_id: str) -> bool:
    users = db.get_subscribed_users()
    ids = [u["chat_id"] for u in db.get_subscribed_users()]
    # Check all users (including unsubscribed)
    with db.get_connection() as conn:
        row = conn.execute("SELECT 1 FROM bot_users WHERE chat_id=?", (str(chat_id),)).fetchone()
    return row is not None


def _register_user(update: Update) -> None:
    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    username = user.username or user.full_name or ""
    db.upsert_user(chat_id, username)


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
    name = update.effective_user.first_name or "bạn"
    text = (
        f"👋 Xin chào <b>{name}</b>!\n\n"
        "🤖 Tôi là <b>Bot Lịch Học VinhUni</b>.\n"
        "Tôi sẽ tự động đồng bộ lịch học và nhắc nhở bạn trước <b>1 ngày</b>.\n\n"
        "<b>📋 Các lệnh có sẵn:</b>\n"
        "/lich – Xem lịch học 7 ngày tới\n"
        "/lich_thang – Xem lịch học tháng này\n"
        "/hom_nay – Xem lịch học hôm nay\n"
        "/ngay_mai – Xem lịch học ngày mai\n"
        "/sync – Đồng bộ lịch ngay bây giờ\n"
        "/status – Xem trạng thái bot\n"
        "/dang_ky – Đăng ký nhận thông báo\n"
        "/huy – Hủy đăng ký thông báo\n"
        "/help – Trợ giúp\n\n"
        f"📚 Đang theo dõi lớp: <code>{', '.join(CLASS_IDS)}</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_lich(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
    await update.message.reply_text("⏳ Đang lấy lịch học...", parse_mode="HTML")
    events = db.get_upcoming_events(days=7)
    msg = build_schedule_message(events, "📅 Lịch học 7 ngày tới")
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_lich_thang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
    await update.message.reply_text("⏳ Đang lấy lịch học...", parse_mode="HTML")
    events = db.get_upcoming_events(days=31)
    msg = build_schedule_message(events, "📅 Lịch học tháng này")
    # Chia nhỏ nếu quá dài
    if len(msg) > 4000:
        chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="HTML")
    else:
        await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_hom_nay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
    today = datetime.now().strftime("%Y-%m-%d")
    events = db.get_events_for_date(today)
    msg = build_schedule_message(events, "📅 Lịch học hôm nay")
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_ngay_mai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    events = db.get_events_for_date(tomorrow)
    msg = build_schedule_message(events, "📅 Lịch học ngày mai")
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
    await update.message.reply_text("🔄 Đang đồng bộ lịch học...", parse_mode="HTML")
    from sync_service import run_sync
    result = await run_sync(bot=context.bot, notify_changes=False)
    msg = build_sync_report(result["new"], result["changed"], result["total"])
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
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


async def cmd_dang_ky(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
    chat_id = str(update.effective_chat.id)
    db.set_user_subscription(chat_id, True)
    await update.message.reply_text(
        "✅ Bạn đã <b>đăng ký</b> nhận thông báo lịch học!\n"
        "Bot sẽ nhắc nhở bạn trước 24h khi có lịch học.",
        parse_mode="HTML",
    )


async def cmd_huy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _register_user(update)
    chat_id = str(update.effective_chat.id)
    db.set_user_subscription(chat_id, False)
    await update.message.reply_text(
        "🔕 Bạn đã <b>hủy đăng ký</b> nhận thông báo.\n"
        "Dùng /dang_ky để đăng ký lại.",
        parse_mode="HTML",
    )


async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "❓ Lệnh không hợp lệ. Dùng /help để xem danh sách lệnh.",
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
    application.add_handler(CommandHandler("dang_ky", cmd_dang_ky))
    application.add_handler(CommandHandler("huy", cmd_huy))
    application.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))
