import time
from dataclasses import dataclass


@dataclass
class SpotPosition:
    symbol: str
    qty: float
    entry: float
    avg_price: float
    tp: float
    tp2: float
    sl: float
    atr: float
    cost: float
    fee_open: float
    open_time: float
    pnl: float = 0.0
    pnl_net: float = 0.0
    tp1_hit: bool = False
    trail_sl: float = 0.0
    fills_count: int = 1
    max_pnl_net: float = 0.0
    tp1_time: float = 0.0
    breakeven: bool = False
    last_event: str = ""
    setup_type: str = ""
    args_text: str = ""


class PaperSpot:
    def __init__(
        self,
        start_balance: float = 100.0,
        taker_fee: float = 0.001,
        maker_fee: float = 0.0008,
        spread_bps: float = 4.0,
        slippage_bps: float = 2.0,
        profit_timeout_sec: int = 900,
        tp1_stall_sec: int = 600,
        min_timeout_profit_usdt: float = 0.10,
        fade_giveback_pct: float = 0.65,
    ):
        self.balance = float(start_balance)
        self.positions = {}
        self.history = []
        self.taker_fee = taker_fee
        self.maker_fee = maker_fee
        self.spread_bps = spread_bps
        self.slippage_bps = slippage_bps
        self.profit_timeout_sec = profit_timeout_sec
        self.tp1_stall_sec = tp1_stall_sec
        self.min_timeout_profit_usdt = min_timeout_profit_usdt
        self.fade_giveback_pct = fade_giveback_pct

    def get_balance(self):
        return round(self.balance, 8)

    def get_all_positions(self):
        return self.positions

    def get_position(self, symbol):
        return self.positions.get(symbol)

    def get_trade_history(self):
        return list(self.history)

    def _normalize_reason(self, reason: str) -> str:
        r = str(reason or "").strip().upper()
        aliases = {
            "TP1": "TP1",
            "TP2": "TP2",
            "SL": "SL",
            "STOP": "SL",
            "STOPLOSS": "SL",
            "BU": "BU",
            "BE": "BU",
            "BREAK_EVEN": "BU",
            "BREAKEVEN": "BU",
            "TIMEOUT": "TIMEOUT",
            "FADE": "FADE",
            "STALL": "STALL",
            "MANUAL": "MANUAL",
            "UNKNOWN": "UNKNOWN",
        }
        return aliases.get(r, r if r else "UNKNOWN")

    def _half_spread_pct(self) -> float:
        return (self.spread_bps / 10000.0) / 2.0

    def _slippage_pct(self) -> float:
        return self.slippage_bps / 10000.0

    def _entry_fill_price(self, ref_price: float) -> float:
        return ref_price * (1.0 + self._half_spread_pct() + self._slippage_pct())

    def _exit_fill_price(self, ref_price: float) -> float:
        return ref_price * (1.0 - self._half_spread_pct() - self._slippage_pct())

    def open_position(self, symbol, qty, price, tp, atr, use_maker=False, setup_type="", args_text=""):
        if qty <= 0 or price <= 0:
            return {"code": "ERROR", "msg": "Invalid qty/price"}

        fill_price = self._entry_fill_price(price)
        fee_rate = self.maker_fee if use_maker else self.taker_fee
        cost = qty * fill_price
        fee_open = cost * fee_rate
        required = cost + fee_open

        if self.balance < required:
            return {"code": "ERROR", "msg": "Insufficient paper spot balance"}

        self.balance -= required
        sl = fill_price - atr * 2
        tp2 = fill_price + atr * 7
        pos = self.positions.get(symbol)

        if pos is None:
            self.positions[symbol] = SpotPosition(
                symbol=symbol.upper(),
                qty=round(qty, 8),
                entry=round(fill_price, 8),
                avg_price=round(fill_price, 8),
                tp=round(tp, 8),
                tp2=round(tp2, 8),
                sl=round(sl, 8),
                atr=round(float(atr), 8),
                cost=round(cost, 8),
                fee_open=round(fee_open, 8),
                open_time=time.time(),
                trail_sl=round(sl, 8),
                setup_type=str(setup_type or ""),
                args_text=str(args_text or ""),
            )
        else:
            new_qty = pos.qty + qty
            new_cost = pos.cost + cost
            new_fee = pos.fee_open + fee_open
            new_avg = new_cost / new_qty if new_qty > 0 else fill_price
            pos.qty = round(new_qty, 8)
            pos.cost = round(new_cost, 8)
            pos.fee_open = round(new_fee, 8)
            pos.avg_price = round(new_avg, 8)
            pos.entry = pos.avg_price
            pos.tp = round(max(pos.tp, tp), 8)
            pos.tp2 = round(max(pos.tp2, tp2), 8)
            pos.sl = round(min(pos.sl, sl), 8)
            pos.atr = round(max(pos.atr, atr), 8)
            pos.fills_count += 1
            if setup_type:
                pos.setup_type = str(setup_type)
            if args_text:
                pos.args_text = str(args_text)

        current = self.positions[symbol]
        self.history.append({
            "symbol": current.symbol,
            "entry": round(current.avg_price, 8),
            "qty": round(qty, 8),
            "reason": "OPEN",
            "open_time": time.time(),
            "setup_type": current.setup_type,
            "args_text": current.args_text,
        })

        return {
            "code": "00000",
            "data": {
                "symbol": symbol.upper(),
                "entry": round(fill_price, 8),
                "qty": round(qty, 8),
                "fee_open": round(fee_open, 8),
                "balance": round(self.balance, 8),
                "setup_type": current.setup_type,
                "args_text": current.args_text,
            },
        }

    def _update_unrealized(self, symbol: str, current_price: float):
        pos = self.positions.get(symbol)
        if not pos:
            return
        gross = (current_price - pos.avg_price) * pos.qty
        fee_close_est = abs(current_price * pos.qty) * self.taker_fee
        pos.pnl = round(gross, 8)
        pos.pnl_net = round(gross - pos.fee_open - fee_close_est, 8)
        if pos.pnl_net > pos.max_pnl_net:
            pos.max_pnl_net = pos.pnl_net

    def _close_position_internal(self, symbol: str, current_price: float, reason: str):
        pos = self.positions.get(symbol)
        if not pos:
            return None

        reason = self._normalize_reason(reason)
        exit_price = self._exit_fill_price(current_price)
        close_notional = abs(exit_price * pos.qty)
        fee_close = close_notional * self.taker_fee
        gross = (exit_price - pos.avg_price) * pos.qty
        net_pnl = gross - pos.fee_open - fee_close
        self.balance += close_notional - fee_close

        trade = {
            "symbol": pos.symbol,
            "entry": round(pos.avg_price, 8),
            "exit": round(exit_price, 8),
            "qty": round(pos.qty, 8),
            "gross_pnl": round(gross, 8),
            "net_pnl": round(net_pnl, 8),
            "fee_open": round(pos.fee_open, 8),
            "fee_close": round(fee_close, 8),
            "reason": reason,
            "opened_at": pos.open_time,
            "closed_at": time.time(),
            "fills_count": pos.fills_count,
            "max_pnl_net": round(pos.max_pnl_net, 8),
            "setup_type": pos.setup_type,
            "args_text": pos.args_text,
        }
        self.history.append(trade)
        del self.positions[symbol]

        return {
            "code": "00000",
            "data": {
                "symbol": symbol,
                "pnl": round(net_pnl, 8),
                "reason": reason,
                "exit_price": round(exit_price, 8),
                "fee_close": round(fee_close, 8),
                "balance": round(self.balance, 8),
                "setup_type": pos.setup_type,
                "args_text": pos.args_text,
            },
        }

    def _event_payload(self, symbol: str, reason: str, current_price: float, event_only: bool = True):
        pos = self.positions.get(symbol)
        if not pos:
            return None
        return {
            "code": "00000",
            "data": {
                "event_only": bool(event_only),
                "symbol": pos.symbol,
                "side": "BUY",
                "market": "SPOT",
                "reason": reason,
                "event": reason,
                "exit_price": round(float(current_price), 8),
                "price": round(float(current_price), 8),
                "entry": round(float(pos.avg_price), 8),
                "tp1": round(float(pos.tp), 8),
                "tp2": round(float(pos.tp2), 8),
                "sl": round(float(pos.sl), 8),
                "trail_sl": round(float(pos.trail_sl), 8),
                "qty": round(float(pos.qty), 8),
                "pnl": round(float(pos.pnl), 8),
                "pnl_net": round(float(pos.pnl_net), 8),
                "max_pnl_net": round(float(pos.max_pnl_net), 8),
                "tp1_hit": bool(pos.tp1_hit),
                "breakeven": bool(getattr(pos, "breakeven", False)),
                "setup_type": pos.setup_type,
                "args_text": pos.args_text,
                "hold_sec": max(0, int(time.time() - pos.open_time)),
            },
        }

    def _partial_close_tp1(self, symbol: str, current_price: float, close_pct: float = 0.5):
        # v1.7.6: SPOT TP1 partial close.
        pos = self.positions.get(symbol)
        if not pos:
            return None

        close_pct = max(0.05, min(float(close_pct), 0.95))
        close_qty = round(float(pos.qty) * close_pct, 8)

        if close_qty <= 0 or close_qty >= float(pos.qty):
            close_qty = round(float(pos.qty) * 0.5, 8)

        if close_qty <= 0 or close_qty >= float(pos.qty):
            pos.tp1_hit = True
            pos.tp1_time = time.time()
            pos.breakeven = True
            pos.sl = round(float(pos.avg_price), 8)
            pos.trail_sl = round(float(pos.avg_price), 8)
            pos.last_event = "TP1"
            return self._event_payload(symbol, "TP1", current_price, event_only=True)

        exit_price = self._exit_fill_price(float(current_price))
        close_notional = abs(exit_price * close_qty)
        fee_close = close_notional * self.taker_fee

        original_qty = float(pos.qty)
        original_cost = float(pos.cost)
        original_fee_open = float(pos.fee_open)
        actual_close_pct = close_qty / original_qty if original_qty > 0 else close_pct

        cost_part = original_cost * actual_close_pct
        fee_open_part = original_fee_open * actual_close_pct

        gross = close_notional - cost_part
        realized_pnl = round(gross, 8)
        realized_pnl_net = round(gross - fee_open_part - fee_close, 8)

        # Spot sell returns USDT minus close fee.
        self.balance += close_notional - fee_close

        remaining_qty = round(original_qty - close_qty, 8)
        remaining_pct = remaining_qty / original_qty if original_qty > 0 else 0.0

        pos.qty = remaining_qty
        pos.cost = round(original_cost * remaining_pct, 8)
        pos.fee_open = round(original_fee_open * remaining_pct, 8)
        pos.entry = round(pos.avg_price, 8)
        pos.tp1_hit = True
        pos.tp1_time = time.time()
        pos.breakeven = True
        pos.sl = round(float(pos.avg_price), 8)
        pos.trail_sl = round(float(pos.avg_price), 8)
        pos.last_event = "TP1"

        self._update_unrealized(symbol, float(current_price))

        return {
            "code": "00000",
            "data": {
                "event_only": True,
                "symbol": pos.symbol,
                "side": "BUY",
                "market": "SPOT",
                "reason": "TP1",
                "event": "TP1",
                "exit_price": round(float(exit_price), 8),
                "price": round(float(exit_price), 8),
                "entry": round(float(pos.avg_price), 8),
                "tp1": round(float(pos.tp), 8),
                "tp2": round(float(pos.tp2), 8),
                "sl": round(float(pos.sl), 8),
                "trail_sl": round(float(pos.trail_sl), 8),
                "closed_qty": close_qty,
                "remaining_qty": pos.qty,
                "close_pct": round(actual_close_pct, 6),
                "realized_pnl": realized_pnl,
                "realized_pnl_net": realized_pnl_net,
                "pnl": round(float(pos.pnl), 8),
                "pnl_net": round(float(pos.pnl_net), 8),
                "max_pnl_net": round(float(pos.max_pnl_net), 8),
                "balance": round(float(self.balance), 8),
                "tp1_hit": bool(pos.tp1_hit),
                "breakeven": bool(pos.breakeven),
                "setup_type": pos.setup_type,
                "args_text": pos.args_text,
                "hold_sec": max(0, int(time.time() - pos.open_time)),
            },
        }

    def check_stops(self, symbol: str, current_price: float):
        pos = self.positions.get(symbol)
        if not pos:
            return None
        if current_price <= 0:
            return {"code": "ERROR", "msg": "Invalid current price"}

        self._update_unrealized(symbol, current_price)
        now = time.time()

        if not pos.tp1_hit and current_price >= pos.tp:
            return self._partial_close_tp1(symbol, current_price)

        if pos.tp1_hit:
            new_trail = current_price - pos.atr * 2
            if new_trail > pos.trail_sl:
                pos.trail_sl = new_trail
                pos.sl = pos.trail_sl

        if not pos.tp1_hit and (now - pos.open_time) >= self.profit_timeout_sec and pos.pnl_net >= self.min_timeout_profit_usdt:
            return self._close_position_internal(symbol, current_price, "TIMEOUT")

        if pos.max_pnl_net >= self.min_timeout_profit_usdt * 2 and pos.pnl_net > 0:
            giveback = pos.max_pnl_net - pos.pnl_net
            if pos.max_pnl_net > 0 and (giveback / pos.max_pnl_net) >= self.fade_giveback_pct:
                return self._close_position_internal(symbol, current_price, "FADE")

        if pos.tp1_hit and pos.tp1_time > 0 and (now - pos.tp1_time) >= self.tp1_stall_sec and pos.pnl_net > 0:
            return self._close_position_internal(symbol, current_price, "STALL")

        if current_price <= pos.sl:
            return self._close_position_internal(symbol, current_price, "BU" if pos.tp1_hit else "SL")

        if pos.tp1_hit and current_price >= pos.tp2:
            return self._close_position_internal(symbol, current_price, "TP2")

        return {
            "code": "00000",
            "data": {
                "closed": False,
                "symbol": pos.symbol,
                "mark_price": round(current_price, 8),
                "pnl": round(pos.pnl, 8),
                "pnl_net": round(pos.pnl_net, 8),
                "tp1_hit": bool(pos.tp1_hit),
                "trail_sl": round(pos.trail_sl, 8),
                "fills_count": int(pos.fills_count),
                "setup_type": pos.setup_type,
                "args_text": pos.args_text,
            }
        }

    def close_position(self, symbol: str, current_price: float, reason: str = "MANUAL"):
        pos = self.positions.get(symbol)
        if not pos:
            return None
        return self._close_position_internal(symbol, current_price, reason)