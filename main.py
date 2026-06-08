"""
main.py – Entry point: khởi động bot, scheduler, module lịch học + WC 2026.
"""
import logging
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot
from telegram import Update
from telegram.ext import Application, ContextTypes

import database as db
import wc_db
from config import (
    LOG_LEVEL, SYNC_HOURS, TELEGRAM_BOT_TOKEN, TIMEZONE,
    WC_ENABLED, WC_DAILY_NOTIFY_HOUR, WC_LIVE_CHECK_MINUTES,
    WC_START_DATE, WC_END_DATE, TELEGRAM_OWNER_USERNAME,
    validate_telegram_token,
)
from handlers import register_fallback_handlers, register_handlers
from wc_handlers import register_wc_handlers

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

VN_TZ = timezone(timedelta(hours=7))


# ── Jobs: Lịch học ────────────────────────────────────────────────────────────

async def job_sync_schedule(bot: Bot) -> None:
    logger.info("⏰ [CRON] Đồng bộ lịch học...")
    from sync_service import run_sync
    result = await run_sync(bot=bot, notify_changes=True)
    logger.info("⏰ [CRON] Sync done: %s", result)


async def job_send_reminders(bot: Bot) -> None:
    logger.info("⏰ [CRON] Kiểm tra nhắc nhở lịch học...")
    from sync_service import run_reminder_check
    count = await run_reminder_check(bot=bot)
    if count:
        logger.info("⏰ [CRON] Đã gửi %d nhắc nhở.", count)


# ── Jobs: World Cup ───────────────────────────────────────────────────────────

