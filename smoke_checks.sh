#!/usr/bin/env bash
set -e

BASE_URL="http://127.0.0.1:8000"

echo "== HEALTH =="
curl -s "${BASE_URL}/api/health"
echo
echo

echo "== DASHBOARD =="
curl -s "${BASE_URL}/api/dashboard"
echo
echo

echo "== PLANNER =="
curl -s "${BASE_URL}/api/spot-planner"
echo
echo

echo "== RUNTIME =="
curl -s "${BASE_URL}/api/debug/runtime"
echo
echo

echo "== RISK STATUS =="
curl -s "${BASE_URL}/api/debug/risk/status"
echo
echo

echo "== OPEN FUTURES TEST =="
curl -s -X POST "${BASE_URL}/api/debug/open-futures" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"LONG","price":65000,"atr":500,"margin_usdt":20,"leverage":3,"setup_type":"smoke_fut","args_text":"smoke test futures"}'
echo
echo

echo "== CLOSE FUTURES TEST =="
curl -s -X POST "${BASE_URL}/api/debug/close-futures" \
  -H "Content-Type: application/json" \
  -d '{"price":65500,"reason":"MANUAL"}'
echo
echo

echo "== OPEN SPOT TEST =="
curl -s -X POST "${BASE_URL}/api/debug/open-spot" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"ETHUSDT","price":3200,"atr":40,"order_usdt":20,"setup_type":"smoke_spot","args_text":"smoke test spot"}'
echo
echo

echo "== CLOSE SPOT TEST =="
curl -s -X POST "${BASE_URL}/api/debug/close-spot" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"ETHUSDT","price":3260,"reason":"MANUAL"}'
echo
echo

echo "== LOG TAIL =="
curl -s "${BASE_URL}/api/debug/logs/tail?lines=30"
echo
echo

echo "SMOKE CHECKS DONE"