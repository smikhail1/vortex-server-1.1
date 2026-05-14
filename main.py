import asyncio
import time

from api_server import APIServer
from config import CONFIG
from exchange_intelligence import ExchangeIntelligenceService
from decision_engine import DecisionEngine
from execution_router import ExecutionRouter
from logger import Logger
from loop_runner import create_task
from market_data import MarketDataStream
from market_oracle import MarketOracle
from market_screener import MarketScreener
from candle_service import CandleService
from planner_data_provider import PlannerDataProvider
from risk_manager import RiskManager
from position_state_engine import PositionStateEngine
from spot_planner import SpotPlannerEngine
from state_manager import StateManager
from strategy import SwingStrategy, apply_exchange_intel_filters_to_analysis
from ta_service import TAService
from trade_manager import TradeManager
from watch_engine import WatchEngine
from watchlist_builder import WatchlistBuilder
from validators import safe_float, safe_str


def _enrich_ta_data_with_screener(ta_data, symbols, screener):
    if screener is None:
        return ta_data

    enriched = dict(ta_data or {})

    for sym in symbols or []:
        key = safe_str(sym).upper()
        current = enriched.get(key)

        if not current:
            continue

        metrics = screener.get_symbol_metrics(key) if hasattr(screener, "get_symbol_metrics") else {}

        if metrics:
            merged = dict(current)

            live_price = merged.get("price")
            merged.update(metrics)

            if live_price is not None:
                merged["price"] = live_price

            enriched[key] = merged

    return enriched


async def pool_loop(state, screener, logger=None) -> None:
    next_rotation = time.time()

    while True:
        try:
            now = time.time()

            if now >= next_rotation:
                if hasattr(screener, "refresh_market_buckets"):
                    buckets = await screener.refresh_market_buckets()
                else:
                    raw = await screener.refresh()
                    buckets = {
                        "fut": raw if isinstance(raw, list) else [],
                        "spot": [],
                    }

                fut = list(buckets.get("fut", []))[: CONFIG.universe.fut_pool_size]
                spot = list(buckets.get("spot", []))[: CONFIG.universe.spot_pool_size]

                await state.set_pool("fut", fut)
                await state.set_pool("spot", spot)

                await state.add_sys_log("🧺 [POOL]", f"fut={fut} | spot={spot}")

                if logger:
                    logger.info("POOL", "pool rotated", {"fut": fut, "spot": spot})

                next_rotation = now + CONFIG.loops.pool_rotation_sec

            await state.update_timer(max(0, int(next_rotation - time.time())))
            await asyncio.sleep(1)

        except Exception as exc:
            await state.add_sys_log("❌ [POOL]", str(exc))
            if logger:
                logger.error("POOL", "pool loop failed", {"error": str(exc)})
            await asyncio.sleep(CONFIG.loops.safe_loop_backoff_sec)


async def system_metrics_loop(state, logger=None) -> None:
    started = time.time()

    while True:
        try:
            uptime_sec = int(time.time() - started)
            hh = uptime_sec // 3600
            mm = (uptime_sec % 3600) // 60
            ss = uptime_sec % 60
            uptime = f"{hh:02d}:{mm:02d}:{ss:02d}"

            await state.update_system_metrics(uptime, 0, 0)
            await asyncio.sleep(CONFIG.loops.system_metrics_sec)

        except Exception as exc:
            await state.add_sys_log("❌ [SYS]", str(exc))
            if logger:
                logger.error("SYS", "system metrics loop failed", {"error": str(exc)})
            await asyncio.sleep(CONFIG.loops.safe_loop_backoff_sec)


async def monitor_loop(state, logger=None) -> None:
    while True:
        try:
            dash = await state.get_dashboard_state()
            health = dash.get("market", {}).get("symbol_health", {}) or {}

            for sym, item in health.items():
                if item.get("status") != "OK":
                    await state.add_sys_log("⚠️ [MONITOR]", f"{sym} degraded | {item.get('error', 'unknown')}")
                    if logger:
                        logger.warning("MONITOR", "symbol degraded", {
                            "symbol": sym,
                            "error": item.get("error", "unknown"),
                        })

            await asyncio.sleep(CONFIG.loops.monitor_sec)

        except Exception as exc:
            await state.add_sys_log("❌ [MONITOR]", str(exc))
            if logger:
                logger.error("MONITOR", "monitor loop failed", {"error": str(exc)})
            await asyncio.sleep(CONFIG.loops.safe_loop_backoff_sec)


