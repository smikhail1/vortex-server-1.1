import os
import time
from typing import Any, Dict, Optional
from config import CONFIG
from paper_futures import PaperFutures
from paper_spot import PaperSpot
from validators import safe_float, safe_str


class ExecutionRouter:

    def get_spot_position(self, symbol):
        """
        Compatibility hotfix for strategy/trade_manager.
        """
        try:
            if hasattr(self.spot_engine, "get_position"):
                return self.spot_engine.get_position(symbol)

            if hasattr(self.spot_engine, "positions"):
                return self.spot_engine.positions.get(symbol)

            return None

        except Exception:
            return None

    def __init__(self, mode: str = CONFIG.trading.mode):
        # Читаем дефолты из .env или конфига
        self.spot_mode = os.environ.get("DEFAULT_SPOT_MODE", safe_str(mode, "PAPER")).upper()
        self.fut_mode = os.environ.get("DEFAULT_FUT_MODE", safe_str(mode, "PAPER")).upper()
        
        self.api_key = os.environ.get("BITGET_SUB_API_KEY", "")
        self.api_secret = os.environ.get("BITGET_SUB_SECRET_KEY", "")
        self.api_passphrase = os.environ.get("BITGET_SUB_PASSPHRASE", "")
        
        if self.api_key and self.api_secret:
            print("[ROUTER] Bitget API keys detected, but real execution is not implemented in this snapshot.", flush=True)

        self.paper_futures = PaperFutures(start_balance=CONFIG.futures.start_balance)
        self.paper_spot = PaperSpot(start_balance=CONFIG.spot.start_balance)
        self.risk_manager = None # Будет проброшен из main.py

    def set_spot_mode(self, mode: str): self.spot_mode = mode.upper()
    def set_fut_mode(self, mode: str): self.fut_mode = mode.upper()
    def get_mode(self) -> str: return f"SPOT:{self.spot_mode}|FUT:{self.fut_mode}"

    def get_futures_balance(self) -> float:
        return self.paper_futures.get_balance() if self.fut_mode == "PAPER" else 0.0
    def get_spot_balance(self) -> float:
        return self.paper_spot.get_balance() if self.spot_mode == "PAPER" else 0.0
    def get_all_spot_positions(self):
        return self.paper_spot.get_all_positions() if self.spot_mode == "PAPER" else {}
    def get_futures_position(self):
        return self.paper_futures.get_position() if self.fut_mode == "PAPER" else None

    # Заглушки для методов, чтобы API не падало
    def open_futures_position(self, **kwargs): return self.paper_futures.open_position(**kwargs) if self.fut_mode == "PAPER" else {"code":"ERR"}
    def open_spot_position(self, **kwargs): return self.paper_spot.open_position(**kwargs) if self.spot_mode == "PAPER" else {"code":"ERR"}
    def check_futures_position(self, p): return self.paper_futures.check_stops(p) if self.fut_mode == "PAPER" else None
    def check_spot_position(self, s, p): return self.paper_spot.check_stops(s, p) if self.spot_mode == "PAPER" else None
    def close_futures_position(self, p, r): return self.paper_futures.close_position(p, r) if self.fut_mode == "PAPER" else None
    def close_spot_position(self, s, p, r): return self.paper_spot.close_position(s, p, r) if self.spot_mode == "PAPER" else None
    def get_runtime_snapshot(self): return {"mode": self.get_mode(), "ts": time.time()}


# --- VORTEX v1.8.1 EXECUTION ROUTER COMPAT ---
def _vortex_router_get_spot_position_v181(self, symbol):
    try:
        sym = str(symbol or "").upper()

        engine = getattr(self, "paper_spot", None)
        if engine is not None:
            if hasattr(engine, "get_position"):
                return engine.get_position(sym)
            if hasattr(engine, "positions"):
                return engine.positions.get(sym)

        engine = getattr(self, "spot_engine", None)
        if engine is not None:
            if hasattr(engine, "get_position"):
                return engine.get_position(sym)
            if hasattr(engine, "positions"):
                return engine.positions.get(sym)

        return None
    except Exception:
        return None


