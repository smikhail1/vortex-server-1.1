import re

file_path = 'api_server.py'
with open(file_path, 'r') as f:
    content = f.read()

# 1. Добавляем маршрут /api/history в список routes
route_pattern = r'(self\.app\.router\.add_get\("/api/dashboard", self\.handle_dashboard\),)'
new_route = r'\1\n            self.app.router.add_get("/api/history", self.handle_history),'
content = re.sub(route_pattern, new_route, content)

# 2. Добавляем саму функцию handle_history
history_handler = """
    async def handle_history(self, request):
        try:
            import os
            import json
            from datetime import datetime
            
            file = 'trades_state.json'
            history_list = []
            
            if os.path.exists(file):
                with open(file, 'r') as f:
                    data = json.load(f)
                    
                # Обрабатываем закрытые сделки
                for pos in data.get('closed', []):
                    # Превращаем timestamp в строку времени
                    close_time = datetime.fromtimestamp(pos.get('closed_at', 0)).strftime('%Y-%m-%d %H:%M:%S')
                    
                    history_list.append({
                        "timestamp": close_time,
                        "symbol": str(pos.get('symbol', '')),
                        "side": str(pos.get('side', '')),
                        "type": str(pos.get('market', '')),
                        "setup_type": str(pos.get('setup_type', '')),
                        "args_text": str(pos.get('close_reason', '')), # Временно кладем причину закрытия сюда
                        "entry_price": str(pos.get('entry', '0')),
                        "target_tp": str(pos.get('tp', '0')),
                        "exit_price": str(pos.get('current_price', '0')),
                        "pnl": str(pos.get('pnl_net', '0')),
                        "status": "CLOSED"
                    })
                    
            return web.json_response(history_list)
        except Exception as e:
            if self.logger: self.logger.error("API", "history failed", {"err": str(e)})
            return web.json_response([])
"""

# Вставляем функцию перед handle_dashboard
handler_pattern = r'(    async def handle_dashboard\(self, request\):)'
content = re.sub(handler_pattern, history_handler + r'\n\1', content)

with open(file_path, 'w') as f:
    f.write(content)
    
print("✅ Адаптер /api/history успешно добавлен в api_server.py")
