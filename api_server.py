import asyncio
import json
from typing import Any, Dict, List

from aiohttp import web
import aiohttp_cors

from config import CONFIG
from validators import safe_float, safe_int, safe_str
from trade_history import build_history, build_stats


class APIServer:
    def __init__(
        self,
        state_manager,
        execution_router=None,
        risk_manager=None,
        position_state_engine=None,
        screener=None,
        logger=None,
        mode: str = "PAPER",
    ):
        self.state = state_manager
        self.router = execution_router
        self.risk_manager = risk_manager
        self.position_state_engine = position_state_engine
        self.screener = screener
        self.logger = logger
        self.mode = safe_str(mode, "PAPER").upper()
        self.app = web.Application()

        cors = aiohttp_cors.setup(
            self.app,
            defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*",
                )
            },
        )

        routes = [
            self.app.router.add_get("/api/dashboard", self.handle_dashboard),
            self.app.router.add_get("/api/history", self.handle_history),
            self.app.router.add_get("/api/health", self.handle_health),
            self.app.router.add_get("/api/mobile_history", self.handle_mobile_history),
            self.app.router.add_get("/api/spot-planner", self.handle_spot_planner),
            self.app.router.add_get("/api/watchlist", self.handle_watchlist),
            self.app.router.add_get("/api/logs", self.handle_logs),
            self.app.router.add_get("/api/positions/state", self.handle_positions_state),
            self.app.router.add_get("/api/debug/screener", self.handle_debug_screener),
            self.app.router.add_get("/api/history", self.handle_history),
            self.app.router.add_get("/api/stats", self.handle_stats),
            self.app.router.add_get("/api/intelligence", self.handle_intelligence),
        ]

        if CONFIG.trading.debug_api_enabled:
            routes.extend([
                self.app.router.add_get("/api/debug/runtime", self.handle_debug_runtime),
                self.app.router.add_get("/api/debug/test-config", self.handle_debug_test_config),
                self.app.router.add_post("/api/debug/open-futures", self.handle_debug_open_futures),
                self.app.router.add_post("/api/debug/close-futures", self.handle_debug_close_futures),
                self.app.router.add_post("/api/debug/force-fut-price", self.handle_debug_force_fut_price),
                self.app.router.add_post("/api/debug/open-spot", self.handle_debug_open_spot),
                self.app.router.add_post("/api/debug/close-spot", self.handle_debug_close_spot),
                self.app.router.add_post("/api/debug/close-all-spot", self.handle_debug_close_all_spot),
                self.app.router.add_post("/api/debug/risk/reset", self.handle_debug_risk_reset),
                self.app.router.add_get("/api/debug/risk/status", self.handle_debug_risk_status),
                self.app.router.add_post("/api/debug/state/reload", self.handle_debug_state_reload),
                self.app.router.add_get("/api/debug/logs/tail", self.handle_debug_logs_tail),
            ])

        for route in routes:
            cors.add(route)

    async def _build_dashboard_payload(self) -> Dict[str, Any]:
        dashboard = await self.state.get_dashboard_state()

        fut_positions = dashboard.get("positions", {}).get("fut", {}) or {}
        spot_positions = dashboard.get("positions", {}).get("spot", {}) or {}
        balances = dashboard.get("account", {}).get("balances", {}) or {}

        dashboard["today"] = {
            "today_realized_fut": 0.0,
            "today_realized_spot": 0.0,
            "today_total_realized": 0.0,
            "today_open_fut": round(sum(safe_float(p.get("pnl_net", 0.0)) for p in fut_positions.values()), 4),
            "today_open_spot": round(sum(safe_float(p.get("pnl_net", 0.0)) for p in spot_positions.values()), 4),
            "today_total_open": round(
                sum(safe_float(p.get("pnl_net", 0.0)) for p in fut_positions.values())
                + sum(safe_float(p.get("pnl_net", 0.0)) for p in spot_positions.values()),
                4,
            ),
        }

        spot_free = safe_float(balances.get("spot", 0.0))
        fut_free = safe_float(balances.get("fut", 0.0))

        spot_open_pnl = sum(safe_float(p.get("pnl_net", 0.0)) for p in spot_positions.values())
        fut_open_pnl = sum(safe_float(p.get("pnl_net", 0.0)) for p in fut_positions.values())

        # Paper futures balance is FREE balance after reserved margin.
        # Equity must add reserved margin back, otherwise the UI shows
        # a false drawdown equal to locked margin while a position is open.
        fut_margin_used = sum(safe_float(p.get("margin", 0.0)) for p in fut_positions.values())
        fut_notional_open = sum(safe_float(p.get("notional", 0.0)) for p in fut_positions.values())

        spot_equity = spot_free + spot_open_pnl
        fut_equity = fut_free + fut_margin_used + fut_open_pnl

        dashboard["portfolio"] = {
            "spot_free": round(spot_free, 4),
            "spot_equity": round(spot_equity, 4),

            "fut_free": round(fut_free, 4),
            "fut_margin_used": round(fut_margin_used, 4),
            "fut_notional_open": round(fut_notional_open, 4),
            "fut_open_pnl": round(fut_open_pnl, 4),
            "fut_equity": round(fut_equity, 4),

            "total_equity": round(spot_equity + fut_equity, 4),
        }

        dashboard["counts"] = {
            "fut_open_positions": len(fut_positions),
            "spot_open_positions": len(spot_positions),
        }

        return dashboard

    async def handle_dashboard(self, request: web.Request) -> web.Response:
        return web.json_response(await self._build_dashboard_payload())


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

    # --- VORTEX v1.8.19 INTELLIGENCE API ---
    def _read_runtime_json_v1819(self, path: str, default: Any = None) -> Any:
        try:
            import os
            if not os.path.exists(path):
                return default if default is not None else {}
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            return {
                "error": "read_failed",
                "path": path,
                "message": safe_str(exc),
            }

    async def handle_intelligence(self, request: web.Request) -> web.Response:
        import time
        outcome_summary = self._read_runtime_json_v1819("_runtime/outcome_summary.json", {})
        policy_recommendations = self._read_runtime_json_v1819("_runtime/policy_recommendations.json", {})
        shadow_adaptive_replay = self._read_runtime_json_v1819("_runtime/shadow_adaptive_replay.json", {})
        adaptive_be_candidates = self._read_runtime_json_v1819("_runtime/adaptive_be_candidates.json", {})
        shadow_policy_simulation = self._read_runtime_json_v1819("_runtime/shadow_policy_simulation.json", {})
        payload = {
            "schema": "vortex.intelligence.api.v1",
            "schema_version": "1.8.19",
            "ts": time.time(),
            "mode": self.mode,
            "available": {
                "outcome_summary": bool(outcome_summary),
                "policy_recommendations": bool(policy_recommendations),
                "shadow_adaptive_replay": bool(shadow_adaptive_replay),
                "adaptive_be_candidates": bool(adaptive_be_candidates),
                "shadow_policy_simulation": bool(shadow_policy_simulation),
            },
            "outcome_summary": outcome_summary,
            "policy_recommendations": policy_recommendations,
            "shadow_adaptive_replay": shadow_adaptive_replay,
            "adaptive_be_candidates": adaptive_be_candidates,
            "shadow_policy_simulation": shadow_policy_simulation,
        }
        return web.json_response(payload)
    # --- END VORTEX v1.8.19 INTELLIGENCE API ---

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(await self.state.get_health_state(mode=self.mode))

    async def handle_spot_planner(self, request: web.Request) -> web.Response:
        return web.json_response(await self.state.get_spot_planner_state())

    def _watch_status_weight(self, item: Dict[str, Any]) -> int:
        status = safe_str(item.get("status")).lower()
        if bool(item.get("confirmed")):
            return 40
        if status == "ready":
            return 30
        if status == "watch":
            return 20
        if status == "blocked":
            return 10
        return 0

    def _dedupe_watchlist_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best: Dict[str, Dict[str, Any]] = {}

        for raw in items:
            if not isinstance(raw, dict):
                continue

            symbol = safe_str(raw.get("symbol")).upper()
            market = safe_str(raw.get("market")).lower()
            if not symbol:
                continue

            key = f"{market or 'na'}::{symbol}"
            candidate_score = (
                self._watch_status_weight(raw),
                safe_float(raw.get("score"), 0.0),
                1 if safe_str(raw.get("side")) else 0,
                safe_float(raw.get("updated_at"), 0.0),
                safe_float(raw.get("created_at"), 0.0),
            )

            current = best.get(key)
            if current is None:
                best[key] = dict(raw)
                best[key]["deduped_from_count"] = 1
                continue

            current_score = (
                self._watch_status_weight(current),
                safe_float(current.get("score"), 0.0),
                1 if safe_str(current.get("side")) else 0,
                safe_float(current.get("updated_at"), 0.0),
                safe_float(current.get("created_at"), 0.0),
            )

            if candidate_score > current_score:
                raw_copy = dict(raw)
                raw_copy["deduped_from_count"] = int(safe_float(current.get("deduped_from_count"), 1)) + 1
                best[key] = raw_copy
            else:
                current["deduped_from_count"] = int(safe_float(current.get("deduped_from_count"), 1)) + 1

        return list(best.values())

    def _runtime_line_to_api_log(self, line: str) -> Dict[str, Any]:
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("not dict")
        except Exception:
            return {
                "ts": "",
                "type": "SYSTEM",
                "level": "INFO",
                "category": "RAW",
                "title": "RAW LOG",
                "message": safe_str(line).strip(),
                "symbol": "",
                "market": "",
                "reason": "",
                "pnl_net": 0.0,
                "extra": {},
            }

        category = safe_str(payload.get("category")).upper()
        status = safe_str(payload.get("status")).upper()
        message = safe_str(payload.get("message"))
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}

        log_type = "SYSTEM"
        if category in {"TRADE", "FUT CLOSED", "SPOT CLOSED"} or "OPEN" in message.upper() or "CLOSED" in category:
            log_type = "TRADE"
        elif category in {"FUT EVENT", "SPOT EVENT"} or "GUIDE" in message.upper() or "TRAIL" in message.upper() or "BE_PROTECT" in message.upper():
            log_type = "GUIDE"
        elif category in {"RISK", "TRADE_MANAGER"} or "COOLDOWN" in message.upper():
            log_type = "RISK"

        data = extra.get("data") if isinstance(extra.get("data"), dict) else extra
        symbol = safe_str(data.get("symbol") or extra.get("symbol")).upper()
        market = safe_str(data.get("market") or extra.get("market")).upper()
        reason = safe_str(data.get("reason") or message or status).upper()
        pnl_net = safe_float(data.get("pnl_net") or extra.get("pnl_net"), 0.0)

        if symbol:
            title = f"{reason} {symbol}"
        else:
            title = f"{category} {message}".strip()

        return {
            "ts": safe_str(payload.get("ts")),
            "type": log_type,
            "level": status or "INFO",
            "category": category,
            "title": title,
            "message": message,
            "symbol": symbol,
            "market": market,
            "reason": reason,
            "pnl_net": pnl_net,
            "extra": extra,
        }

    async def handle_logs(self, request: web.Request) -> web.Response:
        limit = safe_int(request.query.get("limit"), 100)
        if limit <= 0:
            limit = 100
        limit = min(limit, 500)

        type_filter = safe_str(request.query.get("type")).upper()
        raw_text = ""
        if self.logger and hasattr(self.logger, "tail_runtime"):
            raw_text = self.logger.tail_runtime(lines=limit * 3)

        rows = []
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            item = self._runtime_line_to_api_log(line)
            if type_filter and type_filter != "ALL" and item.get("type") != type_filter:
                continue
            rows.append(item)

        rows = rows[-limit:]
        rows.reverse()

        return web.json_response({
            "code": "00000",
            "data": rows,
            "count": len(rows),
        })

    async def handle_watchlist(self, request: web.Request) -> web.Response:
        dash = await self.state.get_dashboard_state()
        raw_items = dash.get("terminal", {}).get("watchlist_mini", []) or []
        items = self._dedupe_watchlist_items(raw_items)

        futures = [x for x in items if safe_str(x.get("market")).lower() == "fut"]
        spot = [x for x in items if safe_str(x.get("market")).lower() == "spot"]

        return web.json_response({
            "code": "00000",
            "data": {
                "futures": futures,
                "spot": spot,
                "all": items,
                "count": len(items),
                "raw_count": len(raw_items),
                "deduped": len(raw_items) != len(items),
            },
        })

    async def handle_positions_state(self, request: web.Request) -> web.Response:
        if self.position_state_engine is None:
            return web.json_response({"code": "00000", "data": {"enabled": False, "open": [], "closed_recent": [], "counts": {"open": 0, "closed_recent": 0}}})

        return web.json_response({
            "code": "00000",
            "data": self.position_state_engine.snapshot(),
        })

    async def handle_debug_screener(self, request: web.Request) -> web.Response:
        if self.screener is None:
            return web.json_response({"code": "ERROR", "msg": "screener unavailable"}, status=503)

        debug = self.screener.get_debug_snapshot() if hasattr(self.screener, "get_debug_snapshot") else {}
        return web.json_response({
            "code": "00000",
            "data": debug,
        })

    async def handle_history(self, request: web.Request) -> web.Response:
        limit = safe_int(request.query.get("limit"), 100)
        if limit <= 0:
            limit = 100
        limit = min(limit, 1000)

        data = build_history(limit=limit)
        return web.json_response({
            "code": "00000",
            "data": data,
            "count": len(data),
        })

    async def handle_stats(self, request: web.Request) -> web.Response:
        stats = build_stats()
        return web.json_response({
            "code": "00000",
            "data": stats,
        })

    async def handle_debug_runtime(self, request: web.Request) -> web.Response:
        state_snapshot = await self.state.get_runtime_snapshot()
        router_snapshot = self.router.get_runtime_snapshot() if self.router else {}
        risk_status = self.risk_manager.get_status() if self.risk_manager else {}

        return web.json_response({
            "state": state_snapshot,
            "router": router_snapshot,
            "risk": risk_status,
            "fut_position": router_snapshot.get("fut_position"),
            "fut_positions": router_snapshot.get("fut_positions", {}),
        })

    async def handle_debug_test_config(self, request: web.Request) -> web.Response:
        return web.json_response({
            "mode": CONFIG.trading.mode,
            "allow_manual_trades": CONFIG.trading.allow_manual_trades,
            "allow_force_close": CONFIG.trading.allow_force_close,
            "allow_risk_reset": CONFIG.trading.allow_risk_reset,
            "debug_api_enabled": CONFIG.trading.debug_api_enabled,
            "futures_margin_usdt": CONFIG.trading.futures_margin_usdt,
            "spot_order_usdt": CONFIG.trading.spot_order_usdt,
            "futures_default_leverage": CONFIG.trading.futures_default_leverage,
            "futures_min_score_to_open": CONFIG.trading.futures_min_score_to_open,
            "spot_min_score_to_open": CONFIG.trading.spot_min_score_to_open,
            "watchlist_min_score": CONFIG.trading.watchlist_min_score,
            "futures_watch_ttl_sec": CONFIG.trading.futures_watch_ttl_sec,
            "spot_watch_ttl_sec": CONFIG.trading.spot_watch_ttl_sec,
            "universe_top_n": CONFIG.universe.top_n,
            "universe_fut_pool_size": CONFIG.universe.fut_pool_size,
            "universe_spot_pool_size": CONFIG.universe.spot_pool_size,
            "fallback_symbols": CONFIG.universe.fallback_symbols,
            "dynamic_universe_enabled": CONFIG.universe.dynamic_enabled,
            "min_quote_volume_usdt": CONFIG.universe.min_quote_volume_usdt,
            "min_last_price": CONFIG.universe.min_last_price,
            "min_24h_range_pct": CONFIG.universe.min_24h_range_pct,
            "max_24h_range_pct": CONFIG.universe.max_24h_range_pct,
            "blacklisted_symbols": CONFIG.universe.blacklisted_symbols,
            "position_state_enabled": CONFIG.position_state.enabled,
            "momentum_enabled": CONFIG.momentum.enabled,
            "momentum_min_range_pct": CONFIG.momentum.min_range_pct,
            "momentum_min_change_abs_pct": CONFIG.momentum.min_change_abs_pct,
            "momentum_min_vol_ratio": CONFIG.momentum.min_vol_ratio,
            "momentum_watch_score": CONFIG.momentum.watch_score,
            "momentum_confirm_score": CONFIG.momentum.confirm_score,
        })

    async def handle_debug_open_futures(self, request: web.Request) -> web.Response:
        if not CONFIG.trading.allow_manual_trades or self.router is None:
            return web.json_response({"code": "ERROR", "msg": "manual futures disabled"}, status=403)

        payload = await request.json()
        result = self.router.manual_open_futures(
            symbol=safe_str(payload.get("symbol"), "BTCUSDT"),
            side=safe_str(payload.get("side"), "LONG"),
            price=safe_float(payload.get("price")),
            atr=safe_float(payload.get("atr")),
            margin_usdt=safe_float(payload.get("margin_usdt"), CONFIG.trading.futures_margin_usdt),
            leverage=safe_float(payload.get("leverage"), CONFIG.trading.futures_default_leverage),
            tp0_mult=0.6,
            tp_mult=safe_float(payload.get("tp_mult"), CONFIG.strategy.futures_tp_atr_mult),
            sl_mult=safe_float(payload.get("sl_mult"), CONFIG.strategy.futures_sl_atr_mult),
            setup_type=safe_str(payload.get("setup_type"), "manual_fut"),
            args_text=safe_str(payload.get("args_text"), "manual futures open"),
        )

        if self.logger:
            self.logger.info("DEBUG_API", "manual futures open", {"payload": payload, "result": result})

        return web.json_response(result)

    async def handle_debug_close_futures(self, request: web.Request) -> web.Response:
        if not CONFIG.trading.allow_force_close or self.router is None:
            return web.json_response({"code": "ERROR", "msg": "manual futures close disabled"}, status=403)

        payload = await request.json()
        current_price = safe_float(payload.get("price"))
        reason = safe_str(payload.get("reason"), "MANUAL")

        result = self.router.close_futures_position(current_price=current_price, reason=reason)
        if result is None:
            result = {"code": "ERROR", "msg": "no open futures position"}

        if self.logger:
            self.logger.info("DEBUG_API", "manual futures close", {"payload": payload, "result": result})

        return web.json_response(result)

    async def handle_debug_force_fut_price(self, request: web.Request) -> web.Response:
        if self.mode != "PAPER":
            return web.json_response({"code": "ERROR", "msg": "force price is PAPER-only"}, status=403)

        if self.router is None:
            return web.json_response({"code": "ERROR", "msg": "router unavailable"}, status=503)

        if not CONFIG.trading.allow_force_close:
            return web.json_response({"code": "ERROR", "msg": "debug force price disabled"}, status=403)

        payload = {}
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        snapshot = self.router.get_runtime_snapshot() if hasattr(self.router, "get_runtime_snapshot") else {}
        before_pos = snapshot.get("fut_position") if isinstance(snapshot, dict) else None

        if not isinstance(before_pos, dict) or not before_pos:
            return web.json_response({"code": "ERROR", "msg": "no open futures position"}, status=409)

        current_symbol = safe_str(before_pos.get("symbol")).upper()
        requested_symbol = safe_str(payload.get("symbol") or request.query.get("symbol")).upper()

        if requested_symbol and requested_symbol != current_symbol:
            response = {
                "code": "ERROR",
                "msg": "symbol mismatch",
                "data": {
                    "requested_symbol": requested_symbol,
                    "current_symbol": current_symbol,
                    "position": before_pos,
                },
            }
            if self.logger:
                self.logger.warning("DEBUG_API", "force futures price symbol mismatch", response.get("data", {}))
            return web.json_response(response, status=409)

        target = safe_str(payload.get("target") or request.query.get("target"), "").lower()
        side = safe_str(before_pos.get("side")).lower()

        entry = safe_float(before_pos.get("entry"), 0.0)
        mark_price = safe_float(before_pos.get("mark_price"), 0.0)
        tp1 = safe_float(before_pos.get("tp1") or before_pos.get("tp"), 0.0)
        tp2 = safe_float(before_pos.get("tp2"), 0.0)
        sl = safe_float(before_pos.get("sl"), 0.0)
        liq = safe_float(before_pos.get("liq_price"), 0.0)

        price = safe_float(payload.get("price") or request.query.get("price"), 0.0)

        if target:
            if target in {"tp", "tp1"}:
                price = tp1
            elif target == "tp2":
                price = tp2
            elif target == "sl":
                price = sl
            elif target in {"liq", "liquidation"}:
                price = liq
            elif target in {"current", "mark"}:
                price = mark_price
            else:
                return web.json_response({"code": "ERROR", "msg": f"unsupported target: {target}"}, status=400)

        if price <= 0:
            return web.json_response({"code": "ERROR", "msg": "price must be > 0"}, status=400)

        force = safe_str(payload.get("force") or request.query.get("force"), "false").lower() in {"1", "true", "yes", "y"}

        ref_price = mark_price if mark_price > 0 else entry
        if ref_price > 0 and not force:
            ratio = price / ref_price
            if ratio < 0.25 or ratio > 4.0:
                response = {
                    "code": "ERROR",
                    "msg": "price scale guard blocked forced price",
                    "data": {
                        "symbol": current_symbol,
                        "side": side,
                        "requested_price": price,
                        "reference_price": ref_price,
                        "ratio": ratio,
                        "hint": "Use correct symbol/price or pass force=true for intentional liquidation tests.",
                    },
                }
                if self.logger:
                    self.logger.warning("DEBUG_API", "force futures price scale blocked", response.get("data", {}))
                return web.json_response(response, status=400)

        result = self.router.check_futures_position(price)

        after = self.router.get_runtime_snapshot() if hasattr(self.router, "get_runtime_snapshot") else {}
        after_pos = after.get("fut_position") if isinstance(after, dict) else None

        response = {
            "code": "00000",
            "data": {
                "symbol": current_symbol,
                "side": side,
                "target": target,
                "forced_price": price,
                "event": result,
                "before": before_pos,
                "after": after_pos,
            },
        }

        if self.logger:
            self.logger.info("DEBUG_API", "force futures price", {
                "symbol": current_symbol,
                "side": side,
                "target": target,
                "price": price,
                "result": result,
                "after_symbol": after_pos.get("symbol") if isinstance(after_pos, dict) else "",
            })

        return web.json_response(response)

    async def handle_debug_open_spot(self, request: web.Request) -> web.Response:
        if not CONFIG.trading.allow_manual_trades or self.router is None:
            return web.json_response({"code": "ERROR", "msg": "manual spot disabled"}, status=403)

        payload = await request.json()
        result = self.router.manual_open_spot(
            symbol=safe_str(payload.get("symbol"), "BTCUSDT"),
            price=safe_float(payload.get("price")),
            atr=safe_float(payload.get("atr")),
            order_usdt=safe_float(payload.get("order_usdt"), CONFIG.trading.spot_order_usdt),
            tp_mult=safe_float(payload.get("tp_mult"), CONFIG.strategy.spot_tp_atr_mult),
            setup_type=safe_str(payload.get("setup_type"), "manual_spot"),
            args_text=safe_str(payload.get("args_text"), "manual spot open"),
        )

        if self.logger:
            self.logger.info("DEBUG_API", "manual spot open", {"payload": payload, "result": result})

        return web.json_response(result)

    async def handle_debug_close_spot(self, request: web.Request) -> web.Response:
        if not CONFIG.trading.allow_force_close or self.router is None:
            return web.json_response({"code": "ERROR", "msg": "manual spot close disabled"}, status=403)

        payload = await request.json()
        symbol = safe_str(payload.get("symbol"), "")
        current_price = safe_float(payload.get("price"))
        reason = safe_str(payload.get("reason"), "MANUAL")

        result = self.router.close_spot_position(symbol=symbol, current_price=current_price, reason=reason)
        if result is None:
            result = {"code": "ERROR", "msg": "no open spot position for symbol"}

        if self.logger:
            self.logger.info("DEBUG_API", "manual spot close", {"payload": payload, "result": result})

        return web.json_response(result)

    async def handle_debug_close_all_spot(self, request: web.Request) -> web.Response:
        if not CONFIG.trading.allow_force_close or self.router is None:
            return web.json_response({"code": "ERROR", "msg": "manual spot close-all disabled"}, status=403)

        payload = await request.json()
        prices = payload.get("prices", {}) or {}
        reason = safe_str(payload.get("reason"), "MANUAL")

        result = self.router.manual_close_all_spot(prices=prices, reason=reason)

        if self.logger:
            self.logger.info("DEBUG_API", "manual spot close-all", {"payload": payload, "result_count": len(result)})

        return web.json_response({"code": "00000", "data": result})

    async def handle_debug_risk_reset(self, request: web.Request) -> web.Response:
        if not CONFIG.trading.allow_risk_reset or self.risk_manager is None:
            return web.json_response({"code": "ERROR", "msg": "risk reset disabled"}, status=403)

        self.risk_manager.reset()

        if self.logger:
            self.logger.info("DEBUG_API", "risk reset", {})

        return web.json_response({"code": "00000", "msg": "risk reset ok"})

    async def handle_debug_risk_status(self, request: web.Request) -> web.Response:
        if self.risk_manager is None:
            return web.json_response({"code": "ERROR", "msg": "risk manager unavailable"}, status=503)
        return web.json_response(self.risk_manager.get_status())

    async def handle_debug_state_reload(self, request: web.Request) -> web.Response:
        payload = await request.json()
        new_state = payload.get("state")

        if not isinstance(new_state, dict):
            return web.json_response({"code": "ERROR", "msg": "state must be dict"}, status=400)

        await self.state.replace_state(new_state)

        if self.logger:
            self.logger.info("DEBUG_API", "state replaced", {})

        return web.json_response({"code": "00000", "msg": "state replaced"})

    async def handle_debug_logs_tail(self, request: web.Request) -> web.Response:
        lines = safe_int(request.query.get("lines"), 50)
        if self.logger is None:
            return web.json_response({"code": "ERROR", "msg": "logger unavailable"}, status=503)

        return web.json_response({
            "code": "00000",
            "data": {
                "lines": lines,
                "tail": self.logger.tail_runtime(lines=lines),
            },
        })

    async def start(self, port: int = CONFIG.server.port) -> None:
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, CONFIG.server.host, port)
        await site.start()

        if self.logger:
            self.logger.info("API", f"server started on {CONFIG.server.host}:{port}", {})
        else:
            print(f"🚀 API server started on port {port}", flush=True)

        while True:
            await asyncio.sleep(3600)