"""
wc_notifier.py – Format thông báo trận đấu World Cup 2026.
"""
from datetime import datetime
from wc_client import team_vn_name

STAGE_VN = {
    "GROUP_STAGE":       "Vòng bảng",
    "LAST_32":           "Vòng 32",
    "LAST_16":           "Vòng 16",
    "QUARTER_FINALS":    "Tứ kết",
    "SEMI_FINALS":       "Bán kết",
    "THIRD_PLACE":       "Tranh hạng 3",
    "FINAL":             "🏆 Chung kết",
}

STATUS_VN = {
    "SCHEDULED":  "🕐 Chưa đấu",
    "LIVE":       "🔴 LIVE",
    "IN_PLAY":    "🔴 LIVE",
    "PAUSED":     "⏸️ Nghỉ giữa hiệp",
    "FINISHED":   "✅ Kết thúc",
    "POSTPONED":  "⏳ Hoãn",
    "CANCELLED":  "❌ Huỷ",
    "SUSPENDED":  "⚠️ Tạm dừng",
    "TIMED":      "⏰ Sắp đấu",
}

WEEKDAY_VN = ["T.Hai", "T.Ba", "T.Tư", "T.Năm", "T.Sáu", "T.Bảy", "CN"]

FLAG_MAP = {
    "Germany":          "🇩🇪", "France":           "🇫🇷", "England":          "🇬🇧",
    "Spain":            "🇪🇸", "Portugal":         "🇵🇹", "Netherlands":      "🇳🇱",
    "Belgium":          "🇧🇪", "Italy":            "🇮🇹", "Croatia":          "🇭🇷",
    "Denmark":          "🇩🇰", "Switzerland":      "🇨🇭", "Sweden":           "🇸🇪",
    "Poland":           "🇵🇱", "Serbia":           "🇷🇸", "Hungary":          "🇭🇺",
    "Austria":          "🇦🇹", "Türkiye":          "🇹🇷", "Turkey":           "🇹🇷",
    "Scotland":         "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Ukraine":          "🇺🇦", "Romania":          "🇷🇴",
    "Slovakia":         "🇸🇰", "Slovenia":         "🇸🇮", "Georgia":          "🇬🇪",
    "Albania":          "🇦🇱",
    "Argentina":        "🇦🇷", "Brazil":           "🇧🇷", "United States":    "🇺🇸",
    "Mexico":           "🇲🇽", "Canada":           "🇨🇦", "Uruguay":          "🇺🇾",
    "Colombia":         "🇨🇴", "Ecuador":          "🇪🇨", "Venezuela":        "🇻🇪",
    "Chile":            "🇨🇱", "Peru":             "🇵🇪", "Panama":           "🇵🇦",
    "Costa Rica":       "🇨🇷", "Honduras":         "🇭🇳", "Jamaica":          "🇯🇲",
    "Japan":            "🇯🇵", "Korea Republic":   "🇰🇷", "IR Iran":          "🇮🇷",
    "Australia":        "🇦🇺", "Saudi Arabia":     "🇸🇦", "Qatar":            "🇶🇦",
    "Jordan":           "🇯🇴", "Iraq":             "🇮🇶", "Uzbekistan":       "🇺🇿",
    "China PR":         "🇨🇳",
    "Morocco":          "🇲🇦", "Nigeria":          "🇳🇬", "Senegal":          "🇸🇳",
    "Egypt":            "🇪🇬", "Côte d'Ivoire":   "🇨🇮", "Cameroon":         "🇨🇲",
    "South Africa":     "🇿🇦", "Tunisia":          "🇹🇳", "Algeria":          "🇩🇿",
    "Ghana":            "🇬🇭", "DR Congo":         "🇨🇩",
    "New Zealand":      "🇳🇿",
}

# ── Kênh VTV theo khung giờ (giờ VN) ─────────────────────────────────────────
# VTV phát sóng toàn bộ 104 trận WC 2026. Kênh chủ lực là VTV3, VTV2, VTV9.
# Ngoài ra có thể xem trực tuyến trên VTVgo, FPT Play, TV360, MyTV.
_VTV_CHANNEL_BY_HOUR: dict[int, str] = {
    # Sáng sớm: VTV3 chủ lực
     0: "VTV3",
     1: "VTV3",
     2: "VTV3",
     3: "VTV3",
    # Sáng: VTV2 + VTV3
     7: "VTV2 / VTV3",
     8: "VTV2 / VTV3",
     9: "VTV2 / VTV3",
    10: "VTV2 / VTV3",
    11: "VTV2 / VTV3",
    # Chiều: VTV3 + VTV9
    15: "VTV3 / VTV9",
    16: "VTV3 / VTV9",
    17: "VTV3 / VTV9",
    18: "VTV3 / VTV9",
    # Tối muộn: VTV3
    22: "VTV3",
    23: "VTV3",
}

