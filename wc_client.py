"""
wc_client.py – Fetch dữ liệu World Cup 2026 từ ESPN public endpoints.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import httpx

from config import WC_API_BASE_URL, WC_STANDINGS_URL, WC_START_DATE, WC_END_DATE

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))

# ── Vietnamese team name mapping ─────────────────────────────────────────────
TEAM_VN_MAP: dict[str, list[str]] = {
    # Châu Âu
    "Đức":            ["Germany"],
    "Pháp":           ["France"],
    "Anh":            ["England"],
    "Tây Ban Nha":    ["Spain"],
    "Bồ Đào Nha":     ["Portugal"],
    "Hà Lan":         ["Netherlands"],
    "Bỉ":             ["Belgium"],
    "Ý":              ["Italy"],
    "Croatia":        ["Croatia"],
    "Đan Mạch":       ["Denmark"],
    "Thụy Sĩ":        ["Switzerland"],
    "Thụy Điển":      ["Sweden"],
    "Ba Lan":         ["Poland"],
    "Serbia":         ["Serbia"],
    "Hungary":        ["Hungary"],
    "Áo":             ["Austria"],
    "Thổ Nhĩ Kỳ":    ["Türkiye", "Turkey"],
    "Scotland":       ["Scotland"],
    "Ukraine":        ["Ukraine"],
    "Romania":        ["Romania"],
    "Slovakia":       ["Slovakia"],
    "Slovenia":       ["Slovenia"],
    "Georgia":        ["Georgia"],
    "Albania":        ["Albania"],
    "Séc":            ["Czech Republic", "Czechia"],  # ESPN dùng "Czechia"
    "Bosnia và Herzegovina": ["Bosnia and Herzegovina"],
    "Bắc Macedonia":  ["North Macedonia"],
    "Kosovo":         ["Kosovo"],
    "Wales":          ["Wales"],
    # Châu Mỹ
    "Argentina":      ["Argentina"],
    "Brazil":         ["Brazil"],
    "Mỹ":             ["United States", "USA"],
    "Mexico":         ["Mexico"],
    "Canada":         ["Canada"],
    "Uruguay":        ["Uruguay"],
    "Colombia":       ["Colombia"],
    "Ecuador":        ["Ecuador"],
    "Venezuela":      ["Venezuela"],
    "Chile":          ["Chile"],
    "Peru":           ["Peru"],
    "Panama":         ["Panama"],
    "Costa Rica":     ["Costa Rica"],
    "Honduras":       ["Honduras"],
    "Jamaica":        ["Jamaica"],
    "Paraguay":       ["Paraguay"],
    "Bolivia":        ["Bolivia"],
    "El Salvador":    ["El Salvador"],
    "Haiti":          ["Haiti"],
    "Guatemala":      ["Guatemala"],
    "Trinidad và Tobago": ["Trinidad and Tobago"],
    "Curaçao":        ["Curaçao"],
    # Châu Á
    "Nhật Bản":       ["Japan"],
    "Hàn Quốc":       ["Korea Republic", "South Korea"],
    "Iran":           ["IR Iran", "Iran"],
    "Úc":             ["Australia"],
    "Ả Rập Saudi":    ["Saudi Arabia"],
    "Qatar":          ["Qatar"],
    "Jordan":         ["Jordan"],
    "Iraq":           ["Iraq"],
    "Uzbekistan":     ["Uzbekistan"],
    "Trung Quốc":     ["China PR", "China"],
    "Indonesia":      ["Indonesia"],
    "Việt Nam":       ["Vietnam"],
    "Thái Lan":       ["Thailand"],
    "Philippines":    ["Philippines"],
    "Bahrain":        ["Bahrain"],
    "Oman":           ["Oman"],
    "UAE":            ["United Arab Emirates", "UAE"],
    # Châu Phi
    "Maroc":          ["Morocco"],
    "Nigeria":        ["Nigeria"],
    "Senegal":        ["Senegal"],
    "Ai Cập":         ["Egypt"],
    "Bờ Biển Ngà":    ["Côte d'Ivoire", "Ivory Coast"],
    "Cameroon":       ["Cameroon"],
    "Nam Phi":        ["South Africa"],
    "Tunisia":        ["Tunisia"],
    "Algeria":        ["Algeria"],
    "Ghana":          ["Ghana"],
    "Congo":          ["DR Congo"],
    "Mali":           ["Mali"],
    "Angola":         ["Angola"],
    "Tanzania":       ["Tanzania"],
    "Mozambique":     ["Mozambique"],
    "Kenya":          ["Kenya"],
    "Zambia":         ["Zambia"],
    "Zimbabwe":       ["Zimbabwe"],
    # Châu Đại Dương
    "New Zealand":    ["New Zealand"],
    "New Caledonia":  ["New Caledonia"],
}

# Tạo reverse map: english name (lowercase) → Vietnamese name
_EN_TO_VN: dict[str, str] = {}
for vn, en_list in TEAM_VN_MAP.items():
    for en in en_list:
        _EN_TO_VN[en.lower()] = vn


def team_vn_name(api_name: str) -> str:
    """Chuyển tên tiếng Anh từ API → tên tiếng Việt nếu có."""
    return _EN_TO_VN.get(api_name.lower(), api_name)


def find_team_api_names(search: str) -> list[str]:
    """
    Tìm tên tiếng Anh của đội dựa vào search string (VN hoặc EN).
    Trả về list các tên có thể dùng để so sánh với API.
    """
    s = search.strip().lower()

    # Tìm chính xác tên VN
    for vn_key, en_list in TEAM_VN_MAP.items():
        if vn_key.lower() == s:
            return [e.lower() for e in en_list]

    # Tìm partial match VN
    candidates = []
    for vn_key, en_list in TEAM_VN_MAP.items():
        if s in vn_key.lower() or vn_key.lower() in s:
            candidates.extend([e.lower() for e in en_list])

    # Tìm partial match EN
    for vn_key, en_list in TEAM_VN_MAP.items():
        for en in en_list:
            if s in en.lower() or en.lower() in s:
                if en.lower() not in candidates:
                    candidates.append(en.lower())

    return candidates


# ── ESPN API helpers ──────────────────────────────────────────────────────────

STATUS_MAP = {
    "STATUS_SCHEDULED": "SCHEDULED",
    "STATUS_FIRST_HALF": "IN_PLAY",
    "STATUS_HALFTIME": "PAUSED",
    "STATUS_SECOND_HALF": "IN_PLAY",
    "STATUS_EXTRA_TIME": "IN_PLAY",
    "STATUS_PENALTY_SHOOTOUT": "IN_PLAY",
    "STATUS_FINAL": "FINISHED",
    "STATUS_FULL_TIME": "FINISHED",
    "STATUS_POSTPONED": "POSTPONED",
    "STATUS_CANCELED": "CANCELLED",
    "STATUS_CANCELLED": "CANCELLED",
    "STATUS_SUSPENDED": "SUSPENDED",
}

STAGE_MAP = {
    "group-stage": "GROUP_STAGE",
    "round-of-32": "LAST_32",
    "round-of-16": "LAST_16",
    "quarterfinal": "QUARTER_FINALS",
    "quarter-final": "QUARTER_FINALS",
    "semifinal": "SEMI_FINALS",
    "semi-final": "SEMI_FINALS",
    "third-place": "THIRD_PLACE",
    "final": "FINAL",
}


def _utc_to_vn(utc_str: str) -> datetime:
    """Chuyển ISO UTC string → datetime Vietnam (UTC+7)."""
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return dt.astimezone(VN_TZ)


def _date_param(date_str: str) -> str:
    return date_str.replace("-", "")


def _vn_date_window(date_str: str) -> tuple[str, str]:
    """Return ESPN date range wide enough to cover a full Vietnam day."""
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    start = target - timedelta(days=1)
    end = target + timedelta(days=1)
    return _date_param(start.isoformat()), _date_param(end.isoformat())


def _score(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _team_name(team: dict) -> str:
    return team.get("displayName") or team.get("shortDisplayName") or team.get("name") or ""


def _pick_competitor(competitors: list[dict], side: str) -> dict:
    for competitor in competitors:
        if competitor.get("homeAway") == side:
            return competitor
    return {}


def _group_label(event: dict) -> str:
    groups = event.get("groups") or {}
    if isinstance(groups, dict):
        name = groups.get("name") or groups.get("abbreviation")
        if name:
            return str(name)
    return ""


def _stage(event: dict) -> str:
    slug = (event.get("season") or {}).get("slug") or ""
    return STAGE_MAP.get(slug, slug.upper().replace("-", "_"))


def _winner(home: dict, away: dict, status: str) -> str | None:
    if status != "FINISHED":
        return None
    if home.get("winner"):
        return "HOME_TEAM"
    if away.get("winner"):
        return "AWAY_TEAM"
    return "DRAW"


def _normalize_match(raw: dict) -> dict:
    """Chuẩn hoá 1 match object từ ESPN về schema nội bộ."""
    competitions = raw.get("competitions") or []
    comp = competitions[0] if competitions else {}
    utc_str = comp.get("date") or comp.get("startDate") or raw.get("date") or ""
    vn_dt   = _utc_to_vn(utc_str) if utc_str else None

    competitors = comp.get("competitors") or []
    home = _pick_competitor(competitors, "home")
    away = _pick_competitor(competitors, "away")
    home_team = home.get("team") or {}
    away_team = away.get("team") or {}

    status_type = (comp.get("status") or {}).get("type") or {}
    status_name = status_type.get("name") or ""
    status = STATUS_MAP.get(status_name, "LIVE" if status_type.get("state") == "in" else "SCHEDULED")

    goals = []
    yellow_cards = []
    red_cards = []

    for detail in comp.get("details") or []:
        type_text = (detail.get("type", {}).get("text", "") or "").lower()
        athletes  = detail.get("athletes") or []
        team      = detail.get("team") or {}
        player    = (athletes[0] if athletes else {}).get("displayName", "")
        minute    = detail.get("clock", {}).get("displayValue") or detail.get("displayTime") or "?"
        team_name_val = _team_name(team)

        if "goal" in type_text:
            goals.append({
                "minute":  minute,
                "team":    team_name_val,
                "scorer":  player,
                "type":    "OWN_GOAL" if detail.get("ownGoal") else ("PENALTY" if detail.get("penaltyKick") else "NORMAL"),
            })
        elif "yellow-red" in type_text or "second yellow" in type_text:
            # Thẻ vàng thứ 2 → thực chất là thẻ đỏ
            red_cards.append({"minute": minute, "team": team_name_val, "player": player, "type": "SECOND_YELLOW"})
        elif "yellow" in type_text:
            yellow_cards.append({"minute": minute, "team": team_name_val, "player": player})
        elif "red" in type_text:
            red_cards.append({"minute": minute, "team": team_name_val, "player": player, "type": "DIRECT_RED"})

    home_score = _score(home.get("score"))
    away_score = _score(away.get("score"))

    return {
        "id":            int(raw.get("id") or comp.get("id") or 0),
        "utc_date":      utc_str,
        "vn_date":       vn_dt.strftime("%Y-%m-%d") if vn_dt else None,
        "vn_time":       vn_dt.strftime("%H:%M") if vn_dt else None,
        "vn_datetime":   vn_dt,
        "status":        status,
        "stage":         _stage(raw),
        "group":         _group_label(raw),
        "matchday":      raw.get("season", {}).get("type"),
        "home_team":     _team_name(home_team),
        "home_team_tla": home_team.get("abbreviation", ""),
        "away_team":     _team_name(away_team),
        "away_team_tla": away_team.get("abbreviation", ""),
        "home_score":    home_score,
        "away_score":    away_score,
        "ht_home":       None,
        "ht_away":       None,
        "winner":        _winner(home, away, status),
        "goals":         goals,
        "yellow_cards":  yellow_cards,
        "red_cards":     red_cards,
    }


async def _get(url: str, params: dict = None) -> dict | list | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params or {})
            if resp.status_code == 429:
                logger.warning("ESPN API rate limit hit.")
                return None
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("ESPN API error [%s]: %s", url, e)
        return None


# ── Public fetch functions ────────────────────────────────────────────────────

def _normalize_fifa_match(raw: dict) -> dict | None:
    """Chuyển đổi 1 FIFA calendar match sang schema nội bộ."""
    utc_str = raw.get("Date") or ""
    if not utc_str:
        return None
    try:
        vn_dt = _utc_to_vn(utc_str)
    except Exception:
        return None

    home = raw.get("Home") or {}
    away = raw.get("Away") or {}

    def _fifa_name(team: dict) -> str:
        for n in (team.get("TeamName") or []):
            if n.get("Locale", "").lower().startswith("en"):
                return n.get("Description", "")
        return team.get("Abbreviation", "")

    home_name   = _fifa_name(home)
    away_name   = _fifa_name(away)
    home_score  = home.get("Score")
    away_score  = away.get("Score")

    # Status từ FIFA fields
    winner      = raw.get("Winner")
    result_type = raw.get("ResultType", 0)
    match_status = raw.get("MatchStatus", 0)
    period      = raw.get("Period", 0)

    if result_type == 1 and (winner is not None or home_score is not None):
        status = "FINISHED"
    elif match_status == 1 or period in (1, 2, 3, 4, 5):
        status = "IN_PLAY"
    else:
        status = "SCHEDULED"

    # Group / Stage label
    group_label = next(
        (g["Description"] for g in (raw.get("GroupName") or []) if g.get("Locale","").lower().startswith("en")),
        ""
    )
    stage_label = next(
        (s["Description"] for s in (raw.get("StageName") or []) if s.get("Locale","").lower().startswith("en")),
        ""
    )

    # Venue
    stadium     = raw.get("Stadium") or {}
    venue_name  = next((n["Description"] for n in (stadium.get("Name") or []) if n.get("Locale","").lower().startswith("en")), "")
    city_name   = next((n["Description"] for n in (stadium.get("CityName") or []) if n.get("Locale","").lower().startswith("en")), "")
    venue       = ", ".join(filter(None, [venue_name, city_name]))

    # Winner label
    home_id = str(home.get("IdTeam", ""))
    away_id = str(away.get("IdTeam", ""))
    if winner == home_id:
        winner_label = "HOME_TEAM"
    elif winner == away_id:
        winner_label = "AWAY_TEAM"
    elif status == "FINISHED":
        winner_label = "DRAW"
    else:
        winner_label = None

    fifa_id  = str(raw.get("IdMatch", ""))
    stage_id = str(raw.get("IdStage", ""))

    return {
        "id":             fifa_id,
        "fifa_match_id":  fifa_id,
        "fifa_stage_id":  stage_id,
        "utc_date":       utc_str,
        "vn_date":        vn_dt.strftime("%Y-%m-%d"),
        "vn_time":        vn_dt.strftime("%H:%M"),
        "vn_datetime":    vn_dt,
        "status":         status,
        "stage":          stage_label,
        "group":          group_label,
        "matchday":       raw.get("MatchDay"),
        "home_team":      home_name,
        "home_team_tla":  home.get("Abbreviation", ""),
        "away_team":      away_name,
        "away_team_tla":  away.get("Abbreviation", ""),
        "home_score":     home_score,
        "away_score":     away_score,
        "ht_home":        None,
        "ht_away":        None,
        "winner":         winner_label,
        "goals":          [],
        "yellow_cards":   [],
        "red_cards":      [],
        "venue":          venue,
        "attendance":     raw.get("Attendance"),
    }


_FIFA_MATCH_CACHE: list[dict] | None = None
_FIFA_CACHE_TS: float = 0.0
_FIFA_CACHE_TTL = 180.0  # 3 phút


async def _get_all_fifa_matches_cached() -> list[dict]:
    """
    Fetch toàn bộ WC 2026 matches từ FIFA, có cache 3 phút.
    WC 2026 có 104 trận, dùng count=200 để lấy tất cả trong 1 request.
    FIFA API ContinuationToken bị lỗi loop vô hạn → không dùng pagination.
    """
    import time
    global _FIFA_MATCH_CACHE, _FIFA_CACHE_TS
    now = time.monotonic()
    if _FIFA_MATCH_CACHE is not None and (now - _FIFA_CACHE_TS) < _FIFA_CACHE_TTL:
        return _FIFA_MATCH_CACHE

    from config import WC_FIFA_API_BASE, WC_FIFA_COMPETITION, WC_FIFA_SEASON
    params = {
        "idSeason":      WC_FIFA_SEASON,
        "idCompetition": WC_FIFA_COMPETITION,
        "count":         200,       # đủ cho 104 trận WC 2026
        "language":      "en",
    }
    data = await _get(f"{WC_FIFA_API_BASE}/calendar/matches", params=params)
    results = []
    if data:
        for raw in (data.get("Results") or []):
            m = _normalize_fifa_match(raw)
            if m:
                results.append(m)

    if results:
        _FIFA_MATCH_CACHE = results
        _FIFA_CACHE_TS = now
        logger.debug("FIFA cache updated: %d matches", len(results))
    return results


async def _fetch_fifa_matches_for_date(date_str: str) -> list[dict]:
    """
    Lấy danh sách trận từ FIFA calendar API cho 1 ngày VN.
    Dùng cache để tránh gọi API nhiều lần.
    """
    all_matches = await _get_all_fifa_matches_cached()
    return [m for m in all_matches if m.get("vn_date") == date_str]



async def fetch_matches_by_date(date_str: str) -> list[dict]:
    """
    Lấy tất cả trận WC trong ngày VN.
    - Nguồn chính: FIFA calendar API (có cả quá khứ + tương lai)
    - Enrich goals/cards: FIFA live/football endpoint
    """
    matches = await _fetch_fifa_matches_for_date(date_str)
    if not matches:
        logger.warning("FIFA returned 0 matches for %s, falling back to ESPN", date_str)
        # Fallback ESPN (chỉ hoạt động với ngày gần đây)
        start, end = _vn_date_window(date_str)
        data = await _get(
            f"{WC_API_BASE_URL}/scoreboard",
            params={"dates": f"{start}-{end}", "limit": 50},
        )
        if data:
            raw_matches = [_normalize_match(m) for m in data.get("events", [])]
            matches = sorted(
                [m for m in raw_matches if m.get("vn_date") == date_str],
                key=lambda m: m.get("vn_time") or "",
            )

    # Enrich goals/cards cho trận đang/đã kết thúc
    active = [m for m in matches if m["status"] in ("FINISHED", "IN_PLAY", "PAUSED", "LIVE")]
    if active:
        await asyncio.gather(
            *[_enrich_match_from_summary(m) for m in active],
            return_exceptions=True,
        )

    return matches



async def _enrich_match_from_summary(match: dict) -> None:
    """
    Fetch FIFA live/football endpoint để lấy goals và bookings chi tiết.

    FIFA API structure:
      HomeTeam.Goals[]     → { Type, IdPlayer, Minute, IdAssistPlayer }
      HomeTeam.Bookings[]  → { Card (1=yellow,2=yr,3=red), IdPlayer, Minute }
      HomeTeam.Players[]   → { IdPlayer, PlayerName[].Description }
    """
    from config import WC_FIFA_API_BASE, WC_FIFA_COMPETITION, WC_FIFA_SEASON, WC_FIFA_STAGE

    fifa_id  = match.get("fifa_match_id")
    stage_id = match.get("fifa_stage_id") or WC_FIFA_STAGE
    if not fifa_id:
        logger.debug("No fifa_match_id for match %s, skipping FIFA enrich", match.get("id"))
        return

    url = f"{WC_FIFA_API_BASE}/live/football/{WC_FIFA_COMPETITION}/{WC_FIFA_SEASON}/{stage_id}/{fifa_id}"
    data = await _get(url, params={"language": "en"})
    if not data:
        logger.debug("No FIFA data for match %s", fifa_id)
        return

    # Combined players từ cả 2 đội (để resolve OWN GOAL player đội đối phương)
    home_data_ref = data.get("HomeTeam") or {}
    away_data_ref = data.get("AwayTeam") or {}
    all_players_combined = (home_data_ref.get("Players") or []) + (away_data_ref.get("Players") or [])

    def _get_player_name(players: list, player_id: str, fallback_combined: bool = True) -> str:
        """Tìm tên cầu thủ từ player list theo ID. Fallback sang combined list nếu không tìm được."""
        search_lists = [players]
        if fallback_combined:
            search_lists.append(all_players_combined)
        for plist in search_lists:
            for p in (plist or []):
                if str(p.get("IdPlayer", "")) == str(player_id):
                    names = p.get("PlayerName") or p.get("ShortName") or []
                    for name_obj in names:
                        if name_obj.get("Locale", "").lower().startswith("en"):
                            return name_obj.get("Description", "")
        return ""  # Trả về chuỗi rỗng nếu không tìm được, sẽ hiển thị là "?"

    def _parse_team(team_data: dict, team_name_str: str) -> tuple[list, list, list]:
        """Parse Goals, Bookings từ 1 đội. Trả về (goals, yellow_cards, red_cards)."""
        players   = team_data.get("Players") or []
        goals_out = []
        yellow    = []
        red       = []

        for g in (team_data.get("Goals") or []):
            player_id = g.get("IdPlayer", "")
            gtype   = g.get("Type", 1)
            minute  = str(g.get("Minute") or "?")
            assist_id = g.get("IdAssistPlayer") or ""

            # FIFA goal Type: 3=OWN_GOAL, others=NORMAL/PENALTY/HEADER (đều là "bàn thắng")
            if gtype == 3:
                goal_type = "OWN_GOAL"
                # OWN GOAL: scorer là cầu thủ đội bạn, tìm trong combined list
                scorer = _get_player_name([], player_id, fallback_combined=True)
            else:
                goal_type = "NORMAL"
                scorer = _get_player_name(players, player_id)

            assist = _get_player_name(players, assist_id) if assist_id else ""

            goals_out.append({
                "minute": minute,
                "team":   team_name_str,
                "scorer": scorer or "?",
                "assist": assist,
                "type":   goal_type,
            })

        for b in (team_data.get("Bookings") or []):
            player = _get_player_name(players, b.get("IdPlayer", "")) or "?"
            minute = str(b.get("Minute") or "?")
            card   = b.get("Card", 1)
            # FIFA Card: 1=yellow, 2=yellow-red (second yellow → đỏ), 3=direct red
            if card == 2:
                red.append({"minute": minute, "team": team_name_str,
                            "player": player, "type": "SECOND_YELLOW"})
            elif card == 3:
                red.append({"minute": minute, "team": team_name_str,
                            "player": player, "type": "DIRECT_RED"})
            else:
                yellow.append({"minute": minute, "team": team_name_str, "player": player})

        return goals_out, yellow, red


    home_data = data.get("HomeTeam") or {}
    away_data = data.get("AwayTeam") or {}

    # Lấy tên đội từ FIFA (có thể khác ESPN)
    home_names = home_data.get("TeamName") or []
    away_names = away_data.get("TeamName") or []
    home_name  = next((n["Description"] for n in home_names if n.get("Locale","").startswith("en")), match.get("home_team","Home"))
    away_name  = next((n["Description"] for n in away_names if n.get("Locale","").startswith("en")), match.get("away_team","Away"))

    home_goals, home_yellow, home_red = _parse_team(home_data, home_name)
    away_goals, away_yellow, away_red = _parse_team(away_data, away_name)

    all_goals  = sorted(home_goals  + away_goals,  key=lambda x: _minute_sort(x.get("minute","")))
    all_yellow = sorted(home_yellow + away_yellow, key=lambda x: _minute_sort(x.get("minute","")))
    all_red    = sorted(home_red    + away_red,    key=lambda x: _minute_sort(x.get("minute","")))

    if all_goals:
        match["goals"] = all_goals
    if all_yellow:
        match["yellow_cards"] = all_yellow
    if all_red:
        match["red_cards"] = all_red

    logger.info("FIFA enriched match %s: %d goals, %d yellow, %d red",
                fifa_id, len(all_goals), len(all_yellow), len(all_red))


def _minute_sort(minute_str: str) -> int:
    """Chuyển '45+2'' → 45, '90+3'' → 90 để sort."""
    try:
        return int(minute_str.rstrip("'").split("+")[0])
    except Exception:
        return 999


async def fetch_today_matches() -> list[dict]:
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    return await fetch_matches_by_date(today)


async def fetch_all_wc_matches() -> list[dict]:
    """Lấy toàn bộ lịch WC 2026 từ FIFA calendar API (cached)."""
    return await _get_all_fifa_matches_cached()


async def fetch_team_matches(team_search: str) -> tuple[list[dict], str]:
    """
    Lấy lịch thi đấu của 1 đội trong WC 2026.
    Trả về (matches, matched_team_name).
    """
    all_matches = await fetch_all_wc_matches()
    if not all_matches:
        return [], ""

    api_names = find_team_api_names(team_search)
    if not api_names:
        api_names = [team_search.lower()]

    result = []
    matched_name = ""
    for match in all_matches:
        home_lower = match["home_team"].lower()
        away_lower = match["away_team"].lower()
        is_match = any(
            n in home_lower or home_lower in n or
            n in away_lower or away_lower in n
            for n in api_names
        )
        if is_match:
            result.append(match)
            if not matched_name:
                # Lấy tên đội mà user tìm
                for n in api_names:
                    if n in home_lower or home_lower in n:
                        matched_name = match["home_team"]
                        break
                    if n in away_lower or away_lower in n:
                        matched_name = match["away_team"]
                        break

    return result, matched_name


async def fetch_live_matches() -> list[dict]:
    """Lấy các trận đang diễn ra."""
    matches = await fetch_today_matches()
    return [m for m in matches if m["status"] in {"LIVE", "IN_PLAY", "PAUSED"}]


async def fetch_finished_today() -> list[dict]:
    """Lấy kết quả các trận đã kết thúc hôm nay."""
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    matches = await fetch_matches_by_date(today)
    return [m for m in matches if m["status"] == "FINISHED"]


async def fetch_standings() -> list[dict]:
    """Lấy bảng xếp hạng các bảng (group stage)."""
    data = await _get(
        WC_STANDINGS_URL,
        params={"region": "us", "lang": "en", "contentorigin": "espn"},
    )
    if not data:
        return []

    standings = []
    for group in data.get("children", []):
        table = []
        entries = (group.get("standings") or {}).get("entries") or []
        for index, entry in enumerate(entries, start=1):
            stats = {
                stat.get("name"): stat.get("value", 0)
                for stat in entry.get("stats", [])
            }
            table.append({
                "position": index,
                "team": {"name": _team_name(entry.get("team") or {})},
                "points": int(stats.get("points", 0) or 0),
                "goalDifference": int(stats.get("pointDifferential", 0) or 0),
                "goalsFor": int(stats.get("pointsFor", 0) or 0),
            })
        standings.append({
            "group": group.get("name") or group.get("abbreviation") or "",
            "table": table,
        })
    return standings