def _vortex_router_get_all_futures_positions_v181(self):
    try:
        pos = None
        if hasattr(self, "get_futures_position"):
            pos = self.get_futures_position()
        if pos is None:
            return {}
        sym = getattr(pos, "symbol", "") or "FUT"
        return {str(sym).upper(): pos}
    except Exception:
        return {}


try:
    ExecutionRouter.get_spot_position = _vortex_router_get_spot_position_v181
    if not hasattr(ExecutionRouter, "get_all_futures_positions"):
        ExecutionRouter.get_all_futures_positions = _vortex_router_get_all_futures_positions_v181
except Exception:
    pass
# --- END VORTEX v1.8.1 EXECUTION ROUTER COMPAT ---


# --- VORTEX v1.8.5b ROUTER RUNTIME SNAPSHOT ---
def _vortex_position_to_dict_v185b(pos):
    if pos is None:
        return {}
    if isinstance(pos, dict):
        return dict(pos)

    out = {}
    keys = [
        "symbol", "side", "qty", "entry", "avg_price", "mark_price",
        "tp0", "tp", "tp1", "tp2", "sl", "trail_sl", "liq_price",
        "atr", "leverage", "margin", "notional", "fee_open",
        "fee_close_est", "pnl", "pnl_net", "max_pnl_net",
        "tp0_hit", "tp1_hit", "breakeven", "last_event",
        "open_time", "opened_at", "open_ts", "setup_type", "args_text",
    ]
    for key in keys:
        try:
            if hasattr(pos, key):
                out[key] = getattr(pos, key)
        except Exception:
            pass

    try:
        if "symbol" in out:
            out["symbol"] = str(out.get("symbol") or "").upper()
    except Exception:
        pass

    return out


def _vortex_router_runtime_snapshot_v185b(self):
    fut_pos = None
    fut_positions = {}
    spot_positions = {}

    try:
        fut_pos = self.get_futures_position()
        if fut_pos is not None:
            sym = getattr(fut_pos, "symbol", "") or "FUT"
            fut_positions[str(sym).upper()] = _vortex_position_to_dict_v185b(fut_pos)
    except Exception:
        pass

    try:
        if hasattr(self, "get_all_futures_positions"):
            raw = self.get_all_futures_positions() or {}
            if isinstance(raw, dict):
                fut_positions = {
                    str(k).upper(): _vortex_position_to_dict_v185b(v)
                    for k, v in raw.items()
                    if v is not None
                }
    except Exception:
        pass

    try:
        raw_spot = self.get_all_spot_positions() if hasattr(self, "get_all_spot_positions") else {}
        if isinstance(raw_spot, dict):
            spot_positions = {
                str(k).upper(): _vortex_position_to_dict_v185b(v)
                for k, v in raw_spot.items()
                if v is not None
            }
    except Exception:
        pass

    fut_bal = 0.0
    spot_bal = 0.0
    try:
        fut_bal = self.get_futures_balance()
    except Exception:
        pass
    try:
        spot_bal = self.get_spot_balance()
    except Exception:
        pass

    return {
        "mode": self.get_mode() if hasattr(self, "get_mode") else "",
        "ts": time.time(),
        "balances": {"fut": fut_bal, "spot": spot_bal},
        "fut_position": _vortex_position_to_dict_v185b(fut_pos),
        "fut_positions": fut_positions,
        "spot_positions": spot_positions,
    }

try:
    ExecutionRouter.get_runtime_snapshot = _vortex_router_runtime_snapshot_v185b
except Exception:
    pass
# --- END VORTEX v1.8.5b ROUTER RUNTIME SNAPSHOT ---
# --- VORTEX v1.8.21a ROUTER API CONTRACTS ---
def _vortex_router_first_value_v1821a(args, kwargs, names, default=None):
    for name in names:
        if name in kwargs and kwargs.get(name) is not None:
            return kwargs.get(name)
    if args:
        return args[0]
    return default


