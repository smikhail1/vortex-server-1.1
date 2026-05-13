with open('api_server.py', 'r') as f:
    code = f.read()

if 'mobile_history' not in code:
    route_injection = 'self.app.router.add_get("/api/mobile_history", self.handle_mobile_history),'
    code = code.replace('self.app.router.add_get("/api/health", self.handle_health),', 
                        'self.app.router.add_get("/api/health", self.handle_health),\n            ' + route_injection)

    handler_code = """
    async def handle_mobile_history(self, request):
        import os, json
        from aiohttp import web
        from datetime import datetime
        res = []
        try:
            if os.path.exists("trades_state.json"):
                with open("trades_state.json", "r") as f:
                    st = json.load(f)
                
                # Добавляем открытые сделки наверх
                for p in st.get("open", {}).values():
                    res.append({
                        "timestamp": datetime.fromtimestamp(p.get("open_time", 0)).strftime('%Y-%m-%d %H:%M:%S'),
                        "symbol": str(p.get("symbol", "")),
                        "side": str(p.get("side", "")),
                        "type": str(p.get("market", "")),
                        "setup_type": str(p.get("setup_type", "")),
                        "args_text": "ACTIVE (Текущий PnL)",
                        "entry_price": str(p.get("entry", "0")),
                        "target_tp": str(p.get("tp", "0")),
                        "exit_price": str(p.get("current_price", "0")),
                        "pnl": str(round(p.get("pnl_net", 0), 4)),
                        "status": "OPEN"
                    })

                # Добавляем закрытые сделки
                for p in reversed(st.get("closed", [])):
                    res.append({
                        "timestamp": datetime.fromtimestamp(p.get("closed_at", 0)).strftime('%Y-%m-%d %H:%M:%S'),
                        "symbol": str(p.get("symbol", "")),
                        "side": str(p.get("side", "")),
                        "type": str(p.get("market", "")),
                        "setup_type": str(p.get("setup_type", "")),
                        "args_text": str(p.get("close_reason", "")),
                        "entry_price": str(p.get("entry", "0")),
                        "target_tp": str(p.get("tp", "0")),
                        "exit_price": str(p.get("current_price", "0")),
                        "pnl": str(round(p.get("pnl_net", 0), 4)),
                        "status": "CLOSED"
                    })
        except Exception as e:
            print("Error mobile history:", e)
        return web.json_response(res)
"""
    code = code.replace('    async def handle_health', handler_code + '\n    async def handle_health')
    
    with open('api_server.py', 'w') as f:
        f.write(code)
    print("✅ Адаптер /api/mobile_history добавлен!")
else:
    print("Маршрут уже существует.")
