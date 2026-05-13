import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

from config import CONFIG
from validators import normalize_symbol, safe_bool, safe_float, safe_int, safe_str


# v1.6.4.6 confirmation helpers
def _vortex_safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

def _vortex_safe_str(value, default=""):
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default

def _vortex_confirm_watch_item(item):
    # Source of truth: stored trigger_price + current price. args_text is ignored.
    try:
        side = _vortex_safe_str(item.get("side")).upper()
        price = _vortex_safe_float(item.get("price"), 0.0)
        trigger = _vortex_safe_float(item.get("trigger_price"), 0.0)
        if price <= 0 or trigger <= 0:
            return item
        if item.get("confirmed") and item.get("status") == "ready":
            return item
        if side == "LONG" and price >= trigger:
            item["confirmed"] = True
            item["status"] = "ready"
            item["confirmation_reason"] = "long confirmation: price >= stored trigger"
        elif side == "SHORT" and price <= trigger:
            item["confirmed"] = True
            item["status"] = "ready"
            item["confirmation_reason"] = "short confirmation: price <= stored trigger"
        else:
            item["confirmed"] = False
            if item.get("status") != "ready":
                item["status"] = "watch"
            item["confirmation_reason"] = ""
    except Exception:
        return item
    return item

def _vortex_confirm_watch_list(items):
    try:
        return [_vortex_confirm_watch_item(dict(x)) if isinstance(x, dict) else x for x in (items or [])]
    except Exception:
        return items

@dataclass

class WatchItem:
    symbol: str
    market: str              # "fut" / "spot"
    side: str                # "LONG" / "SHORT" / "BUY"
    setup_type: str
    score: int
    status: str              # "watch" / "ready" / "expired" / "blocked"
    waiting_for: str
    trigger_price: float
    invalidation_price: float
    created_at: float
    updated_at: float
    expires_at: float
    price: float = 0.0
    atr: float = 0.0
    args_text: str = ""
    confirmed: bool = False
    confirmation_reason: str = ""