def _vortex_router_float_v1821a(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _vortex_router_str_v1821a(value, default=""):
    try:
        if value is None:
            return str(default)
        return str(value)
    except Exception:
        return str(default)


def _vortex_router_is_paper_v1821a(self, market):
    market = _vortex_router_str_v1821a(market).lower()
    if market in {"fut", "future", "futures"}:
        return _vortex_router_str_v1821a(getattr(self, "fut_mode", "PAPER"), "PAPER").upper() == "PAPER"
    if market == "spot":
        return _vortex_router_str_v1821a(getattr(self, "spot_mode", "PAPER"), "PAPER").upper() == "PAPER"
    return False


def _vortex_router_error_v1821a(msg, code="ERROR"):
    return {"code": code, "msg": _vortex_router_str_v1821a(msg)}


def _vortex_router_pos_get_v1821a(pos, *names, default=None):
    if isinstance(pos, dict):
        for name in names:
            if pos.get(name) is not None:
                return pos.get(name)
        return default
    for name in names:
        try:
            if hasattr(pos, name):
                value = getattr(pos, name)
                if value is not None:
                    return value
        except Exception:
            pass
    return default


def _vortex_close_futures_position_v1821a(self, *args, **kwargs):
    current_price = _vortex_router_first_value_v1821a(args, kwargs, ("current_price", "price", "p"), 0.0)
    reason = kwargs.get("reason")
    if reason is None and len(args) >= 2:
        reason = args[1]
    if reason is None:
        reason = "MANUAL"

    if not _vortex_router_is_paper_v1821a(self, "fut"):
        return _vortex_router_error_v1821a("futures close is PAPER-only in this snapshot")
    return self.paper_futures.close_position(_vortex_router_float_v1821a(current_price), _vortex_router_str_v1821a(reason, "MANUAL"))


def _vortex_check_futures_position_v1821a(self, *args, **kwargs):
    current_price = _vortex_router_first_value_v1821a(args, kwargs, ("current_price", "price", "p"), 0.0)
    if not _vortex_router_is_paper_v1821a(self, "fut"):
        return None
    return self.paper_futures.check_stops(_vortex_router_float_v1821a(current_price))


def _vortex_close_spot_position_v1821a(self, *args, **kwargs):
    symbol = kwargs.get("symbol")
    current_price = kwargs.get("current_price", kwargs.get("price"))
    reason = kwargs.get("reason", "MANUAL")

    if symbol is None and len(args) >= 1:
        symbol = args[0]
    if current_price is None and len(args) >= 2:
        current_price = args[1]
    if "reason" not in kwargs and len(args) >= 3:
        reason = args[2]

    symbol = _vortex_router_str_v1821a(symbol).upper()
    if not symbol:
        return _vortex_router_error_v1821a("spot symbol is required")
    if not _vortex_router_is_paper_v1821a(self, "spot"):
        return _vortex_router_error_v1821a("spot close is PAPER-only in this snapshot")
    return self.paper_spot.close_position(symbol, _vortex_router_float_v1821a(current_price), _vortex_router_str_v1821a(reason, "MANUAL"))


def _vortex_check_spot_position_v1821a(self, *args, **kwargs):
    symbol = kwargs.get("symbol")
    current_price = kwargs.get("current_price", kwargs.get("price"))

    if symbol is None and len(args) >= 1:
        symbol = args[0]
    if current_price is None and len(args) >= 2:
        current_price = args[1]

    symbol = _vortex_router_str_v1821a(symbol).upper()
    if not symbol:
        return None
    if not _vortex_router_is_paper_v1821a(self, "spot"):
        return None
    return self.paper_spot.check_stops(symbol, _vortex_router_float_v1821a(current_price))


def _vortex_manual_open_futures_v1821a(
    self,
    symbol="BTCUSDT",
    side="LONG",
    price=0.0,
    atr=0.0,
    margin_usdt=20.0,
    leverage=3.0,
    tp0_mult=0.6,
    tp_mult=2.0,
    sl_mult=1.5,
    setup_type="manual_fut",
    args_text="manual futures open",
    **kwargs,
):
    if not _vortex_router_is_paper_v1821a(self, "fut"):
        return _vortex_router_error_v1821a("manual futures open is PAPER-only in this snapshot")

    symbol = _vortex_router_str_v1821a(symbol, "BTCUSDT").upper()
    side_u = _vortex_router_str_v1821a(side, "LONG").upper()
    price = _vortex_router_float_v1821a(price)
    atr = _vortex_router_float_v1821a(atr)
    margin_usdt = _vortex_router_float_v1821a(margin_usdt)
    leverage = _vortex_router_float_v1821a(leverage, 1.0)

    if price <= 0 or atr <= 0 or margin_usdt <= 0 or leverage <= 0:
        return _vortex_router_error_v1821a("invalid manual futures params")
    if side_u not in {"LONG", "SHORT", "BUY", "SELL"}:
        return _vortex_router_error_v1821a("unsupported futures side")

    side_norm = "LONG" if side_u in {"LONG", "BUY"} else "SHORT"
    qty = (margin_usdt * leverage) / price

    if side_norm == "LONG":
        tp0 = price + atr * _vortex_router_float_v1821a(tp0_mult, 0.6)
        tp = price + atr * _vortex_router_float_v1821a(tp_mult, 2.0)
        tp2 = price + atr * max(_vortex_router_float_v1821a(tp_mult, 2.0), 3.5)
        sl = price - atr * _vortex_router_float_v1821a(sl_mult, 1.5)
    else:
        tp0 = price - atr * _vortex_router_float_v1821a(tp0_mult, 0.6)
        tp = price - atr * _vortex_router_float_v1821a(tp_mult, 2.0)
        tp2 = price - atr * max(_vortex_router_float_v1821a(tp_mult, 2.0), 3.5)
        sl = price + atr * _vortex_router_float_v1821a(sl_mult, 1.5)

    return self.paper_futures.open_position(
        symbol=symbol,
        side=side_norm,
        qty=qty,
        price=price,
        tp=tp,
        sl=sl,
        atr=atr,
        leverage=leverage,
        setup_type=_vortex_router_str_v1821a(setup_type, "manual_fut"),
        args_text=_vortex_router_str_v1821a(args_text, "manual futures open"),
        tp0=tp0,
        tp2=tp2,
    )


def _vortex_manual_open_spot_v1821a(
    self,
    symbol="BTCUSDT",
    price=0.0,
    atr=0.0,
    order_usdt=20.0,
    tp_mult=3.0,
    setup_type="manual_spot",
    args_text="manual spot open",
    **kwargs,
):
    if not _vortex_router_is_paper_v1821a(self, "spot"):
        return _vortex_router_error_v1821a("manual spot open is PAPER-only in this snapshot")

    symbol = _vortex_router_str_v1821a(symbol, "BTCUSDT").upper()
    price = _vortex_router_float_v1821a(price)
    atr = _vortex_router_float_v1821a(atr)
    order_usdt = _vortex_router_float_v1821a(order_usdt)
    if price <= 0 or atr <= 0 or order_usdt <= 0:
        return _vortex_router_error_v1821a("invalid manual spot params")

    qty = order_usdt / price
    tp = price + atr * _vortex_router_float_v1821a(tp_mult, 3.0)
    return self.paper_spot.open_position(
        symbol=symbol,
        qty=qty,
        price=price,
        tp=tp,
        atr=atr,
        setup_type=_vortex_router_str_v1821a(setup_type, "manual_spot"),
        args_text=_vortex_router_str_v1821a(args_text, "manual spot open"),
    )


def _vortex_manual_close_all_spot_v1821a(self, prices=None, reason="MANUAL", **kwargs):
    if not _vortex_router_is_paper_v1821a(self, "spot"):
        return [_vortex_router_error_v1821a("manual spot close-all is PAPER-only in this snapshot")]

    prices = prices if isinstance(prices, dict) else {}
    result = []
    positions = self.get_all_spot_positions() if hasattr(self, "get_all_spot_positions") else {}
    for symbol, pos in list((positions or {}).items()):
        sym = _vortex_router_str_v1821a(symbol or _vortex_router_pos_get_v1821a(pos, "symbol", default="")).upper()
        price = prices.get(sym) or prices.get(sym.lower())
        if price is None:
            price = (
                _vortex_router_pos_get_v1821a(pos, "mark_price")
                or _vortex_router_pos_get_v1821a(pos, "current_price")
                or _vortex_router_pos_get_v1821a(pos, "avg_price")
                or _vortex_router_pos_get_v1821a(pos, "entry")
                or 0.0
            )
        result.append(self.close_spot_position(symbol=sym, current_price=_vortex_router_float_v1821a(price), reason=reason))
    return result


def _vortex_update_futures_sl_v1821a(self, new_sl, reason="GUIDE_SL", **kwargs):
    if not _vortex_router_is_paper_v1821a(self, "fut"):
        return _vortex_router_error_v1821a("futures SL update is PAPER-only in this snapshot")
    if hasattr(self.paper_futures, "update_sl"):
        return self.paper_futures.update_sl(_vortex_router_float_v1821a(new_sl), reason=_vortex_router_str_v1821a(reason, "GUIDE_SL"))
    return None


try:
    ExecutionRouter.close_futures_position = _vortex_close_futures_position_v1821a
    ExecutionRouter.close_spot_position = _vortex_close_spot_position_v1821a
    ExecutionRouter.check_futures_position = _vortex_check_futures_position_v1821a
    ExecutionRouter.check_spot_position = _vortex_check_spot_position_v1821a
    ExecutionRouter.manual_open_futures = _vortex_manual_open_futures_v1821a
    ExecutionRouter.manual_open_spot = _vortex_manual_open_spot_v1821a
    ExecutionRouter.manual_close_all_spot = _vortex_manual_close_all_spot_v1821a
    ExecutionRouter.update_futures_sl = _vortex_update_futures_sl_v1821a
except Exception:
    pass
# --- END VORTEX v1.8.21a ROUTER API CONTRACTS ---


# --- VORTEX v1.8.21f-a HARD FUT PRE-OPEN STATE GUARD ---
def _vortex_open_futures_position_v1821fa(self, *args, **kwargs):
    """
    Hard safety guard:
    If persistent trades_state.json still contains FUT open positions while runtime
    is empty, block a new FUT open instead of overwriting/losing state.
    """
    if not _vortex_router_is_paper_v1821a(self, "fut"):
        return _vortex_router_error_v1821a("futures open is PAPER-only in this snapshot")

    try:
        runtime_pos = None
        if hasattr(self, "paper_futures") and hasattr(self.paper_futures, "get_position"):
            runtime_pos = self.paper_futures.get_position()

        # If runtime already has a position, let PaperFutures return its normal rejection.
        if runtime_pos is None:
            try:
                from persistent_state_guard import evaluate_futures_pre_open_guard

                guard = evaluate_futures_pre_open_guard(
                    symbol=kwargs.get("symbol"),
                    side=kwargs.get("side"),
                    router=self,
                    state_path="trades_state.json",
                    fail_closed=True,
                )
            except Exception as exc:
                guard = {
                    "allow": False,
                    "code": "STATE_GUARD_EXCEPTION",
                    "reason": f"state_guard_exception:{exc}",
                }

            if not guard.get("allow", False):
                return {
                    "code": "BLOCK_OPEN_STATE_MISMATCH",
                    "msg": guard.get("reason", "persistent state guard blocked futures open"),
                    "guard": guard,
                }

    except Exception as exc:
        return {
            "code": "BLOCK_OPEN_STATE_MISMATCH",
            "msg": f"persistent state guard fatal:{exc}",
            "guard": {"allow": False, "reason": str(exc)},
        }

    return self.paper_futures.open_position(*args, **kwargs)


try:
    ExecutionRouter.open_futures_position = _vortex_open_futures_position_v1821fa
except Exception:
    pass
# --- END VORTEX v1.8.21f-a HARD FUT PRE-OPEN STATE GUARD ---


# --- VORTEX v1.8.21h-a ENTRY SAFETY POLICY ---
_vortex_prev_open_futures_position_v1821h = ExecutionRouter.open_futures_position

def _vortex_open_futures_position_v1821h(self, *args, **kwargs):
    """
    Final pre-open safety gate before FUT open.
    Blocks weak EA grades, disabled setups, blacklisted symbols, repeat symbol trades,
    and excessive daily FUT activity.
    """
    try:
        from entry_safety_policy import evaluate_entry_safety

        policy = evaluate_entry_safety(
            args=args,
            kwargs=kwargs,
            trades_path="trades.csv",
        )

        if not policy.get("allow", False):
            return {
                "code": "BLOCK_ENTRY_SAFETY_POLICY",
                "msg": policy.get("reason", "entry safety policy blocked futures open"),
                "policy": policy,
            }

    except Exception as exc:
        return {
            "code": "BLOCK_ENTRY_SAFETY_POLICY",
            "msg": f"entry safety policy fatal:{exc}",
            "policy": {
                "allow": False,
                "code": "ENTRY_SAFETY_EXCEPTION",
                "reason": str(exc),
            },
        }

    return _vortex_prev_open_futures_position_v1821h(self, *args, **kwargs)


try:
    ExecutionRouter.open_futures_position = _vortex_open_futures_position_v1821h
except Exception:
    pass
# --- END VORTEX v1.8.21h-a ENTRY SAFETY POLICY ---


# --- VORTEX v1.8.21h-b ENTRY CANDIDATE JOURNAL ---
_vortex_prev_open_futures_position_v1821hb = ExecutionRouter.open_futures_position

def _vortex_open_futures_position_v1821hb(self, *args, **kwargs):
    """
    Observability wrapper:
    logs every FUT open attempt with EA/setup/policy/result into
    _runtime/entry_candidates.jsonl.
    """
    policy = None

    try:
        from entry_safety_policy import evaluate_entry_safety
        policy = evaluate_entry_safety(
            args=args,
            kwargs=kwargs,
            trades_path="trades.csv",
        )
    except Exception as exc:
        policy = {
            "allow": False,
            "code": "ENTRY_SAFETY_EXCEPTION",
            "reason": str(exc),
        }

    if not policy.get("allow", False):
        result = {
            "code": "BLOCK_ENTRY_SAFETY_POLICY",
            "msg": policy.get("reason", "entry safety policy blocked futures open"),
            "policy": policy,
        }
        try:
            from entry_candidate_journal import log_entry_candidate
            log_entry_candidate(
                args=args,
                kwargs=kwargs,
                policy=policy,
                result=result,
                final_action="BLOCKED",
            )
        except Exception:
            pass
        return result

    result = _vortex_prev_open_futures_position_v1821hb(self, *args, **kwargs)

    try:
        from entry_candidate_journal import log_entry_candidate
        final_action = "OPEN_ATTEMPT"
        if isinstance(result, dict) and str(result.get("code")) != "00000":
            final_action = "OPEN_REJECTED_BY_ROUTER"
        log_entry_candidate(
            args=args,
            kwargs=kwargs,
            policy=policy,
            result=result if isinstance(result, dict) else {"code": "UNKNOWN", "msg": str(result)},
            final_action=final_action,
        )
    except Exception:
        pass

    return result


try:
    ExecutionRouter.open_futures_position = _vortex_open_futures_position_v1821hb
except Exception:
    pass
# --- END VORTEX v1.8.21h-b ENTRY CANDIDATE JOURNAL ---

