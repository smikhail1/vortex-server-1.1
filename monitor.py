import urllib.request
import json
import time
import os
from datetime import datetime

API_URL = "http://127.0.0.1:8000/api/debug/runtime"

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_data():
    try:
        with urllib.request.urlopen(API_URL, timeout=2) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        return {"error": str(e)}

def render():
    while True:
        data = get_data()
        clear()
        
        print(f"=== VORTEX LIVE MONITOR | {datetime.now().strftime('%H:%M:%S')} ===")
        
        if "error" in data:
            print(f"\033[91m[!] ОШИБКА API (Сервер запущен?): {data['error']}\033[0m")
        else:
            # Секция 1: Система
            meta = data.get("meta", {})
            sys = data.get("system", {})
            macro = sys.get("macro", {})
            
            print(f"\033[94m[SYSTEM]\033[0m Mode: {meta.get('mode', 'N/A')} | Uptime: {sys.get('uptime', '00:00:00')}")
            print(f"\033[94m[MARKET]\033[0m BTC: ${macro.get('bitget_btc', 0):,.1f} | Funding Tickers: {len(macro.get('funding_rates', {}))}")
            print(f"\033[94m[POOLS]\033[0m  FUT: {len(sys.get('fut_pool', []))} | SPOT: {len(sys.get('spot_pool', []))}")
            
            print("-" * 55)
            
            # Секция 2: Финансы
            acc = data.get("account", {}).get("balances", {})
            print(f"\033[92m[WALLET]\033[0m FUT: {acc.get('fut', 0.0):.2f} USDT | SPOT: {acc.get('spot', 0.0):.2f} USDT")
            
            # Секция 3: Позиции
            pos_fut = data.get("positions", {}).get("fut", {})
            pos_spot = data.get("positions", {}).get("spot", {})
            
            print(f"\033[93m[POSITIONS]\033[0m")
            if not pos_fut and not pos_spot:
                print("  > Активных сделок нет (ЧИСТО)")
            else:
                for sym, p in pos_fut.items():
                    side = p.get('side', 'N/A')
                    entry = p.get('entry', 0.0)
                    pnl = p.get('pnl', 0.0)
                    color = "\033[92m" if pnl >= 0 else "\033[91m"
                    print(f"  > [FUT] {sym}: {side} | Entry: {entry} | PnL: {color}{pnl:.2f}\033[0m")
                for sym, p in pos_spot.items():
                    print(f"  > [SPOT] {sym}: BUY | Entry: {p.get('entry', 0.0)}")

            print("-" * 55)
            
            # Секция 4: Логи
            logs = sys.get("sys_logs", [])[:5]
            print(f"\033[90m[LAST LOGS]\033[0m")
            for line in logs:
                print(f"  {line}")

        print("\n\033[90m(Ctrl+C для выхода)\033[0m")
        time.sleep(2)

if __name__ == "__main__":
    try:
        render()
    except KeyboardInterrupt:
        print("\nМониторинг остановлен.")