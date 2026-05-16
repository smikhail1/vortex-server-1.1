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

# --- VORTEX v1.8.5b POSITION VISIBILITY SYNC ---
async def _vortex_sync_router_snapshot_v185b(self, router):
    try:
        f_bal = safe_float(router.get_futures_balance())
    except Exception:
        f_bal = 0.0

    try:
        s_bal = safe_float(router.get_spot_balance())
    except Exception:
        s_bal = 0.0

    fut_positions = {}
    spot_positions = {}

    try:
        raw_fut = {}
        if hasattr(router, "get_all_futures_positions"):
            raw_fut = router.get_all_futures_positions() or {}
        elif hasattr(router, "get_futures_position"):
            pos = router.get_futures_position()
            if pos is not None:
                sym = "FUT"
                if isinstance(pos, dict):
                    sym = safe_str(pos.get("symbol") or "FUT").upper()
                else:
                    sym = safe_str(getattr(pos, "symbol", "") or "FUT").upper()
                raw_fut = {sym: pos}

        if isinstance(raw_fut, dict):
            for sym, pos in raw_fut.items():
                if pos is None:
                    continue
                key = safe_str(sym).upper()
                if key:
                    fut_positions[key] = self._serialize_position_object(pos, "FUT")
    except Exception:
        fut_positions = {}

    try:
        raw_spot = router.get_all_spot_positions() if hasattr(router, "get_all_spot_positions") else {}

        if isinstance(raw_spot, dict):
            items = list(raw_spot.items())
        elif isinstance(raw_spot, list):
            items = []
            for pos in raw_spot:
                if isinstance(pos, dict):
                    sym = safe_str(pos.get("symbol")).upper()
                else:
                    sym = safe_str(getattr(pos, "symbol", "")).upper()
                if sym:
                    items.append((sym, pos))
        else:
            items = []

        for sym, pos in items:
            if pos is None:
                continue
            key = safe_str(sym).upper()
            if key:
                spot_positions[key] = self._serialize_position_object(pos, "SPOT")
    except Exception:
        spot_positions = {}

    async with self._lock:
        self.state.setdefault("account", {}).setdefault("balances", {})
        self.state["account"]["balances"]["fut"] = f_bal
        self.state["account"]["balances"]["spot"] = s_bal

        self.state.setdefault("positions", {})
        self.state["positions"]["fut"] = fut_positions
        self.state["positions"]["spot"] = spot_positions

try:
    StateManager.sync_router_snapshot = _vortex_sync_router_snapshot_v185b
except Exception:
    pass
# --- END VORTEX v1.8.5b POSITION VISIBILITY SYNC ---



# --- VORTEX v1.8.7c ATOMIC WATCHLIST SWAP SAFEGUARD ---
async def _vortex_set_watchlist_mini_v187c(self, items):
    try:
        new_items = list(items or [])
    except Exception:
        new_items = []

    async with self._lock:
        terminal = self.state.setdefault("terminal", {})
        prev = terminal.get("watchlist_mini", []) or []

        if not new_items and prev:
            terminal.setdefault("watchlist_meta", {})
            terminal["watchlist_meta"].update({
                "preserved_previous": True,
                "last_empty_swap_skipped": time.time(),
                "previous_count": len(prev),
            })
            return

        terminal["watchlist_mini"] = new_items
        terminal.setdefault("watchlist_meta", {})
        terminal["watchlist_meta"].update({
            "preserved_previous": False,
            "last_update_ts": time.time(),
            "count": len(new_items),
        })

try:
    StateManager.set_watchlist_mini = _vortex_set_watchlist_mini_v187c
except Exception:
    pass
# --- END VORTEX v1.8.7c ATOMIC WATCHLIST SWAP SAFEGUARD ---



# --- VORTEX v1.8.7d_fix PERSISTENT WATCHLIST MEMORY ---
def _vortex_watchlist_init_memory_v187d_fix(self):
    try:
        if not hasattr(self, "_last_non_empty_watchlist"):
            self._last_non_empty_watchlist = []
        if not hasattr(self, "_last_non_empty_watchlist_ts"):
            self._last_non_empty_watchlist_ts = 0.0
    except Exception:
        pass