async def sync_router_loop(state, router, logger=None) -> None:
    while True:
        try:
            await state.sync_router_snapshot(router)
            await asyncio.sleep(CONFIG.loops.router_sync_sec)

        except Exception as exc:
            await state.add_sys_log("❌ [SYNC]", str(exc))
            if logger:
                logger.error("SYNC", "router sync failed", {"error": str(exc)})
            await asyncio.sleep(CONFIG.loops.safe_loop_backoff_sec)


async def planner_market_loop(state, provider, logger=None) -> None:
    while True:
        try:
            snapshot = await provider.build_snapshot()
            await state.update_planner_market_data(snapshot)

            count = len(snapshot.get("symbols", {}))
            await state.add_sys_log("🧠 [PLANNER]", f"market snapshot updated | symbols={count}")

            if logger:
                logger.info("PLANNER", "planner market snapshot updated", {"symbols": count})

        except Exception as exc:
            await state.add_sys_log("❌ [PLANNER]", f"market loop error | {exc}")
            if logger:
                logger.error("PLANNER", "planner market loop failed", {"error": str(exc)})

        await asyncio.sleep(CONFIG.loops.planner_market_sec)


async def planner_loop(state, planner_engine, logger=None) -> None:
    while True:
        try:
            dashboard = await state.get_dashboard_state()
            planner_market_data = dashboard.get("planner", {}).get("market_data", {})
            macro = dashboard.get("system", {}).get("macro", {})

            if not planner_market_data:
                await state.add_sys_log("⏳ [PLANNER]", "market data empty, waiting for snapshot")
                await asyncio.sleep(10)
                continue

            planner_payload = planner_engine.build(
                planner_market_data=planner_market_data,
                macro=macro,
            )

            await state.update_spot_planner(planner_payload)

            count = len(planner_payload.get("ideas", []))
            await state.add_sys_log("📘 [PLANNER]", f"ideas updated | count={count}")

            if logger:
                logger.info("PLANNER", "planner ideas updated", {"count": count})

        except Exception as exc:
            await state.add_sys_log("❌ [PLANNER]", f"planner loop error | {exc}")
            if logger:
                logger.error("PLANNER", "planner loop failed", {"error": str(exc)})

        await asyncio.sleep(CONFIG.loops.planner_sec)


async def watchlist_loop(state, watchlist_builder, watch_engine, screener=None, logger=None) -> None:
    while True:
        try:
            dash = await state.get_dashboard_state()

            ta_data = dash.get("market", {}).get("ta_data", {})
            fut_pool = dash.get("system", {}).get("fut_pool", [])
            spot_pool = dash.get("system", {}).get("spot_pool", [])
            macro_filter = dash.get("system", {}).get("macro", {}).get("global_filter", "allow_all")

            ta_data = _enrich_ta_data_with_screener(
                ta_data,
                list(fut_pool) + list(spot_pool),
                screener,
            )

            engine_items = watch_engine.snapshot()

            if engine_items:
                items = engine_items
            else:
                items = watchlist_builder.build(
                    ta_data=ta_data,
                    fut_pool=fut_pool,
                    spot_pool=spot_pool,
                    macro_filter=macro_filter,
                )

            await state.set_watchlist_mini(items)

            if logger:
                logger.info("WATCHLIST", "watchlist updated", {"count": len(items)})

        except Exception as exc:
            await state.add_sys_log("❌ [WATCHLIST]", str(exc))
            if logger:
                logger.error("WATCHLIST", "watchlist loop failed", {"error": str(exc)})

        await asyncio.sleep(CONFIG.loops.watchlist_sec)


