from typing import Dict, List

from config import CONFIG
from validators import safe_float, safe_int, safe_str


class WatchlistBuilder:
    """
    Terminal watchlist builder.

    VORTEX 1.5:
    - отображает не только "ready", но и реальные WATCH-кандидаты;
    - не открывает сделки;
    - нужен для UI/Android/API слоя.
    """

    def __init__(self, strategy, logger=None) -> None:
        self.strategy = strategy
        self.logger = logger

    def _status_from_analysis(self, analysis: Dict[str, object], current: Dict[str, object]) -> str:
        setup_type = safe_str(analysis.get("setup_type"))
        if analysis.get("should_open"):
            if "momentum" in setup_type:
                return "ready"
            return "watch"

        blocked_reason = safe_str(analysis.get("blocked_reason"))
        if blocked_reason.startswith("momentum_watch:"):
            return "momentum_watch"
        price = safe_float(current.get("price"))
        ema20 = safe_float(current.get("ema20"))
        atr = safe_float(current.get("atr"))

        if blocked_reason:
            if blocked_reason.startswith("score<") and price > 0 and ema20 > 0 and atr > 0:
                if abs(price - ema20) <= atr * 0.75:
                    return "near_entry"
            return "blocked"

        return "watch"

    def _build_item(
        self,
        symbol: str,
        market: str,
        current: Dict[str, object],
        analysis: Dict[str, object],
    ) -> Dict[str, object]:
        score = safe_int(analysis.get("score"), 0)
        status = self._status_from_analysis(analysis, current)
        blocked_reason = safe_str(analysis.get("blocked_reason"))
        args_text = safe_str(analysis.get("args_text")) or blocked_reason
        signal = safe_str(analysis.get("signal"))
        setup_type = safe_str(analysis.get("setup_type"), "-")

        waiting_for = "strategy score / setup"
        trigger_price = 0.0
        invalidation_price = 0.0

        if status == "blocked":
            waiting_for = blocked_reason
        elif status == "momentum_watch":
            waiting_for = blocked_reason.replace("momentum_watch:", "")

        if market == "fut" and hasattr(self.strategy, "momentum"):
            momentum = self.strategy.momentum.evaluate_futures(
                current,
                market_regime=safe_str(current.get("market_regime"), ""),
            )
            if momentum.active:
                trigger_price = momentum.trigger_price
                invalidation_price = momentum.invalidation_price
                if not signal:
                    signal = momentum.side
                if setup_type == "-":
                    setup_type = momentum.setup_type
                if status in {"momentum_watch", "ready"}:
                    args_text = momentum.reason

        return {
            "symbol": safe_str(symbol).upper(),
            "price": round(safe_float(current.get("price")), 8),
            "market": market,
            "side": signal,
            "score": score,
            "setup_type": setup_type,
            "args_text": args_text,
            "status": status,
            "waiting_for": waiting_for,
            "trigger_price": round(safe_float(trigger_price), 8),
            "invalidation_price": round(safe_float(invalidation_price), 8),
            "expires_in_sec": 0,
        }

    def build(
        self,
        ta_data: Dict[str, Dict[str, object]],
        fut_pool: List[str],
        spot_pool: List[str],
        macro_filter: str,
    ) -> List[Dict[str, object]]:
        items: List[Dict[str, object]] = []

        for symbol in fut_pool:
            current = ta_data.get(symbol)
            if not current:
                continue

            analysis = self.strategy.analyze_futures(current, macro_filter)
            item = self._build_item(symbol, "fut", current, analysis)

            if (
                item["status"] in {"ready", "watch", "momentum_watch", "near_entry", "blocked"}
                or item["score"] >= CONFIG.trading.watchlist_min_score
            ):
                items.append(item)

        for symbol in spot_pool:
            current = ta_data.get(symbol)
            if not current:
                continue

            analysis = self.strategy.analyze_spot(current, macro_filter)
            item = self._build_item(symbol, "spot", current, analysis)

            if (
                item["status"] in {"ready", "watch", "momentum_watch", "near_entry", "blocked"}
                or item["score"] >= CONFIG.trading.watchlist_min_score
            ):
                items.append(item)

        if not items:
            for symbol in fut_pool:
                current = ta_data.get(symbol)
                if current:
                    items.append({
                        "symbol": safe_str(symbol).upper(),
                        "price": round(safe_float(current.get("price")), 8),
                        "market": "fut",
                        "side": "",
                        "score": 0,
                        "setup_type": "-",
                        "args_text": "watch fallback",
                        "status": "watch",
                        "waiting_for": "data/strategy",
                        "trigger_price": 0.0,
                        "invalidation_price": 0.0,
                        "expires_in_sec": 0,
                    })

            for symbol in spot_pool:
                current = ta_data.get(symbol)
                if current:
                    items.append({
                        "symbol": safe_str(symbol).upper(),
                        "price": round(safe_float(current.get("price")), 8),
                        "market": "spot",
                        "side": "BUY",
                        "score": 0,
                        "setup_type": "-",
                        "args_text": "watch fallback",
                        "status": "watch",
                        "waiting_for": "data/strategy",
                        "trigger_price": 0.0,
                        "invalidation_price": 0.0,
                        "expires_in_sec": 0,
                    })

        status_rank = {
            "ready": 5,
            "watch": 4,
            "momentum_watch": 4,
            "near_entry": 3,
            "blocked": 2,
            "expired": 1,
        }

        items.sort(
            key=lambda x: (
                status_rank.get(safe_str(x.get("status")), 0),
                safe_int(x.get("score"), 0),
            ),
            reverse=True,
        )

        limit = safe_int(getattr(CONFIG.trading, "watchlist_display_limit", 40), 40)
        limit = max(20, min(80, limit))
        return items[:limit]
