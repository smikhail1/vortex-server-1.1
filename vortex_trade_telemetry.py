
"""Structured trade telemetry helpers for Android logs."""
from __future__ import annotations
from typing import Any, Dict


def compact_trade_extra(symbol: str, side: str = "", event: str = "", price: float = 0.0,
                        analysis: Dict[str, Any] | None = None,
                        exchange_ctx: Dict[str, Any] | None = None,
                        risk: Dict[str, Any] | None = None,
                        pnl: Dict[str, Any] | None = None) -> Dict[str, Any]:
    a = analysis or {}
    x = exchange_ctx or {}
    r = risk or {}
    p = pnl or {}
    return {
        "event": event,
        "symbol": symbol,
        "side": side,
        "price": price,
        "setup_type": a.get("setup_type"),
        "score": a.get("score"),
        "args_text": a.get("args_text"),
        "trigger_price": a.get("trigger_price"),
        "invalidation_price": a.get("invalidation_price"),
        "oi_signal": x.get("oi_signal"),
        "oi_change_pct": x.get("oi_change_pct"),
        "funding_signal": x.get("funding_signal"),
        "funding_pct": x.get("funding_pct"),
        "current_positions": r.get("current_positions"),
        "max_positions": r.get("max_positions"),
        "pnl_net": p.get("pnl_net"),
        "max_pnl_net": p.get("max_pnl_net"),
        "close_reason": p.get("reason"),
    }


async def emit_state_log(state: Any, title: str, message: str, extra: Dict[str, Any]) -> None:
    try:
        await state.add_sys_log(title, message, extra=extra)
    except TypeError:
        try:
            await state.add_sys_log(title, f"{message} | {extra}")
        except Exception:
            pass
    except Exception:
        pass