class WatchEngine:
    """
    VORTEX 1.5 WATCH -> CONFIRMATION layer.

    Задача:
    - strategy больше не открывает сделку сразу;
    - сильный сетап попадает в WATCH;
    - сделка открывается только после подтверждения цены.

    Confirmation v1:
    - LONG/BUY: price пробивает trigger_price вверх с ATR-buffer.
    - SHORT:    price пробивает trigger_price вниз с ATR-buffer.

    Важный фикс:
    - обычные сетапы в dead/chaotic/unknown блокируются;
    - dead_override_momentum_* НЕ блокируется по dead regime,
      иначе Momentum Hunter физически не может подтвердиться.
    """

    def __init__(self, logger=None) -> None:
        self.logger = logger
        self._items: Dict[str, WatchItem] = {}

    def _key(self, symbol: str, market: str, side: str) -> str:
        return f"{normalize_symbol(symbol)}::{safe_str(market).lower()}::{safe_str(side).upper()}"

    def _ttl_for_market(self, market: str) -> int:
        return (
            CONFIG.trading.spot_watch_ttl_sec
            if safe_str(market).lower() == "spot"
            else CONFIG.trading.futures_watch_ttl_sec
        )

    def _buffer_for_market(self, market: str) -> float:
        return (
            CONFIG.trading.spot_confirmation_buffer_atr
            if safe_str(market).lower() == "spot"
            else CONFIG.trading.futures_confirmation_buffer_atr
        )

    def _is_dead_override(self, setup_type: str) -> bool:
        setup = safe_str(setup_type).lower()
        return "dead_override" in setup or setup.startswith("dead_override_")

    def _build_trigger(self, side: str, setup_type: str, current: Dict[str, Any]) -> Tuple[float, float, str]:
        price = safe_float(current.get("price"))
        atr = safe_float(current.get("atr"))
        recent_high = safe_float(current.get("recent_high"))
        recent_low = safe_float(current.get("recent_low"))
        ema20 = safe_float(current.get("ema20"))
        ema50 = safe_float(current.get("ema50"))

        side_u = safe_str(side).upper()
        setup = safe_str(setup_type)

        if side_u in {"LONG", "BUY"}:
            trigger = recent_high if recent_high > 0 else price + atr * 0.25
            invalidation = recent_low if recent_low > 0 else min(ema20, ema50, price - atr)
            waiting_for = "breakout/reclaim above local high"

            if "retest" in setup:
                trigger = max(price + atr * 0.10, ema20)
                waiting_for = "retest reclaim"
            elif "breakout" in setup:
                trigger = price + atr * 0.10
                waiting_for = "breakout continuation confirmation"
            elif "momentum" in setup:
                trigger = recent_high if recent_high > 0 else price + atr * CONFIG.momentum.trigger_atr_buffer
                waiting_for = "momentum trigger breakout"

            return round(trigger, 8), round(invalidation, 8), waiting_for

        trigger = recent_low if recent_low > 0 else price - atr * 0.25
        invalidation = recent_high if recent_high > 0 else max(ema20, ema50, price + atr)
        waiting_for = "breakdown/reclaim below local low"

        if "retest" in setup:
            trigger = min(price - atr * 0.10, ema20 if ema20 > 0 else price)
            waiting_for = "retest rejection"
        elif "breakout" in setup:
            trigger = price - atr * 0.10
            waiting_for = "breakout continuation confirmation"
        elif "momentum" in setup:
            trigger = recent_low if recent_low > 0 else price - atr * CONFIG.momentum.trigger_atr_buffer
            waiting_for = "momentum trigger breakdown"

        return round(trigger, 8), round(invalidation, 8), waiting_for

    def upsert_from_analysis(
        self,
        symbol: str,
        market: str,
        current: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        sym = normalize_symbol(symbol)
        mkt = safe_str(market).lower()

        if not sym or mkt not in {"fut", "spot"}:
            return None

        if not safe_bool(analysis.get("should_open")):
            return None

        side = safe_str(analysis.get("signal")).upper()

        if mkt == "spot":
            side = "BUY"

        if side not in {"LONG", "SHORT", "BUY"}:
            return None

        price = safe_float(current.get("price"))
        atr = safe_float(current.get("atr"))

        if price <= 0 or atr <= 0:
            return None

        now = time.time()
        ttl = self._ttl_for_market(mkt)
        setup_type = safe_str(analysis.get("setup_type"), "-")

        # MomentumEngine может уже передать trigger/invalidation.
        trigger = safe_float(analysis.get("trigger_price"), 0.0)
        invalidation = safe_float(analysis.get("invalidation_price"), 0.0)

        if trigger > 0:
            if side in {"LONG", "BUY"}:
                waiting_for = "momentum trigger breakout" if "momentum" in setup_type else "trigger confirmation"
            else:
                waiting_for = "momentum trigger breakdown" if "momentum" in setup_type else "trigger confirmation"
        else:
            trigger, invalidation, waiting_for = self._build_trigger(side, setup_type, current)

        key = self._key(sym, mkt, side)
        prev = self._items.get(key)

        created_at = prev.created_at if prev else now

        # v1.6.3.2-clean: freeze trigger while candidate is active.
        # This prevents a moving-target trigger that can run away from price.
        if prev and prev.status in {"watch", "ready"} and not self._is_expired(prev, now):
            trigger = prev.trigger_price
            invalidation = prev.invalidation_price
            waiting_for = prev.waiting_for
            status = prev.status
            confirmed = bool(prev.confirmed)
            confirmation_reason = prev.confirmation_reason
            expires_at = prev.expires_at
        else:
            status = "watch"
            confirmed = False
            confirmation_reason = ""
            expires_at = created_at + ttl

        item = WatchItem(
            symbol=sym,
            market=mkt,
            side=side,
            setup_type=setup_type,
            score=safe_int(analysis.get("score"), 0),
            status=status,
            waiting_for=waiting_for,
            trigger_price=round(trigger, 8),
            invalidation_price=round(invalidation, 8),
            created_at=created_at,
            updated_at=now,
            expires_at=expires_at,
            price=round(price, 8),
            atr=round(atr, 8),
            args_text=safe_str(analysis.get("args_text")),
            confirmed=confirmed,
            confirmation_reason=confirmation_reason,
        )

        self._items[key] = item

        if self.logger and prev is None:
            self.logger.info("WATCH", "candidate added", asdict(item))

        return self.to_public(item)

    def _is_expired(self, item: WatchItem, now: Optional[float] = None) -> bool:
        ts = time.time() if now is None else now
        return ts >= item.expires_at

    def prune(self) -> None:
        now = time.time()
        expired_keys = [key for key, item in self._items.items() if self._is_expired(item, now)]

        for key in expired_keys:
            item = self._items.pop(key, None)

            if item and self.logger:
                self.logger.info("WATCH", "candidate expired", self.to_public(item))

    def remove(self, symbol: str, market: str, side: str = "") -> None:
        sym = normalize_symbol(symbol)
        mkt = safe_str(market).lower()
        side_u = safe_str(side).upper()

        if side_u:
            self._items.pop(self._key(sym, mkt, side_u), None)
            return

        for key in list(self._items.keys()):
            if key.startswith(f"{sym}::{mkt}::"):
                self._items.pop(key, None)

    def check_confirmation_for_item(self, item: WatchItem, current: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self._is_expired(item):
            item.status = "expired"
            return None

        price = safe_float(current.get("price"))
        atr = safe_float(current.get("atr"), item.atr)
        ema20 = safe_float(current.get("ema20"))
        market_regime = safe_str(current.get("market_regime"), "unknown").lower()
        breakout = safe_bool(current.get("breakout"))
        breakout_dir = safe_str(current.get("breakout_dir")).lower()

        if price <= 0 or atr <= 0:
            return None

        is_dead_override = self._is_dead_override(item.setup_type)

        # Критичный фикс:
        # обычные сетапы в dead/chaotic/unknown блокируем,
        # но dead_override_momentum_* пропускаем к price confirmation.
        if market_regime in {"dead", "chaotic", "unknown"} and not is_dead_override:
            item.status = "blocked"
            item.confirmation_reason = f"bad regime during watch:{market_regime}"
            return None

        buffer_abs = atr * self._buffer_for_market(item.market)

        if item.side in {"LONG", "BUY"}:
            confirmed = (
                price >= item.trigger_price + buffer_abs
                and (ema20 <= 0 or price >= ema20 or is_dead_override)
            ) or (breakout and breakout_dir == "up")

            invalidated = item.invalidation_price > 0 and price <= item.invalidation_price - buffer_abs

            if invalidated:
                item.status = "blocked"
                item.confirmation_reason = "long invalidation broken"
                return None

            if confirmed:
                item.status = "ready"
                item.confirmed = True
                item.price = round(price, 8)
                item.atr = round(atr, 8)
                item.updated_at = time.time()

                if is_dead_override:
                    item.confirmation_reason = "dead override momentum long confirmed"
                else:
                    item.confirmation_reason = "long confirmation: trigger reclaimed"

                return self.to_public(item)

        if item.side == "SHORT":
            confirmed = (
                price <= item.trigger_price - buffer_abs
                and (ema20 <= 0 or price <= ema20 or is_dead_override)
            ) or (breakout and breakout_dir == "down")

            invalidated = item.invalidation_price > 0 and price >= item.invalidation_price + buffer_abs

            if invalidated:
                item.status = "blocked"
                item.confirmation_reason = "short invalidation broken"
                return None

            if confirmed:
                item.status = "ready"
                item.confirmed = True
                item.price = round(price, 8)
                item.atr = round(atr, 8)
                item.updated_at = time.time()

                if is_dead_override:
                    item.confirmation_reason = "dead override momentum short confirmed"
                else:
                    item.confirmation_reason = "short confirmation: trigger reclaimed"

                return self.to_public(item)

        item.price = round(price, 8)
        item.atr = round(atr, 8)
        item.updated_at = time.time()

        return None

    def confirmed_items(self, ta_data: Dict[str, Dict[str, Any]], market: Optional[str] = None) -> List[Dict[str, Any]]:
        self.prune()

        out: List[Dict[str, Any]] = []

        for item in list(self._items.values()):
            if market and item.market != safe_str(market).lower():
                continue

            current = ta_data.get(item.symbol) or {}
            confirmed = self.check_confirmation_for_item(item, current)

            if confirmed:
                out.append(confirmed)

        out.sort(
            key=lambda x: (
                safe_int(x.get("score")),
                safe_float(x.get("updated_at")),
            ),
            reverse=True,
        )

        return out

    def snapshot(self) -> List[Dict[str, Any]]:
        self.prune()

        items = [self.to_public(item) for item in self._items.values()]
        rank = {
            "ready": 4,
            "watch": 3,
            "blocked": 2,
            "expired": 1,
        }

        items.sort(
            key=lambda x: (
                rank.get(safe_str(x.get("status")), 0),
                safe_int(x.get("score")),
            ),
            reverse=True,
        )

        return items

    def to_public(self, item: WatchItem) -> Dict[str, Any]:
        now = time.time()
        data = asdict(item)
        data["expires_in_sec"] = max(0, int(item.expires_at - now))
        return data