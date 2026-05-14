import os

print("Установка интеграции Spot Planner...")

with open("main.py", "r", encoding="utf-8") as f:
    main_code = f.read()

# 1. Извлекаем данные планера в начале цикла
old_vars = """            ta_data = dash.get("market", {}).get("ta_data", {})
            fut_pool = dash.get("system", {}).get("fut_pool", [])
            spot_pool = dash.get("system", {}).get("spot_pool", [])
            macro_filter = dash.get("system", {}).get("macro", {}).get("global_filter", "allow_all")"""

new_vars = """            ta_data = dash.get("market", {}).get("ta_data", {})
            fut_pool = dash.get("system", {}).get("fut_pool", [])
            spot_pool = dash.get("system", {}).get("spot_pool", [])
            macro_filter = dash.get("system", {}).get("macro", {}).get("global_filter", "allow_all")
            planner_state = dash.get("planner", {}).get("spot_planner", {}) or {}
            planner_map = {x.get("symbol"): x for x in planner_state.get("spot_ideas", []) if isinstance(x, dict)}"""
main_code = main_code.replace(old_vars, new_vars)

# 2. Передаем идеи планера в Стратегию
main_code = main_code.replace(
    'analysis = strategy.analyze_spot(current, macro_filter)',
    'analysis = strategy.analyze_spot(current, macro_filter, planner_idea=planner_map.get(sym))'
)

# 3. Фиксируем ордер 10 USDT и берем Тейк из планера
old_spot_order = """                    order_usdt = CONFIG.trading.spot_order_usdt * CONFIG.trading.spot_entry_1_pct
                    qty = order_usdt / price

                    result = router.open_spot_position(
                        symbol=sym,
                        qty=qty,
                        price=price,
                        tp=ladder["tp"],"""

new_spot_order = """                    tp = safe_float(analysis.get("tp_base")) if analysis.get("setup_type") == "planner_spot" else ladder["tp"]
                    order_usdt = 10.0  # [FIX] Фиксированный объем 10 USDT для спота
                    qty = order_usdt / price

                    result = router.open_spot_position(
                        symbol=sym,
                        qty=qty,
                        price=price,
                        tp=tp,"""
main_code = main_code.replace(old_spot_order, new_spot_order)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(main_code)
print("✅ main.py: Планер интегрирован, объем 10 USDT установлен.")


with open("strategy.py", "r", encoding="utf-8") as f:
    strat_code = f.read()

old_strat = """    def analyze_spot(self, current, macro_filter="allow_all"):
        res = self.analyze_futures(current, macro_filter)
        if res.get("signal") == "SHORT": res["should_open"] = False; res["signal"] = None
        return res"""

new_strat = """    def analyze_spot(self, current, macro_filter="allow_all", planner_idea=None):
        if planner_idea and planner_idea.get("ready"):
            return self._result(
                should_open=True,
                signal="BUY",
                score=planner_idea.get("score", 80),
                setup_type="planner_spot",
                args=[f"Planner Tier {planner_idea.get('tier')}", planner_idea.get("action_hint")],
                threshold=0,
                extra={
                    "trigger_price": current.get("price", 0.0) * 0.9999, # Мгновенное подтверждение
                    "invalidation_price": planner_idea.get("invalid_level", 0.0),
                    "tp_base": planner_idea.get("tp_base", current.get("price", 0.0) * 1.1)
                }
            )
            
        res = self.analyze_futures(current, macro_filter)
        if res.get("signal") == "SHORT": 
            res["should_open"] = False
            res["signal"] = None
        return res"""
strat_code = strat_code.replace(old_strat, new_strat)

with open("strategy.py", "w", encoding="utf-8") as f:
    f.write(strat_code)
print("✅ strategy.py: Добавлена логика planner_spot.")
