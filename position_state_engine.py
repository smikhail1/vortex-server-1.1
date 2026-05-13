import time
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from config import CONFIG
from validators import normalize_symbol, safe_bool, safe_float, safe_str

@dataclass
class PositionEvent:
    ts: float
    event: str
    message: str = ""
    price: float = 0.0
    pnl: float = 0.0
    pnl_net: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PositionState:
    trade_id: str
    symbol: str
    market: str
    side: str
    state: str
    entry: float
    current_price: float
    qty: float
    tp: float
    tp2: float
    sl: float
    trail_sl: float
    pnl: float
    pnl_net: float
    max_pnl_net: float
    max_drawdown_net: float
    open_time: float
    updated_at: float
    hold_sec: int
    setup_type: str = ""
    args_text: str = ""
    tp1_hit: bool = False
    breakeven: bool = False
    trail_active: bool = False
    close_reason: str = ""
    closed_at: float = 0.0
    events: List[PositionEvent] = field(default_factory=list)

class PositionStateEngine:
    def __init__(self, logger=None) -> None:
        self.logger = logger
        self.enabled = bool(CONFIG.position_state.enabled)
        self.max_events = int(CONFIG.position_state.max_events_per_position)
        self.max_closed = int(CONFIG.position_state.max_closed_positions)
        self._storage_file = 'trades_state.json'
        self._tmp_file = 'trades_state.json.tmp'
        self._open: Dict[str, PositionState] = {}
        self._closed: List[PositionState] = []
        self._load_from_disk()

    def _save_to_disk(self):
        try:
            data = {
                "open": {k: asdict(v) for k, v in self._open.items()},
                "closed": [asdict(v) for v in self._closed[-self.max_closed:]]
            }
            # Атомарная запись для предотвращения повреждения JSON при краше
            with open(self._tmp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(self._tmp_file, self._storage_file)
        except Exception as e:
            if self.logger: self.logger.error("STATE_ENGINE", "Save failed", {"err": str(e)})

    def _load_from_disk(self):
        if not os.path.exists(self._storage_file): return
        try:
            with open(self._storage_file, 'r') as f:
                data = json.load(f)
            for k, v in data.get("open", {}).items():
                events_raw = v.pop('events', [])
                events = [PositionEvent(**ev) for ev in events_raw]
                self._open[k] = PositionState(**v, events=events)
            if self.logger: self.logger.info("STATE_ENGINE", "State restored from disk", {"open": len(self._open)})
        except Exception as e:
            if self.logger: self.logger.error("STATE_ENGINE", "Load failed (JSON corrupted?)", {"err": str(e)})

    def _make_trade_id(self, symbol, market, side, open_time):
        return f"{normalize_symbol(symbol)}-{safe_str(market).upper()}-{safe_str(side).upper()}-{int(open_time)}"

    def _key(self, symbol, market):
        return f"{normalize_symbol(symbol)}::{safe_str(market).upper()}"

    def _event(self, state, event, message="", price=0.0, pnl=0.0, pnl_net=0.0, extra=None):
        ev = PositionEvent(ts=time.time(), event=safe_str(event).upper(), message=safe_str(message), price=safe_float(price), pnl=safe_float(pnl), pnl_net=safe_float(pnl_net), extra=extra or {})
        state.events.append(ev)
        if len(state.events) > self.max_events: state.events = state.events[-self.max_events:]
        if self.logger: self.logger.info("TRADES", f"{state.symbol} {ev.event}: {ev.message} | Price: {ev.price} | PnL: {ev.pnl_net}", {"symbol": state.symbol, "event": ev.event})

    def open_from_position(self, pos, market):
        if not self.enabled or pos is None: return None
        symbol = normalize_symbol(getattr(pos, "symbol", ""))
        market_u = safe_str(market).upper()
        key = self._key(symbol, market_u)
        if key in self._open: return self.to_public(self._open[key])
        
        side = safe_str(getattr(pos, "side", "BUY")).upper()
        open_time = safe_float(getattr(pos, "open_time", time.time()), time.time())
        state = PositionState(
            trade_id=self._make_trade_id(symbol, market_u, side, open_time),
            symbol=symbol, market=market_u, side=side, state="OPENED",
            entry=safe_float(getattr(pos, "entry", 0.0)), current_price=safe_float(getattr(pos, "mark_price", 0.0)),
            qty=safe_float(getattr(pos, "qty", 0.0)), tp=safe_float(getattr(pos, "tp", 0.0)), tp2=safe_float(getattr(pos, "tp2", 0.0)),
            sl=safe_float(getattr(pos, "sl", 0.0)), trail_sl=safe_float(getattr(pos, "sl", 0.0)),
            pnl=0.0, pnl_net=0.0, max_pnl_net=0.0, max_drawdown_net=0.0,
            open_time=open_time, updated_at=time.time(), hold_sec=0
        )
        self._open[key] = state
        self._event(state, "OPENED", "position opened", price=state.entry)
        self._save_to_disk()
        return self.to_public(state)

    def update_from_position(self, pos, market, current_price=None):
        if not self.enabled or pos is None: return None
        key = self._key(getattr(pos, "symbol", ""), market)
        if key not in self._open: return self.open_from_position(pos, market)
        state = self._open[key]
        state.current_price = safe_float(current_price or getattr(pos, "mark_price", state.current_price))
        state.pnl_net = safe_float(getattr(pos, "pnl_net", state.pnl_net))
        state.max_pnl_net = max(state.max_pnl_net, state.pnl_net)
        state.hold_sec = int(time.time() - state.open_time)
        state.updated_at = time.time()
        self._save_to_disk()
        return self.to_public(state)

    def close(self, symbol, market, data):
        key = self._key(symbol, market)
        state = self._open.pop(key, None)
        if not state: return None
        state.state = "CLOSED"
        state.closed_at = time.time()
        state.close_reason = safe_str(data.get("reason", "UNKNOWN"))
        self._closed.append(state)
        self._save_to_disk()
        return self.to_public(state)

    def to_public(self, state: PositionState, include_events: bool = True) -> Dict[str, Any]:
        d = asdict(state)
        if not include_events: d["events"] = []
        return d

    def snapshot(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "open": [self.to_public(x) for x in self._open.values()], "closed_recent": [self.to_public(x, False) for x in self._closed[-20:]]}