import asyncio, time

from market_data import MarketDataStream
from ta_engine import TAEngine
from strategy import SwingStrategy      # Перешли на Swing
from market_screener import MarketScreener # Наш новый умный скринер
from paper_futures import PaperFutures
from paper_spot import PaperSpot
from api_server import APIServer
from sys_monitor import SysMonitor
from market_oracle import MarketOracle
import logger

DASHBOARD = {
    "start_time": time.time(),
    "balances": {"fut": 100.0, "spot": 100.0},
    "current_prices": {},
    "fut_pool": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT"],
    "spot_pool": [],
    "sys_logs": [],
    "daily_pnl_fut": 0.0, "daily_pnl_spot": 0.0,
    "fut_trades": [], "spot_trades": [],
    "fut_args": {}, "spot_args": {},
    "fut_wins": 0, "fut_losses": 0,
    "spot_wins": 0, "spot_losses": 0,
    "scanner_candidates": [], "scanner_updated": 0,
    "server_status": {"uptime": "00:00:00", "ram_mb": "0", "ping_ms": "0"},
    "last_pool_update": 0,
    "macro": {"global_filter": "allow_all", "btc_trend": "neutral",
              "funding_rate": 0.0, "binance_btc": 0.0}
}

def add_sys_log(tag, message):
    msg = f"🕒 {time.strftime('%H:%M:%S')} {tag} {message}"
    DASHBOARD["sys_logs"].insert(0, msg)
    if len(DASHBOARD["sys_logs"]) > 50:
        DASHBOARD["sys_logs"].pop()
    print(msg)

def format_trade(sym, pnl, reason):
    reason_ru = {"TP": "Тейк", "SL": "Стоп", "BU": "Б/У", "TIMEOUT": "Таймаут"}.get(reason, reason)
    icon = "✅" if pnl > 0 else ("🚨" if pnl < 0 else "🛡️")
    return f"{icon} [{time.strftime('%H:%M:%S')}] {sym} | {round(pnl, 3)} USDT ({reason_ru})"

def update_pools(screener, fut_eng, spot_eng):
    try:
        active_fut = [fut_eng.get_position().symbol] if fut_eng.get_position() else []
        active_spot = list(spot_eng.get_all_positions().keys())

        # Запрашиваем топ волатильных монет у скринера
        top_coins = screener.update_watchlist()
        if not top_coins:
            top_coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT"]

        new_fut = active_fut + [s for s in top_coins if s not in active_fut][:5 - len(active_fut)]
        new_spot = active_spot + [s for s in top_coins if s not in active_spot][:3 - len(active_spot)]

        added = set(new_fut) - set(DASHBOARD["fut_pool"])
        if added:
            add_sys_log("🔄 [РОТАЦИЯ]", f"+{','.join(added)}")

        DASHBOARD["fut_pool"] = new_fut
        DASHBOARD["spot_pool"] = new_spot
        DASHBOARD["last_pool_update"] = time.time()

    except Exception as e:
        add_sys_log("⚠️ [РОТАЦИЯ]", str(e))

