from typing import Any, Dict, List, Optional
from validators import safe_float, safe_str


def _clone(item: Dict[str, Any]) -> Dict[str, Any]:
    return dict(item or {})


class ConfirmationDecision:
    def __init__(self, item: Dict[str, Any], confirmed: bool, status: str, reason: str):
        self.item = _clone(item)
        self.confirmed = bool(confirmed)
        self.status = status
        self.reason = reason

    def as_item(self) -> Dict[str, Any]:
        out = _clone(self.item)
        out["confirmed"] = self.confirmed
        out["confirmation_status"] = self.status
        out["confirmation_reason"] = self.reason

        if self.confirmed:
            out["status"] = "ready"
            out["waiting_for"] = self.reason
        else:
            out["status"] = "watch"
            out["waiting_for"] = self.reason

        return out


class FuturesConfirmationEngine:
    """
    Futures confirmation v1.8.3:
    - LONG waits price >= trigger
    - SHORT waits price <= trigger
    - invalidation guard
    - ATR sanity
    - volume sanity
    - keeps high-score momentum candidates in WATCH instead of hard BLOCKED
    """

    def confirm(self, item: Dict[str, Any], ta: Dict[str, Any]) -> ConfirmationDecision:
        item = _clone(item)
        ta = ta or {}

        symbol = safe_str(item.get("symbol")).upper()
        side = safe_str(item.get("side")).upper()
        setup_type = safe_str(item.get("setup_type")).lower()

        price = safe_float(ta.get("price") or item.get("price"), 0.0)
        trigger = safe_float(item.get("trigger_price"), 0.0)
        invalid = safe_float(item.get("invalidation_price"), 0.0)
        atr = safe_float(ta.get("atr") or item.get("atr"), 0.0)
        vol_ratio = safe_float(ta.get("vol_ratio"), 1.0)
        rsi = safe_float(ta.get("rsi_main"), 50.0)
        score = safe_float(item.get("score"), 0.0)

        if not symbol or side not in {"LONG", "SHORT"}:
            return ConfirmationDecision(item, False, "BLOCKED", "invalid futures item")

        if price <= 0 or trigger <= 0:
            return ConfirmationDecision(item, False, "WAIT_DATA", "waiting valid futures price/trigger")

        if atr > 0 and price > 0:
            atr_pct = atr / price * 100.0
            if atr_pct > 6.0 and "momentum" not in setup_type:
                return ConfirmationDecision(item, False, "WAIT_ATR", f"ATR too high {atr_pct:.2f}%")

        if 0 < vol_ratio < 0.35:
            return ConfirmationDecision(item, False, "WAIT_VOLUME", f"volume weak {vol_ratio:.2f}")

        if side == "LONG":
            if invalid > 0 and price <= invalid:
                return ConfirmationDecision(item, False, "INVALIDATED", "LONG invalidated: price <= invalidation")

            # Avoid buying very overheated non-momentum trend entries.
            if rsi >= 84 and "momentum" not in setup_type:
                return ConfirmationDecision(item, False, "WAIT_RSI", f"LONG RSI hot {rsi:.1f}")

            if price >= trigger:
                return ConfirmationDecision(item, True, "READY", "LONG trigger breakout confirmed")

            return ConfirmationDecision(item, False, "WAIT_TRIGGER", "waiting LONG breakout/reclaim trigger")

        if side == "SHORT":
            if invalid > 0 and price >= invalid:
                return ConfirmationDecision(item, False, "INVALIDATED", "SHORT invalidated: price >= invalidation")

            # Avoid shorting extremely oversold non-momentum trend entries.
            if rsi <= 16 and "momentum" not in setup_type:
                return ConfirmationDecision(item, False, "WAIT_RSI", f"SHORT RSI oversold {rsi:.1f}")

            if price <= trigger:
                return ConfirmationDecision(item, True, "READY", "SHORT trigger breakdown confirmed")

            return ConfirmationDecision(item, False, "WAIT_TRIGGER", "waiting SHORT breakdown trigger")

        return ConfirmationDecision(item, False, "BLOCKED", "unsupported futures side")