def _vtv_channel(vn_time: str) -> str:
    """Trả về tên kênh VTV dự kiến dựa vào giờ phát sóng."""
    try:
        hour = int(vn_time.split(":")[0])
        # Tìm kênh gần nhất theo giờ
        for h in sorted(_VTV_CHANNEL_BY_HOUR.keys()):
            if hour <= h:
                return _VTV_CHANNEL_BY_HOUR[h]
        # Giờ muộn hơn tất cả → lấy kênh giờ muộn nhất
        return _VTV_CHANNEL_BY_HOUR[max(_VTV_CHANNEL_BY_HOUR.keys())]
    except Exception:
        return "VTV3"


def flag(team: str) -> str:
    return FLAG_MAP.get(team, "🏳️")


def team_label(team: str) -> str:
    vn = team_vn_name(team)
    f  = flag(team)
    return f"{f} {vn}" if vn != team else f"{f} {team}"


def _fmt_date(vn_date: str) -> str:
    try:
        d = datetime.strptime(vn_date, "%Y-%m-%d")
        wd = WEEKDAY_VN[d.weekday()]
        return f"{wd} {d.strftime('%d/%m/%Y')}"
    except Exception:
        return vn_date


def _goals_by_team(goals: list[dict], team: str) -> str:
    """Format danh sách bàn thắng của 1 đội."""
    scorers = []
    for g in goals:
        if g.get("team", "").lower() == team.lower():
            name    = g.get("scorer", "?")
            minute  = g.get("minute", "?")
            typ     = g.get("type", "NORMAL")
            suffix  = " (OG)" if typ == "OWN_GOAL" else (" (P)" if typ == "PENALTY" else "")
            scorers.append(f"{name}{suffix} {minute}'")
    return ", ".join(scorers) if scorers else ""


def _cards_by_team(cards: list[dict], team: str, is_red: bool = False) -> str:
    """Format danh sách thẻ của 1 đội."""
    items = []
    for c in cards:
        if c.get("team", "").lower() == team.lower():
            player  = c.get("player", "?")
            minute  = c.get("minute", "?")
            suffix  = " (2Y)" if c.get("type") == "SECOND_YELLOW" else ""
            items.append(f"{player}{suffix} {minute}'")
    return ", ".join(items) if items else ""


def format_match(m: dict, show_scorers: bool = True) -> str:
    """Format 1 trận đấu thành tin nhắn Telegram."""
    home       = m["home_team"]
    away       = m["away_team"]
    status     = m.get("status", "SCHEDULED")
    stage      = STAGE_VN.get(m.get("stage", ""), m.get("stage", ""))
    grp        = m.get("grp") or m.get("group", "")
    grp_label  = f" | {grp.replace('GROUP_', 'Bảng ')}" if grp else ""
    status_lbl = STATUS_VN.get(status, status)
    time_str   = m.get("vn_time") or "TBA"

    home_lbl = team_label(home)
    away_lbl = team_label(away)

    # Tỉ số
    if status in ("FINISHED", "LIVE", "IN_PLAY", "PAUSED") and m.get("home_score") is not None:
        hs, as_ = m["home_score"], m["away_score"]
        score_line = f"<b>{home_lbl}  {hs} – {as_}  {away_lbl}</b>"

        # Hiệp 1
        ht_info = ""
        if m.get("ht_home") is not None:
            ht_info = f"\n  <i>Hiệp 1: {m['ht_home']} – {m['ht_away']}</i>"

        # Người ghi bàn
        scorer_lines = ""
        if show_scorers and m.get("goals"):
            h_scorers = _goals_by_team(m["goals"], home)
            a_scorers = _goals_by_team(m["goals"], away)
            if h_scorers:
                scorer_lines += f"\n  ⚽ {team_vn_name(home)}: {h_scorers}"
            if a_scorers:
                scorer_lines += f"\n  ⚽ {team_vn_name(away)}: {a_scorers}"

        result = (
            f"{score_line}{ht_info}{scorer_lines}\n"
            f"  {status_lbl} | {stage}{grp_label} | {time_str} (VN)"
        )
    else:
        result = (
            f"<b>{home_lbl}  vs  {away_lbl}</b>\n"
            f"  {status_lbl} | {stage}{grp_label} | 🕐 {time_str} (VN)"
        )

    return result


