#!/usr/bin/env bash
set -e

echo "==================================================="
echo "🧪 VORTEX TEST SUITE RUNNER (NATIVE MODE)"
echo "==================================================="

TEST_FILES=(
    "test_console_scenarios.py"
    "test_fee_guard_scenarios.py"
    "test_integration_scenarios_v2.py"
    "test_momentum_engine.py"
    "test_position_state_engine.py"
    "test_regime_scenarios.py"
    "test_screener_scenarios.py"
    "test_strategy_scenarios.py"
    "test_trade_manager_scenarios.py"
    "test_watchlist_snapshot.py"
)

PASSED=0
FAILED=0
FAILED_TESTS=""

for file in "${TEST_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -n "⏳ Running $file ... "
        # Запускаем скрипт напрямую, скрываем вывод, ловим код возврата
        if python3 "$file" > /dev/null 2>&1; then
            echo "✅ PASSED"
            PASSED=$((PASSED + 1))
        else
            echo "❌ FAILED"
            FAILED=$((FAILED + 1))
            FAILED_TESTS="$FAILED_TESTS\n  - $file"
        fi
    else
        echo "⚠️ SKIPPED: $file not found!"
    fi
done

echo ""
echo "==================================================="
echo "📊 TEST SUMMARY"
echo "==================================================="
echo "✅ Passed: $PASSED"
echo "❌ Failed: $FAILED"

if [ $FAILED -gt 0 ]; then
    echo -e "\n🚨 Упавшие модули:$FAILED_TESTS"
    echo -e "\n💡 Совет: Чтобы увидеть детальную ошибку, запусти проблемный тест вручную так:"
    echo "python3 <название_файла.py>"
    exit 1
else
    echo -e "\n🎉 ALL TESTS PASSED! Архитектура монолитна."
    exit 0
fi
