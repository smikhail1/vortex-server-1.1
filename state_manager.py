import asyncio
import copy
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from config import CONFIG, DEFAULT_STATE_META
from validators import (
    normalize_symbol, safe_float, safe_int, safe_str,
    validate_planner_payload, validate_position_payload,
    validate_symbol_health, validate_ta_payload, validate_watchlist_payload,
)

class StateManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized: return
        self._lock = asyncio.Lock()
        self._sys_logs: Deque[str] = deque(maxlen=CONFIG.logging.max_sys_logs)
        self._started_ts: float = time.time()
        self.state: Dict[str, Any] = {
            "meta": dict(DEFAULT_STATE_META),
            "market": {
                "prices": {}, 
                "ta_data": {}, 
                "symbol_health": {},
                "last_market_update_ts": 0.0, 
                "last_ta_update_ts": 0.0
            },
            "account": {"balances": {"fut": float(CONFIG.futures.start_balance), "spot": float(CONFIG.spot.start_balance)}},
            "positions": {"fut": {}, "spot": {}},
            "system": {
                "fut_pool": [], "spot_pool": [],
                "macro": {"btc_trend": "neutral", "global_filter": "allow_all", "binance_btc": 0.0, "funding_rates": {}},
                "rotation_timer": 0, "sys_logs": [], "uptime": "00:00:00",
            },
            "planner": {"market_data": {}, "ideas": [], "spot_planner": {}},
            "terminal": {"watchlist_mini": []},
        }
        self._initialized = True

    async def get_dashboard_state(self) -> Dict[str, Any]:
        async with self._lock:
            self.state["system"]["sys_logs"] = list(self._sys_logs)
            return copy.deepcopy(self.state)

    async def get_runtime_snapshot(self) -> Dict[str, Any]:
        async with self._lock:
            res = copy.deepcopy(self.state)
            uptime_sec = int(time.time() - self._started_ts)
            res["system"]["uptime"] = time.strftime('%H:%M:%S', time.gmtime(uptime_sec))
            return res

    async def update_macro(self, macro: Dict[str, Any]) -> None:
        async with self._lock:
            if isinstance(macro, dict):
                self.state["system"]["macro"].update(macro)

    async def update_market_price(self, symbol: str, price: float, ts: Optional[float] = None) -> None:
        async with self._lock:
            sym = normalize_symbol(symbol)
            self.state["market"]["prices"][sym] = safe_float(price)
            self.state["market"]["last_market_update_ts"] = safe_float(ts, time.time())

    async def update_ta_data(self, ta_map: Dict[str, Dict[str, Any]]) -> None:
        async with self._lock:
            self.state["market"]["ta_data"] = ta_map
            self.state["market"]["last_ta_update_ts"] = time.time()

    async def set_watchlist_mini(self, items: List[Dict[str, Any]]) -> None:
        async with self._lock:
            self.state["terminal"]["watchlist_mini"] = items

    async def get_health_state(self, mode: Optional[str] = None) -> Dict[str, Any]:
        async with self._lock:
            now = time.time()
            lm = self.state["market"].get("last_market_update_ts", 0.0)
            lt = self.state["market"].get("last_ta_update_ts", 0.0)
            return {
                "status": "online" if (now - lm) < 30 else "degraded",
                "mode": mode or self.state["meta"].get("mode", "PAPER"),
                "uptime": "active",
                "market_age_sec": round(now - lm, 1) if lm > 0 else 9999.0,
                "ta_age_sec": round(now - lt, 1) if lt > 0 else 9999.0,
                "server_time": int(now),
            }

    async def sync_router_snapshot(self, router: Any) -> None:
        try:
            f_bal = safe_float(router.get_futures_balance())
            s_bal = safe_float(router.get_spot_balance())
            async with self._lock:
                self.state["account"]["balances"]["fut"] = f_bal
                self.state["account"]["balances"]["spot"] = s_bal
        except: pass

    async def add_sys_log(self, tag: str, message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {tag} {message}"
        async with self._lock: self._sys_logs.appendleft(line)

    async def set_pool(self, m, s):
        async with self._lock: self.state["system"][f"{m}_pool"] = s
        
    async def set_mode(self, m):
        async with self._lock: self.state["meta"]["mode"] = m.upper()
        
    async def update_timer(self, s):
        async with self._lock: self.state["system"]["rotation_timer"] = s
        
    async def update_system_metrics(self, u, r, p):
        async with self._lock:
            self.state["system"]["uptime"] = safe_str(u, "00:00:00")
            self.state["system"]["ram_mb"] = safe_float(r, 0.0)
            self.state["system"]["ping_ms"] = safe_float(p, 0.0)

    # [ФИКС] Убираем pass и сохраняем данные Планера в стейт
    async def update_planner_market_data(self, s):
        async with self._lock:
            self.state["planner"]["market_data"] = s

    async def update_spot_planner(self, p):
        async with self._lock:
            self.state["planner"]["spot_planner"] = p
            self.state["planner"]["ideas"] = p.get("ideas", [])

    async def get_pool(self, m): return self.state["system"].get(f"{m}_pool", [])
    async def get_spot_planner_state(self): return self.state["planner"].get("spot_planner", self.state["planner"])
    async def replace_state(self, n):
        if not isinstance(n, dict):
            raise ValueError("state must be dict")
        async with self._lock:
            self.state = copy.deepcopy(n)
            self.state.setdefault("meta", dict(DEFAULT_STATE_META))
            self.state.setdefault("market", {})
            self.state["market"].setdefault("prices", {})
            self.state["market"].setdefault("ta_data", {})
            self.state["market"].setdefault("symbol_health", {})
            self.state["market"].setdefault("last_market_update_ts", 0.0)
            self.state["market"].setdefault("last_ta_update_ts", 0.0)
            self.state.setdefault("account", {"balances": {}})
            self.state["account"].setdefault("balances", {})
            self.state["account"]["balances"].setdefault("fut", float(CONFIG.futures.start_balance))
            self.state["account"]["balances"].setdefault("spot", float(CONFIG.spot.start_balance))
            self.state.setdefault("positions", {"fut": {}, "spot": {}})
            self.state["positions"].setdefault("fut", {})
            self.state["positions"].setdefault("spot", {})
            self.state.setdefault("system", {})
            self.state["system"].setdefault("sys_logs", [])
            self.state.setdefault("planner", {"market_data": {}, "ideas": [], "spot_planner": {}})
            self.state.setdefault("terminal", {"watchlist_mini": []})
            self._sys_logs.clear()
            for line in list(self.state["system"].get("sys_logs", []))[:CONFIG.logging.max_sys_logs]:
                self._sys_logs.append(safe_str(line))
    async def clear_sys_logs(self):
        async with self._lock:
            self._sys_logs.clear()
            self.state["system"]["sys_logs"] = []
    async def set_symbol_health(self, s, p):
        sym = normalize_symbol(s)
        payload = p if isinstance(p, dict) else {"status": safe_str(p, "UNKNOWN")}
        async with self._lock:
            self.state["market"].setdefault("symbol_health", {})
            self.state["market"]["symbol_health"][sym] = payload
    def _serialize_position_object(self, p, m):
        if p is None:
            return {}
        if isinstance(p, dict):
            data = dict(p)
        else:
            data = {}
            for key in [
                "symbol", "side", "qty", "entry", "avg_price", "mark_price",
                "tp0", "tp", "tp1", "tp2", "sl", "trail_sl", "liq_price",
                "atr", "leverage", "margin", "notional", "fee_open",
                "fee_close_est", "pnl", "pnl_net", "max_pnl_net",
                "tp0_hit", "tp1_hit", "breakeven", "last_event",
                "open_time", "setup_type", "args_text", "fills_count",
            ]:
                if hasattr(p, key):
                    data[key] = getattr(p, key)
        data["market"] = safe_str(m).upper()
        if "symbol" in data:
            data["symbol"] = safe_str(data.get("symbol")).upper()
        open_time = safe_float(data.get("open_time"), 0.0)
        if open_time > 0:
            import time
            data["hold_sec"] = max(0, int(time.time() - open_time))
        return data