class SpotConfirmationEngine:
    """
    Spot confirmation v1.8.3:
    - planner-aware
    - softer than futures
    - supports buy zone, breakout trigger, strong planner score
    - blocks invalidated/hot/dead-volume entries
    """

    def confirm(
        self,
        item: Dict[str, Any],
        ta: Dict[str, Any],
        planner_idea: Optional[Dict[str, Any]] = None,
    ) -> ConfirmationDecision:
        item = _clone(item)
        ta = ta or {}
        idea = planner_idea or {}

        symbol = safe_str(item.get("symbol")).upper()
        side = safe_str(item.get("side")).upper() or "BUY"
        setup_type = safe_str(item.get("setup_type")).lower()

        price = safe_float(ta.get("price") or item.get("price"), 0.0)
        trigger = safe_float(item.get("trigger_price"), 0.0)
        invalid_item = safe_float(item.get("invalidation_price"), 0.0)

        rsi = safe_float(ta.get("rsi_main"), 50.0)
        vol_ratio = safe_float(ta.get("vol_ratio"), 1.0)
        atr = safe_float(ta.get("atr") or item.get("atr"), 0.0)

        idea_score = safe_float(idea.get("score"), safe_float(item.get("score"), 0.0))
        idea_ready = bool(idea.get("ready", False))
        tier = safe_str(idea.get("tier")).upper()
        action_hint = safe_str(idea.get("action_hint")).upper()

        entry_low = safe_float(idea.get("entry_zone_low"), 0.0)
        entry_high = safe_float(idea.get("entry_zone_high"), 0.0)
        invalid_idea = safe_float(idea.get("invalid_level"), 0.0)
        invalid = invalid_idea if invalid_idea > 0 else invalid_item

        if not symbol:
            return ConfirmationDecision(item, False, "BLOCKED", "invalid spot item")

        if side not in {"BUY", "LONG"}:
            return ConfirmationDecision(item, False, "BLOCKED", "spot supports BUY only")

        if price <= 0:
            return ConfirmationDecision(item, False, "WAIT_DATA", "waiting valid spot price")

        if invalid > 0 and price <= invalid:
            return ConfirmationDecision(item, False, "INVALIDATED", "spot idea invalidated")

        if rsi >= 86:
            return ConfirmationDecision(item, False, "WAIT_RSI", f"spot RSI hot {rsi:.1f}")

        if 0 < vol_ratio < 0.30:
            return ConfirmationDecision(item, False, "WAIT_VOLUME", f"spot volume dead {vol_ratio:.2f}")

        if atr > 0 and price > 0:
            atr_pct = atr / price * 100.0
            if atr_pct > 9.0:
                return ConfirmationDecision(item, False, "WAIT_ATR", f"spot ATR too high {atr_pct:.2f}%")

        # Best case: planner buy zone.
        if entry_low > 0 and entry_high > 0:
            if entry_low <= price <= entry_high and (idea_ready or idea_score >= 65):
                return ConfirmationDecision(item, True, "READY", "spot planner buy zone confirmed")
            if price < entry_low:
                return ConfirmationDecision(item, False, "WAIT_ZONE", "price below planner buy zone")
            if price > entry_high and "BREAKOUT" not in action_hint and "MOMENTUM" not in setup_type:
                return ConfirmationDecision(item, False, "WAIT_PULLBACK", "price above planner buy zone")

        # Breakout style spot candidate.
        if trigger > 0 and price >= trigger:
            if idea_score >= 60 or safe_float(item.get("score"), 0.0) >= 7:
                return ConfirmationDecision(item, True, "READY", "spot trigger breakout confirmed")
            return ConfirmationDecision(item, False, "WAIT_PLANNER_SCORE", "spot trigger hit but planner score weak")

        # Strong planner idea may enter even without exact zone if not overheated.
        if (idea_ready or tier in {"A", "B"}) and idea_score >= 82 and rsi < 78:
            return ConfirmationDecision(item, True, "READY", "strong planner idea confirmed")

        return ConfirmationDecision(item, False, "WAIT_CONFIRMATION", "waiting spot planner/trigger confirmation")


class ConfirmationEngine:
    def __init__(self) -> None:
        self.futures = FuturesConfirmationEngine()
        self.spot = SpotConfirmationEngine()

    def _update_watch_item(self, watch_engine, item: Dict[str, Any]) -> None:
        try:
            # Preferred if WatchEngine supports direct upsert.
            if hasattr(watch_engine, "upsert"):
                watch_engine.upsert(item)
                return
        except Exception:
            pass

        try:
            # Fallback: no mutation; UI still sees old item until next loop.
            return
        except Exception:
            return

    def confirmed_futures_items(self, watch_engine, ta_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            items = watch_engine.snapshot()
        except Exception:
            return out

        for item in items:
            if safe_str(item.get("market")).lower() != "fut":
                continue

            sym = safe_str(item.get("symbol")).upper()
            decision = self.futures.confirm(item, ta_data.get(sym, {}) or {})
            updated = decision.as_item()
            self._update_watch_item(watch_engine, updated)

            if decision.confirmed:
                out.append(updated)

        return out

    def confirmed_spot_items(
        self,
        watch_engine,
        ta_data: Dict[str, Dict[str, Any]],
        planner_map: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            items = watch_engine.snapshot()
        except Exception:
            return out

        for item in items:
            if safe_str(item.get("market")).lower() != "spot":
                continue

            sym = safe_str(item.get("symbol")).upper()
            decision = self.spot.confirm(item, ta_data.get(sym, {}) or {}, planner_map.get(sym))
            updated = decision.as_item()
            self._update_watch_item(watch_engine, updated)

            if decision.confirmed:
                out.append(updated)

        return out
