import csv
import json
import os
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import CONFIG
from validators import safe_float, safe_str


class Logger:
    """
    Два канала логирования:
    1. trades.csv   — история сделок
    2. vortex.log   — runtime/system/debug/errors

    VORTEX 1.5:
    - trades.csv пишет единый расширенный контракт;
    - OPEN события тоже пишутся, но /api/stats считает только закрытые сделки.
    """

    def __init__(
        self,
        trades_filepath: str = CONFIG.logging.trades_csv_path,
        runtime_filepath: str = CONFIG.logging.runtime_log_path,
        print_to_stdout: bool = CONFIG.logging.print_to_stdout,
    ) -> None:
        self.trades_filepath = trades_filepath
        self.runtime_filepath = runtime_filepath
        self.print_to_stdout = bool(print_to_stdout)
        self._lock = threading.Lock()

        self.trade_fieldnames = [
            "ts",
            "symbol",
            "side",
            "market",
            "entry",
            "tp",
            "exit",
            "pnl",
            "pnl_net",
            "reason",
            "hold_sec",
            "setup_type",
            "args_text",
        ]

        self._ensure_trade_file()
        self._ensure_runtime_file()

    def _ensure_trade_file(self) -> None:
        if not os.path.exists(self.trades_filepath):
            with open(self.trades_filepath, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.trade_fieldnames)
                writer.writeheader()

    def _ensure_runtime_file(self) -> None:
        if not os.path.exists(self.runtime_filepath):
            with open(self.runtime_filepath, mode="w", encoding="utf-8") as f:
                f.write("")

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def _write_runtime_line(self, line: str) -> None:
        with self._lock:
            with open(self.runtime_filepath, mode="a", encoding="utf-8") as f:
                f.write(line + "\n")

        if self.print_to_stdout:
            print(line, flush=True)

    def log_event(
        self,
        category: str,
        status: str,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "ts": self._now_iso(),
            "category": safe_str(category).upper(),
            "status": safe_str(status).upper(),
            "message": safe_str(message),
            "extra": extra or {},
        }
        self._write_runtime_line(json.dumps(payload, ensure_ascii=False))

    def info(self, category: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        self.log_event(category=category, status="INFO", message=message, extra=extra)

    def warning(self, category: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        self.log_event(category=category, status="WARNING", message=message, extra=extra)

    def error(self, category: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        self.log_event(category=category, status="ERROR", message=message, extra=extra)

    def debug(self, category: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        self.log_event(category=category, status="DEBUG", message=message, extra=extra)

    def log_error(self, module: str, exc: Exception, extra: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "exception_type": exc.__class__.__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
        }
        if extra:
            payload.update(extra)
        self.log_event(category=module, status="ERROR", message=str(exc), extra=payload)

    def log_trade(
        self,
        symbol: str,
        side: str,
        market: str,
        entry: Any = None,
        tp: Any = None,
        exit_price: Any = None,
        pnl: Any = None,
        pnl_net: Any = None,
        reason: str = "UNKNOWN",
        hold_sec: Any = 0,
        setup_type: str = "",
        args_text: str = "",
        **legacy_kwargs: Any,
    ) -> None:
        """
        Единый writer для trades.csv.

        Поддерживает новую сигнатуру и частично старые имена:
        trade_type -> market
        entry_price -> entry
        target_tp -> tp
        status -> reason
        """
        if "trade_type" in legacy_kwargs and not market:
            market = legacy_kwargs.get("trade_type")
        if entry is None and "entry_price" in legacy_kwargs:
            entry = legacy_kwargs.get("entry_price")
        if tp is None and "target_tp" in legacy_kwargs:
            tp = legacy_kwargs.get("target_tp")
        if reason == "UNKNOWN" and "status" in legacy_kwargs:
            reason = legacy_kwargs.get("status")

        row = {
            "ts": self._now_iso(),
            "symbol": safe_str(symbol).upper(),
            "side": safe_str(side).upper(),
            "market": safe_str(market).upper(),
            "entry": safe_float(entry, 0.0),
            "tp": safe_float(tp, 0.0),
            "exit": safe_float(exit_price, 0.0),
            "pnl": safe_float(pnl, 0.0),
            "pnl_net": safe_float(pnl_net, 0.0),
            "reason": safe_str(reason).upper(),
            "hold_sec": int(safe_float(hold_sec, 0.0)),
            "setup_type": safe_str(setup_type),
            "args_text": safe_str(args_text),
        }

        with self._lock:
            file_exists = os.path.exists(self.trades_filepath)
            with open(self.trades_filepath, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.trade_fieldnames)
                if (not file_exists) or os.path.getsize(self.trades_filepath) == 0:
                    writer.writeheader()
                writer.writerow(row)

        self.log_event(
            category="TRADE",
            status=row["reason"],
            message=f'{row["market"]} {row["symbol"]} {row["side"]}',
            extra=row,
        )

    def tail_runtime(self, lines: int = 100) -> str:
        if lines <= 0:
            return ""

        if not os.path.exists(self.runtime_filepath):
            return ""

        with open(self.runtime_filepath, mode="r", encoding="utf-8") as f:
            all_lines = f.readlines()

        return "".join(all_lines[-lines:])

    def clear_runtime_log(self) -> None:
        with self._lock:
            with open(self.runtime_filepath, mode="w", encoding="utf-8") as f:
                f.write("")

    def clear_trades_csv(self) -> None:
        with self._lock:
            with open(self.trades_filepath, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.trade_fieldnames)
                writer.writeheader()
