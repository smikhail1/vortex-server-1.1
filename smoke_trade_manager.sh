#!/usr/bin/env bash
set -e

echo "== RUN TRADE MANAGER TESTS =="
python3 test_trade_manager_scenarios.py

echo
echo "== QUICK RUNTIME CHECK =="
python3 - <<'PY'
from execution_router import ExecutionRouter

router = ExecutionRouter(mode="PAPER")
print(router.get_runtime_snapshot())
PY