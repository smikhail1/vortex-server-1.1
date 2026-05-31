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
        daily_loss_limit_usdt: float = CONFIG.risk.daily_loss_limit_usdt,
        max_open_futures_positions: int = CONFIG.risk.max_open_futures_positions,
        max_open_spot_positions: int = CONFIG.risk.max_open_spot_positions,
        loss_streak_limit: int = CONFIG.risk.loss_streak_limit,
        loss_streak_cooldown_sec: int = CONFIG.risk.loss_streak_cooldown_sec,
        persistence_enabled: bool = CONFIG.risk.persistence_enabled,
        persistence_path: str = CONFIG.risk.persistence_path,
    ) -> None:
        self.futures_symbol_cooldown_sec = max(0, int(futures_symbol_cooldown_sec))
        self.spot_symbol_cooldown_sec = max(0, int(spot_symbol_cooldown_sec))
        self.max_trades_per_symbol_per_day = max(0, int(max_trades_per_symbol_per_day))
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

    def _norm_key(self, symbol: str, market_type: str) -> Tuple[str, str]:
        sym = safe_str(symbol).upper()
        mkt = safe_str(market_type).lower()
        if mkt in {"futures", "future"}:
            mkt = "fut"
        return sym, mkt

    def _trade_day_key(self, symbol: str, market_type: str) -> Tuple[str, str, str]:
        sym, mkt = self._norm_key(symbol, market_type)
        return self._day_key(), sym, mkt

    def _cooldown_sec(self, market_type: str) -> int:
        mkt = safe_str(market_type).lower()
        if mkt in {"fut", "future", "futures"}:
            return self.futures_symbol_cooldown_sec
        if mkt == "spot":
            return self.spot_symbol_cooldown_sec
        return 0

    def _remaining_cooldown(self, key: Tuple[str, str], now: float) -> int:
        sym, mkt = key
        cooldown = self._cooldown_sec(mkt)
        if cooldown <= 0:
            return 0

        last_open = float(self.last_open_ts.get(key, 0.0) or 0.0)
        last_close = float(self.last_close_ts.get(key, 0.0) or 0.0)
        last_event = max(last_open, last_close)
        if last_event <= 0:
            return 0

        elapsed = max(0.0, now - last_event)
        remaining = int(max(0.0, cooldown - elapsed))
        return remaining

    def _check_circuit_breaker(self):
        """Daily loss circuit breaker."""
        if self.daily_realized_pnl <= self.daily_loss_limit_usdt:
            if not self.circuit_breaker_active:
                self.circuit_breaker_active = True
                self.block_reason = f"STOP-CRANE: Daily loss {self.daily_realized_pnl:.2f}$ reached limit {self.daily_loss_limit_usdt}$"
            return True
        return False

    def can_open(self, symbol: str, market_type: str) -> tuple[bool, str]:
        self._maybe_reset_day()

        if self._check_circuit_breaker():
            return False, self.block_reason

        sym, mkt = self._norm_key(symbol, market_type)
        if not sym:
            return False, "symbol required"
        if not mkt:
            return False, "market_type required"

        if mkt in self.regime_blocks:
            return False, self.regime_blocks[mkt]

        now = time.time()
        key = (sym, mkt)

        day_key = self._trade_day_key(sym, mkt)
        trades_today = int(self.trades_per_day.get(day_key, 0) or 0)
        if self.max_trades_per_symbol_per_day > 0 and trades_today >= self.max_trades_per_symbol_per_day:
            return False, f"daily symbol trade limit: {sym} {mkt} {trades_today}/{self.max_trades_per_symbol_per_day}"

        remaining = self._remaining_cooldown(key, now)
        if remaining > 0:
            return False, f"symbol cooldown: {sym} {mkt} {remaining}s remaining"

        streak_count = int(self.consecutive_losses.get(key, 0))
        if streak_count >= self.loss_streak_limit:
            elapsed = now - float(self.last_loss_ts.get(key, 0.0) or 0.0)
            if elapsed < self.loss_streak_cooldown_sec:
                remaining_loss = int(max(0.0, self.loss_streak_cooldown_sec - elapsed))
                return False, f"loss streak cooldown: {sym} {mkt} {remaining_loss}s remaining"

        return True, "ok"

    def register_open(self, symbol: str, market_type: str) -> None:
        self._maybe_reset_day()
        sym, mkt = self._norm_key(symbol, market_type)
        if not sym or not mkt:
            return
        key = (sym, mkt)
        day_key = self._trade_day_key(sym, mkt)
        self.last_open_ts[key] = time.time()
        self.trades_per_day[day_key] += 1
        self._save_state()

    # VORTEX v1.8.24-f0 spot pnl accounting fix
    def register_realized_pnl(self, pnl: float = 0.0, reason: str = "PARTIAL") -> None:
        """Account a partial realized leg without marking the symbol closed."""
        self._maybe_reset_day()
        self.daily_realized_pnl += safe_float(pnl)
        self._check_circuit_breaker()
        self._save_state()

    def register_close(self, symbol: str, market_type: str, pnl: float = 0.0, reason: str = "CLOSE") -> None:
        self._maybe_reset_day()
        value = safe_float(pnl)
        self.daily_realized_pnl += value

        sym, mkt = self._norm_key(symbol, market_type)
        if not sym or not mkt:
            self._check_circuit_breaker()
            self._save_state()
            return

        key = (sym, mkt)
        now = time.time()
        self.last_close_ts[key] = now

        if value < 0:
            self.consecutive_losses[key] += 1
            self.last_loss_ts[key] = now
        else:
            self.consecutive_losses[key] = 0
            if key in self.last_loss_ts:
                del self.last_loss_ts[key]

        self._check_circuit_breaker()
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
        today = self._day_key()
        trades_today = {
            f"{sym}:{mkt}": count
            for (day, sym, mkt), count in self.trades_per_day.items()
            if day == today
        }
        now = time.time()
        cooldowns = {}
        for key in set(list(self.last_open_ts.keys()) + list(self.last_close_ts.keys())):
            remaining = self._remaining_cooldown(key, now)
            if remaining > 0:
                sym, mkt = key
                cooldowns[f"{sym}:{mkt}"] = remaining

        return {
            "block_new_entries": self.daily_realized_pnl <= self.daily_loss_limit_usdt or self.circuit_breaker_active,
            "block_reason": self.block_reason,
            "daily_realized_pnl": round(self.daily_realized_pnl, 4),
            "daily_loss_limit_usdt": self.daily_loss_limit_usdt,
            "day": self.last_reset_day,
            "max_open_futures_positions": self.max_open_futures_positions,
            "max_open_spot_positions": self.max_open_spot_positions,
            "futures_symbol_cooldown_sec": self.futures_symbol_cooldown_sec,
            "spot_symbol_cooldown_sec": self.spot_symbol_cooldown_sec,
            "max_trades_per_symbol_per_day": self.max_trades_per_symbol_per_day,
            "trades_per_day": trades_today,
            "active_symbol_cooldowns": cooldowns,
            "loss_streaks": {f"{sym}:{mkt}": int(v) for (sym, mkt), v in self.consecutive_losses.items() if int(v) > 0},
        }

    def _tuple_key_to_str(self, key) -> str:
        return "|".join(str(x) for x in key)

    def _str_to_2tuple(self, value: str) -> Tuple[str, str]:
        parts = str(value).split("|")
        if len(parts) >= 2:
            return safe_str(parts[0]).upper(), safe_str(parts[1]).lower()
        return safe_str(value).upper(), ""

    def _str_to_3tuple(self, value: str) -> Tuple[str, str, str]:
        parts = str(value).split("|")
        if len(parts) >= 3:
            return safe_str(parts[0]), safe_str(parts[1]).upper(), safe_str(parts[2]).lower()
        return self._day_key(), safe_str(value).upper(), ""

    def _serialize_state(self) -> Dict:
        return {
            "schema": "vortex.risk_manager_state.v1",
            "schema_version": "1.8.21b",
            "daily_realized_pnl": self.daily_realized_pnl,
            "last_reset_day": self.last_reset_day,
            "circuit_breaker_active": self.circuit_breaker_active,
            "block_reason": self.block_reason,
            "last_open_ts": {self._tuple_key_to_str(k): v for k, v in self.last_open_ts.items()},
            "last_close_ts": {self._tuple_key_to_str(k): v for k, v in self.last_close_ts.items()},
            "trades_per_day": {self._tuple_key_to_str(k): v for k, v in self.trades_per_day.items()},
            "last_loss_ts": {self._tuple_key_to_str(k): v for k, v in self.last_loss_ts.items()},
            "consecutive_losses": {self._tuple_key_to_str(k): v for k, v in self.consecutive_losses.items()},
        }

    def _save_state(self) -> None:
        if self._store:
            self._store.save(self._serialize_state())

    def _load_state(self) -> None:
        if not self._store:
            return
        d = self._store.load()
        if not isinstance(d, dict):
            return

        saved_day = safe_str(d.get("last_reset_day"))
        today = self._day_key()
        self.last_reset_day = saved_day or today

        if saved_day == today:
            self.daily_realized_pnl = safe_float(d.get("daily_realized_pnl"))
            self.circuit_breaker_active = bool(d.get("circuit_breaker_active", False))
            self.block_reason = safe_str(d.get("block_reason"), "")

        for raw_key, value in (d.get("last_open_ts") or {}).items():
            self.last_open_ts[self._str_to_2tuple(raw_key)] = safe_float(value)
        for raw_key, value in (d.get("last_close_ts") or {}).items():
            self.last_close_ts[self._str_to_2tuple(raw_key)] = safe_float(value)
        for raw_key, value in (d.get("last_loss_ts") or {}).items():
            self.last_loss_ts[self._str_to_2tuple(raw_key)] = safe_float(value)
        for raw_key, value in (d.get("consecutive_losses") or {}).items():
            self.consecutive_losses[self._str_to_2tuple(raw_key)] = int(safe_float(value))
        for raw_key, value in (d.get("trades_per_day") or {}).items():
            key = self._str_to_3tuple(raw_key)
            if key[0] == today:
                self.trades_per_day[key] = int(safe_float(value))

        self._maybe_reset_day()

    def reset(self):
        self.daily_realized_pnl = 0.0
        self.circuit_breaker_active = False
        self.block_reason = ""
        self.trades_per_day.clear()
        self._save_state()


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