async def job_wc_daily_notify(bot: Bot) -> None:
    """Gửi lịch trận WC hôm nay lúc 0h."""
    vn_today = datetime.now(VN_TZ).date()
    if not (WC_START_DATE <= vn_today <= WC_END_DATE):
        return

    logger.info("⏰ [WC] Gửi lịch trận hôm nay...")
    from wc_client import fetch_today_matches
    from wc_notifier import build_daily_wc_message

    vn_date = vn_today.strftime("%Y-%m-%d")
    matches = await fetch_today_matches()
    for m in matches:
        wc_db.upsert_match(m)

    if not matches:
        logger.info("⏰ [WC] Hôm nay không có trận nào.")
        return

    msg = build_daily_wc_message(matches, vn_date)
    users = db.get_subscribed_users()
    for user in users:
        try:
            await bot.send_message(
                chat_id=user["chat_id"], text=msg,
                parse_mode="HTML", disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error("WC notify error for %s: %s", user["chat_id"], e)


async def job_wc_result_check(bot: Bot) -> None:
    """Kiểm tra & thông báo kết quả trận vừa kết thúc (chạy mỗi N phút)."""
    vn_today = datetime.now(VN_TZ).date()
    if not (WC_START_DATE <= vn_today <= WC_END_DATE):
        return

    from wc_client import fetch_today_matches
    from wc_notifier import build_result_message

    matches = await fetch_today_matches()

    new_results = []
    for m in matches:
        _, score_changed = wc_db.upsert_match(m)
        if (
            m["status"] == "FINISHED"
            and not wc_db.is_wc_notified(m["id"], "result")
        ):
            new_results.append(m)
            wc_db.mark_wc_notified(m["id"], "result")

    if not new_results:
        return

    logger.info("⏰ [WC] %d kết quả mới, gửi thông báo...", len(new_results))
    users = db.get_subscribed_users()
    for m in new_results:
        msg = build_result_message(m)
        for user in users:
            try:
                await bot.send_message(
                    chat_id=user["chat_id"], text=msg,
                    parse_mode="HTML", disable_web_page_preview=True,
                )
            except Exception as e:
                logger.error("WC result notify error %s: %s", user["chat_id"], e)


# ── Startup / Shutdown ────────────────────────────────────────────────────────

async def _run_initial_sync(bot: Bot) -> None:
    try:
        from sync_service import run_sync
        result = await run_sync(bot=bot, notify_changes=False)
        logger.info("✅ Initial sync: %s", result)
    except Exception:
        logger.exception("Initial sync lỗi")


async def on_startup(application: Application) -> None:
    logger.info("🚀 Bot đang khởi động...")
    db.init_db()
    wc_db.init_wc_tables()

    bot = application.bot
    scheduler: AsyncIOScheduler = application.bot_data["scheduler"]
    me = await bot.get_me()
    logger.info("🤖 Telegram bot identity: @%s (id=%s)", me.username, me.id)

    # ── Lịch học: đồng bộ 0h,7h,12h,17h ─────────────────────────────────────
    hours_str = ",".join(str(h) for h in SYNC_HOURS)
    scheduler.add_job(
        job_sync_schedule,
        trigger=CronTrigger(hour=hours_str, minute=0, timezone=TIMEZONE),
        args=[bot], id="sync_schedule", replace_existing=True,
    )
    # Nhắc nhở lịch học mỗi giờ
    scheduler.add_job(
        job_send_reminders,
        trigger=CronTrigger(minute=0, timezone=TIMEZONE),
        args=[bot], id="send_reminders", replace_existing=True,
    )

    # ── WC 2026 ───────────────────────────────────────────────────────────────
    if WC_ENABLED:
        # Lịch trận hôm nay lúc 0h
        scheduler.add_job(
            job_wc_daily_notify,
            trigger=CronTrigger(hour=WC_DAILY_NOTIFY_HOUR, minute=0, timezone=TIMEZONE),
            args=[bot], id="wc_daily", replace_existing=True,
        )
        # Kiểm tra kết quả định kỳ
        if WC_LIVE_CHECK_MINUTES > 0:
            scheduler.add_job(
                job_wc_result_check,
                trigger=IntervalTrigger(minutes=WC_LIVE_CHECK_MINUTES, timezone=TIMEZONE),
                args=[bot], id="wc_results", replace_existing=True,
            )
        logger.info("✅ WC 2026 module enabled (daily=%dh, check every %dmin)",
                    WC_DAILY_NOTIFY_HOUR, WC_LIVE_CHECK_MINUTES)

    scheduler.start()
    logger.info("✅ Scheduler đã khởi động. Giờ đồng bộ lịch học: %s", SYNC_HOURS)

    # Chạy sync lần đầu ở background để polling nhận lệnh ngay sau startup.
    asyncio.create_task(_run_initial_sync(bot))

    logger.info("🤖 Bot sẵn sàng!")


async def on_shutdown(application: Application) -> None:
    scheduler: AsyncIOScheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("👋 Bot đã tắt.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Telegram handler error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Bot gặp lỗi khi xử lý lệnh này. Kiểm tra logs trên server để xem chi tiết."
            )
        except Exception:
            logger.exception("Failed to send error message to Telegram")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    token_ok, token_message = validate_telegram_token(TELEGRAM_BOT_TOKEN)
    if not token_ok:
        logger.critical("Telegram bot token invalid: %s", token_message)
        logger.critical(
            "Set TELEGRAM_BOT_TOKEN in Coolify Environment Variables. "
            "BOT_TOKEN and TELEGRAM_TOKEN are also accepted as aliases."
        )
        sys.exit(1)

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    application.bot_data["scheduler"] = scheduler

    register_handlers(application)
    if WC_ENABLED:
        register_wc_handlers(application)
    register_fallback_handlers(application)
    application.add_error_handler(on_error)

    if TELEGRAM_OWNER_USERNAME:
        logger.info("Owner gate enabled for @%s.", TELEGRAM_OWNER_USERNAME)
    else:
        logger.info("Owner gate enabled: first Telegram user who sends /start will claim the bot.")

    logger.info("▶️  Bot bắt đầu polling...")
    application.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
