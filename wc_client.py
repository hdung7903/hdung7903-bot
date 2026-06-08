"""
wc_client.py – Fetch dữ liệu World Cup 2026 từ football-data.org API.

Đăng ký API key miễn phí tại: https://www.football-data.org/client/register
Free tier: 10 req/min, đủ dùng cho bot.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from config import FOOTBALL_API_KEY, FOOTBALL_API_URL, WC_COMPETITION_CODE, TIMEZONE

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


# ── API helpers ───────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {"X-Auth-Token": FOOTBALL_API_KEY} if FOOTBALL_API_KEY else {}


def _utc_to_vn(utc_str: str) -> datetime:
    """Chuyển ISO UTC string → datetime Vietnam (UTC+7)."""
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return dt.astimezone(VN_TZ)


def _normalize_match(raw: dict) -> dict:
    """Chuẩn hoá 1 match object từ API."""
    utc_str = raw.get("utcDate", "")
    vn_dt   = _utc_to_vn(utc_str) if utc_str else None

    home = raw.get("homeTeam", {})
    away = raw.get("awayTeam", {})
    score = raw.get("score", {})
    ft   = score.get("fullTime", {})
    ht   = score.get("halfTime", {})

    # Goals / scorers
    goals = []
    for g in raw.get("goals", []):
        goals.append({
            "minute":  g.get("minute"),
            "team":    g.get("team", {}).get("name", ""),
            "scorer":  g.get("scorer", {}).get("name", ""),
            "type":    g.get("type", "NORMAL"),  # NORMAL, OWN_GOAL, PENALTY
        })

    return {
        "id":           raw.get("id"),
        "utc_date":     utc_str,
        "vn_date":      vn_dt.strftime("%Y-%m-%d") if vn_dt else None,
        "vn_time":      vn_dt.strftime("%H:%M") if vn_dt else None,
        "vn_datetime":  vn_dt,
        "status":       raw.get("status", "SCHEDULED"),
        "stage":        raw.get("stage", ""),
        "group":        raw.get("group") or "",
        "matchday":     raw.get("matchday"),
        "home_team":    home.get("name", ""),
        "home_team_tla": home.get("tla", ""),
        "away_team":    away.get("name", ""),
        "away_team_tla": away.get("tla", ""),
        "home_score":   ft.get("home"),
        "away_score":   ft.get("away"),
        "ht_home":      ht.get("home"),
        "ht_away":      ht.get("away"),
        "winner":       score.get("winner"),  # HOME_TEAM, AWAY_TEAM, DRAW, null
        "goals":        goals,
    }


async def _get(endpoint: str, params: dict = None) -> dict | list | None:
    url = f"{FOOTBALL_API_URL}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_headers(), params=params or {})
            if resp.status_code == 429:
                logger.warning("Football API rate limit hit.")
                return None
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("Football API error [%s]: %s", endpoint, e)
        return None


# ── Public fetch functions ────────────────────────────────────────────────────

async def fetch_matches_by_date(date_str: str) -> list[dict]:
    """Lấy tất cả trận WC trong ngày (YYYY-MM-DD)."""
    data = await _get(
        f"/competitions/{WC_COMPETITION_CODE}/matches",
        params={"dateFrom": date_str, "dateTo": date_str},
    )
    if not data:
        return []
    matches = data.get("matches", [])
    return [_normalize_match(m) for m in matches]


async def fetch_today_matches() -> list[dict]:
    from datetime import date
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    return await fetch_matches_by_date(today)


async def fetch_all_wc_matches() -> list[dict]:
    """Lấy toàn bộ lịch WC 2026."""
    from config import WC_START_DATE, WC_END_DATE
    data = await _get(
        f"/competitions/{WC_COMPETITION_CODE}/matches",
        params={
            "dateFrom": WC_START_DATE.isoformat(),
            "dateTo":   WC_END_DATE.isoformat(),
        },
    )
    if not data:
        return []
    return [_normalize_match(m) for m in data.get("matches", [])]


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
    data = await _get(
        f"/competitions/{WC_COMPETITION_CODE}/matches",
        params={"status": "LIVE,IN_PLAY,PAUSED"},
    )
    if not data:
        return []
    return [_normalize_match(m) for m in data.get("matches", [])]


async def fetch_finished_today() -> list[dict]:
    """Lấy kết quả các trận đã kết thúc hôm nay."""
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    matches = await fetch_matches_by_date(today)
    return [m for m in matches if m["status"] == "FINISHED"]


async def fetch_standings() -> list[dict]:
    """Lấy bảng xếp hạng các bảng (group stage)."""
    data = await _get(f"/competitions/{WC_COMPETITION_CODE}/standings")
    if not data:
        return []
    return data.get("standings", [])
