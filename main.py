"""
main.py – Entry point: khởi động bot, scheduler, module lịch học + WC 2026.
"""
import logging
import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot, BotCommand
from telegram import Update
from telegram.error import NetworkError, TimedOut, Conflict
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
from error_reporter import setup_error_reporting

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


def _on_scheduler_event(event) -> None:
    """Ghi rõ job bị bỏ lỡ/crash để error reporter gửi alert lên Telegram."""
    if event.code == EVENT_JOB_MISSED:
        logger.error("Scheduler missed job %s scheduled at %s", event.job_id, event.scheduled_run_time)
        return
    logger.error(
        "Scheduler job %s crashed: %s\n%s",
        event.job_id,
        event.exception,
        event.traceback or "",
    )


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
    """Kiểm tra & thông báo kết quả trận vừa kết thúc (chạy mỗi N phút).
    
    Smart check: chỉ fetch API nếu hôm nay có trận đang diễn ra hoặc
    sắp diễn ra trong vòng 3 giờ tới, để tiết kiệm API calls.
    """
    vn_today = datetime.now(VN_TZ).date()
    if not (WC_START_DATE <= vn_today <= WC_END_DATE):
        return

    from wc_client import fetch_today_matches
    from wc_notifier import build_result_message

    # Kiểm tra nhanh từ DB: hôm nay có trận nào chưa kết thúc không?
    vn_date_str = vn_today.strftime("%Y-%m-%d")
    cached = wc_db.get_matches_by_date(vn_date_str)
    now_vn = datetime.now(VN_TZ)

    has_active = False
    for m in cached:
        status = m.get("status", "")
        # Đang live
        if status in ("LIVE", "IN_PLAY", "PAUSED"):
            has_active = True
            break
        # Chưa đấu và sắp bắt đầu trong 3h tới
        if status == "SCHEDULED":
            vn_time_str = m.get("vn_time")
            if vn_time_str:
                try:
                    match_dt = datetime.strptime(f"{vn_date_str} {vn_time_str}", "%Y-%m-%d %H:%M")
                    match_dt = match_dt.replace(tzinfo=VN_TZ)
                    delta_minutes = (match_dt - now_vn).total_seconds() / 60
                    if -30 <= delta_minutes <= 180:  # Từ 30 phút trước đến 3h sau giờ KO
                        has_active = True
                        break
                except Exception:
                    has_active = True  # Không parse được → cứ check

    if not has_active and cached:
        # Tất cả trận hôm nay đã kết thúc hoặc chưa đến giờ → skip
        return

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

def _build_bot_commands() -> list[BotCommand]:
    commands = [
        BotCommand("start", "Khởi động bot"),
        BotCommand("help", "Xem danh sách lệnh"),
        BotCommand("lich", "Xem lịch học 7 ngày tới"),
        BotCommand("lich_thang", "Xem lịch học tháng này"),
        BotCommand("hom_nay", "Xem lịch học hôm nay"),
        BotCommand("ngay_mai", "Xem lịch học ngày mai"),
        BotCommand("sync", "Đồng bộ lịch học ngay"),
        BotCommand("status", "Xem trạng thái bot"),
        BotCommand("gcal_status", "Kiểm tra Google Calendar"),
        BotCommand("dang_ky", "Đăng ký nhận thông báo"),
        BotCommand("huy", "Hủy nhận thông báo"),
        BotCommand("qrbank", "QR chuyển khoản ngân hàng"),
    ]
    if WC_ENABLED:
        commands.extend([
            BotCommand("wc", "World Cup 2026"),
            BotCommand("wchelp", "Trợ giúp World Cup"),
            BotCommand("wc_help", "Trợ giúp World Cup"),
        ])
    return commands


async def _run_initial_sync(bot: Bot) -> None:
    try:
        from sync_service import run_sync
        result = await run_sync(bot=bot, notify_changes=True)
        logger.info("✅ Initial sync: %s", result)
    except Exception:
        logger.exception("Initial sync lỗi")


