"""
wc_client.py – Fetch dữ liệu World Cup 2026 từ ESPN public endpoints.
"""
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
    # Châu Đại Dương
    "New Zealand":    ["New Zealand"],
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

async def fetch_matches_by_date(date_str: str) -> list[dict]:
    """Lấy tất cả trận WC trong ngày Việt Nam (YYYY-MM-DD)."""
    start, end = _vn_date_window(date_str)
    data = await _get(
        f"{WC_API_BASE_URL}/scoreboard",
        params={"dates": f"{start}-{end}", "limit": 50},
    )
    if not data:
        return []
    matches = [_normalize_match(m) for m in data.get("events", [])]
    return sorted(
        [m for m in matches if m.get("vn_date") == date_str],
        key=lambda m: m.get("vn_time") or "",
    )


async def fetch_today_matches() -> list[dict]:
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    return await fetch_matches_by_date(today)


async def fetch_all_wc_matches() -> list[dict]:
    """Lấy toàn bộ lịch WC 2026."""
    data = await _get(
        f"{WC_API_BASE_URL}/scoreboard",
        params={
            "dates": f"{_date_param(WC_START_DATE.isoformat())}-{_date_param(WC_END_DATE.isoformat())}",
            "limit": 200,
        },
    )
    if not data:
        return []
    return [_normalize_match(m) for m in data.get("events", [])]


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