async def strategy_loop(
    state,
    router,
    strategy,
    decision_engine,
    trade_logger,
    risk_manager,
    watch_engine,
    screener=None,
    logger=None,
    open_close_lock=None,
) -> None:
    while True:
        try:
            dash = await state.get_dashboard_state()

            ta_data = dash.get("market", {}).get("ta_data", {})
            fut_pool = dash.get("system", {}).get("fut_pool", [])
            spot_pool = dash.get("system", {}).get("spot_pool", [])
            macro_filter = dash.get("system", {}).get("macro", {}).get("global_filter", "allow_all")
            
            # ИНТЕГРАЦИЯ ПЛАНЕРА ДЛЯ СПОТА
            planner_state = dash.get("planner", {}).get("spot_planner", {}) or {}
            planner_map = {x.get("symbol"): x for x in planner_state.get("spot_ideas", []) if isinstance(x, dict)}

            ta_data = _enrich_ta_data_with_screener(
                ta_data,
                list(fut_pool) + list(spot_pool),
                screener,
            )

            risk_status = risk_manager.get_status()

            if not hasattr(strategy_loop, "_cooldown_prefilter_log_ts"):
                strategy_loop._cooldown_prefilter_log_ts = {}

            if risk_status["block_new_entries"]:
                msg = (
                    f"daily stop active | "
                    f"day={risk_status['daily_realized_pnl']:.4f} / "
                    f"limit={risk_status['daily_loss_limit_usdt']:.4f}"
                )

                await state.add_sys_log("🛑 [RISK]", msg)

                if logger:
                    logger.warning("RISK", "daily stop active", {
                        "daily_realized_pnl": risk_status["daily_realized_pnl"],
                        "daily_loss_limit_usdt": risk_status["daily_loss_limit_usdt"],
                    })

                await asyncio.sleep(CONFIG.loops.strategy_sec)
                continue

            current_fut_open_count = 1 if router.get_futures_position() is not None else 0
            current_spot_open_count = len(router.get_all_spot_positions())

            # 1) Scan futures
            for sym in fut_pool:
                current = ta_data.get(sym)

                if not current:
                    continue

                analysis = strategy.analyze_futures(current, macro_filter)

                if analysis.get("should_open"):
                    try:
                        can_preopen, preopen_reason = risk_manager.can_open(sym, "fut")
                    except Exception:
                        can_preopen, preopen_reason = True, ""

                    if (not can_preopen) and "cooldown after open" in safe_str(preopen_reason, "").lower():
                        try:
                            _now = time.time()
                            _key = f"{sym}::fut"
                            _log_map = getattr(strategy_loop, "_cooldown_prefilter_log_ts", {})
                            _last = float(_log_map.get(_key, 0.0) or 0.0)
                            _throttle_sec = 300.0
                            if logger and (_now - _last >= _throttle_sec):
                                logger.info("WATCH", "futures candidate skipped by cooldown prefilter", {
                                    "symbol": sym,
                                    "reason": preopen_reason,
                                    "setup_type": analysis.get("setup_type"),
                                    "score": analysis.get("score"),
                                    "throttle_sec": _throttle_sec,
                                })
                                _log_map[_key] = _now
                                strategy_loop._cooldown_prefilter_log_ts = _log_map
                        except Exception:
                            pass
                        continue

                    item = watch_engine.upsert_from_analysis(
                        symbol=sym,
                        market="fut",
                        current=current,
                        analysis=analysis,
                    )

                    if item:
                        await state.add_sys_log(
                            "👁 [FUT WATCH]",
                            f"{sym} {item.get('side')} {item.get('setup_type')} "
                            f"score={item.get('score')} trigger={safe_float(item.get('trigger_price')):.8f}",
                        )

                        if logger:
                            logger.info("WATCH", "futures candidate", item)

                else:
                    if logger:
                        logger.info("STRATEGY", "futures not watchable", {
                            "symbol": sym,
                            "reason": analysis.get("blocked_reason"),
                            "score": analysis.get("score"),
                            "setup_type": analysis.get("setup_type"),
                            "signal": analysis.get("signal"),
                        })

            # 2) Confirm futures
            try:
                current_fut_open_count = len(router.get_all_futures_positions())
            except Exception:
                current_fut_open_count = 1 if router.get_futures_position() is not None else 0

            if current_fut_open_count < risk_status["max_open_futures_positions"]:
                for item in watch_engine.confirmed_items(ta_data, market="fut"):
                    sym = safe_str(item.get("symbol")).upper()
                    current = ta_data.get(sym)

                    if not current:
                        continue

                    try:
                        if router.get_futures_position(sym) is not None:
                            watch_engine.remove(sym, "fut", safe_str(item.get("side")).upper())
                            continue
                    except TypeError:
                        pass
                    except Exception:
                        pass

                    side = safe_str(item.get("side")).upper()
                    analysis = {
                        "should_open": True,
                        "signal": side,
                        "setup_type": safe_str(item.get("setup_type")),
                        "score": safe_float(item.get("score"), 0.0),
                        "args_text": safe_str(item.get("args_text")),
                        "blocked_reason": "",
                        "trigger_price": safe_float(item.get("trigger_price"), 0.0),
                        "invalidation_price": safe_float(item.get("invalidation_price"), 0.0),
                    }

                    await state.add_sys_log(
                        "📥 FUT OPEN_ATTEMPT",
                        f"{sym} {side} confirmed -> decision | trigger={safe_float(item.get('trigger_price')):.8f}",
                    )

                    try:
                        current_fut_open_count = len(router.get_all_futures_positions())
                    except Exception:
                        current_fut_open_count = 1 if router.get_futures_position() is not None else 0

                    decision = decision_engine.evaluate(
                        symbol=sym,
                        market="fut",
                        analysis=analysis,
                        risk_manager=risk_manager,
                        current_open_count=current_fut_open_count,
                        max_open_positions=risk_status["max_open_futures_positions"],
                    )

                    if not decision["allow"]:
                        reason = safe_str(decision.get("reason"), "")
                        await state.add_sys_log("⚠️ [FUT WATCH]", f"{sym} confirmation blocked | {reason}")

                        if logger:
                            logger.info("WATCH", "futures confirmation blocked", {
                                "symbol": sym,
                                "reason": reason,
                                "analysis": analysis,
                                "watch": item,
                            })

                        if "cooldown after open" in reason.lower():
                            try:
                                watch_engine.remove(sym, "fut", side)
                                await state.add_sys_log("🧊 [FUT WATCH]", f"{sym} removed from watchlist during cooldown | {reason}")
                                if logger:
                                    logger.info("WATCH", "cooldown watch item removed", {
                                        "symbol": sym,
                                        "side": side,
                                        "reason": reason,
                                    })
                            except Exception as exc:
                                if logger:
                                    logger.warning("WATCH", "cooldown watch cleanup failed", {
                                        "symbol": sym,
                                        "side": side,
                                        "error": str(exc),
                                    })

                        continue

                    price = safe_float(current.get("price"), 0.0)
                    atr_abs = safe_float(current.get("atr"), 0.0)

                    if price <= 0 or atr_abs <= 0 or side not in {"LONG", "SHORT"}:
                        if logger:
                            logger.warning("WATCH", "invalid confirmed futures params", {
                                "symbol": sym,
                                "price": price,
                                "atr": atr_abs,
                                "side": side,
                            })

                        continue

                    atr_pct = (atr_abs / price * 100.0) if price > 0 else 0.0
                    max_entry_atr_pct = safe_float(getattr(CONFIG.strategy, "max_bad_atr_pct", 4.0), 4.0)
                    if atr_pct > max_entry_atr_pct:
                        await state.add_sys_log(
                            "⚠️ [FUT BLOCK]",
                            f"{sym} blocked | ATR too high {atr_pct:.2f}% > {max_entry_atr_pct:.2f}%",
                        )
                        if logger:
                            logger.info("RISK", "futures atr cap blocked", {
                                "symbol": sym,
                                "atr_pct": round(atr_pct, 4),
                                "max_entry_atr_pct": max_entry_atr_pct,
                                "setup_type": analysis.get("setup_type"),
                            })
                        watch_engine.remove(sym, "fut", side)
                        continue

                    ladder = strategy.calculate_futures_trade(
                        price=price,
                        side=side,
                        atr=atr_abs,
                        setup_type=analysis.get("setup_type"),
                    )

                    qty = CONFIG.trading.futures_margin_usdt / price

                    result = {"code": "LOCKED_NOT_RUN"}
                    opened = False
                    lock = open_close_lock or asyncio.Lock()
                    async with lock:
                        try:
                            current_fut_open_count = len(router.get_all_futures_positions())
                        except Exception:
                            current_fut_open_count = 1 if router.get_futures_position() is not None else 0

                        if current_fut_open_count < risk_status.get("max_open_futures_positions", 1):
                            risk_status_locked = risk_manager.get_status()
                            decision_locked = decision_engine.evaluate(
                                symbol=sym,
                                market="fut",
                                analysis=analysis,
                                risk_manager=risk_manager,
                                current_open_count=current_fut_open_count,
                                max_open_positions=risk_status_locked["max_open_futures_positions"],
                            )
                            if not decision_locked["allow"]:
                                result = {"code": "LOCKED_BLOCKED", "reason": decision_locked["reason"]}
                                await state.add_sys_log("⚠️ [FUT WATCH]", f"{sym} locked confirmation blocked | {decision_locked['reason']}")
                                if logger:
                                    logger.info("WATCH", "futures locked confirmation blocked", {
                                        "symbol": sym,
                                        "reason": decision_locked["reason"],
                                        "analysis": analysis,
                                        "watch": item,
                                    })
                            else:
                                result = router.open_futures_position(
                                    symbol=sym,
                                    side=side,
                                    qty=qty,
                                    price=price,
                                    tp0=ladder.get("tp0"),
                                    tp=ladder.get("tp"),
                                    tp2=ladder.get("tp2"),
                                    sl=ladder.get("sl"),
                                    atr=atr_abs,
                                    leverage=ladder.get("leverage", 3.0),
                                    setup_type=safe_str(analysis.get("setup_type")),
                                    args_text=safe_str(analysis.get("args_text")),
                                )

                                if result.get("code") == "00000":
                                    risk_manager.register_open(sym, "fut")
                                    watch_engine.remove(sym, "fut", side)
                                    opened = True
                        else:
                            result = {"code": "MAX_FUTURES_POSITIONS_REACHED"}

                    if opened:
                        open_msg = (
                            f"{sym} {side} {analysis['setup_type']} @ {price:.8f} | "
                            f"confirmed={safe_str(item.get('confirmation_reason'))} | "
                            f"{analysis['args_text']}"
                        )

                        await state.add_sys_log("🟢 [FUT OPEN]", open_msg)

                        if logger:
                            logger.info("STRATEGY", "futures opened from watch", {
                                "symbol": sym,
                                "side": side,
                                "setup_type": analysis.get("setup_type"),
                                "price": price,
                                "score": analysis.get("score"),
                                "tp": ladder["tp"],
                                "sl": ladder["sl"],
                                "watch": item,
                            })

                        trade_logger.log_trade(
                            symbol=sym,
                            side=side,
                            market="FUT",
                            entry=result["data"]["entry"],
                            tp=ladder["tp"],
                            exit_price=0.0,
                            pnl=0.0,
                            pnl_net=0.0,
                            reason="OPEN",
                            hold_sec=0,
                            setup_type=safe_str(analysis.get("setup_type")),
                            args_text=safe_str(analysis.get("args_text")),
                        )

                        current_fut_open_count += 1

                        if current_fut_open_count >= risk_status["max_open_futures_positions"]:
                            break

                    else:
                        await state.add_sys_log("⚠️ [FUT OPEN_REJECT]", f"{sym} rejected | {result}")
                        if logger:
                            logger.warning("STRATEGY", "futures open rejected", {
                                "symbol": sym,
                                "result": result,
                            })

            # 3) Scan spot: strong LONG-only setups go to WATCH.
            for sym in spot_pool:
                if router.get_spot_position(sym) is not None:
                    continue

                current = ta_data.get(sym)

                if not current:
                    continue

                # ИНТЕГРАЦИЯ ПЛАНЕРА ДЛЯ АНАЛИЗА
                analysis = strategy.analyze_spot(current, macro_filter, planner_idea=planner_map.get(sym))

                if analysis.get("should_open"):
                    item = watch_engine.upsert_from_analysis(
                        symbol=sym,
                        market="spot",
                        current=current,
                        analysis=analysis,
                    )

                    if item:
                        await state.add_sys_log(
                            "👁 [SPOT WATCH]",
                            f"{sym} BUY {item.get('setup_type')} "
                            f"score={item.get('score')} trigger={safe_float(item.get('trigger_price')):.8f}",
                        )

                        if logger:
                            logger.info("WATCH", "spot candidate", item)

                else:
                    if logger:
                        logger.info("STRATEGY", "spot not watchable", {
                            "symbol": sym,
                            "reason": analysis.get("blocked_reason"),
                            "score": analysis.get("score"),
                            "setup_type": analysis.get("setup_type"),
                            "signal": analysis.get("signal"),
                        })

            # 4) Confirm spot: only confirmed WATCH candidates open Entry 1.
            if current_spot_open_count < risk_status["max_open_spot_positions"]:
                for item in watch_engine.confirmed_items(ta_data, market="spot"):
                    sym = safe_str(item.get("symbol")).upper()

                    if router.get_spot_position(sym) is not None:
                        watch_engine.remove(sym, "spot")
                        continue

                    current = ta_data.get(sym)

                    if not current:
                        continue
                        
                    # ИНТЕГРАЦИЯ ПЛАНЕРА ДЛЯ ПОДТВЕРЖДЕНИЯ
                    analysis = strategy.analyze_spot(current, macro_filter, planner_idea=planner_map.get(sym))

                    decision = decision_engine.evaluate(
                        symbol=sym,
                        market="spot",
                        analysis=analysis,
                        risk_manager=risk_manager,
                        current_open_count=current_spot_open_count,
                        max_open_positions=risk_status["max_open_spot_positions"],
                    )

                    if not decision["allow"]:
                        await state.add_sys_log("⚠️ [SPOT WATCH]", f"{sym} confirmation blocked | {decision['reason']}")

                        if logger:
                            logger.info("WATCH", "spot confirmation blocked", {
                                "symbol": sym,
                                "reason": decision["reason"],
                                "analysis": analysis,
                                "watch": item,
                            })

                        continue

                    price = safe_float(current.get("price"), 0.0)
                    atr_abs = safe_float(current.get("atr"), 0.0)

                    if price <= 0 or atr_abs <= 0:
                        if logger:
                            logger.warning("WATCH", "invalid confirmed spot params", {
                                "symbol": sym,
                                "price": price,
                                "atr": atr_abs,
                            })

                        continue

                    ladder = strategy.calculate_spot_ladder(
                        price=price,
                        atr=atr_abs,
                        setup_type=analysis.get("setup_type"),
                    )

                    # ИНТЕГРАЦИЯ ПЛАНЕРА ДЛЯ TP И ФИКСАЦИЯ НА 10 USDT
                    tp = safe_float(analysis.get("tp_base")) if analysis.get("setup_type") == "planner_spot" else ladder["tp"]
                    order_usdt = 10.0  # Фиксированный объем 10 USDT для спота
                    qty = order_usdt / price

                    result = router.open_spot_position(
                        symbol=sym,
                        qty=qty,
                        price=price,
                        tp=tp,
                        atr=atr_abs,
                        setup_type=safe_str(analysis.get("setup_type")),
                        args_text=safe_str(analysis.get("args_text")),
                    )

                    if result.get("code") == "00000":
                        risk_manager.register_open(sym, "spot")
                        watch_engine.remove(sym, "spot")

                        open_msg = (
                            f"{sym} BUY {analysis['setup_type']} @ {price:.8f} | "
                            f"entry1={order_usdt:.2f} USDT | "
                            f"confirmed={safe_str(item.get('confirmation_reason'))} | "
                            f"{analysis['args_text']}"
                        )

                        await state.add_sys_log("🟢 [SPOT OPEN]", open_msg)

                        if logger:
                            logger.info("STRATEGY", "spot opened from watch", {
                                "symbol": sym,
                                "setup_type": analysis.get("setup_type"),
                                "price": price,
                                "score": analysis.get("score"),
                                "tp": tp,
                                "order_usdt": order_usdt,
                                "watch": item,
                            })

                        trade_logger.log_trade(
                            symbol=sym,
                            side="BUY",
                            market="SPOT",
                            entry=result["data"]["entry"],
                            tp=tp,
                            exit_price=0.0,
                            pnl=0.0,
                            pnl_net=0.0,
                            reason="OPEN",
                            hold_sec=0,
                            setup_type=safe_str(analysis.get("setup_type")),
                            args_text=safe_str(analysis.get("args_text")),
                        )

                        current_spot_open_count += 1

                        if current_spot_open_count >= risk_status["max_open_spot_positions"]:
                            break

                    else:
                        if logger:
                            logger.warning("STRATEGY", "spot open rejected", {
                                "symbol": sym,
                                "result": result,
                            })

        except Exception as exc:
            await state.add_sys_log("❌ [STRATEGY]", str(exc))
            if logger:
                logger.error("STRATEGY", "strategy loop failed", {"error": str(exc)})

        await asyncio.sleep(CONFIG.loops.strategy_sec)


