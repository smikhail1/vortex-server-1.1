import time
from dataclasses import dataclass

from config import CONFIG


@dataclass
class FuturesPosition:
    symbol: str
    side: str
    qty: float
    entry: float
    mark_price: float
    tp: float
    sl: float
    atr: float
    leverage: float
    margin: float
    notional: float
    fee_open: float
    fee_close_est: float
    open_time: float

    tp0: float = 0.0
    tp2: float = 0.0
    pnl: float = 0.0
    pnl_net: float = 0.0
    breakeven: bool = False
    tp0_hit: bool = False
    tp1_hit: bool = False
    trail_sl: float = 0.0
    liq_price: float = 0.0
    max_pnl_net: float = 0.0
    tp1_time: float = 0.0
    last_event: str = ""

    setup_type: str = ""
    args_text: str = ""


class PaperFutures:
    """
    Realistic paper futures engine.
    VORTEX 1.7: Smart Scaling (TP0 -> TP1 -> TP2) + Breakeven protection.
    """

    def __init__(
        self,
        start_balance: float = 100.0,
        taker_fee: float = 0.0006,
        maker_fee: float = 0.0002,
        spread_bps: float = 4.0,
        slippage_bps: float = 2.0,
        maintenance_margin_rate: float = 0.005,
        profit_timeout_sec: int = 3600,
        tp1_stall_sec: int = 420,
        min_timeout_profit_usdt: float = 0.15,
        fade_giveback_pct: float = 0.65,
    ):
        self.balance = float(start_balance)
        self.pos = None
        self.history = []

        self.taker_fee = float(taker_fee)
        self.maker_fee = float(maker_fee)
        self.spread_bps = float(spread_bps)
        self.slippage_bps = float(slippage_bps)
        self.maintenance_margin_rate = float(maintenance_margin_rate)

        self.profit_timeout_sec = int(profit_timeout_sec)
        self.tp1_stall_sec = int(tp1_stall_sec)
        self.min_timeout_profit_usdt = float(min_timeout_profit_usdt)
        self.fade_giveback_pct = float(fade_giveback_pct)
        self.trailing_atr_mult = float(getattr(CONFIG.futures, "trailing_atr_mult", 1.5))

    def get_balance(self):
        return round(self.balance, 8)

    def get_position(self):
        return self.pos

    def get_trade_history(self):
        return list(self.history)

    def _normalize_side(self, side: str) -> str:
        s = str(side).lower()
        if s in ("long", "buy"):
            return "long"
        if s in ("short", "sell"):
            return "short"
        return s

    def _half_spread_pct(self) -> float:
        return (self.spread_bps / 10000.0) / 2.0

    def _slippage_pct(self) -> float:
        return self.slippage_bps / 10000.0

    def _entry_fill_price(self, ref_price: float, side: str) -> float:
        side = self._normalize_side(side)
        hp = self._half_spread_pct()
        sp = self._slippage_pct()
        return ref_price * (1.0 + hp + sp) if side == "long" else ref_price * (1.0 - hp - sp)

    def _exit_fill_price(self, ref_price: float, side: str) -> float:
        side = self._normalize_side(side)
        hp = self._half_spread_pct()
        sp = self._slippage_pct()
        return ref_price * (1.0 - hp - sp) if side == "long" else ref_price * (1.0 + hp + sp)

    def _calc_liq_price(self, entry: float, side: str, leverage: float) -> float:
        mmr = self.maintenance_margin_rate
        if leverage <= 0:
            leverage = 1.0
        if self._normalize_side(side) == "long":
            liq = entry * (1.0 - (1.0 / leverage) + mmr)
        else:
            liq = entry * (1.0 + (1.0 / leverage) - mmr)
        return max(liq, 0.0)

    def _tp2_mult(self, setup_type: str = "") -> float:
        setup = str(setup_type or "").lower()
        if "momentum" in setup:
            return float(getattr(CONFIG.futures, "momentum_tp2_atr_mult", 3.5))
        return float(getattr(CONFIG.futures, "futures_tp2_atr_mult", getattr(CONFIG.strategy, "futures_tp2_atr_mult", 5.0)))

    def _event_payload(self, reason: str, current_price: float, event_only: bool = True):
        p = self.pos
        if not p:
            return None
        return {
            "code": "00000",
            "data": {
                "event_only": bool(event_only),
                "symbol": p.symbol,
                "side": p.side.upper(),
                "reason": reason,
                "exit_price": round(float(current_price), 8),
                "pnl": p.pnl,
                "pnl_net": p.pnl_net,
                "max_pnl_net": p.max_pnl_net,
                "entry": p.entry,
                "tp0": p.tp0,
                "tp1": p.tp,
                "tp2": p.tp2,
                "sl": p.sl,
                "trail_sl": p.trail_sl,
                "tp0_hit": p.tp0_hit,
                "tp1_hit": p.tp1_hit,
                "breakeven": p.breakeven,
                "setup_type": p.setup_type,
                "args_text": p.args_text,
                "hold_sec": max(0, int(time.time() - p.open_time)),
            },
        }

    def open_position(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        tp: float,
        sl: float,
        atr: float,
        leverage: float = 3.0,
        use_maker: bool = False,
        setup_type: str = "",
        args_text: str = "",
        tp0: float = 0.0,
        tp2: float = 0.0,
    ):
        if self.pos is not None:
            return {"code": "ERROR", "msg": "Position already open"}
        if qty <= 0 or price <= 0 or leverage <= 0:
            return {"code": "ERROR", "msg": "Invalid qty/price/leverage"}

        side_norm = self._normalize_side(side)
        fill_price = self._entry_fill_price(price, side_norm)
        notional = qty * fill_price
        margin = notional / leverage
        fee_rate = self.maker_fee if use_maker else self.taker_fee
        fee_open = notional * fee_rate
        required = margin + fee_open
        if self.balance < required:
            return {"code": "ERROR", "msg": "Insufficient paper balance"}

        self.balance -= required
        
        if tp0 == 0.0:
            tp0 = fill_price + atr * 0.6 if side_norm == "long" else fill_price - atr * 0.6
        if tp2 == 0.0:
            tp2_mult = self._tp2_mult(setup_type)
            tp2 = fill_price + atr * tp2_mult if side_norm == "long" else fill_price - atr * tp2_mult
            
        trail_sl = sl
        liq_price = self._calc_liq_price(fill_price, side_norm, leverage)
        fee_close_est = notional * fee_rate

        self.pos = FuturesPosition(
            symbol=symbol,
            side=side_norm,
            qty=qty,
            entry=round(fill_price, 8),
            mark_price=round(fill_price, 8),
            tp0=round(tp0, 8),
            tp=round(tp, 8),
            tp2=round(tp2, 8),
            sl=round(sl, 8),
            atr=round(float(atr), 8),
            leverage=float(leverage),
            margin=round(margin, 8),
            notional=round(notional, 8),
            fee_open=round(fee_open, 8),
            fee_close_est=round(fee_close_est, 8),
            open_time=time.time(),
            trail_sl=round(trail_sl, 8),
            liq_price=round(liq_price, 8),
            setup_type=str(setup_type or ""),
            args_text=str(args_text or ""),
        )
        return {"code": "00000", "data": self._position_payload()}

    def _position_payload(self):
        p = self.pos
        if not p:
            return {}
        return {
            "symbol": p.symbol,
            "side": p.side.upper(),
            "qty": round(p.qty, 8),
            "entry": p.entry,
            "mark_price": p.mark_price,
            "tp0": p.tp0,
            "tp1": p.tp,
            "tp2": p.tp2,
            "sl": p.sl,
            "trail_sl": p.trail_sl,
            "liq_price": p.liq_price,
            "pnl": p.pnl,
            "pnl_net": p.pnl_net,
            "tp0_hit": p.tp0_hit,
            "tp1_hit": p.tp1_hit,
            "breakeven": p.breakeven,
            "setup_type": p.setup_type,
            "args_text": p.args_text,
            "hold_sec": max(0, int(time.time() - p.open_time)),
            "max_pnl_net": p.max_pnl_net,
        }

    def update_sl(self, new_sl: float, reason: str = "GUIDE_SL"):
        if not self.pos:
            return None
        p = self.pos
        value = round(float(new_sl), 8)
        if value <= 0:
            return None

        old_sl = p.sl
        if p.side == "long":
            if value <= old_sl:
                return None
        else:
            if old_sl > 0 and value >= old_sl:
                return None

        p.sl = value
        p.trail_sl = value
        if reason == "BE_PROTECT":
            p.breakeven = True
            if not p.tp0_hit:
                p.tp0_hit = True
                p.tp1_time = time.time()
        p.last_event = reason
        return self._event_payload(reason, p.mark_price or p.entry, event_only=True)

    def _update_unrealized(self, current_price: float):
        if not self.pos:
            return
        p = self.pos
        p.mark_price = float(current_price)
        gross = (current_price - p.entry) * p.qty if p.side == "long" else (p.entry - current_price) * p.qty
        exit_notional_est = abs(current_price * p.qty)
        fee_close_est = exit_notional_est * self.taker_fee
        p.pnl = round(gross, 8)
        p.fee_close_est = round(fee_close_est, 8)
        p.pnl_net = round(gross - p.fee_open - fee_close_est, 8)
        if p.pnl_net > p.max_pnl_net:
            p.max_pnl_net = p.pnl_net

    def _partial_close(self, current_price: float, close_pct: float, level_name: str):
        p = self.pos
        if not p:
            return None

        close_qty = round(float(p.qty) * close_pct, 8)

        if close_qty <= 0 or close_qty >= float(p.qty):
            return self._event_payload(level_name, current_price, event_only=True)

        exit_price = self._exit_fill_price(float(current_price), p.side)
        close_notional = abs(exit_price * close_qty)
        fee_close = close_notional * self.taker_fee
        fee_open_part = float(p.fee_open) * close_pct
        released_margin = float(p.margin) * close_pct

        gross = (exit_price - p.entry) * close_qty if p.side == "long" else (p.entry - exit_price) * close_qty
        realized_pnl = round(gross, 8)
        realized_pnl_net = round(gross - fee_open_part - fee_close, 8)

        self.balance += released_margin + realized_pnl_net

        remaining_pct = 1.0 - close_pct
        p.qty = round(float(p.qty) - close_qty, 8)
        p.margin = round(float(p.margin) * remaining_pct, 8)
        p.notional = round(float(p.notional) * remaining_pct, 8)
        p.fee_open = round(float(p.fee_open) * remaining_pct, 8)
        p.fee_close_est = round(float(p.fee_close_est) * remaining_pct, 8)

        if level_name == "TP0":
            p.breakeven = True
            p.tp0_hit = True
            p.tp1_time = time.time()
            p.sl = p.entry
            p.trail_sl = p.entry
        elif level_name == "TP1":
            p.tp1_hit = True

        p.last_event = level_name
        self._update_unrealized(float(current_price))

        payload = self._event_payload(level_name, current_price, event_only=True)
        if payload:
            payload["data"]["closed_qty"] = close_qty
            payload["data"]["remaining_qty"] = p.qty
            payload["data"]["close_pct"] = close_pct
            payload["data"]["realized_pnl"] = realized_pnl
            payload["data"]["realized_pnl_net"] = realized_pnl_net
            payload["data"]["balance"] = round(float(self.balance), 8)
        return payload

    def check_stops(self, current_price: float):
        if not self.pos:
            return None
        p = self.pos
        self._update_unrealized(current_price)
        now = time.time()

        if p.side == "long" and current_price <= p.liq_price:
            return self.close_position(current_price, reason="LIQ")
        if p.side == "short" and current_price >= p.liq_price:
            return self.close_position(current_price, reason="LIQ")

        if not p.breakeven and not p.tp0_hit:
            tp0_hit_now = (p.side == "long" and current_price >= p.tp0) or (p.side == "short" and current_price <= p.tp0)
            if tp0_hit_now:
                return self._partial_close(current_price, close_pct=0.40, level_name="TP0")

        if p.tp0_hit and not p.tp1_hit:
            tp1_hit_now = (p.side == "long" and current_price >= p.tp) or (p.side == "short" and current_price <= p.tp)
            if tp1_hit_now:
                return self._partial_close(current_price, close_pct=0.50, level_name="TP1")

        if p.tp0_hit:
            old_sl = p.sl
            if p.side == "long":
                new_trail = current_price - p.atr * self.trailing_atr_mult
                if new_trail > p.trail_sl:
                    p.trail_sl = round(new_trail, 8)
                    p.sl = p.trail_sl
            else:
                new_trail = current_price + p.atr * self.trailing_atr_mult
                if new_trail < p.trail_sl:
                    p.trail_sl = round(new_trail, 8)
                    p.sl = p.trail_sl
            if p.sl != old_sl:
                p.last_event = "TRAIL"
                return self._event_payload("TRAIL", current_price, event_only=True)

        if not p.tp0_hit and (now - p.open_time) >= self.profit_timeout_sec and p.pnl_net >= self.min_timeout_profit_usdt:
            return self.close_position(current_price, reason="TIMEOUT")

        min_fade_profit = max(self.min_timeout_profit_usdt, 0.05)
        if p.max_pnl_net >= min_fade_profit and p.pnl_net > 0:
            giveback = p.max_pnl_net - p.pnl_net
            if p.max_pnl_net > 0 and (giveback / p.max_pnl_net) >= self.fade_giveback_pct and p.pnl_net >= min_fade_profit:
                return self.close_position(current_price, reason="FADE")

        if p.tp0_hit and p.tp1_time > 0 and (now - p.tp1_time) >= self.tp1_stall_sec and p.pnl_net > 0:
            return self.close_position(current_price, reason="STALL")

        reason = None
        if p.side == "long":
            if current_price <= p.sl:
                reason = "BU" if p.breakeven else "SL"
            elif p.tp1_hit and current_price >= p.tp2:
                reason = "TP2"
        else:
            if current_price >= p.sl:
                reason = "BU" if p.breakeven else "SL"
            elif p.tp1_hit and current_price <= p.tp2:
                reason = "TP2"

        if reason:
            return self.close_position(current_price, reason=reason)
        return None

    def close_position(self, price: float, reason: str = "MANUAL"):
        if not self.pos:
            return None
        p = self.pos
        exit_price = self._exit_fill_price(price, p.side)
        self._update_unrealized(exit_price)
        pnl = p.pnl
        pnl_net = p.pnl_net
        close_notional = abs(exit_price * p.qty)
        fee_close = close_notional * self.taker_fee
        gross = (exit_price - p.entry) * p.qty if p.side == "long" else (p.entry - exit_price) * p.qty
        pnl = round(gross, 8)
        pnl_net = round(gross - p.fee_open - fee_close, 8)
        self.balance += p.margin + pnl_net
        hold_sec = max(0, int(time.time() - p.open_time))
        record = {
            "symbol": p.symbol,
            "side": p.side.upper(),
            "entry": p.entry,
            "exit_price": round(exit_price, 8),
            "pnl": pnl,
            "pnl_net": pnl_net,
            "fee_open": p.fee_open,
            "fee_close": round(fee_close, 8),
            "reason": reason,
            "hold_sec": hold_sec,
            "setup_type": p.setup_type,
            "args_text": p.args_text,
            "tp0_hit": p.tp0_hit,
            "tp1_hit": p.tp1_hit,
            "max_pnl_net": p.max_pnl_net,
        }
        self.history.append(record)
        self.pos = None
        return {"code": "00000", "data": record}