async def _vortex_set_watchlist_mini_v187d_fix(self, items):
    _vortex_watchlist_init_memory_v187d_fix(self)

    try:
        new_items = list(items or [])
    except Exception:
        new_items = []

    async with self._lock:
        terminal = self.state.setdefault("terminal", {})
        prev_state = terminal.get("watchlist_mini", []) or []
        prev_memory = getattr(self, "_last_non_empty_watchlist", []) or []

        if not new_items:
            restore = prev_state or prev_memory
            terminal.setdefault("watchlist_meta", {})

            if restore:
                terminal["watchlist_mini"] = list(restore)
                terminal["watchlist_meta"].update({
                    "preserved_previous": True,
                    "source": "state" if prev_state else "memory",
                    "last_empty_swap_skipped": time.time(),
                    "restored_count": len(restore),
                    "memory_age_sec": round(time.time() - float(getattr(self, "_last_non_empty_watchlist_ts", 0.0) or 0.0), 1),
                })
                return

            terminal["watchlist_mini"] = []
            terminal["watchlist_meta"].update({
                "preserved_previous": False,
                "source": "empty_no_previous",
                "last_update_ts": time.time(),
                "count": 0,
            })
            return

        self._last_non_empty_watchlist = list(new_items)
        self._last_non_empty_watchlist_ts = time.time()

        terminal["watchlist_mini"] = new_items
        terminal.setdefault("watchlist_meta", {})
        terminal["watchlist_meta"].update({
            "preserved_previous": False,
            "source": "fresh",
            "last_update_ts": time.time(),
            "count": len(new_items),
            "memory_count": len(self._last_non_empty_watchlist),
        })


async def _vortex_get_dashboard_state_v187d_fix(self):
    _vortex_watchlist_init_memory_v187d_fix(self)

    async with self._lock:
        self.state["system"]["sys_logs"] = list(self._sys_logs)

        terminal = self.state.setdefault("terminal", {})
        current = terminal.get("watchlist_mini", []) or []
        memory = getattr(self, "_last_non_empty_watchlist", []) or []

        if not current and memory:
            terminal["watchlist_mini"] = list(memory)
            terminal.setdefault("watchlist_meta", {})
            terminal["watchlist_meta"].update({
                "preserved_previous": True,
                "source": "dashboard_memory_restore",
                "restored_count": len(memory),
                "restored_ts": time.time(),
                "memory_age_sec": round(time.time() - float(getattr(self, "_last_non_empty_watchlist_ts", 0.0) or 0.0), 1),
            })

        return copy.deepcopy(self.state)


async def _vortex_replace_state_v187d_fix(self, n):
    _vortex_watchlist_init_memory_v187d_fix(self)

    if not isinstance(n, dict):
        raise ValueError("state must be dict")

    memory = list(getattr(self, "_last_non_empty_watchlist", []) or [])
    memory_ts = float(getattr(self, "_last_non_empty_watchlist_ts", 0.0) or 0.0)

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
        self.state.setdefault("terminal", {})
        self.state["terminal"].setdefault("watchlist_mini", [])

        current = self.state["terminal"].get("watchlist_mini", []) or []
        if current:
            self._last_non_empty_watchlist = list(current)
            self._last_non_empty_watchlist_ts = time.time()
        elif memory:
            self._last_non_empty_watchlist = memory
            self._last_non_empty_watchlist_ts = memory_ts
            self.state["terminal"]["watchlist_mini"] = list(memory)
            self.state["terminal"].setdefault("watchlist_meta", {})
            self.state["terminal"]["watchlist_meta"].update({
                "preserved_previous": True,
                "source": "replace_state_memory_restore",
                "restored_count": len(memory),
                "restored_ts": time.time(),
            })

        self._sys_logs.clear()
        for line in list(self.state["system"].get("sys_logs", []))[:CONFIG.logging.max_sys_logs]:
            self._sys_logs.append(safe_str(line))


try:
    StateManager.set_watchlist_mini = _vortex_set_watchlist_mini_v187d_fix
    StateManager.get_dashboard_state = _vortex_get_dashboard_state_v187d_fix
    StateManager.replace_state = _vortex_replace_state_v187d_fix
except Exception:
    pass
# --- END VORTEX v1.8.7d_fix PERSISTENT WATCHLIST MEMORY ---



# --- VORTEX v1.8.8 STATE AUTHORITY GUARD ---
# Purpose:
# - one state authority runtime diagnostics
# - durable last-good watchlist cache survives service restart
# - empty watchlist builds cannot wipe terminal state if cache exists

import json as _vortex_json
from pathlib import Path as _VortexPath

_VORTEX_WATCHLIST_CACHE_PATH = _VortexPath("_runtime/watchlist_cache.json")


