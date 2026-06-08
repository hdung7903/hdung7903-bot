"""
wc_handlers.py – Telegram handlers cho module World Cup 2026.

Cú pháp lệnh:
  /wc                    → Lịch trận hôm nay
  /wc live               → Trận đang diễn ra
  /wc ket_qua            → Kết quả hôm qua
  /wc DD-MM              → Lịch theo ngày  (vd: /wc 15-06)
  /wc DD/MM              → Tương tự        (vd: /wc 15/06)
  /wc <đội>              → Lịch thi đấu 1 đội (vd: /wc Việt Nam, /wc france)
  /wc bang A             → Bảng xếp hạng bảng A
  /wc bang               → Toàn bộ bảng xếp hạng
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

import wc_db
from wc_client import (
    fetch_matches_by_date, fetch_team_matches,
    fetch_today_matches, fetch_live_matches,
    fetch_standings,
)
from wc_notifier import (
    build_daily_wc_message, build_team_schedule_message,
    build_standings_message, format_match,
)

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))


async def _send_long(update: Update, text: str) -> None:
    """Gửi tin nhắn dài, tự động chia nhỏ nếu > 4000 ký tự."""
    MAX = 4000
    for i in range(0, len(text), MAX):
        await update.message.reply_text(
            text[i:i + MAX], parse_mode="HTML",
            disable_web_page_preview=True,
        )


def _parse_date_arg(arg: str) -> str | None:
    """Chuyển 'DD-MM' hoặc 'DD/MM' → 'YYYY-MM-DD' (năm 2026/2027)."""
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})", arg.strip())
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    year = 2026 if month >= 6 else 2027  # WC kéo đến tháng 7/2026
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


# ── Handler chính /wc ─────────────────────────────────────────────────────────

async def cmd_wc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args  # list các arg sau /wc

    # /wc → lịch hôm nay
    if not args:
        await _wc_today(update)
        return

    keyword = " ".join(args).strip()
    kw_lower = keyword.lower()

    # /wc live
    if kw_lower in ("live", "trực tiếp", "dang_dau", "đang đấu"):
        await _wc_live(update)
        return

    # /wc ket_qua | /wc kq | /wc results
    if kw_lower in ("ket_qua", "kq", "kết quả", "results", "result"):
        await _wc_results_today(update)
        return

    # /wc bang | /wc bang A | /wc standings
    if kw_lower in ("bang", "bảng", "standings", "xep_hang", "xếp hạng"):
        await _wc_standings(update)
        return

    if re.match(r"^b[aả]ng\s+[a-p]$", kw_lower, re.IGNORECASE):
        grp = kw_lower.split()[-1].upper()
        await _wc_standings(update, group_filter=grp)
        return

    # /wc DD-MM | /wc DD/MM
    date_str = _parse_date_arg(keyword)
    if date_str:
        await _wc_by_date(update, date_str)
        return

    # /wc <team name>
    await _wc_team(update, keyword)


# ── Sub-handlers ──────────────────────────────────────────────────────────────

async def _wc_today(update: Update) -> None:
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    await update.message.reply_text("⏳ Đang lấy lịch trận...", parse_mode="HTML")

    # Thử lấy từ DB trước (cache)
    matches = wc_db.get_matches_by_date(today)

    # Nếu DB rỗng hoặc API key có, fetch live
    if not matches:
        matches = await fetch_today_matches()
        for m in matches:
            wc_db.upsert_match(m)

    msg = build_daily_wc_message(matches, today)
    await _send_long(update, msg)


async def _wc_by_date(update: Update, date_str: str) -> None:
    await update.message.reply_text("⏳ Đang tìm...", parse_mode="HTML")
    matches = wc_db.get_matches_by_date(date_str)
    if not matches:
        matches = await fetch_matches_by_date(date_str)
        for m in matches:
            wc_db.upsert_match(m)

    msg = build_daily_wc_message(matches, date_str)
    await _send_long(update, msg)


async def _wc_live(update: Update) -> None:
    await update.message.reply_text("🔴 Đang kiểm tra trận live...", parse_mode="HTML")
    matches = await fetch_live_matches()
    if not matches:
        await update.message.reply_text(
            "⚽ Hiện không có trận nào đang diễn ra.", parse_mode="HTML"
        )
        return

    lines = ["🔴 <b>Đang diễn ra – World Cup 2026</b>\n"]
    for m in matches:
        lines.append(format_match(m, show_scorers=True))
        lines.append("─" * 28)
    await _send_long(update, "\n".join(lines))


async def _wc_results_today(update: Update) -> None:
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    await update.message.reply_text("⏳ Đang lấy kết quả...", parse_mode="HTML")

    matches = wc_db.get_finished_matches_date(today)
    if not matches:
        # Thử fetch lại
        raw = await fetch_matches_by_date(today)
        for m in raw:
            wc_db.upsert_match(m)
        matches = wc_db.get_finished_matches_date(today)

    if not matches:
        await update.message.reply_text(
            "⚽ Chưa có kết quả nào hôm nay.", parse_mode="HTML"
        )
        return

    lines = [f"✅ <b>Kết quả hôm nay – World Cup 2026</b>\n"]
    for m in matches:
        lines.append(format_match(m, show_scorers=True))
        lines.append("─" * 28)
    await _send_long(update, "\n".join(lines))


async def _wc_team(update: Update, team_search: str) -> None:
    await update.message.reply_text(
        f"🔍 Tìm lịch đấu của <b>{team_search}</b>...", parse_mode="HTML"
    )
    matches, matched_name = await fetch_team_matches(team_search)

    if not matches:
        await update.message.reply_text(
            f"❌ Không tìm thấy đội <b>{team_search}</b> trong WC 2026.\n"
            "Thử nhập tên tiếng Anh hoặc tiếng Việt khác.",
            parse_mode="HTML",
        )
        return

    msg = build_team_schedule_message(matches, matched_name or team_search)
    await _send_long(update, msg)


async def _wc_standings(update: Update, group_filter: str = None) -> None:
    await update.message.reply_text("⏳ Đang lấy bảng xếp hạng...", parse_mode="HTML")
    standings = await fetch_standings()

    if group_filter:
        standings = [
            s for s in standings
            if group_filter.upper() in (s.get("group", "") or "")
        ]

    msg = build_standings_message(standings)
    await _send_long(update, msg)


# ── Help message ──────────────────────────────────────────────────────────────

async def cmd_wc_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "⚽ <b>World Cup 2026 – Hướng dẫn</b>\n\n"
        "<b>Lệnh cơ bản:</b>\n"
        "/wc – Lịch trận hôm nay\n"
        "/wc live – Trận đang diễn ra 🔴\n"
        "/wc ket_qua – Kết quả hôm nay ✅\n\n"
        "<b>Tìm theo ngày:</b>\n"
        "/wc 15-06 – Lịch ngày 15 tháng 6\n"
        "/wc 04-07 – Lịch ngày 04 tháng 7\n\n"
        "<b>Tìm theo đội:</b>\n"
        "/wc Pháp – Lịch thi đấu của Pháp 🇫🇷\n"
        "/wc Argentina – Lịch thi đấu Argentina 🇦🇷\n"
        "/wc Japan – Nhật Bản 🇯🇵\n\n"
        "<b>Bảng xếp hạng:</b>\n"
        "/wc bang – Toàn bộ bảng xếp hạng\n"
        "/wc bang A – Chỉ bảng A\n\n"
        "📅 WC 2026: <b>11/06/2026 – 19/07/2026</b>\n"
        "🏟️ Địa điểm: USA, Canada, Mexico"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ── Register ──────────────────────────────────────────────────────────────────

def register_wc_handlers(application) -> None:
    application.add_handler(CommandHandler("wc", cmd_wc))
    application.add_handler(CommandHandler("wchelp", cmd_wc_help))
    application.add_handler(CommandHandler("wc_help", cmd_wc_help))
