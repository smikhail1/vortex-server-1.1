import asyncio, time

from market_data      import MarketDataStream
from ta_engine        import TAEngine
from strategy         import SwingStrategy
from market_screener  import MarketScreener
from paper_futures    import PaperFutures
from paper_spot       import PaperSpot
from api_server       import APIServer
from sys_monitor      import SysMonitor
from market_oracle    import MarketOracle
import logger

DASHBOARD = {
    "start_time":      time.time(),
    "balances":        {"fut": 100.0, "spot": 100.0},
    "current_prices":  {},
    "fut_pool":        ["BTCUSDT", "ETHUSDT"],
    "spot_pool":       [],
    "sys_logs":        [],
    "daily_pnl_fut":   0.0,
    "daily_pnl_spot":  0.0,
    "fut_trades":      [],
    "spot_trades":     [],
    "fut_args":        {},
    "spot_args":       {},
    "fut_wins":        0,
    "fut_losses":      0,
    "spot_wins":       0,
    "spot_losses":     0,
    "scanner_top":     [],
    "server_status":   {"uptime": "00:00:00", "ram_mb": "0", "ping_ms": "0"},
    "last_pool_update": 0,
    "macro":           {"global_filter": "allow_all", "btc_trend": "neutral",
                        "binance_btc": 0.0, "oi_amount": 0.0, "fng_value": 50},
}

def add_sys_log(tag, message):
    msg = f"🕒 {time.strftime('%H:%M:%S')} {tag} {message}"
    DASHBOARD["sys_logs"].insert(0, msg)
    if len(DASHBOARD["sys_logs"]) > 50:
        DASHBOARD["sys_logs"].pop()
    print(msg)

def format_trade(sym, pnl, reason):
    ru = {"TP1":"Тейк1","TP2":"Тейк2","SL":"Стоп",
          "BU":"Б/У","TIMEOUT":"Таймаут"}.get(reason, reason)
    icon = "✅" if pnl > 0 else ("🚨" if pnl < 0 else "🛡️")
    return f"{icon} [{time.strftime('%H:%M:%S')}] {sym} | {round(pnl,3)} USDT ({ru})"

def update_pools(screener, fut_eng, spot_eng, stream, engines):
    try:
        active_fut  = [fut_eng.get_position().symbol] if fut_eng.get_position() else []
        active_spot = list(spot_eng.get_all_positions().keys())

        base = ["BTCUSDT", "ETHUSDT"]
        candidates = screener.update_watchlist()
        DASHBOARD["scanner_top"] = candidates

        new_fut = list(dict.fromkeys(
            active_fut + base +
            [s for s in candidates if s not in active_fut + base]
        ))[:8]

        new_spot = list(dict.fromkeys(
            active_spot +
            [s for s in candidates if s not in active_spot]
        ))[:3]

        added_fut  = set(new_fut)  - set(DASHBOARD["fut_pool"])
        removed_fut = set(DASHBOARD["fut_pool"]) - set(new_fut)

        if added_fut or removed_fut:
            add_sys_log("🔄 [РОТАЦИЯ]",
                f"Фьюч +[{','.join(added_fut) or '-'}] "
                f"-[{','.join(removed_fut) or '-'}]")

        DASHBOARD["fut_pool"]  = new_fut
        DASHBOARD["spot_pool"] = new_spot
        DASHBOARD["last_pool_update"] = time.time()

        stream.fut_symbols  = new_fut
        stream.spot_symbols = new_spot

        for s in set(new_fut + new_spot):
            if s not in engines:
                engines[s] = TAEngine()

    except Exception as e:
        add_sys_log("⚠️ [РОТАЦИЯ]", str(e))