async def main():
    logger.init_logger()
    add_sys_log("🚀 [SYSTEM]", "Vortex Swing Terminal запускается...")

    fut_eng = PaperFutures()
    spot_eng = PaperSpot()
    strat = SwingStrategy()
    screener = MarketScreener()

    asyncio.create_task(SysMonitor(DASHBOARD).start())
    asyncio.create_task(MarketOracle(DASHBOARD).start())
    asyncio.create_task(APIServer(DASHBOARD).start(port=8080))

    # Первичное заполнение пула
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, update_pools, screener, fut_eng, spot_eng)

    stream = MarketDataStream(DASHBOARD["fut_pool"], DASHBOARD["spot_pool"])
    engines = {s: TAEngine() for s in set(DASHBOARD["fut_pool"] + DASHBOARD["spot_pool"])}
    asyncio.create_task(stream.connect())

    add_sys_log("✅ [SYSTEM]", f"Пул фьючерсов: {DASHBOARD['fut_pool']}")

    while True:
        try:
            # Свинг не терпит суеты, анализируем реже
            await asyncio.sleep(5)

            # Ротация каждые 15 минут
            if time.time() - DASHBOARD["last_pool_update"] > 900:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, update_pools, screener, fut_eng, spot_eng)
                stream.fut_symbols = DASHBOARD["fut_pool"]
                stream.spot_symbols = DASHBOARD["spot_pool"]
                for s in set(DASHBOARD["fut_pool"] + DASHBOARD["spot_pool"]):
                    if s not in engines:
                        engines[s] = TAEngine()

            global_filter = DASHBOARD.get("macro", {}).get("global_filter", "allow_all")

            # --- ФЬЮЧЕРСЫ ---
            for s in list(DASHBOARD["fut_pool"]):
                buf = stream.buffers.get(s, {})
                price = buf.get("last_price", 0)
                if price <= 0: continue
                DASHBOARD["current_prices"][s] = price

                if s not in engines: engines[s] = TAEngine()
                analysis = engines[s].analyze_all(buf)
                if not analysis:
                    DASHBOARD["fut_args"][s] = "Сбор данных 1h/4h..."
                    continue

                pos = fut_eng.get_position()

                if not pos:
                    sig = strat.analyze_futures(analysis, s, global_filter)
                    DASHBOARD["fut_args"][s] = sig.get("args_text", "Ожидание...")
                    
                    if sig.get("signal", "neutral") != "neutral":
                        # OCO Ордер: Плечо 3х, объем $200 (маржа ~$66)
                        leverage = sig.get("leverage", 3)
                        qty = round((200 * leverage) / price, 6)
                        tp = sig.get("take_profit", 0)
                        sl = sig.get("stop_loss", 0)

                        if fut_eng.open_position(s, sig["signal"], qty, price, tp, sl, analysis["atr"])["code"] == "00000":
                            add_sys_log("🎯 [FUT]", f"Вход {sig['signal'].upper()} {s} @ {price:.4f} (TP:{tp:.2f} SL:{sl:.2f})")
                            DASHBOARD["fut_args"][s] = f"🔴 В СДЕЛКЕ | TP:{tp:.2f} SL:{sl:.2f}"

                elif pos.symbol == s:
                    fee = 200.0 * 3 * 0.0012 # Комиссия с учетом плеча
                    duration = time.time() - pos.open_time
                    DASHBOARD["fut_args"][s] = (
                        f"🔴 СДЕЛКА ({pos.side.upper()}) | "
                        f"En:{pos.entry:.4f} TP:{pos.tp:.4f} | "
                        f"PnL: {round(pos.pnl - fee, 2)}"
                    )

                    # Убрали принудительный таймаут. Ждем TP или SL
                    r = fut_eng.check_stops(price)

                    if r:
                        net_pnl = r["data"]["pnl"] - fee
                        DASHBOARD["daily_pnl_fut"] += net_pnl
                        if net_pnl > 0: DASHBOARD["fut_wins"] += 1
                        else: 
                            DASHBOARD["fut_losses"] += 1
                            strat.set_cooldown(s) # Остывание 4 часа при минусе
                        
                        t_fmt = format_trade(s, net_pnl, r["data"]["reason"])
                        DASHBOARD["fut_trades"].insert(0, t_fmt)
                        if len(DASHBOARD["fut_trades"]) > 50: DASHBOARD["fut_trades"].pop()
                        
                        add_sys_log("💰 [FUT]", t_fmt)
                        logger.log_trade("FUT", s, net_pnl, r["data"]["reason"], duration, fut_eng.get_balance(), spot_eng.get_balance())
                        DASHBOARD["fut_args"][s] = "Остывание..."

            # --- СПОТ ---
            for s in list(DASHBOARD["spot_pool"]):
                buf = stream.buffers.get(s, {})
                price = buf.get("last_price", 0)
                if price <= 0: continue
                DASHBOARD["current_prices"][s] = price

                if s not in engines: engines[s] = TAEngine()
                analysis = engines[s].analyze_all(buf)
                if not analysis:
                    DASHBOARD["spot_args"][s] = "Сбор данных 1h/4h..."
                    continue

                pos_s = spot_eng.get_position(s)
                res_s = spot_eng.check_stops(s, price)
                
                if res_s:
                    net_pnl = res_s["data"]["pnl"] - (33.3 * 0.002)
                    DASHBOARD["daily_pnl_spot"] += net_pnl
                    if net_pnl > 0: DASHBOARD["spot_wins"] += 1
                    else: DASHBOARD["spot_losses"] += 1
                    
                    t_fmt = format_trade(s, net_pnl, res_s["data"]["reason"])
                    DASHBOARD["spot_trades"].insert(0, t_fmt)
                    if len(DASHBOARD["spot_trades"]) > 50: DASHBOARD["spot_trades"].pop()
                    
                    logger.log_trade("SPOT", s, net_pnl, res_s["data"]["reason"], time.time() - (pos_s.open_time if pos_s else time.time()), fut_eng.get_balance(), spot_eng.get_balance())
                    DASHBOARD["spot_args"][s] = "Остывание..."
                    continue

                if pos_s:
                    fee_s = 33.3 * 0.002
                    DASHBOARD["spot_args"][s] = f"🟢 В СДЕЛКЕ | En:{pos_s.entry:.4f} | PnL: {round(pos_s.pnl - fee_s, 2)}"
                else:
                    sig_s = strat.analyze_spot(analysis, s, global_filter)
                    DASHBOARD["spot_args"][s] = sig_s.get("args_text", "Ожидание...")
                    
                    if sig_s.get("signal") == "long_dca" and len(spot_eng.get_all_positions()) < 3:
                        orders = sig_s.get("orders", [])
                        tp = sig_s.get("take_profit", 0)
                        if orders:
                            # В Paper-режиме открываем позицию по рынку на первую ступень лесенки (20% от $100)
                            first_order_qty = round((100 * (orders[0]["size_pct"] / 100)) / price, 6)
                            if spot_eng.open_position(s, first_order_qty, price, tp, analysis["atr"])["code"] == "00000":
                                add_sys_log("🎯 [SPOT]", f"Вход DCA {s} @ {price:.4f} (Ступень 1)")
                                DASHBOARD["spot_args"][s] = f"🟢 СДЕЛКА DCA | TP:{tp:.2f}"

            DASHBOARD["balances"]["fut"] = round(fut_eng.get_balance(), 2)
            DASHBOARD["balances"]["spot"] = round(spot_eng.get_balance(), 2)

        except Exception as e:
            add_sys_log("⚠️ [ERR]", str(e))
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
