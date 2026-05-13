#!/usr/bin/env bash
set -e

echo "== RUN INTEGRATION TESTS V2 =="
python3 test_integration_scenarios_v2.py

echo
echo "== QUICK ROUTER SNAPSHOT =="
python3 - <<'PY'
from execution_router import ExecutionRouter

router = ExecutionRouter(mode="PAPER")
print(router.get_runtime_snapshot())
PY