import time
from collections import defaultdict
from typing import Dict, Optional, Tuple

from config import CONFIG
from risk_state_store import RiskStateStore
from validators import safe_float, safe_str


class RiskManager:
    """
    Risk layer:
    - cooldown per symbol/market
    - daily symbol cap
    - daily realized loss guard
    - loss-streak cooldown
    - persistent state across restarts
    """

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

        self.regime_blocks: Dict[str, str] = {}
        self.last_loss_ts: Dict[Tuple[str, str], float] = {}
        self.consecutive_losses: Dict[Tuple[str, str], int] = defaultdict(int)

        self._store: Optional[RiskStateStore] = RiskStateStore(persistence_path) if self.persistence_enabled else None
        self._load_state()

    def _day_key(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    @staticmethod
    def _encode_key(key: Tuple[str, str]) -> str:
        return f"{key[0]}::{key[1]}"

    @staticmethod
    def _decode_key(value: str) -> Optional[Tuple[str, str]]:
        parts = safe_str(value).split("::", 1)
        if len(parts) != 2:
            return None
        return safe_str(parts[0]).upper(), safe_str(parts[1]).lower()

    def _serialize_state(self) -> Dict[str, object]:
        return {
            "last_reset_day": self.last_reset_day,
            "daily_realized_pnl": round(self.daily_realized_pnl, 10),
            "last_open_ts": {
                self._encode_key(k): round(v, 6) for k, v in self.last_open_ts.items()
            },
            "last_loss_ts": {
                self._encode_key(k): round(v, 6) for k, v in self.last_loss_ts.items()
            },
            "last_close_ts": {
                self._encode_key(k): round(v, 6) for k, v in self.last_close_ts.items()
            },
            "consecutive_losses": {
                self._encode_key(k): int(v) for k, v in self.consecutive_losses.items()
            },
        }

    def _save_state(self) -> None:
        if self._store is None:
            return
        self._store.save(self._serialize_state())

    def _load_state(self) -> None:
        if self._store is None:
            return

        data = self._store.load()
        if not data:
            return

        saved_day = safe_str(data.get("last_reset_day"), "")
        today = self._day_key()

        self.last_reset_day = today
        if saved_day == today:
            self.daily_realized_pnl = safe_float(data.get("daily_realized_pnl"), 0.0)
        else:
            self.daily_realized_pnl = 0.0

        self.last_open_ts.clear()
        for raw_key, raw_val in (data.get("last_open_ts") or {}).items():
            key = self._decode_key(raw_key)
            if key is not None:
                self.last_open_ts[key] = safe_float(raw_val, 0.0)

        self.last_loss_ts.clear()
        for raw_key, raw_val in (data.get("last_loss_ts") or {}).items():
            key = self._decode_key(raw_key)
            if key is not None:
                self.last_loss_ts[key] = safe_float(raw_val, 0.0)

        self.last_close_ts.clear()
        for raw_key, raw_val in (data.get("last_close_ts") or {}).items():
            key = self._decode_key(raw_key)
            if key is not None:
                self.last_close_ts[key] = safe_float(raw_val, 0.0)

        self.consecutive_losses.clear()
        for raw_key, raw_val in (data.get("consecutive_losses") or {}).items():
            key = self._decode_key(raw_key)
            if key is not None:
                self.consecutive_losses[key] = max(0, int(raw_val))

    def _maybe_reset_day(self) -> None:
        today = self._day_key()
        if today != self.last_reset_day:
            self.daily_realized_pnl = 0.0
            self.trades_per_day.clear()
            self.regime_blocks.clear()
            self.last_reset_day = today
            self._save_state()

    def _cooldown_sec(self, market_type: str) -> int:
        return self.futures_symbol_cooldown_sec if market_type == "fut" else self.spot_symbol_cooldown_sec

    def set_regime_block(self, market_type: str, reason: str = "") -> None:
        mkt = safe_str(market_type).lower()
        self.regime_blocks[mkt] = reason or "regime blocked"

    def clear_regime_block(self, market_type: str) -> None:
        mkt = safe_str(market_type).lower()
        if mkt in self.regime_blocks:
            del self.regime_blocks[mkt]

    def can_open(self, symbol: str, market_type: str) -> tuple[bool, str]:
        self._maybe_reset_day()

        sym = safe_str(symbol).upper()
        mkt = safe_str(market_type).lower()

        if self.daily_realized_pnl <= self.daily_loss_limit_usdt:
            return False, "daily loss limit reached"

        if mkt in self.regime_blocks:
            return False, self.regime_blocks[mkt]

        key = (sym, mkt)
        now = time.time()

        streak_count = int(self.consecutive_losses.get(key, 0))
        if streak_count >= self.loss_streak_limit:
            elapsed = now - self.last_loss_ts.get(key, 0.0)
            if elapsed < self.loss_streak_cooldown_sec:
                left = int(self.loss_streak_cooldown_sec - elapsed)
                return False, f"loss streak cooldown ({left}s left)"

        cooldown = self._cooldown_sec(mkt)

        last_close = self.last_close_ts.get(key, 0.0)
        if last_close > 0 and now - last_close < cooldown:
            left = int(cooldown - (now - last_close))
            return False, f"cooldown after close ({left}s left)"

        last_ts = self.last_open_ts.get(key, 0.0)
        if last_ts > 0 and now - last_ts < cooldown:
            left = int(cooldown - (now - last_ts))
            return False, f"cooldown after open ({left}s left)"

        day_key = (self.last_reset_day, sym, mkt)
        if self.trades_per_day.get(day_key, 0) >= self.max_trades_per_symbol_per_day:
            return False, "symbol daily cap reached"

        return True, "ok"

    def register_open(self, symbol: str, market_type: str) -> None:
        self._maybe_reset_day()

        sym = safe_str(symbol).upper()
        mkt = safe_str(market_type).lower()
        now = time.time()

        self.last_open_ts[(sym, mkt)] = now
        self.trades_per_day[(self.last_reset_day, sym, mkt)] += 1
        self._save_state()

    def register_close(self, symbol: str, market_type: str, pnl: float = 0.0, reason: str = "CLOSE") -> None:
        self._maybe_reset_day()

        sym = safe_str(symbol).upper()
        mkt = safe_str(market_type).lower()
        value = safe_float(pnl)
        self.daily_realized_pnl += value

        key = (sym, mkt)
        now = time.time()
        reason_upper = safe_str(reason, "CLOSE").upper()

        # v1.7.2: smarter cooldown policy.
        # Only real damage events should create close-cooldown:
        # - negative pnl
        # - hard exits: SL / LIQ
        #
        # Profitable or neutral exits like TIMEOUT / TP2 / FADE / STALL / BU
        # must not block trend continuation entries.
        hard_cooldown_reasons = {"SL", "LIQ"}
        should_cooldown_after_close = value < 0 or reason_upper in hard_cooldown_reasons

        if should_cooldown_after_close:
            self.last_close_ts[key] = now
        else:
            # Clear stale close cooldown after profitable/neutral close.
            if key in self.last_close_ts:
                del self.last_close_ts[key]

        if value < 0:
            self.consecutive_losses[key] += 1
            self.last_loss_ts[key] = now
        else:
            self.consecutive_losses[key] = 0

        self._save_state()

    def get_status(self) -> Dict[str, object]:
        self._maybe_reset_day()
        now = time.time()
        streaks = {}
        for key, count in self.consecutive_losses.items():
            if count <= 0:
                continue
            elapsed = now - self.last_loss_ts.get(key, 0.0)
            cooldown_left = max(0, int(self.loss_streak_cooldown_sec - elapsed))
            streaks[self._encode_key(key)] = {
                "count": int(count),
                "cooldown_left_sec": cooldown_left,
            }

        close_cooldowns = {}
        for key, last_ts in self.last_close_ts.items():
            cooldown = self._cooldown_sec(key[1])
            left = max(0, int(cooldown - (now - last_ts)))
            if left > 0:
                close_cooldowns[self._encode_key(key)] = left

        return {
            "block_new_entries": self.daily_realized_pnl <= self.daily_loss_limit_usdt,
            "daily_realized_pnl": round(self.daily_realized_pnl, 8),
            "daily_loss_limit_usdt": round(self.daily_loss_limit_usdt, 8),
            "day": self.last_reset_day,
            "max_open_futures_positions": self.max_open_futures_positions,
            "max_open_spot_positions": self.max_open_spot_positions,
            "regime_blocks": dict(self.regime_blocks),
            "loss_streak_limit": self.loss_streak_limit,
            "loss_streak_cooldown_sec": self.loss_streak_cooldown_sec,
            "consecutive_losses": streaks,
            "close_cooldowns": close_cooldowns,
            "persistence_enabled": self.persistence_enabled,
        }

    def reset(self) -> None:
        self.last_open_ts.clear()
        self.last_close_ts.clear()
        self.trades_per_day.clear()
        self.regime_blocks.clear()
        self.last_loss_ts.clear()
        self.consecutive_losses.clear()
        self.daily_realized_pnl = 0.0
        self.last_reset_day = self._day_key()
        self._save_state()
