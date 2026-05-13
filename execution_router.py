import time
from typing import Any, Dict, Optional

from config import CONFIG
from paper_futures import PaperFutures
from paper_spot import PaperSpot
from validators import safe_float, safe_str


class ExecutionRouter:
    """
    Единая точка open/check/close.
    Сейчас реализован PAPER backend.
    Интерфейс уже готов к будущему REAL backend.
    """

    def __init__(self, mode: str = CONFIG.trading.mode):
        self.mode = safe_str(mode, "PAPER").upper()

        self.paper_futures = PaperFutures(
            start_balance=CONFIG.futures.start_balance,
            taker_fee=CONFIG.futures.taker_fee,
            maker_fee=CONFIG.futures.maker_fee,
            spread_bps=CONFIG.futures.spread_bps,
            slippage_bps=CONFIG.futures.slippage_bps,
            maintenance_margin_rate=CONFIG.futures.maintenance_margin_rate,
            profit_timeout_sec=CONFIG.futures.profit_timeout_sec,
            tp1_stall_sec=CONFIG.futures.tp1_stall_sec,
            min_timeout_profit_usdt=CONFIG.futures.min_timeout_profit_usdt,
            fade_giveback_pct=CONFIG.futures.fade_giveback_pct,
        )

        self.paper_spot = PaperSpot(
            start_balance=CONFIG.spot.start_balance,
            taker_fee=CONFIG.spot.taker_fee,
            maker_fee=CONFIG.spot.maker_fee,
            spread_bps=CONFIG.spot.spread_bps,
            slippage_bps=CONFIG.spot.slippage_bps,
            profit_timeout_sec=CONFIG.spot.profit_timeout_sec,
            tp1_stall_sec=CONFIG.spot.tp1_stall_sec,
            min_timeout_profit_usdt=CONFIG.spot.min_timeout_profit_usdt,
            fade_giveback_pct=CONFIG.spot.fade_giveback_pct,
        )

    def get_mode(self) -> str:
        return self.mode

    def get_futures_balance(self) -> float:
        if self.mode == "PAPER":
            return self.paper_futures.get_balance()
        return 0.0

    def get_spot_balance(self) -> float:
        if self.mode == "PAPER":
            return self.paper_spot.get_balance()
        return 0.0

    def get_futures_position(self):
        if self.mode == "PAPER":
            return self.paper_futures.get_position()
        return None

    def get_spot_position(self, symbol: str):
        if self.mode == "PAPER":
            return self.paper_spot.get_position(symbol)
        return None

    def get_all_spot_positions(self) -> Dict[str, Any]:
        if self.mode == "PAPER":
            return self.paper_spot.get_all_positions()
        return {}

    def get_futures_history(self):
        if self.mode == "PAPER":
            return self.paper_futures.get_trade_history()
        return []

    def get_spot_history(self):
        if self.mode == "PAPER":
            return self.paper_spot.get_trade_history()
        return []

    def open_futures_position(self, symbol, side, qty, price, tp, sl, atr, leverage=3.0, setup_type="", args_text="", tp0=None, tp2=None):
        if self.mode == "PAPER":
            kwargs = {
                "symbol": symbol, "side": side, "qty": qty, "price": price,
                "tp": tp, "sl": sl, "atr": atr, "leverage": leverage,
                "setup_type": setup_type, "args_text": args_text
            }
            if tp0 is not None: kwargs["tp0"] = tp0
            if tp2 is not None: kwargs["tp2"] = tp2
            return self.paper_futures.open_position(**kwargs)
        return {"code": "ERROR", "msg": "REAL mode not implemented yet"}

    def check_futures_position(self, current_price: float):
        if self.mode == "PAPER":
            return self.paper_futures.check_stops(current_price)
        return None

    def close_futures_position(self, current_price: float, reason: str = "MANUAL"):
        if self.mode == "PAPER":
            return self.paper_futures.close_position(current_price, reason)
        return None

    def update_futures_sl(self, new_sl: float, reason: str = "GUIDE_SL"):
        if self.mode == "PAPER" and hasattr(self.paper_futures, "update_sl"):
            return self.paper_futures.update_sl(new_sl, reason=reason)
        return None

    def open_spot_position(self, symbol, qty, price, tp, atr, setup_type="", args_text=""):
        if self.mode == "PAPER":
            return self.paper_spot.open_position(
                symbol=symbol,
                qty=qty,
                price=price,
                tp=tp,
                atr=atr,
                setup_type=setup_type,
                args_text=args_text,
            )
        return {"code": "ERROR", "msg": "REAL mode not implemented yet"}

    def check_spot_position(self, symbol, current_price: float):
        if self.mode == "PAPER":
            return self.paper_spot.check_stops(symbol, current_price)
        return None

    def close_spot_position(self, symbol: str, current_price: float, reason: str = "MANUAL"):
        if self.mode == "PAPER":
            return self.paper_spot.close_position(symbol, current_price, reason)
        return None

    def manual_open_futures(
        self,
        symbol: str,
        side: str,
        price: float,
        atr: float,
        margin_usdt: float,
        leverage: float = 3.0,
        tp0_mult: float = 0.6,
        tp_mult: float = 2.0,
        tp2_mult: float = 3.5,
        sl_mult: float = 1.5,
        setup_type: str = "manual_fut",
        args_text: str = "manual open futures",
    ):
        px = safe_float(price)
        atr_abs = safe_float(atr)
        margin = safe_float(margin_usdt)
        lev = safe_float(leverage, 3.0)
        qty = margin / px if px > 0 else 0.0
        s = safe_str(side).upper()

        if s == "LONG":
            tp0 = px + atr_abs * tp0_mult
            tp = px + atr_abs * tp_mult
            tp2 = px + atr_abs * tp2_mult
            sl = px - atr_abs * sl_mult
        else:
            tp0 = px - atr_abs * tp0_mult
            tp = px - atr_abs * tp_mult
            tp2 = px - atr_abs * tp2_mult
            sl = px + atr_abs * sl_mult

        return self.open_futures_position(
            symbol=symbol, side=s, qty=qty, price=px, tp=tp, sl=sl, atr=atr_abs,
            leverage=lev, setup_type=setup_type, args_text=args_text, tp0=tp0, tp2=tp2
        )

    def manual_open_spot(
        self,
        symbol: str,
        price: float,
        atr: float,
        order_usdt: float,
        tp_mult: float = 3.0,
        setup_type: str = "manual_spot",
        args_text: str = "manual open spot",
    ):
        px = safe_float(price)
        atr_abs = safe_float(atr)
        usdt = safe_float(order_usdt)
        qty = usdt / px if px > 0 else 0.0
        tp = px + atr_abs * tp_mult

        return self.open_spot_position(
            symbol=symbol,
            qty=qty,
            price=px,
            tp=tp,
            atr=atr_abs,
            setup_type=setup_type,
            args_text=args_text,
        )

    def manual_close_all_spot(self, prices: Dict[str, float], reason: str = "MANUAL"):
        closed = []
        for symbol, pos in list(self.get_all_spot_positions().items()):
            current_price = safe_float(prices.get(symbol), 0.0)
            if current_price > 0:
                result = self.close_spot_position(symbol, current_price, reason)
                if result:
                    closed.append(result)
        return closed

    def get_runtime_snapshot(self) -> Dict[str, Any]:
        fut_pos = self.get_futures_position()
        spot_positions = self.get_all_spot_positions()

        fut_position_dict: Optional[Dict[str, Any]] = None
        if fut_pos is not None:
            _open_time = getattr(fut_pos, "open_time", 0.0) or 0.0
            fut_position_dict = {
                "symbol": getattr(fut_pos, "symbol", ""),
                "side": getattr(fut_pos, "side", ""),
                "qty": getattr(fut_pos, "qty", 0.0),
                "entry": getattr(fut_pos, "entry", 0.0),
                "mark_price": getattr(fut_pos, "mark_price", 0.0),
                "tp0": getattr(fut_pos, "tp0", 0.0), # Добавили микро-тейк в вывод
                "tp": getattr(fut_pos, "tp", 0.0),
                "tp1": getattr(fut_pos, "tp", 0.0),
                "tp2": getattr(fut_pos, "tp2", 0.0),
                "sl": getattr(fut_pos, "sl", 0.0),
                "trail_sl": getattr(fut_pos, "trail_sl", 0.0),
                "liq_price": getattr(fut_pos, "liq_price", 0.0),
                "atr": getattr(fut_pos, "atr", 0.0),
                "leverage": getattr(fut_pos, "leverage", 0.0),
                "margin": getattr(fut_pos, "margin", 0.0),
                "notional": getattr(fut_pos, "notional", 0.0),
                "fee_open": getattr(fut_pos, "fee_open", 0.0),
                "fee_close_est": getattr(fut_pos, "fee_close_est", 0.0),
                "pnl": getattr(fut_pos, "pnl", 0.0),
                "pnl_net": getattr(fut_pos, "pnl_net", 0.0),
                "max_pnl_net": getattr(fut_pos, "max_pnl_net", 0.0),
                "tp1_hit": bool(getattr(fut_pos, "tp1_hit", False)),
                "tp1_time": getattr(fut_pos, "tp1_time", 0.0),
                "breakeven": bool(getattr(fut_pos, "breakeven", False)),
                "last_event": getattr(fut_pos, "last_event", ""),
                "open_time": _open_time,
                "hold_sec": max(0, int(time.time() - _open_time)) if _open_time else 0,
                "setup_type": getattr(fut_pos, "setup_type", ""),
                "args_text": getattr(fut_pos, "args_text", ""),
            }

        spot_positions_dict: Dict[str, Any] = {}
        for symbol, pos in spot_positions.items():
            spot_positions_dict[symbol] = {
                "symbol": getattr(pos, "symbol", symbol),
                "qty": getattr(pos, "qty", 0.0),
                "entry": getattr(pos, "entry", 0.0),
                "avg_price": getattr(pos, "avg_price", 0.0),
                "tp": getattr(pos, "tp", 0.0),
                "tp2": getattr(pos, "tp2", 0.0),
                "sl": getattr(pos, "sl", 0.0),
                "pnl": getattr(pos, "pnl", 0.0),
                "pnl_net": getattr(pos, "pnl_net", 0.0),
                "fills_count": getattr(pos, "fills_count", 1),
                "setup_type": getattr(pos, "setup_type", ""),
                "args_text": getattr(pos, "args_text", ""),
            }

        return {
            "mode": self.get_mode(),
            "balances": {
                "fut": self.get_futures_balance(),
                "spot": self.get_spot_balance(),
            },
            "fut_position": fut_position_dict,
            "spot_positions": spot_positions_dict,
            "ts": time.time(),
        }