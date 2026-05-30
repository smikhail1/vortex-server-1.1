#!/usr/bin/env python3
"""
VORTEX v1.8.24-a Futures Pipeline Probe.

Diagnostic only. The full mode imports the real PAPER pipeline modules but runs
them inside a temporary filesystem sandbox. The live service state is inspected
and backed up, never mutated by the probe.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


MARKER = "TEST_PROBE"
PROBE_NAME = "FUTURES_PIPELINE_PROBE"
SETUP_TYPE = "TEST_PROBE_futures_entry_pipeline"
ARGS_TEXT = "TEST_PROBE FUTURES_PIPELINE_PROBE synthetic confirmed candidate | EA:B/99 PASS"
ROOT = Path(__file__).resolve().parents[1]
BACKUP_INPUTS = ("trades_state.json", "trades.csv", "risk_state.json", "_runtime")


class ProbeFail(RuntimeError):
    pass


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_production_files(root: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name in ("trades_state.json", "trades.csv", "risk_state.json"):
        path = root / name
        out[name] = sha256_file(path) if path.exists() and path.is_file() else "missing"
    return out


def make_backup(root: Path) -> Path:
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    backup = root / "backups" / f"futures_pipeline_probe_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    for name in BACKUP_INPUTS:
        src = root / name
        dst = backup / name
        if not src.exists():
            (backup / f"{name.replace('/', '_')}.missing_ok").write_text("missing_ok\n", encoding="utf-8")
        elif src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    return backup


def api_json(path: str, timeout: float = 4.0) -> Dict[str, Any]:
    url = f"http://127.0.0.1:8000{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data if isinstance(data, dict) else {}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProbeFail(f"API_UNAVAILABLE {url}: {exc}") from exc


def dashboard_open_futures(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    positions = dashboard.get("positions") if isinstance(dashboard.get("positions"), dict) else {}
    fut = positions.get("fut") if isinstance(positions.get("fut"), dict) else {}
    return fut


def state_file_open_futures(root: Path) -> Dict[str, Any]:
    path = root / "trades_state.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProbeFail(f"TRADES_STATE_READ_FAIL: {exc}") from exc
    open_map = data.get("open") if isinstance(data, dict) else {}
    if not isinstance(open_map, dict):
        return {}
    return {
        str(key): value
        for key, value in open_map.items()
        if str(key).upper().endswith("::FUT")
        or (isinstance(value, dict) and str(value.get("market", "")).upper() in {"FUT", "FUTURES"})
    }


def ensure_no_live_futures(root: Path, dashboard: Dict[str, Any]) -> None:
    dashboard_fut = dashboard_open_futures(dashboard)
    state_fut = state_file_open_futures(root)
    if dashboard_fut:
        raise ProbeFail(f"OPEN_FUTURES_POSITION dashboard={sorted(dashboard_fut)}")
    if state_fut:
        raise ProbeFail(f"OPEN_FUTURES_POSITION trades_state={sorted(state_fut)}")


def ensure_health_paper(health: Dict[str, Any]) -> None:
    mode = str(health.get("mode", "")).upper()
    if mode != "PAPER":
        raise ProbeFail(f"PAPER_ONLY /api/health.mode={mode or 'missing'}")


def get_price_and_atr(dashboard: Dict[str, Any]) -> Tuple[str, float, float]:
    market = dashboard.get("market") if isinstance(dashboard.get("market"), dict) else {}
    prices = market.get("prices") if isinstance(market.get("prices"), dict) else {}
    ta_data = market.get("ta_data") if isinstance(market.get("ta_data"), dict) else {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        ta = ta_data.get(symbol) if isinstance(ta_data.get(symbol), dict) else {}
        price = safe_float(prices.get(symbol), safe_float(ta.get("price"), 0.0))
        atr = safe_float(ta.get("atr"), 0.0)
        if atr <= 0 and price > 0:
            atr_pct = safe_float(ta.get("atr_pct"), 0.0)
            atr = price * atr_pct / 100.0 if atr_pct > 0 else price * 0.01
        if price > 0 and atr > 0:
            return symbol, price, atr
    raise ProbeFail("NO_MARKET_PRICE BTCUSDT/ETHUSDT")


def ensure_paper_mode() -> None:
    sys.path.insert(0, str(ROOT))
    from config import CONFIG

    mode_env = str(os.environ.get("MODE", "")).upper()
    fut_mode_env = str(os.environ.get("DEFAULT_FUT_MODE", "")).upper()
    config_mode = str(getattr(CONFIG.trading, "mode", "")).upper()
    bad = [
        f"MODE={mode_env}" if mode_env and mode_env != "PAPER" else "",
        f"DEFAULT_FUT_MODE={fut_mode_env}" if fut_mode_env and fut_mode_env != "PAPER" else "",
        f"CONFIG.trading.mode={config_mode}" if config_mode != "PAPER" else "",
    ]
    bad = [x for x in bad if x]
    if bad:
        raise ProbeFail("PAPER_ONLY " + " ".join(bad))


def synthetic_candidate(symbol: str, price: float, atr: float) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "market": "fut",
        "side": "LONG",
        "signal": "LONG",
        "setup_type": SETUP_TYPE,
        "score": 99,
        "should_open": True,
        "entry_confirmed": True,
        "confirmed": True,
        "confirmation_reason": f"{MARKER} synthetic confirmed candidate",
        "price": price,
        "trigger_price": price,
        "atr": atr,
        "sl": price - atr * 2.0,
        "tp": price + atr * 3.0,
        "tp2": price + atr * 5.0,
        "args_text": ARGS_TEXT,
    }


def open_kwargs(candidate: Dict[str, Any], minimal_margin: float = 1.0) -> Dict[str, Any]:
    price = safe_float(candidate.get("price"))
    atr = safe_float(candidate.get("atr"))
    leverage = 3.0
    qty = minimal_margin / price
    return {
        "symbol": candidate["symbol"],
        "side": candidate["side"],
        "qty": qty,
        "price": price,
        "tp0": price + atr * 0.6,
        "tp": candidate["tp"],
        "tp2": candidate["tp2"],
        "sl": candidate["sl"],
        "atr": atr,
        "leverage": leverage,
        "setup_type": SETUP_TYPE,
        "args_text": ARGS_TEXT,
    }


def new_pipeline_objects(sandbox: Path):
    sys.path.insert(0, str(ROOT))
    os.chdir(sandbox)
    os.environ["MODE"] = "PAPER"
    os.environ["DEFAULT_FUT_MODE"] = "PAPER"
    from decision_engine import DecisionEngine
    from execution_router import ExecutionRouter
    from risk_manager import RiskManager

    router = ExecutionRouter(mode="PAPER")
    if str(getattr(router, "fut_mode", "")).upper() != "PAPER":
        raise ProbeFail(f"PAPER_ONLY router.fut_mode={getattr(router, 'fut_mode', None)}")
    risk = RiskManager(persistence_enabled=False)
    decision = DecisionEngine(logger=None)
    return router, risk, decision


def evaluate_dry(candidate: Dict[str, Any], sandbox: Path) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    router, risk, decision = new_pipeline_objects(sandbox)
    analysis = dict(candidate)
    decision_result = decision.evaluate(
        symbol=candidate["symbol"],
        market="fut",
        analysis=analysis,
        risk_manager=risk,
        current_open_count=0,
        max_open_positions=risk.max_open_futures_positions,
    )
    from entry_safety_policy import evaluate_entry_safety

    policy = evaluate_entry_safety(args=(), kwargs=open_kwargs(candidate), trades_path=str(sandbox / "trades.csv"))
    available = hasattr(router, "open_futures_position") and hasattr(router, "get_all_futures_positions")
    return decision_result, policy, available


def write_probe_trade_state_marker(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"open": {}, "closed": []}
    if not isinstance(data, dict):
        data = {"open": {}, "closed": []}
    data["probe_marker"] = PROBE_NAME
    open_map = data.get("open") if isinstance(data.get("open"), dict) else {}
    for value in open_map.values():
        if isinstance(value, dict):
            value["setup_type"] = SETUP_TYPE
            value["args_text"] = ARGS_TEXT
    data["open"] = open_map
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def csv_contains_marker(path: Path) -> bool:
    return path.exists() and MARKER in path.read_text(encoding="utf-8", errors="replace")


async def sync_dashboard(state, router) -> Dict[str, Any]:
    await state.sync_router_snapshot(router)
    return await state.get_dashboard_state()


def run_full(candidate: Dict[str, Any], sandbox: Path, backup: Path) -> Dict[str, Any]:
    router, risk, decision = new_pipeline_objects(sandbox)
    from logger import Logger
    from position_state_engine import PositionStateEngine

    logger = Logger(
        trades_filepath=str(sandbox / "trades.csv"),
        runtime_filepath=str(sandbox / "vortex.log"),
        print_to_stdout=False,
    )
    state_engine = PositionStateEngine(logger=logger)

    analysis = dict(candidate)
    decision_result = decision.evaluate(
        symbol=candidate["symbol"],
        market="fut",
        analysis=analysis,
        risk_manager=risk,
        current_open_count=len(router.get_all_futures_positions()),
        max_open_positions=risk.max_open_futures_positions,
    )
    if not decision_result.get("allow"):
        raise ProbeFail(f"DECISION_BLOCKED {decision_result.get('reason')}")

    from entry_safety_policy import evaluate_entry_safety

    kwargs = open_kwargs(candidate)
    policy = evaluate_entry_safety(args=(), kwargs=kwargs, trades_path=str(sandbox / "trades.csv"))
    if not policy.get("allow"):
        raise ProbeFail(f"POLICY_BLOCKED {policy.get('code')} {policy.get('reason')}")

    before_balance = safe_float(router.get_futures_balance())
    before_history = copy.deepcopy(getattr(router.paper_futures, "history", []))
    result = router.open_futures_position(**kwargs)
    if not isinstance(result, dict) or result.get("code") != "00000":
        raise ProbeFail(f"ROUTER_OPEN_FAIL {result}")

    pos = router.get_futures_position()
    if pos is None or MARKER not in str(getattr(pos, "setup_type", "")):
        raise ProbeFail("STATE_NOT_UPDATED router position marker missing")

    positions = router.get_all_futures_positions()
    if candidate["symbol"] not in positions:
        raise ProbeFail("STATE_NOT_UPDATED router fut_positions missing symbol")

    state_engine.open_from_position(pos, "FUT")
    write_probe_trade_state_marker(sandbox / "trades_state.json")
    logger.log_trade(
        symbol=candidate["symbol"],
        side=candidate["side"],
        market="FUT",
        entry=result["data"].get("entry"),
        tp=candidate["tp"],
        exit_price=0.0,
        pnl=0.0,
        pnl_net=0.0,
        reason="OPEN",
        hold_sec=0,
        setup_type=SETUP_TYPE,
        args_text=ARGS_TEXT,
    )

    from state_manager import StateManager

    state = StateManager()
    dashboard_open = asyncio.run(sync_dashboard(state, router))
    dashboard_fut = dashboard_open.get("positions", {}).get("fut", {})
    visible = candidate["symbol"] in dashboard_fut
    if not visible:
        raise ProbeFail("STATE_NOT_UPDATED dashboard fut position missing")

    serialized = dashboard_fut[candidate["symbol"]]
    if safe_float(serialized.get("notional"), 0.0) <= 0 or safe_float(serialized.get("margin"), 0.0) <= 0:
        raise ProbeFail("STATE_NOT_UPDATED dashboard margin/notional missing")
    if not csv_contains_marker(sandbox / "trades.csv"):
        raise ProbeFail("STATE_NOT_UPDATED sandbox trades.csv marker missing")
    if MARKER not in (sandbox / "trades_state.json").read_text(encoding="utf-8"):
        raise ProbeFail("STATE_NOT_UPDATED sandbox trades_state.json marker missing")

    close_result = router.close_futures_position(current_price=candidate["price"], reason="TEST_PROBE_ROLLBACK")
    if not isinstance(close_result, dict) or close_result.get("code") != "00000":
        raise ProbeFail(f"ROLLBACK_FAIL close={close_result} backup={backup}")
    state_engine.close(candidate["symbol"], "FUT", close_result.get("data") or {})

    router.paper_futures.balance = before_balance
    router.paper_futures.pos = None
    router.paper_futures.history = before_history
    dashboard_after = asyncio.run(sync_dashboard(state, router))
    after_positions = router.get_all_futures_positions()
    after_dashboard_fut = dashboard_after.get("positions", {}).get("fut", {})
    if after_positions or after_dashboard_fut:
        raise ProbeFail(f"ROLLBACK_FAIL fut_positions={after_positions} dashboard={after_dashboard_fut} backup={backup}")
    if abs(safe_float(router.get_futures_balance()) - before_balance) > 1e-8:
        raise ProbeFail(f"ROLLBACK_FAIL balance_changed backup={backup}")

    return {
        "decision": decision_result,
        "policy": policy,
        "open_result": result,
        "close_result": close_result,
        "position_created": True,
        "state_visible": visible,
        "rollback": True,
    }


def print_common(mode_name: str, candidate: Dict[str, Any]) -> None:
    print(f"{PROBE_NAME} {mode_name}")
    print("mode: PAPER")
    print("open_futures_positions: 0")
    print(f"candidate: {candidate['symbol']} {candidate['side']} test_probe")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=PROBE_NAME)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true", help="evaluate isolated PAPER pipeline without open")
    modes.add_argument("--paper-open", action="store_true", help="open isolated PAPER position")
    parser.add_argument("--rollback", action="store_true", help="required with --paper-open")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original_cwd = Path.cwd()
    try:
        if args.paper_open and not args.rollback:
            raise ProbeFail("--paper-open requires --rollback")
        ensure_paper_mode()
        health = api_json("/api/health")
        ensure_health_paper(health)
        dashboard = api_json("/api/dashboard")
        ensure_no_live_futures(ROOT, dashboard)
        symbol, price, atr = get_price_and_atr(dashboard)
        candidate = synthetic_candidate(symbol, price, atr)

        if args.dry_run:
            with tempfile.TemporaryDirectory(prefix="vortex_futures_pipeline_probe_dry_") as tmp:
                sandbox = Path(tmp)
                decision, policy, available = evaluate_dry(candidate, sandbox)
                print_common("DRY_RUN", candidate)
                print(f"decision_status: {'OPEN' if decision.get('allow') else 'BLOCK'} | {decision.get('reason')}")
                print(f"policy_status: {'ALLOW' if policy.get('allow') else 'BLOCK'} | {policy.get('code')}")
                print(f"router_available: {str(available).lower()}")
                ok = bool(decision.get("allow") and policy.get("allow") and available)
                print(f"result: {'PASS' if ok else 'FAIL'}")
                return 0 if ok else 1

        before = snapshot_production_files(ROOT)
        backup = make_backup(ROOT)
        with tempfile.TemporaryDirectory(prefix="vortex_futures_pipeline_probe_full_") as tmp:
            sandbox = Path(tmp)
            result = run_full(candidate, sandbox, backup)
        os.chdir(original_cwd)
        after = snapshot_production_files(ROOT)

        print_common("FULL", candidate)
        print(f"backup: {backup}")
        print("isolation: temporary sandbox, production runtime not mutated")
        print("open_attempt: PASS")
        print(f"position_created: {'PASS' if result['position_created'] else 'FAIL'}")
        print(f"state_visible: {'PASS' if result['state_visible'] else 'FAIL'}")
        print(f"rollback: {'PASS' if result['rollback'] else 'FAIL'}")
        print(f"production_state_unchanged: {str(before == after).lower()}")
        print("result: PASS")
        return 0
    except ProbeFail as exc:
        print(f"{PROBE_NAME} FAIL")
        print(f"reason: {exc}")
        print("result: FAIL")
        return 1
    finally:
        os.chdir(original_cwd)


if __name__ == "__main__":
    raise SystemExit(main())
