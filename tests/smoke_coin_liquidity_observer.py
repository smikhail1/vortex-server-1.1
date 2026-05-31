import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import coin_liquidity_observer as observer

main_text = (ROOT / "main.py").read_text(encoding="utf-8")
api_text = (ROOT / "api_server.py").read_text(encoding="utf-8")
html_text = (ROOT / "web" / "market_analytics.html").read_text(encoding="utf-8")
module_text = (ROOT / "coin_liquidity_observer.py").read_text(encoding="utf-8")

assert observer.SCHEMA == "vortex.coin_liquidity.shadow.v1"
assert 'name="coin_liquidity_observer"' in main_text
assert "/api/analytics/coin-liquidity" in api_text
assert '"coin_liquidity": self._market_pulse_coin_liquidity_1824e' in api_text
assert "Ликвидность / поток сделок" in html_text
assert "SHADOW · READ-ONLY" in html_text
assert '"block_longs": False' in module_text
assert '"block_shorts": False' in module_text
assert '"read_only": True' in module_text
assert "smart_money_bias" not in module_text
assert "/api/v2/mix/market/taker-buy-sell" in module_text
assert "/api/v2/mix/market/open-interest" in module_text

item = observer.build_shadow_item(
    symbol="BTCUSDT",
    futures_ticker={"lastPr": "100.1", "change24h": "0.02", "fundingRate": "0.0001"},
    spot_ticker={"lastPr": "100"},
    oi_value=110.0,
    previous_oi=100.0,
    taker_buy_volume=70.0,
    taker_sell_volume=30.0,
)
assert item["read_only"] is True
assert item["block_longs"] is False
assert item["block_shorts"] is False
assert item["liquidity_bias"] in {"mild_long", "strong_long"}

partial = observer.build_shadow_item(
    symbol="ARBUSDT",
    futures_ticker={"lastPr": "0.10", "change24h": "-0.01", "fundingRate": "0.0001"},
    spot_ticker={"lastPr": "0.10"},
    oi_value=100.0,
    previous_oi=99.0,
    taker_buy_volume=0.0,
    taker_sell_volume=0.0,
    taker_available=False,
)
assert partial["available"] is True
assert partial["partial"] is True
assert partial["taker_buy_pct"] is None
assert "taker_data_unavailable" in partial["warnings"]
assert partial["block_longs"] is False
assert partial["block_shorts"] is False

print("OK: smoke_coin_liquidity_observer")