def build_result_message(match: dict) -> str:
    """Thông báo kết quả trận đấu vừa kết thúc – đầy đủ chi tiết."""
    home   = match["home_team"]
    away   = match["away_team"]
    hs     = match.get("home_score", 0)
    as_    = match.get("away_score", 0)
    stage  = STAGE_VN.get(match.get("stage", ""), match.get("stage", ""))
    grp    = match.get("grp") or match.get("group", "")
    grp_label = f" | {grp.replace('GROUP_', 'Bảng ')}" if grp else ""
    time_str  = match.get("vn_time") or "?"
    winner    = match.get("winner")

    home_lbl = team_label(home)
    away_lbl = team_label(away)

    # Tiêu đề kết quả
    if winner == "HOME_TEAM":
        result_icon = "🏆"
    elif winner == "AWAY_TEAM":
        result_icon = "🏆"
    else:
        result_icon = "🤝"

    lines = [
        f"🏁 <b>KẾT QUẢ TRẬN ĐẤU</b>",
        f"",
        f"<b>{home_lbl}  {hs} – {as_}  {away_lbl}</b>",
        f"  {stage}{grp_label} | {time_str} (VN)",
    ]

    # Hiệp 1
    if match.get("ht_home") is not None:
        lines.append(f"  <i>Hiệp 1: {match['ht_home']} – {match['ht_away']}</i>")

    # Người ghi bàn
    goals = match.get("goals") or []
    if goals:
        lines.append("")
        lines.append("⚽ <b>Bàn thắng:</b>")
        h_scorers = _goals_by_team(goals, home)
        a_scorers = _goals_by_team(goals, away)
        if h_scorers:
            lines.append(f"  {flag(home)} {team_vn_name(home)}: {h_scorers}")
        if a_scorers:
            lines.append(f"  {flag(away)} {team_vn_name(away)}: {a_scorers}")

    # Thẻ vàng
    yellow = match.get("yellow_cards") or []
    if yellow:
        lines.append("")
        lines.append("🟨 <b>Thẻ vàng:</b>")
        h_y = _cards_by_team(yellow, home)
        a_y = _cards_by_team(yellow, away)
        if h_y:
            lines.append(f"  {flag(home)} {team_vn_name(home)}: {h_y}")
        if a_y:
            lines.append(f"  {flag(away)} {team_vn_name(away)}: {a_y}")

    # Thẻ đỏ
    red = match.get("red_cards") or []
    if red:
        lines.append("")
        lines.append("🟥 <b>Thẻ đỏ:</b>")
        h_r = _cards_by_team(red, home, is_red=True)
        a_r = _cards_by_team(red, away, is_red=True)
        if h_r:
            lines.append(f"  {flag(home)} {team_vn_name(home)}: {h_r}")
        if a_r:
            lines.append(f"  {flag(away)} {team_vn_name(away)}: {a_r}")

    # Kết quả chung
    lines.append("")
    if winner == "HOME_TEAM":
        lines.append(f"🏆 {result_icon} <b>{team_vn_name(home)}</b> giành chiến thắng!")
    elif winner == "AWAY_TEAM":
        lines.append(f"🏆 {result_icon} <b>{team_vn_name(away)}</b> giành chiến thắng!")
    else:
        lines.append(f"🤝 Trận đấu kết thúc hoà!")

    return "\n".join(lines)