async def trade_manager_loop(state, router, trade_manager, trade_logger, risk_manager, logger=None, open_close_lock=None) -> None:
    while True:
        try:
            await trade_manager.loop(
                state=state,
                router=router,
                trade_logger=trade_logger,
                risk_manager=risk_manager,
                open_close_lock=open_close_lock,
            )

        except Exception as exc:
            await state.add_sys_log("❌ [TRADE_MANAGER]", str(exc))
            if logger:
                logger.error("TRADE_MANAGER", "trade manager loop failed", {"error": str(exc)})

        await asyncio.sleep(CONFIG.loops.execution_sec)



async def exchange_intel_loop(session, state, logger, exchange_intel):
    while True:
        try:
            dash = await state.get_dashboard() if hasattr(state, "get_dashboard") else {}
            fut_pool = dash.get("system", {}).get("fut_pool", []) or []
            if not fut_pool and hasattr(state, "dashboard"):
                fut_pool = state.dashboard.get("system", {}).get("fut_pool", []) or []
            await exchange_intel.update_all(session, fut_pool)
            try:
                await state.add_sys_log("🧠 EX_INTEL", f"updated {len(fut_pool)} futures symbols", extra={"count": len(fut_pool)})
            except TypeError:
                await state.add_sys_log("🧠 EX_INTEL", f"updated {len(fut_pool)} futures symbols")
        except Exception as exc:
            if logger:
                logger.warning("EX_INTEL", "exchange intelligence loop error", {"error": str(exc)[:240]})
        await asyncio.sleep(int(getattr(getattr(CONFIG, "exchange_intel", None), "update_sec", 60)))


