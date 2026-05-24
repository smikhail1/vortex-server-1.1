import sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tempfile
from pathlib import Path

from entry_safety_policy import evaluate_entry_safety, parse_ea


def write_trades(path: Path, text: str):
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_parse_ea():
    ea = parse_ea("ADX ok | EA:B/74 ALLOW_SHADOW")
    assert ea["present"] is True
    assert ea["grade"] == "B"
    assert ea["score"] == 74
    assert ea["label"] == "ALLOW_SHADOW"


def test_blocks_no_ea():
    with tempfile.TemporaryDirectory() as td:
        trades = Path(td) / "trades.csv"
        write_trades(trades, "")
        d = evaluate_entry_safety(
            kwargs={
                "symbol": "TESTUSDT",
                "side": "LONG",
                "setup_type": "momentum_long",
                "args_text": "momentum score=10 confirmed",
            },
            trades_path=str(trades),
            now_ts=1779600000,
        )
        assert d["allow"] is False
        assert d["code"] == "BLOCK_NO_EA"


def test_blocks_ea_c_and_d():
    with tempfile.TemporaryDirectory() as td:
        trades = Path(td) / "trades.csv"
        write_trades(trades, "")

        for text, code in [
            ("EA:C/73 SHADOW_ONLY", "BLOCK_EA_C"),
            ("EA:D/29 BLOCK_SHADOW", "BLOCK_EA_D"),
        ]:
            d = evaluate_entry_safety(
                kwargs={
                    "symbol": "TESTUSDT",
                    "side": "LONG",
                    "setup_type": "momentum_long",
                    "args_text": text,
                },
                trades_path=str(trades),
                now_ts=1779600000,
            )
            assert d["allow"] is False
            assert d["code"] == code


def test_blocks_low_b_score():
    with tempfile.TemporaryDirectory() as td:
        trades = Path(td) / "trades.csv"
        write_trades(trades, "")
        d = evaluate_entry_safety(
            kwargs={
                "symbol": "TESTUSDT",
                "side": "LONG",
                "setup_type": "momentum_long",
                "args_text": "EA:B/64 ALLOW_SHADOW",
            },
            trades_path=str(trades),
            now_ts=1779600000,
        )
        assert d["allow"] is False
        assert d["code"] == "BLOCK_EA_SCORE_LOW"


def test_blocks_blacklist():
    with tempfile.TemporaryDirectory() as td:
        trades = Path(td) / "trades.csv"
        write_trades(trades, "")
        d = evaluate_entry_safety(
            kwargs={
                "symbol": "HYPEUSDT",
                "side": "LONG",
                "setup_type": "momentum_long",
                "args_text": "EA:B/74 ALLOW_SHADOW",
            },
            trades_path=str(trades),
            now_ts=1779600000,
        )
        assert d["allow"] is False
        assert d["code"] == "BLOCK_SYMBOL_BLACKLIST"


def test_blocks_disabled_setup():
    with tempfile.TemporaryDirectory() as td:
        trades = Path(td) / "trades.csv"
        write_trades(trades, "")
        d = evaluate_entry_safety(
            kwargs={
                "symbol": "TESTUSDT",
                "side": "SHORT",
                "setup_type": "trend_short_v1.8.1",
                "args_text": "EA:B/74 ALLOW_SHADOW",
            },
            trades_path=str(trades),
            now_ts=1779600000,
        )
        assert d["allow"] is False
        assert d["code"] == "BLOCK_SETUP_DISABLED"


def test_blocks_symbol_already_traded_today():
    with tempfile.TemporaryDirectory() as td:
        trades = Path(td) / "trades.csv"
        write_trades(trades, "2026-05-24 01:00:00,TESTUSDT,LONG,FUT,1,2,0,0,0,OPEN,0,momentum_long,args")
        d = evaluate_entry_safety(
            kwargs={
                "symbol": "TESTUSDT",
                "side": "LONG",
                "setup_type": "momentum_long",
                "args_text": "EA:B/74 ALLOW_SHADOW",
            },
            trades_path=str(trades),
            now_ts=1779660000,
        )
        assert d["allow"] is False
        assert d["code"] == "BLOCK_SYMBOL_ALREADY_TRADED_TODAY"


def test_allows_strong_b_clean_symbol():
    with tempfile.TemporaryDirectory() as td:
        trades = Path(td) / "trades.csv"
        write_trades(trades, "")
        d = evaluate_entry_safety(
            kwargs={
                "symbol": "TESTUSDT",
                "side": "LONG",
                "setup_type": "momentum_long",
                "args_text": "momentum ok | EA:B/74 ALLOW_SHADOW",
            },
            trades_path=str(trades),
            now_ts=1779600000,
        )
        assert d["allow"] is True
        assert d["code"] == "ALLOW_ENTRY_SAFETY"


if __name__ == "__main__":
    test_parse_ea()
    test_blocks_no_ea()
    test_blocks_ea_c_and_d()
    test_blocks_low_b_score()
    test_blocks_blacklist()
    test_blocks_disabled_setup()
    test_blocks_symbol_already_traded_today()
    test_allows_strong_b_clean_symbol()
    print("OK: smoke_entry_safety_policy")
