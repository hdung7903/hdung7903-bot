"""Debug how many FIFA matches and which dates they cover."""
import asyncio, logging
logging.basicConfig(level=logging.WARNING)
import os; os.environ["PYTHONIOENCODING"] = "utf-8"

from wc_client import _get_all_fifa_matches_cached

async def test():
    matches = await _get_all_fifa_matches_cached()
    print(f"Total FIFA matches: {len(matches)}")
    by_date = {}
    for m in matches:
        d = m.get("vn_date", "?")
        by_date[d] = by_date.get(d, 0) + 1
    for d in sorted(by_date):
        print(f"  {d}: {by_date[d]} matches")

asyncio.run(test())