async def main() -> None:
    logger = Logger()
    exchange_intel = ExchangeIntelligenceService(getattr(CONFIG, "exchange_intel", None), logger=logger)

    logger.info("BOOT", "starting VORTEX core", {})

    state = StateManager()
    await state.set_mode(CONFIG.trading.mode)

    screener = MarketScreener(logger=logger)
    data = MarketDataStream(state, logger=logger)
    oracle = MarketOracle(state, logger=logger)
    candle_service = CandleService(state, logger=logger)
    ta_service = TAService(state, candle_service=candle_service, logger=logger)

    strategy = SwingStrategy()
    decision_engine = DecisionEngine(logger=logger)
    watchlist_builder = WatchlistBuilder(strategy=strategy, logger=logger)
    watch_engine = WatchEngine(logger=logger)

    risk_manager = RiskManager()
    router = ExecutionRouter(mode=CONFIG.trading.mode)
    open_close_lock = asyncio.Lock()

    position_state_engine = PositionStateEngine(logger=logger)
    trade_manager = TradeManager(logger=logger, position_state_engine=position_state_engine)

    planner_provider = PlannerDataProvider(logger=logger)
    planner_engine = SpotPlannerEngine(logger=logger)

    api = APIServer(
        state_manager=state,
        execution_router=router,
        risk_manager=risk_manager,
        position_state_engine=position_state_engine,
        screener=screener,
        logger=logger,
        mode=CONFIG.trading.mode,
    )

    logger.info("BOOT", "all services initialized", {})

    tasks = [
        create_task(data.loop(), name="market_data"),
        create_task(pool_loop(state, screener, logger=logger), name="pool"),
        create_task(oracle.loop(), name="oracle"),
        create_task(candle_service.loop(), name="candles"),
        create_task(ta_service.loop(), name="ta"),
        create_task(system_metrics_loop(state, logger=logger), name="system_metrics"),
        create_task(monitor_loop(state, logger=logger), name="monitor"),
        create_task(sync_router_loop(state, router, logger=logger), name="router_sync"),
        create_task(planner_market_loop(state, planner_provider, logger=logger), name="planner_market"),
        create_task(planner_loop(state, planner_engine, logger=logger), name="planner"),
        create_task(
            watchlist_loop(
                state,
                watchlist_builder,
                watch_engine,
                screener=screener,
                logger=logger,
            ),
            name="watchlist",
        ),
        create_task(
            strategy_loop(
                state=state,
                router=router,
                strategy=strategy,
                decision_engine=decision_engine,
                trade_logger=logger,
                risk_manager=risk_manager,
                watch_engine=watch_engine,
                screener=screener,
                logger=logger,
                open_close_lock=open_close_lock,
            ),
            name="strategy",
        ),
        create_task(
            trade_manager_loop(
                state=state,
                router=router,
                trade_manager=trade_manager,
                trade_logger=logger,
                risk_manager=risk_manager,
                logger=logger,
                open_close_lock=open_close_lock,
            ),
            name="trade_manager",
        ),
        create_task(api.start(port=CONFIG.server.port), name="api"),
    ]

    try:
        await asyncio.gather(*tasks)

    except asyncio.CancelledError:
        logger.warning("BOOT", "main cancelled", {})
        raise

    except Exception as exc:
        logger.error("BOOT", "fatal main error", {"error": str(exc)})
        raise


if __name__ == "__main__":
    asyncio.run(main())