#!/usr/bin/env bash
set -e

echo "== RUN SCREENER TESTS =="
python3 test_screener_scenarios.py

echo
echo "== QUICK RUNTIME CHECK =="
python3 - <<'PY'
import asyncio
from market_screener import MarketScreener

async def main():
    s = MarketScreener()
    universe = await s.refresh()
    debug = await s.get_debug_info()

    print("Universe size:", len(universe))
    print("Top 15:", universe[:15])

    banned = {"USDCUSDT", "FDUSDUSDT", "USD1USDT", "XAUTUSDT", "PAXGUSDT", "币安人生USDT", "BARDUSDT"}
    bad_hits = [x for x in universe[:20] if x in banned]
    print("Banned hits in top20:", bad_hits)

    if bad_hits:
        raise SystemExit("BAD UNIVERSE: banned symbols detected in top20")

    print("Debug:", debug)

asyncio.run(main())
PY