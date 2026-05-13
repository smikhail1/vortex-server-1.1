from typing import Dict
from validators import safe_bool, safe_int, safe_str

class DecisionEngine:
    def __init__(self, logger=None) -> None:
        self.logger = logger

    def evaluate(self, symbol: str, market: str, analysis: Dict[str, object], risk_manager, current_open_count: int, max_open_positions: int) -> Dict[str, object]:
        sym = safe_str(symbol).upper()
        mkt = safe_str(market).lower()
        if not analysis:
            return {"allow": False, "reason": "empty analysis", "symbol": sym, "market": mkt, "analysis": {}}

        allowed, risk_reason = risk_manager.can_open(sym, mkt)
        if not allowed:
            return {"allow": False, "reason": risk_reason, "symbol": sym, "market": mkt, "analysis": analysis}

        if current_open_count >= max_open_positions:
            return {"allow": False, "reason": "max open positions reached", "symbol": sym, "market": mkt, "analysis": analysis}

        setup_type = safe_str(analysis.get("setup_type"))
        if "dead" in setup_type and "momentum" in setup_type:
            if self.logger: self.logger.info("STRATEGY", f"quality filter: momentum blocked in DEAD regime for {sym}", {})
            return {"allow": False, "reason": "Blocked: Momentum in DEAD regime", "symbol": sym, "market": mkt, "analysis": analysis}

        if not safe_bool(analysis.get("should_open")):
            return {"allow": False, "reason": safe_str(analysis.get("blocked_reason"), "strategy says no"), "symbol": sym, "market": mkt, "analysis": analysis}

        return {"allow": True, "reason": "ok", "symbol": sym, "market": mkt, "signal": safe_str(analysis.get("signal")), "score": safe_int(analysis.get("score"), 0), "setup_type": setup_type, "analysis": analysis}