def _vortex_ensure_runtime_dir_v188():
    try:
        _VORTEX_WATCHLIST_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _vortex_load_watchlist_cache_v188():
    try:
        if not _VORTEX_WATCHLIST_CACHE_PATH.exists():
            return []
        data = _vortex_json.loads(_VORTEX_WATCHLIST_CACHE_PATH.read_text(encoding="utf-8"))
        items = data.get("items", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []
    except Exception:
        return []


def _vortex_save_watchlist_cache_v188(items):
    try:
        _vortex_ensure_runtime_dir_v188()
        payload = {
            "ts": time.time(),
            "count": len(items or []),
            "items": list(items or []),
        }
        _VORTEX_WATCHLIST_CACHE_PATH.write_text(
            _vortex_json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _vortex_state_authority_init_v188(self):
    try:
        if not hasattr(self, "_authority_instance_id"):
            self._authority_instance_id = f"StateManager:{id(self)}:{int(time.time())}"
        if not hasattr(self, "_last_non_empty_watchlist"):
            self._last_non_empty_watchlist = []
        if not hasattr(self, "_last_non_empty_watchlist_ts"):
            self._last_non_empty_watchlist_ts = 0.0

        if not self._last_non_empty_watchlist:
            cached = _vortex_load_watchlist_cache_v188()
            if cached:
                self._last_non_empty_watchlist = list(cached)
                self._last_non_empty_watchlist_ts = time.time()
    except Exception:
        pass


async def _vortex_set_watchlist_mini_v188(self, items):
    _vortex_state_authority_init_v188(self)

    try:
        new_items = list(items or [])
    except Exception:
        new_items = []

    async with self._lock:
        terminal = self.state.setdefault("terminal", {})
        prev_state = terminal.get("watchlist_mini", []) or []
        prev_memory = getattr(self, "_last_non_empty_watchlist", []) or []

        if not prev_memory:
            prev_memory = _vortex_load_watchlist_cache_v188()

        if not new_items:
            restore = prev_state or prev_memory
            terminal.setdefault("watchlist_meta", {})

            if restore:
                terminal["watchlist_mini"] = list(restore)
                terminal["watchlist_meta"].update({
                    "preserved_previous": True,
                    "source": "state" if prev_state else ("memory" if getattr(self, "_last_non_empty_watchlist", []) else "disk_cache"),
                    "last_empty_swap_skipped": time.time(),
                    "restored_count": len(restore),
                    "authority_instance_id": getattr(self, "_authority_instance_id", ""),
                })
                return

            terminal["watchlist_mini"] = []
            terminal.setdefault("watchlist_meta", {})
            terminal["watchlist_meta"].update({
                "preserved_previous": False,
                "source": "empty_no_previous",
                "last_update_ts": time.time(),
                "count": 0,
                "authority_instance_id": getattr(self, "_authority_instance_id", ""),
            })
            return

        self._last_non_empty_watchlist = list(new_items)
        self._last_non_empty_watchlist_ts = time.time()
        _vortex_save_watchlist_cache_v188(new_items)

        terminal["watchlist_mini"] = new_items
        terminal.setdefault("watchlist_meta", {})
        terminal["watchlist_meta"].update({
            "preserved_previous": False,
            "source": "fresh",
            "last_update_ts": time.time(),
            "count": len(new_items),
            "memory_count": len(self._last_non_empty_watchlist),
            "authority_instance_id": getattr(self, "_authority_instance_id", ""),
        })


async def _vortex_get_dashboard_state_v188(self):
    _vortex_state_authority_init_v188(self)

    async with self._lock:
        self.state["system"]["sys_logs"] = list(self._sys_logs)
        self.state.setdefault("meta", {})
        self.state["meta"]["state_authority_id"] = getattr(self, "_authority_instance_id", "")

        terminal = self.state.setdefault("terminal", {})
        current = terminal.get("watchlist_mini", []) or []
        memory = getattr(self, "_last_non_empty_watchlist", []) or []
        if not memory:
            memory = _vortex_load_watchlist_cache_v188()

        if not current and memory:
            terminal["watchlist_mini"] = list(memory)
            terminal.setdefault("watchlist_meta", {})
            terminal["watchlist_meta"].update({
                "preserved_previous": True,
                "source": "dashboard_memory_restore" if getattr(self, "_last_non_empty_watchlist", []) else "dashboard_disk_cache_restore",
                "restored_count": len(memory),
                "restored_ts": time.time(),
                "authority_instance_id": getattr(self, "_authority_instance_id", ""),
            })

        return copy.deepcopy(self.state)


async def _vortex_replace_state_v188(self, n):
    _vortex_state_authority_init_v188(self)

    if not isinstance(n, dict):
        raise ValueError("state must be dict")

    memory = list(getattr(self, "_last_non_empty_watchlist", []) or [])
    if not memory:
        memory = _vortex_load_watchlist_cache_v188()
    memory_ts = float(getattr(self, "_last_non_empty_watchlist_ts", 0.0) or 0.0)

    async with self._lock:
        self.state = copy.deepcopy(n)
        self.state.setdefault("meta", dict(DEFAULT_STATE_META))
        self.state["meta"]["state_authority_id"] = getattr(self, "_authority_instance_id", "")

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
        self.state.setdefault("terminal", {})
        self.state["terminal"].setdefault("watchlist_mini", [])

        current = self.state["terminal"].get("watchlist_mini", []) or []
        if current:
            self._last_non_empty_watchlist = list(current)
            self._last_non_empty_watchlist_ts = time.time()
            _vortex_save_watchlist_cache_v188(current)
        elif memory:
            self._last_non_empty_watchlist = list(memory)
            self._last_non_empty_watchlist_ts = memory_ts or time.time()
            self.state["terminal"]["watchlist_mini"] = list(memory)
            self.state["terminal"].setdefault("watchlist_meta", {})
            self.state["terminal"]["watchlist_meta"].update({
                "preserved_previous": True,
                "source": "replace_state_memory_restore",
                "restored_count": len(memory),
                "restored_ts": time.time(),
                "authority_instance_id": getattr(self, "_authority_instance_id", ""),
            })

        self._sys_logs.clear()
        for line in list(self.state["system"].get("sys_logs", []))[:CONFIG.logging.max_sys_logs]:
            self._sys_logs.append(safe_str(line))


try:
    StateManager.set_watchlist_mini = _vortex_set_watchlist_mini_v188
    StateManager.get_dashboard_state = _vortex_get_dashboard_state_v188
    StateManager.replace_state = _vortex_replace_state_v188
except Exception:
    pass
# --- END VORTEX v1.8.8 STATE AUTHORITY GUARD ---



# --- VORTEX v1.8.8b CACHE HYGIENE + PLANNER STABILITY ---
def _vortex_is_valid_watchlist_cache_item_v188b(item):
    try:
        if not isinstance(item, dict):
            return False
        sym = safe_str(item.get("symbol")).upper()
        if not sym or sym in {"TEST", "TESTUSDT", "DUMMY", "DUMMYUSDT"}:
            return False
        if not sym.endswith("USDT"):
            return False
        return True
    except Exception:
        return False


def _vortex_clean_watchlist_items_v188b(items):
    cleaned = []
    seen = set()
    try:
        for item in list(items or []):
            if not _vortex_is_valid_watchlist_cache_item_v188b(item):
                continue
            sym = safe_str(item.get("symbol")).upper()
            market = safe_str(item.get("market")).lower() or "na"
            key = f"{market}:{sym}"
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(item)
    except Exception:
        return []
    return cleaned


def _vortex_load_watchlist_cache_v188b():
    try:
        raw = _vortex_load_watchlist_cache_v188()
        cleaned = _vortex_clean_watchlist_items_v188b(raw)
        if raw and not cleaned:
            try:
                _VORTEX_WATCHLIST_CACHE_PATH.unlink(missing_ok=True)
            except Exception:
                pass
        return cleaned
    except Exception:
        return []


def _vortex_save_watchlist_cache_v188b(items):
    cleaned = _vortex_clean_watchlist_items_v188b(items)
    if not cleaned:
        return
    try:
        _vortex_save_watchlist_cache_v188(cleaned)
    except Exception:
        pass


async def _vortex_set_watchlist_mini_v188b(self, items):
    _vortex_state_authority_init_v188(self)

    try:
        new_items = _vortex_clean_watchlist_items_v188b(items)
    except Exception:
        new_items = []

    async with self._lock:
        terminal = self.state.setdefault("terminal", {})
        prev_state = _vortex_clean_watchlist_items_v188b(terminal.get("watchlist_mini", []) or [])
        prev_memory = _vortex_clean_watchlist_items_v188b(getattr(self, "_last_non_empty_watchlist", []) or [])

        if not prev_memory:
            prev_memory = _vortex_load_watchlist_cache_v188b()

        if not new_items:
            restore = prev_state or prev_memory
            terminal.setdefault("watchlist_meta", {})

            if restore:
                terminal["watchlist_mini"] = list(restore)
                terminal["watchlist_meta"].update({
                    "preserved_previous": True,
                    "source": "state" if prev_state else ("memory" if getattr(self, "_last_non_empty_watchlist", []) else "disk_cache"),
                    "last_empty_swap_skipped": time.time(),
                    "restored_count": len(restore),
                    "authority_instance_id": getattr(self, "_authority_instance_id", ""),
                    "cache_hygiene": "v1.8.8b",
                })
                return

            terminal["watchlist_mini"] = []
            terminal["watchlist_meta"] = {
                "preserved_previous": False,
                "source": "empty_no_valid_previous",
                "last_update_ts": time.time(),
                "count": 0,
                "authority_instance_id": getattr(self, "_authority_instance_id", ""),
                "cache_hygiene": "v1.8.8b",
            }
            return

        self._last_non_empty_watchlist = list(new_items)
        self._last_non_empty_watchlist_ts = time.time()
        _vortex_save_watchlist_cache_v188b(new_items)

        terminal["watchlist_mini"] = new_items
        terminal.setdefault("watchlist_meta", {})
        terminal["watchlist_meta"].update({
            "preserved_previous": False,
            "source": "fresh",
            "last_update_ts": time.time(),
            "count": len(new_items),
            "memory_count": len(self._last_non_empty_watchlist),
            "authority_instance_id": getattr(self, "_authority_instance_id", ""),
            "cache_hygiene": "v1.8.8b",
        })


async def _vortex_get_dashboard_state_v188b(self):
    _vortex_state_authority_init_v188(self)

    async with self._lock:
        self.state["system"]["sys_logs"] = list(self._sys_logs)
        self.state.setdefault("meta", {})
        self.state["meta"]["state_authority_id"] = getattr(self, "_authority_instance_id", "")

        terminal = self.state.setdefault("terminal", {})
        current = _vortex_clean_watchlist_items_v188b(terminal.get("watchlist_mini", []) or [])
        memory = _vortex_clean_watchlist_items_v188b(getattr(self, "_last_non_empty_watchlist", []) or [])
        if not memory:
            memory = _vortex_load_watchlist_cache_v188b()

        if current:
            terminal["watchlist_mini"] = current
        elif memory:
            terminal["watchlist_mini"] = list(memory)
            terminal.setdefault("watchlist_meta", {})
            terminal["watchlist_meta"].update({
                "preserved_previous": True,
                "source": "dashboard_memory_restore" if getattr(self, "_last_non_empty_watchlist", []) else "dashboard_disk_cache_restore",
                "restored_count": len(memory),
                "restored_ts": time.time(),
                "authority_instance_id": getattr(self, "_authority_instance_id", ""),
                "cache_hygiene": "v1.8.8b",
            })

        return copy.deepcopy(self.state)


async def _vortex_update_planner_market_data_v188b(self, snapshot):
    if not isinstance(snapshot, dict):
        return

    new_symbols = snapshot.get("symbols", {}) or {}
    new_count = len(new_symbols) if isinstance(new_symbols, dict) else 0

    async with self._lock:
        planner = self.state.setdefault("planner", {"market_data": {}, "ideas": [], "spot_planner": {}})
        old_snapshot = planner.get("market_data", {}) or {}
        old_symbols = old_snapshot.get("symbols", {}) if isinstance(old_snapshot, dict) else {}
        old_count = len(old_symbols) if isinstance(old_symbols, dict) else 0

        # Guard: do not replace a healthy planner snapshot with tiny/empty refresh.
        if old_count >= 20 and new_count < max(10, int(old_count * 0.45)):
            planner.setdefault("market_meta", {})
            planner["market_meta"].update({
                "preserved_previous": True,
                "source": "planner_snapshot_guard",
                "old_count": old_count,
                "new_count": new_count,
                "skipped_ts": time.time(),
            })
            return

        planner["market_data"] = snapshot
        planner.setdefault("market_meta", {})
        planner["market_meta"].update({
            "preserved_previous": False,
            "source": "fresh",
            "symbols": new_count,
            "updated_ts": time.time(),
        })


try:
    StateManager.set_watchlist_mini = _vortex_set_watchlist_mini_v188b
    StateManager.get_dashboard_state = _vortex_get_dashboard_state_v188b
    StateManager.update_planner_market_data = _vortex_update_planner_market_data_v188b
except Exception:
    pass
# --- END VORTEX v1.8.8b CACHE HYGIENE + PLANNER STABILITY ---



# --- VORTEX v1.8.8c_fix SINGLETON STATE AUTHORITY LOCK ---
# Safe version:
# - keeps original StateManager initialization model intact
# - uses class-level _instance instead of object.__new__
# - records repeated StateManager() calls for audit

import traceback as _vortex_traceback

_VORTEX_STATE_REUSE_COUNT = 0
_VORTEX_STATE_REUSE_TRACES = []


def _vortex_state_new_v188c_fix(cls, *args, **kwargs):
    global _VORTEX_STATE_REUSE_COUNT
    global _VORTEX_STATE_REUSE_TRACES

    if getattr(cls, "_instance", None) is None:
        inst = super(StateManager, cls).__new__(cls)
        cls._instance = inst
        try:
            inst._initialized = False
            inst._authority_instance_id = f"StateManagerSingleton:{id(inst)}:{int(time.time())}"
            inst._authority_created_ts = time.time()
        except Exception:
            pass
        return inst

    _VORTEX_STATE_REUSE_COUNT += 1
    try:
        trace = "".join(_vortex_traceback.format_stack(limit=8))
        _VORTEX_STATE_REUSE_TRACES.append({
            "ts": time.time(),
            "reuse_count": _VORTEX_STATE_REUSE_COUNT,
            "trace": trace,
        })
        if len(_VORTEX_STATE_REUSE_TRACES) > 10:
            _VORTEX_STATE_REUSE_TRACES = _VORTEX_STATE_REUSE_TRACES[-10:]
    except Exception:
        pass

    return cls._instance


def _vortex_state_singleton_meta_v188c_fix(self):
    return {
        "singleton_id": getattr(self, "_authority_instance_id", f"StateManagerSingleton:{id(self)}"),
        "created_ts": float(getattr(self, "_authority_created_ts", 0.0) or 0.0),
        "reuse_count": _VORTEX_STATE_REUSE_COUNT,
        "current_object_id": id(self),
        "recent_reuse_traces_count": len(_VORTEX_STATE_REUSE_TRACES),
    }


async def _vortex_get_dashboard_state_v188c_fix(self):
    try:
        if "_vortex_get_dashboard_state_v188b" in globals():
            res = await _vortex_get_dashboard_state_v188b(self)
        elif "_vortex_get_dashboard_state_v188" in globals():
            res = await _vortex_get_dashboard_state_v188(self)
        else:
            async with self._lock:
                self.state["system"]["sys_logs"] = list(self._sys_logs)
                res = copy.deepcopy(self.state)

        res.setdefault("meta", {})
        res["meta"]["state_singleton"] = _vortex_state_singleton_meta_v188c_fix(self)
        res["meta"]["state_authority_id"] = res["meta"]["state_singleton"].get("singleton_id", "")
        return res
    except Exception:
        async with self._lock:
            self.state.setdefault("meta", {})
            self.state["meta"]["state_singleton"] = _vortex_state_singleton_meta_v188c_fix(self)
            self.state["meta"]["state_authority_id"] = self.state["meta"]["state_singleton"].get("singleton_id", "")
            self.state["system"]["sys_logs"] = list(self._sys_logs)
            return copy.deepcopy(self.state)


async def _vortex_get_runtime_snapshot_v188c_fix(self):
    res = await self.get_dashboard_state()
    try:
        uptime_sec = int(time.time() - self._started_ts)
        res.setdefault("system", {})
        res["system"]["uptime"] = time.strftime('%H:%M:%S', time.gmtime(uptime_sec))
    except Exception:
        pass
    return res


def _vortex_get_state_singleton_debug_v188c_fix(self):
    return {
        "meta": _vortex_state_singleton_meta_v188c_fix(self),
        "recent_reuse_traces": list(_VORTEX_STATE_REUSE_TRACES),
    }


try:
    StateManager.__new__ = staticmethod(_vortex_state_new_v188c_fix)
    StateManager.get_dashboard_state = _vortex_get_dashboard_state_v188c_fix
    StateManager.get_runtime_snapshot = _vortex_get_runtime_snapshot_v188c_fix
    StateManager.get_state_singleton_debug = _vortex_get_state_singleton_debug_v188c_fix
except Exception:
    pass
# --- END VORTEX v1.8.8c_fix SINGLETON STATE AUTHORITY LOCK ---

