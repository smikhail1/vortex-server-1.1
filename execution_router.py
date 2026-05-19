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
            print(f"[ROUTER] 🔑 Bitget Sub-account API Keys detected! Ready for REAL execution.", flush=True)

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



# --- VORTEX v1.8.19e MULTI FUTURES ROUTER ---
try:
    def _router_all_fut(self):
        try:
            if self.fut_mode=='PAPER' and hasattr(self.paper_futures,'get_all_positions'):
                return self.paper_futures.get_all_positions()
            pos=self.get_futures_position() if hasattr(self,'get_futures_position') else None
            if pos is None: return {}
            sym=str(getattr(pos,'symbol','') or 'FUT').upper()
            return {sym:pos}
        except Exception: return {}

    def _router_get_fut(self,symbol=None):
        try:
            if self.fut_mode=='PAPER' and hasattr(self.paper_futures,'get_position'):
                return self.paper_futures.get_position(symbol)
        except TypeError:
            return self.paper_futures.get_position()
        except Exception:
            return None
        return None

    def _router_check_fut_sym(self,symbol,price):
        try:
            if self.fut_mode=='PAPER' and hasattr(self.paper_futures,'check_position'):
                return self.paper_futures.check_position(symbol,price)
        except Exception: return None
        return None

    def _router_close_fut_sym(self,symbol,price,reason='MANUAL'):
        try:
            if self.fut_mode=='PAPER': return self.paper_futures.close_position(price,reason,symbol=symbol)
        except TypeError:
            return self.paper_futures.close_position(price,reason)
        except Exception: return None
        return None

    ExecutionRouter.get_all_futures_positions=_router_all_fut
    ExecutionRouter.get_futures_position=_router_get_fut
    ExecutionRouter.check_futures_position_for_symbol=_router_check_fut_sym
    ExecutionRouter.close_futures_position_for_symbol=_router_close_fut_sym
except Exception:
    pass
# --- END VORTEX v1.8.19e MULTI FUTURES ROUTER ---
