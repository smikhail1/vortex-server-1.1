from validators import safe_str


class DefensiveGates:
    def _sym(self, value):
        return safe_str(value).upper()

    def _market(self, value):
        return safe_str(value).lower()

    def has_opposite_market_exposure(self, symbol, market, router, watch_engine=None):
        symbol = self._sym(symbol)
        market = self._market(market)

        if not symbol:
            return True, "empty symbol"

        try:
            if market == "spot":
                pos = None
                try:
                    pos = router.get_futures_position(symbol)
                except TypeError:
                    pos = router.get_futures_position()
                    if pos is not None and self._sym(getattr(pos, "symbol", "")) != symbol:
                        pos = None
                if pos is not None:
                    return True, f"{symbol} already has futures exposure"

            if market == "fut":
                if hasattr(router, "get_spot_position") and router.get_spot_position(symbol) is not None:
                    return True, f"{symbol} already has spot exposure"
        except Exception:
            pass

        try:
            if watch_engine is not None:
                opposite = "fut" if market == "spot" else "spot"
                for item in watch_engine.snapshot():
                    if self._sym(item.get("symbol")) == symbol and self._market(item.get("market")) == opposite:
                        return True, f"{symbol} already watched in {opposite}"
        except Exception:
            pass

        return False, ""

    def spot_planner_gate(self, symbol, planner_idea, analysis):
        symbol = self._sym(symbol)
        idea = planner_idea or {}
        analysis = analysis or {}
        setup_type = safe_str(analysis.get("setup_type")).lower()

        if not idea:
            return False, f"{symbol} spot blocked: no planner idea"

        try:
            score = float(idea.get("score") or 0.0)
        except Exception:
            score = 0.0

        ready = bool(idea.get("ready", False))
        tier = safe_str(idea.get("tier")).upper()

        if setup_type.startswith("trend_follow") and not (ready or tier in {"A", "B"} or score >= 70):
            return False, f"{symbol} spot blocked: trend-follow without planner confirmation"

        if score < 60 and not ready and tier not in {"A", "B"}:
            return False, f"{symbol} spot blocked: planner score too weak"

        return True, ""

    def should_remove_ready_after_block(self, reason):
        r = safe_str(reason).lower()
        return (
            "loss streak cooldown" in r
            or "daily stop" in r
            or "cooldown after open" in r
            or "max open" in r
        )
