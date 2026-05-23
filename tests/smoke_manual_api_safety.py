from __future__ import annotations

from pathlib import Path


def main():
    text = Path("api_server.py").read_text(encoding="utf-8")
    expected = [
        'if self.mode != "PAPER" or not CONFIG.trading.allow_manual_trades or self.router is None:',
        'if self.mode != "PAPER" or not CONFIG.trading.allow_force_close or self.router is None:',
    ]
    for item in expected:
        if item not in text:
            raise AssertionError(f"missing PAPER-only guard: {item}")

    router_text = Path("execution_router.py").read_text(encoding="utf-8")
    for name in [
        "manual_open_futures",
        "manual_open_spot",
        "manual_close_all_spot",
        "_vortex_close_futures_position_v1821a",
        "_vortex_close_spot_position_v1821a",
    ]:
        if name not in router_text:
            raise AssertionError(f"missing router contract symbol: {name}")

    if "Ready for REAL execution" in router_text:
        raise AssertionError("unsafe REAL execution ready message is still present")

    print("OK: smoke_manual_api_safety")


if __name__ == "__main__":
    main()