async def main():
    logger.init_logger()
    add_sys_log("🚀 [SYSTEM]", "Vortex Swing Terminal v2 запускается...")

    fut_eng  = PaperFutures()
    spot_eng = PaperSpot()
    strat    = SwingStrategy()
    screener = MarketScreener()

    asyncio.create_task(SysMonitor(DASHBOARD).start())
    asyncio.create_task(MarketOracle(DASHBOARD).start())
    asyncio.create_task(APIServer(DASHBOARD).start(port=8080))

    stream  = MarketDataStream(DASHBOARD["fut_pool"], DASHBOARD["spot_pool"])
    engines = {s: TAEngine() for s in DASHBOARD["fut_pool"]}
    asyncio.create_task(stream.connect())

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, update_pools, screener, fut_eng, spot_eng, stream, engines
    )
    add_sys_log("✅ [SYSTEM]", f"Пул: {DASHBOARD['fut_pool']}")

    while True:
        try:
            await asyncio.sleep(5)

            if time.time() - DASHBOARD["last_pool_update"] > 900:
                await loop.run_in_executor(
                    None, update_pools, screener, fut_eng, spot_eng, stream, engines
                )

            global_filter = DASHBOARD["macro"].get("global_filter", "allow_all")

            # ═══════════ ФЬЮЧЕРСЫ ═══════════
            for s in list(DASHBOARD["fut_pool"]):
                buf   = stream.buffers.get(s, {})
                price = buf.get("last_price", 0)
                if price <= 0:
                    continue
                DASHBOARD["current_prices"][s] = price

                if s not in engines:
                    engines[s] = TAEngine()
                analysis = engines[s].analyze_all(buf)

                if not analysis:
                    DASHBOARD["fut_args"][s] = "Сбор данных 30m/4H..."
                    continue

                pos = fut_eng.get_position()

                if not pos:
                    sig = strat.analyze_futures(analysis, s, global_filter)
                    DASHBOARD["fut_args"][s] = sig.get("args_text", "Ожидание...")

                    if sig.get("signal", "neutral") != "neutral":
                        tp  = sig.get("take_profit", 0)
                        sl  = sig.get("stop_loss",   0)
                        lev = sig.get("leverage",    3)
                        qty = round((100 * lev) / price, 6)

                        if fut_eng.open_position(
                            s, sig["signal"], qty, price, tp, sl, analysis["atr"]
                        )["code"] == "00000":
                            add_sys_log("🎯 [FUT]",
                                f"{sig['signal'].upper()} {s} @ {price:.4f} "
                                f"TP:{tp:.4f} SL:{sl:.4f}")
                            DASHBOARD["fut_args"][s] = (
                                f"🔴 В СДЕЛКЕ ({sig['signal'].upper()}) | "
                                f"TP:{tp:.4f} SL:{sl:.4f} | PnL:0.00"
                            )

                elif pos.symbol == s:
                    fee = 100.0 * 3 * 0.0012
                    dur = time.time() - pos.open_time
                    DASHBOARD["fut_args"][s] = (
                        f"🔴 В СДЕЛКЕ ({pos.side.upper()}) | "
                        f"En:{pos.entry:.4f} | "
                        f"PnL:{round(pos.pnl - fee, 2)}"
                    )
                    r = fut_eng.check_stops(price)
                    if r:
                        net_pnl = r["data"]["pnl"] - fee
                        DASHBOARD["daily_pnl_fut"] += net_pnl
                        reason = r["data"]["reason"]
                        if net_pnl > 0:
                            DASHBOARD["fut_wins"] += 1
                            strat.reset_streak(s)
                        else:
                            DASHBOARD["fut_losses"] += 1
                            strat.add_loss(s)

                        t_fmt = format_trade(s, net_pnl, reason)
                        DASHBOARD["fut_trades"].insert(0, t_fmt)
                        if len(DASHBOARD["fut_trades"]) > 50:
                            DASHBOARD["fut_trades"].pop()
                        add_sys_log("💰 [FUT]", t_fmt)
                        logger.log_trade("FUT", s, net_pnl, reason, dur,
                                         fut_eng.get_balance(), spot_eng.get_balance())
                        DASHBOARD["fut_args"][s] = "Ожидание..."

                        if s not in ("BTCUSDT", "ETHUSDT"):
                            if s in screener.watchlist:
                                del screener.watchlist[s]

                else:
                    sig = strat.analyze_futures(analysis, s, global_filter)
                    DASHBOARD["fut_args"][s] = sig.get("args_text", "Ожидание...")
                
                # Микро-пауза для разгрузки сервера API
                await asyncio.sleep(0.01)

            # ═══════════ СПОТ ═══════════
            for s in list(DASHBOARD["spot_pool"]):
                buf   = stream.buffers.get(s, {})
                price = buf.get("last_price", 0)
                if price <= 0:
                    continue
                DASHBOARD["current_prices"][s] = price

                if s not in engines:
                    engines[s] = TAEngine()
                analysis = engines[s].analyze_all(buf)

                if not analysis:
                    DASHBOARD["spot_args"][s] = "Сбор данных 30m/4H..."
                    continue

                pos_s = spot_eng.get_position(s)
                res_s = spot_eng.check_stops(s, price)

                if res_s:
                    net_pnl = res_s["data"]["pnl"] - (33.3 * 0.002)
                    DASHBOARD["daily_pnl_spot"] += net_pnl
                    reason = res_s["data"]["reason"]
                    if net_pnl > 0:
                        DASHBOARD["spot_wins"] += 1
                    else:
                        DASHBOARD["spot_losses"] += 1

                    t_fmt = format_trade(s, net_pnl, reason)
                    DASHBOARD["spot_trades"].insert(0, t_fmt)
                    if len(DASHBOARD["spot_trades"]) > 50:
                        DASHBOARD["spot_trades"].pop()
                    logger.log_trade("SPOT", s, net_pnl, reason,
                                     time.time() - (pos_s.open_time if pos_s else time.time()),
                                     fut_eng.get_balance(), spot_eng.get_balance())
                    DASHBOARD["spot_args"][s] = "Ожидание..."

                    if s in screener.watchlist:
                        del screener.watchlist[s]
                    continue

                if pos_s:
                    fee_s = 33.3 * 0.002
                    DASHBOARD["spot_args"][s] = (
                        f"🟢 В СДЕЛКЕ | En:{pos_s.entry:.4f} | "
                        f"PnL:{round(pos_s.pnl - fee_s, 2)}"
                    )
                else:
                    sig_s = strat.analyze_spot(analysis, s, global_filter)
                    DASHBOARD["spot_args"][s] = sig_s.get("args_text", "Поиск...")

                    if (sig_s.get("signal") == "long_dca"
                            and len(spot_eng.get_all_positions()) < 3):
                        orders = sig_s.get("orders", [])
                        tp     = sig_s.get("take_profit", 0)
                        if orders:
                            qty = round(
                                (100 * orders[0]["size_pct"] / 100) / price, 6
                            )
                            if spot_eng.open_position(
                                s, qty, price, tp, analysis["atr"]
                            )["code"] == "00000":
                                add_sys_log("🎯 [SPOT]",
                                    f"DCA {s} @ {price:.4f} TP:{tp:.4f}")
                                DASHBOARD["spot_args"][s] = (
                                    f"🟢 В СДЕЛКЕ (DCA 1) | TP:{tp:.4f}"
                                )
                
                # Микро-пауза для разгрузки сервера API
                await asyncio.sleep(0.01)

            DASHBOARD["balances"]["fut"]  = round(fut_eng.get_balance(), 2)
            DASHBOARD["balances"]["spot"] = round(spot_eng.get_balance(), 2)

        except Exception as e:
            add_sys_log("⚠️ [ERR]", str(e))
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())