#!/usr/bin/env python3
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api_server.py"
HTML = ROOT / "web" / "market_analytics.html"


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def main() -> None:
    require(API.exists(), "api_server.py missing")
    require(HTML.exists(), "web/market_analytics.html missing")
    api = API.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    require('"/analytics/market"' in api, "web route /analytics/market missing")
    require('"/api/analytics/market-pulse"' in api, "API route /api/analytics/market-pulse missing")
    require("handle_market_pulse_1824b" in api, "market pulse handler missing")
    require("handle_market_analytics_page_1824b" in api, "analytics page handler missing")
    require("vortex.market_pulse.api.v1" in api, "market pulse schema missing")
    require("_market_pulse_watch_summary_1824b" in api, "watchlist summary helper missing")
    require("_market_pulse_near_entries_1824b" in api, "near entries helper missing")
    require("_market_pulse_human_summary_1824b" in api, "human summary helper missing")
    require("Cache-Control" in api and "no-store" in api, "no-store headers missing")
    require("Content-Security-Policy" in api, "analytics HTML CSP missing")

    require("VORTEX MARKET PULSE" in html, "page title missing")
    for label in ("Индексы рынка", "Фьючерсы", "Почему бот не входит?", "Pump Advisor"):
        require(label in html, f"HTML block missing: {label}")
    require("/api/analytics/market-pulse" in html, "HTML does not fetch market pulse API")
    require("setInterval" in html, "auto-refresh missing")
    require("read-only" in html.lower(), "read-only meaning missing")

    dangerous_button = re.compile(r"<button[^>]*>\s*(BUY|SELL|OPEN|CLOSE|КУПИТЬ|ПРОДАТЬ|ОТКРЫТЬ|ЗАКРЫТЬ)\s*</button>", re.I)
    require(not dangerous_button.search(html), "trading action button found")
    for forbidden in (
        "/api/debug/open-futures",
        "/api/debug/close-futures",
        "/api/debug/open-spot",
        "/api/debug/close-spot",
        "/api/debug/risk/reset",
    ):
        require(forbidden not in html, f"forbidden mutating endpoint in HTML: {forbidden}")

    print("OK: smoke_market_analytics_page")


if __name__ == "__main__":
    main()
