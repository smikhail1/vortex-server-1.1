import time
from collections import defaultdict
from typing import Dict, Optional, Tuple

from config import CONFIG
from risk_state_store import RiskStateStore
from validators import safe_float, safe_str


class RiskManager:
    def __init__(
        self,
        futures_symbol_cooldown_sec: int = CONFIG.risk.futures_symbol_cooldown_sec,
        spot_symbol_cooldown_sec: int = CONFIG.risk.spot_symbol_cooldown_sec,
        max_trades_per_symbol_per_day: int = CONFIG.risk.max_trades_per_symbol_per_day,
        daily_loss_limit_usdt: float = -10.0, 
        max_open_futures_positions: int = CONFIG.risk.max_open_futures_positions,
        max_open_spot_positions: int = CONFIG.risk.max_open_spot_positions,
        loss_streak_limit: int = CONFIG.risk.loss_streak_limit,
        loss_streak_cooldown_sec: int = CONFIG.risk.loss_streak_cooldown_sec,
        persistence_enabled: bool = CONFIG.risk.persistence_enabled,
        persistence_path: str = CONFIG.risk.persistence_path,
    ) -> None:
        self.futures_symbol_cooldown_sec = int(futures_symbol_cooldown_sec)
        self.spot_symbol_cooldown_sec = int(spot_symbol_cooldown_sec)
        self.max_trades_per_symbol_per_day = int(max_trades_per_symbol_per_day)
        self.daily_loss_limit_usdt = float(daily_loss_limit_usdt)
        self.max_open_futures_positions = int(max_open_futures_positions)
        self.max_open_spot_positions = int(max_open_spot_positions)
        self.loss_streak_limit = max(1, int(loss_streak_limit))
        self.loss_streak_cooldown_sec = max(0, int(loss_streak_cooldown_sec))
        self.persistence_enabled = bool(persistence_enabled)

        self.last_open_ts: Dict[Tuple[str, str], float] = {}
        self.last_close_ts: Dict[Tuple[str, str], float] = {}
        self.trades_per_day: Dict[Tuple[str, str, str], int] = defaultdict(int)
        self.daily_realized_pnl: float = 0.0
        self.last_reset_day: str = self._day_key()
        self.circuit_breaker_active = False 
        self.block_reason = ""

        self.regime_blocks: Dict[str, str] = {}
        self.last_loss_ts: Dict[Tuple[str, str], float] = {}
        self.consecutive_losses: Dict[Tuple[str, str], int] = defaultdict(int)

        self._store: Optional[RiskStateStore] = RiskStateStore(persistence_path) if self.persistence_enabled else None
        self._load_state()

    def _day_key(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def _check_circuit_breaker(self):
        """Механизм анализа и остановки при потерях"""
        if self.daily_realized_pnl <= self.daily_loss_limit_usdt:
            if not self.circuit_breaker_active:
                self.circuit_breaker_active = True
                self.block_reason = f"🚨 STOP-CRANE: Daily loss {self.daily_realized_pnl:.2f}$ reached limit {self.daily_loss_limit_usdt}$"
            return True
        return False

    def can_open(self, symbol: str, market_type: str) -> tuple[bool, str]:
        self._maybe_reset_day()
        if self._check_circuit_breaker():
            return False, self.block_reason
        
        sym = safe_str(symbol).upper()
        mkt = safe_str(market_type).lower()
        if mkt in self.regime_blocks: return False, self.regime_blocks[mkt]
        
        now = time.time()
        key = (sym, mkt)
        streak_count = int(self.consecutive_losses.get(key, 0))
        if streak_count >= self.loss_streak_limit:
            elapsed = now - self.last_loss_ts.get(key, 0.0)
            if elapsed < self.loss_streak_cooldown_sec:
                return False, f"loss streak cooldown"

        return True, "ok"

    def register_close(self, symbol: str, market_type: str, pnl: float = 0.0, reason: str = "CLOSE") -> None:
        self._maybe_reset_day()
        value = safe_float(pnl)
        self.daily_realized_pnl += value
        
        if value < 0:
            self._check_circuit_breaker()
            
        sym = safe_str(symbol).upper()
        mkt = safe_str(market_type).lower()
        key = (sym, mkt)
        now = time.time()
        
        if value < 0:
            self.consecutive_losses[key] += 1
            self.last_loss_ts[key] = now
            self.last_close_ts[key] = now
        else:
            self.consecutive_losses[key] = 0
            if key in self.last_close_ts: del self.last_close_ts[key]
        
        self._save_state()

    def _maybe_reset_day(self) -> None:
        today = self._day_key()
        if today != self.last_reset_day:
            self.daily_realized_pnl = 0.0
            self.circuit_breaker_active = False
            self.block_reason = ""
            self.trades_per_day.clear()
            self.last_reset_day = today
            self._save_state()

    def get_status(self) -> Dict[str, object]:
        self._maybe_reset_day()
        return {
            "block_new_entries": self.daily_realized_pnl <= self.daily_loss_limit_usdt or self.circuit_breaker_active,
            "block_reason": self.block_reason,
            "daily_realized_pnl": round(self.daily_realized_pnl, 4),
            "daily_loss_limit_usdt": self.daily_loss_limit_usdt,
            "day": self.last_reset_day,
            "max_open_futures_positions": self.max_open_futures_positions,
            "max_open_spot_positions": self.max_open_spot_positions,
        }

    def _serialize_state(self) -> Dict: return {"daily_realized_pnl": self.daily_realized_pnl, "last_reset_day": self.last_reset_day}
    def _save_state(self) -> None: 
        if self._store: self._store.save(self._serialize_state())
    def _load_state(self) -> None:
        if self._store:
            d = self._store.load()
            if d and d.get("last_reset_day") == self._day_key():
                self.daily_realized_pnl = safe_float(d.get("daily_realized_pnl"))
    def register_open(self, s, m): self.last_open_ts[(s.upper(), m.lower())] = time.time()
    def reset(self): self.daily_realized_pnl = 0.0; self.circuit_breaker_active = False


# --- VORTEX v1.8.1 RISK STATUS COMPAT ---
try:
    _vortex_original_risk_get_status = RiskManager.get_status

    def _vortex_risk_get_status_v181(self):
        data = _vortex_original_risk_get_status(self)
        if not isinstance(data, dict):
            data = {}

        try:
            from config import CONFIG
            default_fut = getattr(CONFIG.risk, "max_open_futures_positions", 1)
            default_spot = getattr(CONFIG.risk, "max_open_spot_positions", 5)
        except Exception:
            default_fut = 1
            default_spot = 5

        data.setdefault("max_open_futures_positions", getattr(self, "max_open_futures_positions", default_fut))
        data.setdefault("max_open_spot_positions", getattr(self, "max_open_spot_positions", default_spot))
        data.setdefault("block_reason", getattr(self, "block_reason", ""))
        return data

    RiskManager.get_status = _vortex_risk_get_status_v181
except Exception:
    pass
# --- END VORTEX v1.8.1 RISK STATUS COMPAT ---