async def on_startup(application: Application) -> None:
    logger.info("🚀 Bot đang khởi động...")
    db.init_db()
    wc_db.init_wc_tables()

    bot = application.bot
    scheduler: AsyncIOScheduler = application.bot_data["scheduler"]
    scheduler.add_listener(_on_scheduler_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    me = await bot.get_me()
    logger.info("🤖 Telegram bot identity: @%s (id=%s)", me.username, me.id)
    await bot.set_my_commands(_build_bot_commands())
    logger.info("✅ Telegram slash commands synced.")

    # ── Error reporting: gửi ERROR/CRITICAL lên Telegram ─────────────────────
    try:
        subscribed = db.get_subscribed_users()
        alert_chat_ids = [u["chat_id"] for u in subscribed] if subscribed else []
        loop = asyncio.get_event_loop()
        setup_error_reporting(bot, alert_chat_ids, loop)
    except Exception:
        logger.warning("Không setup được error reporting (sử sắp chưa có user đăng ký)")

    # ── Lịch học: đồng bộ 0h,7h,12h,17h ─────────────────────────────────────
    hours_str = ",".join(str(h) for h in SYNC_HOURS)
    scheduler.add_job(
        job_sync_schedule,
        trigger=CronTrigger(hour=hours_str, minute=0, timezone=TIMEZONE),
        args=[bot], id="sync_schedule", replace_existing=True,
        coalesce=True, misfire_grace_time=7200, max_instances=1,
    )
    # Nhắc nhở lịch học mỗi 30 phút (để không bỏ lỡ cửa sổ nhắc)
    scheduler.add_job(
        job_send_reminders,
        trigger=CronTrigger(minute="0,30", timezone=TIMEZONE),
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


# Trạng thái theo dõi network để tránh spam log khi mất mạng liên tục
_net_down_since: float = 0.0        # monotonic time khi mất mạng lần đầu
_net_last_log: float = 0.0          # monotonic time lần cuối log warning
_NET_LOG_INITIAL_INTERVAL = 60      # 1 phút đầu: log mỗi 1 phút
_NET_LOG_MAX_INTERVAL = 600         # Sau đó: log tối đa mỗi 10 phút


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _net_down_since, _net_last_log

    # Conflict thường xảy ra ngắn hạn khi Coolify vừa thay container: request
    # getUpdates dài của instance cũ chưa kịp kết thúc. Không tự thoát process,
    # vì sẽ làm deployment rơi vào restart loop; PTB sẽ retry polling.
    if isinstance(context.error, Conflict):
        logger.warning(
            "Telegram polling conflict: một instance khác vừa/đang polling. "
            "Giữ process chạy và chờ polling retry."
        )
        return

    # Lỗi mạng/kết nối – không cần traceback
    is_network_err = isinstance(
        context.error,
        (NetworkError, TimedOut, httpx.ConnectError, httpx.TimeoutException)
    )
    if is_network_err:
        now = time.monotonic()
        if _net_down_since == 0.0:
            _net_down_since = now
            _net_last_log = now
            logger.warning("Mất kết nối mạng: %s", context.error)
        else:
            # Tính interval log tăng dần theo thời gian mất mạng
            down_secs = now - _net_down_since
            log_interval = min(_NET_LOG_INITIAL_INTERVAL * max(1, int(down_secs / 120)),
                               _NET_LOG_MAX_INTERVAL)
            if now - _net_last_log >= log_interval:
                _net_last_log = now
                logger.warning("Vẫn mất kết nối (%.0f phút): %s",
                               down_secs / 60, context.error)
        return

    # Kết nối trở lại – reset counter
    if _net_down_since > 0.0:
        down_mins = (time.monotonic() - _net_down_since) / 60
        logger.info("✅ Kết nối mạng phục hồi sau %.0f phút.", down_mins)
        _net_down_since = 0.0
        _net_last_log = 0.0

    logger.exception("Telegram handler error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Bot gặp lỗi khi xử lý lệnh này. Kiểm tra logs trên server để xem chi tiết."
            )
        except Exception:
            logger.exception("Failed to send error message to Telegram")


# ── Main ──────────────────────────────────────────────────────────────────────

# Độ trễ retry khi mất mạng: bắt đầu 5s, tăng dần lên tối đa 60s
_RETRY_INITIAL_DELAY = 5
_RETRY_MAX_DELAY = 60


def _build_application(scheduler: AsyncIOScheduler) -> Application:
    """Tạo Application instance mới (cần rebuild sau mỗi lần restart)."""
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(15)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(15)
        .concurrent_updates(8)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    application.bot_data["scheduler"] = scheduler
    application.bot_data["started_at"] = datetime.now(timezone.utc)
    return application


def main() -> None:
    token_ok, token_message = validate_telegram_token(TELEGRAM_BOT_TOKEN)
    if not token_ok:
        logger.critical("Telegram bot token invalid: %s", token_message)
        logger.critical(
            "Set TELEGRAM_BOT_TOKEN in Coolify Environment Variables. "
            "BOT_TOKEN and TELEGRAM_TOKEN are also accepted as aliases."
        )
        sys.exit(1)

    if TELEGRAM_OWNER_USERNAME:
        logger.info("Owner gate enabled for @%s.", TELEGRAM_OWNER_USERNAME)
    else:
        logger.info("Owner gate enabled: first Telegram user who sends /start will claim the bot.")

    retry_delay = _RETRY_INITIAL_DELAY
    attempt = 0

    while True:
        attempt += 1
        scheduler = AsyncIOScheduler(timezone=TIMEZONE)
        application = _build_application(scheduler)

        register_handlers(application)
        if WC_ENABLED:
            register_wc_handlers(application)
        register_fallback_handlers(application)
        application.add_error_handler(on_error)

        try:
            logger.info("▶️  Bot bắt đầu polling... (lần thử #%d)", attempt)
            application.run_polling(
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=False,
            )
            # run_polling() thoát bình thường (SIGTERM/SIGINT) → dừng hẳn
            logger.info("👋 Bot dừng bình thường.")
            break

        except SystemExit as e:
            # sys.exit() từ on_error (Conflict) hoặc lỗi config → thoát thật
            logger.critical("Bot thoát với code %s, không retry.", e.code)
            raise

        except KeyboardInterrupt:
            logger.info("👋 Bot dừng do Ctrl+C.")
            break

        except Exception as e:
            # Mọi exception khác (NetworkError, crash, ...) → retry
            logger.error(
                "❌ Bot crash (lần #%d): %s – thử lại sau %ds...",
                attempt, e, retry_delay,
            )
            time.sleep(retry_delay)
            # Backoff có giới hạn: 5 → 10 → 20 → 40 → 60 → 60 → ...
            retry_delay = min(retry_delay * 2, _RETRY_MAX_DELAY)
            continue

        # Reset delay khi chạy thành công một lúc
        retry_delay = _RETRY_INITIAL_DELAY


if __name__ == "__main__":
    main()