def build_daily_wc_message(matches: list[dict], vn_date: str) -> str:
    """Thông báo lịch trận ngày hôm nay – có kênh VTV."""
    date_label = _fmt_date(vn_date)
    if not matches:
        return f"⚽ <b>WC 2026 – {date_label}</b>\n\n<i>Hôm nay không có trận nào.</i>"

    lines = [f"⚽ <b>World Cup 2026 – {date_label}</b>\n"]
    for m in sorted(matches, key=lambda x: x.get("vn_time") or ""):
        home       = m["home_team"]
        away       = m["away_team"]
        status     = m.get("status", "SCHEDULED")
        stage      = STAGE_VN.get(m.get("stage", ""), m.get("stage", ""))
        grp        = m.get("grp") or m.get("group", "")
        grp_label  = f" | {grp.replace('GROUP_', 'Bảng ')}" if grp else ""
        status_lbl = STATUS_VN.get(status, status)
        time_str   = m.get("vn_time") or "TBA"
        home_lbl   = team_label(home)
        away_lbl   = team_label(away)
        channel    = _vtv_channel(time_str)

        if status in ("FINISHED", "LIVE", "IN_PLAY", "PAUSED") and m.get("home_score") is not None:
            hs, as_ = m["home_score"], m["away_score"]
            lines.append(f"<b>{home_lbl}  {hs} – {as_}  {away_lbl}</b>")

            # Người ghi bàn
            if m.get("goals"):
                h_sc = _goals_by_team(m["goals"], home)
                a_sc = _goals_by_team(m["goals"], away)
                if h_sc:
                    lines.append(f"  ⚽ {team_vn_name(home)}: {h_sc}")
                if a_sc:
                    lines.append(f"  ⚽ {team_vn_name(away)}: {a_sc}")

            # Thẻ vàng
            if m.get("yellow_cards"):
                h_y = _cards_by_team(m["yellow_cards"], home)
                a_y = _cards_by_team(m["yellow_cards"], away)
                if h_y:
                    lines.append(f"  🟨 {team_vn_name(home)}: {h_y}")
                if a_y:
                    lines.append(f"  🟨 {team_vn_name(away)}: {a_y}")

            # Thẻ đỏ
            if m.get("red_cards"):
                h_r = _cards_by_team(m["red_cards"], home)
                a_r = _cards_by_team(m["red_cards"], away)
                if h_r:
                    lines.append(f"  🟥 {team_vn_name(home)}: {h_r}")
                if a_r:
                    lines.append(f"  🟥 {team_vn_name(away)}: {a_r}")

            lines.append(f"  {status_lbl} | {stage}{grp_label} | {time_str} (VN)")
        else:
            lines.append(f"<b>{home_lbl}  vs  {away_lbl}</b>")
            lines.append(f"  🕐 {time_str} (VN) | {stage}{grp_label}")
            lines.append(f"  📺 {channel} · VTVgo · FPT Play · TV360")

        lines.append("─" * 28)

    lines.append(f"\n📊 Tổng: <b>{len(matches)}</b> trận")
    lines.append("📺 Xem trên: <b>VTV2 / VTV3 / VTV9</b> và VTVgo, FPT Play, TV360, MyTV")
    return "\n".join(lines)


def build_team_schedule_message(matches: list[dict], team_name: str) -> str:
    """Lịch thi đấu của 1 đội."""
    vn = team_vn_name(team_name)
    f  = flag(team_name)
    if not matches:
        return f"⚽ Không tìm thấy lịch thi đấu cho <b>{f} {vn}</b>."

    lines = [f"⚽ <b>Lịch thi đấu: {f} {vn}</b>\n"]
    for m in sorted(matches, key=lambda x: (x.get("vn_date") or "", x.get("vn_time") or "")):
        date_lbl = _fmt_date(m.get("vn_date") or "")
        lines.append(f"📅 <b>{date_lbl}</b>")
        lines.append(format_match(m, show_scorers=True))
        lines.append("─" * 28)

    played  = sum(1 for m in matches if m.get("status") == "FINISHED")
    wins    = sum(
        1 for m in matches
        if m.get("status") == "FINISHED" and (
            (m["winner"] == "HOME_TEAM" and team_name.lower() in m["home_team"].lower()) or
            (m["winner"] == "AWAY_TEAM" and team_name.lower() in m["away_team"].lower())
        )
    )
    if played:
        lines.append(f"\n📊 Đã đấu: <b>{played}</b> | Thắng: <b>{wins}</b>")

    return "\n".join(lines)


def build_standings_message(standings: list[dict]) -> str:
    """Bảng xếp hạng vòng bảng."""
    if not standings:
        return "⚽ Chưa có dữ liệu bảng xếp hạng."

    lines = ["🏆 <b>Bảng xếp hạng WC 2026</b>\n"]
    for standing in standings:
        grp_name = standing.get("group", "")
        if grp_name:
            lines.append(f"\n<b>📊 {grp_name.replace('GROUP_', 'Bảng ')}</b>")
        table = standing.get("table", [])
        for row in table:
            pos  = row.get("position", "")
            team = row.get("team", {}).get("name", "")
            pts  = row.get("points", 0)
            gd   = row.get("goalDifference", 0)
            gf   = row.get("goalsFor", 0)
            gd_s = f"+{gd}" if gd > 0 else str(gd)
            lines.append(
                f"  {pos}. {team_label(team)}  <b>{pts}pts</b>  ({gf} bàn, HS {gd_s})"
            )

    return "\n".join(lines)
