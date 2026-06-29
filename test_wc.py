"""Quick test for current WC state."""
import asyncio
import logging
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
logging.basicConfig(level=logging.WARNING)

from wc_client import fetch_matches_by_date, fetch_standings
from wc_notifier import build_daily_wc_message, build_result_message, flag, team_vn_name, build_standings_message

async def test():
    today = "2026-06-29"
    print("=== Today:", today, "===")
    matches = await fetch_matches_by_date(today)
    print(f"Matches: {len(matches)}")
    for m in matches:
        ht = m.get("home_team")
        at = m.get("away_team")
        st = m.get("status")
        hs = m.get("home_score")
        as_ = m.get("away_score")
        ng = len(m.get("goals") or [])
        ny = len(m.get("yellow_cards") or [])
        nr = len(m.get("red_cards") or [])
        print(f"  {m['vn_time']} | {ht} vs {at} | {st} | {hs}-{as_} | G={ng} Y={ny} R={nr}")

    print()
    msg = build_daily_wc_message(matches, today)
    print(msg)
    print()

    if matches:
        finished = [m for m in matches if m.get("status") == "FINISHED"]
        if finished:
            print("=== Result message ===")
            print(build_result_message(finished[0]))

    print()
    print("=== Flag/VN tests ===")
    for t in ["Curaçao", "Cuw", "CUW", "Saudi Arabia", "KSA", "IR Iran", "Haiti"]:
        print(f"  {t}: flag={flag(t)} vn={team_vn_name(t)}")

asyncio.run(test())
