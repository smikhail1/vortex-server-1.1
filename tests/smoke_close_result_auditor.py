from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from close_result_auditor import normalize_close_result, record_close_result, read_close_audit


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    tmp = Path("/tmp/vortex_close_result_audit_smoke.jsonl")
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass

    data = {
        "symbol": "BTCUSDT",
        "side": "LONG",
        "reason": "WEAK_PROGRESS_STALE",
        "entry": 100.0,
        "exit_price": 99.5,
        "pnl": -0.04,
        "pnl_net": -0.06,
        "hold_sec": 1900,
        "closed": True,
        "setup_type": "smoke",
        "args_text": "EA:D/10 BLOCK_SHADOW",
    }
    fallback = {"symbol": "BTCUSDT", "side": "LONG", "entry": 100.0}
    result = {"code": "00000", "data": data}

    rec = normalize_close_result(data=data, fallback_pos=fallback, market="FUT", source="smoke", result=result)
    assert_true(rec["schema_version"] == "1.8.21c", "schema version mismatch")
    assert_true(rec["symbol"] == "BTCUSDT", "symbol mismatch")
    assert_true(rec["market"] == "FUT", "market mismatch")
    assert_true(rec["reason"] == "WEAK_PROGRESS_STALE", "reason mismatch")
    assert_true(rec["was_close_result"] is True, "close result not detected")

    record_close_result(data=data, fallback_pos=fallback, market="FUT", source="smoke", result=result, audit_path=str(tmp), trade_logger_attempted=True)
    rows = read_close_audit(path=str(tmp), limit=10)
    assert_true(len(rows) == 1, f"expected 1 audit row, got {len(rows)}")
    assert_true(rows[0]["trade_logger_attempted"] is True, "extra flag not persisted")

    raw = json.loads(tmp.read_text(encoding="utf-8").splitlines()[0])
    assert_true(raw["schema"] == "vortex.close_result_audit.v1", "raw schema mismatch")

    print("OK: smoke_close_result_auditor")


if __name__ == "__main__":
    main()
