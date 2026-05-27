import asyncio
import time

from api_server import APIServer
from config import CONFIG
from exchange_intelligence import ExchangeIntelligenceService
from decision_engine import DecisionEngine
from defensive_gates import DefensiveGates
from trade_snapshot_recorder import TradeSnapshotRecorder
from execution_router import ExecutionRouter
from logger import Logger
from market_heatmap import market_heatmap_loop
from setup_zone import setup_zone_loop
from context_fusion import context_fusion_loop
from ichimoku_context import ichimoku_context_loop
from macro_regime_engine import macro_regime_loop
from pump_short_advisor import pump_short_advisor_loop
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
from strategy_observer import strategy_observer_loop
from ta_service import TAService
from trade_manager import TradeManager
from watch_engine import WatchEngine
from watchlist_builder import WatchlistBuilder
from confirmation_engine import ConfirmationEngine
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
            # v1.8.7b planner dynamic universe
            try:
                dash = await state.get_dashboard_state()
                system = dash.get("system", {}) or {}
                fut_pool = list(system.get("fut_pool", []) or [])
                spot_pool = list(system.get("spot_pool", []) or [])
                base_universe = list(getattr(CONFIG.planner, "snapshot_universe", []) or [])

                dynamic_enabled = bool(getattr(CONFIG.planner, "dynamic_universe_from_pool", True))
                dynamic_limit = int(getattr(CONFIG.planner, "dynamic_universe_limit", 40) or 40)
                include_spot = bool(getattr(CONFIG.planner, "dynamic_universe_include_spot", True))

                if dynamic_enabled:
                    merged = []
                    seen = set()

                    for sym in fut_pool:
                        key = safe_str(sym).upper()
                        if key and key not in seen:
                            merged.append(key)
                            seen.add(key)
                        if len(merged) >= dynamic_limit:
                            break

                    if include_spot and len(merged) < dynamic_limit:
                        for sym in spot_pool:
                            key = safe_str(sym).upper()
                            if key and key not in seen:
                                merged.append(key)
                                seen.add(key)
                            if len(merged) >= dynamic_limit:
                                break

                    if len(merged) < min(18, dynamic_limit):
                        for sym in base_universe:
                            key = safe_str(sym).upper()
                            if key and key not in seen:
                                merged.append(key)
                                seen.add(key)
                            if len(merged) >= dynamic_limit:
                                break

                    if merged:
                        provider.universe = merged

                    if logger:
                        logger.info("PLANNER_PROVIDER", "dynamic universe updated", {
                            "count": len(getattr(provider, "universe", []) or []),
                            "limit": dynamic_limit,
                            "from_fut_pool": len(fut_pool),
                            "from_spot_pool": len(spot_pool),
                            "preview": list(getattr(provider, "universe", []) or [])[:25],
                        })
            except Exception as exc:
                if logger:
                    logger.warning("PLANNER_PROVIDER", "dynamic universe update failed; static universe kept", {
                        "error": str(exc),
                    })

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

            # v1.8.7c atomic watchlist swap:
            # never replace a non-empty watchlist with temporary empty output during pool/TA refresh.
            previous_items = dash.get("terminal", {}).get("watchlist_mini", []) or []
            built_count = len(items)

            if not items and previous_items:
                items = previous_items
                if logger:
                    logger.warning("WATCHLIST", "empty watchlist build skipped; previous snapshot preserved", {
                        "previous_count": len(previous_items),
                        "built_count": built_count,
                        "fut_pool_count": len(fut_pool or []),
                        "spot_pool_count": len(spot_pool or []),
                        "ta_count": len(ta_data or {}),
                    })

            await state.set_watchlist_mini(items)

            if logger:
                meta = {}
                try:
                    latest_dash = await state.get_dashboard_state()
                    meta = latest_dash.get("terminal", {}).get("watchlist_meta", {}) or {}
                except Exception:
                    meta = {}

                actual_count = len(items)
                try:
                    actual_count = len((latest_dash.get("terminal", {}) or {}).get("watchlist_mini", []) or [])
                except Exception:
                    pass

                logger.info("WATCHLIST", "watchlist updated", {
                    "count": actual_count,
                    "built_count": built_count,
                    "preserved_previous": bool(meta.get("preserved_previous", False)),
                    "watchlist_source": meta.get("source", "fresh"),
                    "restored_count": meta.get("restored_count", 0),
                    "authority_instance_id": meta.get("authority_instance_id", ""),
                })

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
    confirmation_engine,
    defensive_gates,
    screener=None,
    logger=None,
    open_close_lock=None,
    trade_snapshot_recorder=None,
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

                    blocked_cross, cross_reason = defensive_gates.has_opposite_market_exposure(sym, "fut", router, watch_engine)
                    if blocked_cross:
                        if logger:
                            logger.info("DEFENSE", "futures candidate blocked by cross-market exposure", {
                                "symbol": sym,
                                "reason": cross_reason,
                                "setup_type": analysis.get("setup_type"),
                                "score": analysis.get("score"),
                            })
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
                for item in confirmation_engine.confirmed_futures_items(watch_engine, ta_data):
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

                        if defensive_gates.should_remove_ready_after_block(reason):
                            try:
                                watch_engine.remove(sym, "fut", side)
                                await state.add_sys_log("🧯 [FUT WATCH]", f"{sym} removed from ready watch | {reason}")
                                if logger:
                                    logger.info("DEFENSE", "ready futures watch removed after defensive block", {
                                        "symbol": sym,
                                        "side": side,
                                        "reason": reason,
                                    })
                            except Exception as exc:
                                if logger:
                                    logger.warning("DEFENSE", "ready futures watch remove failed", {
                                        "symbol": sym,
                                        "side": side,
                                        "error": str(exc),
                                    })
                            continue

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

                    # VORTEX v1.8.20a: shadow-only Entry Argument Engine.
                    # It builds a proof chain for the confirmed entry without blocking execution yet.
                    try:
                        from entry_argument_engine import evaluate_and_record_entry_argument

                        entry_argument = evaluate_and_record_entry_argument(
                            symbol=sym,
                            side=side,
                            setup_type=safe_str(analysis.get("setup_type")),
                            analysis=analysis,
                            current=current,
                            ladder=ladder,
                            macro_filter=macro_filter,
                            watch=item,
                        )

                        analysis["entry_argument"] = entry_argument

                        entry_summary = safe_str(entry_argument.get("summary"), "")
                        if entry_summary:
                            base_args = safe_str(analysis.get("args_text"), "")
                            if entry_summary not in base_args:
                                analysis["args_text"] = (base_args + " | " + entry_summary).strip(" |")

                        if logger:
                            logger.info("ENTRY_ARGUMENT", "futures entry argument shadow", {
                                "symbol": sym,
                                "side": side,
                                "setup_type": safe_str(analysis.get("setup_type")),
                                "entry_grade": entry_argument.get("entry_grade"),
                                "confidence": entry_argument.get("confidence"),
                                "decision": entry_argument.get("decision"),
                                "arguments_for": entry_argument.get("arguments_for", [])[:6],
                                "arguments_against": entry_argument.get("arguments_against", [])[:6],
                            })
                    except Exception as exc:
                        if logger:
                            logger.warning("ENTRY_ARGUMENT", "entry argument shadow failed open", {
                                "symbol": sym,
                                "side": side,
                                "setup_type": safe_str(analysis.get("setup_type")),
                                "error": str(exc),
                            })

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

                            # VORTEX v1.8.19j-r2: post-close cooldown + pre-open guards.
                            # This mutates decision_locked before the existing block branch.
                            if decision_locked.get("allow"):
                                try:
                                    from post_close_cooldown import can_open_futures
                                    guard_decision = can_open_futures(
                                        symbol=sym,
                                        side=side,
                                        setup_type=safe_str(analysis.get("setup_type")),
                                        analysis=analysis,
                                        price=price,
                                        ladder=ladder,
                                    )
                                except Exception as exc:
                                    guard_decision = {"allow": True, "reason": f"guard_error_fail_open:{exc}"}
                                    if logger:
                                        logger.warning("RISK", "futures pre-open guard failed open", {
                                            "symbol": sym,
                                            "error": str(exc),
                                        })

                                if not guard_decision.get("allow", True):
                                    decision_locked = {
                                        "allow": False,
                                        "reason": guard_decision.get("reason", "pre_open_guard_blocked"),
                                    }
                                    if logger:
                                        logger.info("RISK", "futures pre-open guard blocked", {
                                            "symbol": sym,
                                            "side": side,
                                            "setup_type": safe_str(analysis.get("setup_type")),
                                            "reason": decision_locked["reason"],
                                            "guard": guard_decision,
                                        })

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

                        if trade_snapshot_recorder:
                            try:
                                trade_snapshot_recorder.record_open(
                                    symbol=sym,
                                    market="FUT",
                                    side=side,
                                    result=result,
                                    current=current,
                                    analysis=analysis,
                                    watch=item,
                                    planner_idea=planner_map.get(sym),
                                    ladder=ladder,
                                    risk_status=risk_status,
                                    macro_filter=macro_filter,
                                    order={
                                        "qty": qty,
                                        "entry": result["data"].get("entry"),
                                        "margin_usdt": CONFIG.trading.futures_margin_usdt,
                                        "leverage": ladder.get("leverage", 3.0),
                                    },
                                )
                            except Exception as exc:
                                if logger:
                                    logger.warning("ANALYTICS", "futures snapshot record failed", {
                                        "symbol": sym,
                                        "error": str(exc),
                                    })

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
                planner_idea = planner_map.get(sym)
                analysis = strategy.analyze_spot(current, macro_filter, planner_idea=planner_idea)

                spot_ok, spot_reason = defensive_gates.spot_planner_gate(sym, planner_idea, analysis)
                if not spot_ok:
                    if logger:
                        logger.info("DEFENSE", "spot candidate blocked by planner discipline", {
                            "symbol": sym,
                            "reason": spot_reason,
                            "setup_type": analysis.get("setup_type"),
                            "score": analysis.get("score"),
                        })
                    continue

                blocked_cross, cross_reason = defensive_gates.has_opposite_market_exposure(sym, "spot", router, watch_engine)
                if blocked_cross:
                    if logger:
                        logger.info("DEFENSE", "spot candidate blocked by cross-market exposure", {
                            "symbol": sym,
                            "reason": cross_reason,
                            "setup_type": analysis.get("setup_type"),
                            "score": analysis.get("score"),
                        })
                    continue

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
                for item in confirmation_engine.confirmed_spot_items(watch_engine, ta_data, planner_map):
                    sym = safe_str(item.get("symbol")).upper()

                    if router.get_spot_position(sym) is not None:
                        watch_engine.remove(sym, "spot")
                        continue

                    current = ta_data.get(sym)

                    if not current:
                        continue
                        
                    # ИНТЕГРАЦИЯ ПЛАНЕРА ДЛЯ ПОДТВЕРЖДЕНИЯ
                    planner_idea = planner_map.get(sym)
                    spot_ok, spot_reason = defensive_gates.spot_planner_gate(sym, planner_idea, item)
                    if not spot_ok:
                        await state.add_sys_log("⚠️ [SPOT WATCH]", f"{sym} defensive block | {spot_reason}")
                        if logger:
                            logger.info("DEFENSE", "spot confirmation blocked by planner discipline", {
                                "symbol": sym,
                                "reason": spot_reason,
                                "watch": item,
                            })
                        try:
                            watch_engine.remove(sym, "spot")
                        except Exception:
                            pass
                        continue

                    blocked_cross, cross_reason = defensive_gates.has_opposite_market_exposure(sym, "spot", router, watch_engine)
                    if blocked_cross:
                        await state.add_sys_log("⚠️ [SPOT WATCH]", f"{sym} defensive block | {cross_reason}")
                        if logger:
                            logger.info("DEFENSE", "spot confirmation blocked by cross-market exposure", {
                                "symbol": sym,
                                "reason": cross_reason,
                                "watch": item,
                            })
                        try:
                            watch_engine.remove(sym, "spot")
                        except Exception:
                            pass
                        continue

                    analysis = strategy.analyze_spot(current, macro_filter, planner_idea=planner_idea)

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
                    order_usdt = CONFIG.trading.spot_order_usdt  # audit-fix: use config value
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

                        if trade_snapshot_recorder:
                            try:
                                trade_snapshot_recorder.record_open(
                                    symbol=sym,
                                    market="SPOT",
                                    side="BUY",
                                    result=result,
                                    current=current,
                                    analysis=analysis,
                                    watch=item,
                                    planner_idea=planner_map.get(sym),
                                    ladder={"tp": tp, "sl": ladder.get("sl"), "tp2": ladder.get("tp2")},
                                    risk_status=risk_status,
                                    macro_filter=macro_filter,
                                    order={
                                        "qty": qty,
                                        "entry": result["data"].get("entry"),
                                        "order_usdt": order_usdt,
                                    },
                                )
                            except Exception as exc:
                                if logger:
                                    logger.warning("ANALYTICS", "spot snapshot record failed", {
                                        "symbol": sym,
                                        "error": str(exc),
                                    })

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
    confirmation_engine = ConfirmationEngine()
    defensive_gates = DefensiveGates()

    risk_manager = RiskManager()
    router = ExecutionRouter(mode=CONFIG.trading.mode)
    open_close_lock = asyncio.Lock()

    position_state_engine = PositionStateEngine(logger=logger)
    trade_manager = TradeManager(logger=logger, position_state_engine=position_state_engine)
    trade_snapshot_recorder = TradeSnapshotRecorder(logger=logger)

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
        # --- VORTEX v1.8.21l-c ICHIMOKU CONTEXT TASK ---
        create_task(
            ichimoku_context_loop(
                state=state,
                candle_service=candle_service,
                logger=logger,
            ),
            name="ichimoku_context",
        ),
        # --- END VORTEX v1.8.21l-c ICHIMOKU CONTEXT TASK ---
        # --- VORTEX v1.8.21l-f-r2 MACRO REGIME TASK ---
        create_task(
            macro_regime_loop(
                state=state,
                logger=logger,
            ),
            name="macro_regime",
        ),
        # --- END VORTEX v1.8.21l-f-r2 MACRO REGIME TASK ---
        # --- VORTEX v1.8.21m-a PUMP SHORT ADVISOR TASK ---
        create_task(
            pump_short_advisor_loop(
                state=state,
                candle_service=candle_service,
                logger=logger,
            ),
            name="pump_short_advisor",
        ),
        # --- END VORTEX v1.8.21m-a PUMP SHORT ADVISOR TASK ---
        # --- VORTEX v1.8.21k-a MARKET HEATMAP TASK ---
        create_task(
            market_heatmap_loop(
                state=state,
                logger=logger,
            ),
            name="market_heatmap",
        ),
        # --- END VORTEX v1.8.21k-a MARKET HEATMAP TASK ---
        # --- VORTEX v1.8.21k-b SETUP ZONE TASK ---
        create_task(
            setup_zone_loop(
                state=state,
                logger=logger,
            ),
            name="setup_zone",
        ),
        # --- END VORTEX v1.8.21k-b SETUP ZONE TASK ---
        # --- VORTEX v1.8.21k-c CONTEXT FUSION TASK ---
        create_task(
            context_fusion_loop(
                state=state,
                logger=logger,
            ),
            name="context_fusion",
        ),
        # --- END VORTEX v1.8.21k-c CONTEXT FUSION TASK ---
        # --- VORTEX v1.8.21i-a STRATEGY OBSERVER TASK ---
        create_task(
            strategy_observer_loop(
                state=state,
                strategy=strategy,
                logger=logger,
            ),
            name="strategy_observer",
        ),
        # --- END VORTEX v1.8.21i-a STRATEGY OBSERVER TASK ---
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
                confirmation_engine=confirmation_engine,
                defensive_gates=defensive_gates,
                screener=screener,
                logger=logger,
                open_close_lock=open_close_lock,
                trade_snapshot_recorder=trade_snapshot_recorder,
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