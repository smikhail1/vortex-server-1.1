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
