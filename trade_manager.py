import time
import asyncio
import aiohttp
import traceback
from typing import Any, Dict, Optional
from validators import safe_float, safe_str
from position_guide import PositionGuide

class TradeManager:
    def __init__(self, logger=None, position_state_engine=None) -> None:
        self.logger = logger
        self.position_state_engine = position_state_engine
        self._price_cache: Dict[str, float] = {}
        self.guide = PositionGuide()
        self._price_diff_warn_ts: Dict[str, float] = {}

    async def loop(self, state, router, trade_logger=None, risk_manager=None, open_close_lock=None) -> None:
        try:
            await self.process_futures(state=state, router=router, trade_logger=trade_logger, risk_manager=risk_manager, open_close_lock=open_close_lock)
        except Exception as exc:
            self._log_error("TRADE_MANAGER", f"Futures loop critical crash: {exc}", {"trace": traceback.format_exc()})
            
        try:
            await self.process_spot(state=state, router=router, trade_logger=trade_logger, risk_manager=risk_manager)
        except Exception as exc:
            self._log_error("TRADE_MANAGER", f"Spot loop critical crash: {exc}", {"trace": traceback.format_exc()})

    def _log_info(self, category: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        if self.logger:
            try: self.logger.info(category, message, extra or {})
            except Exception: pass

    def _log_warning(self, category: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        if self.logger:
            try: self.logger.warning(category, message, extra or {})
            except Exception: pass

    def _log_error(self, category: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        if self.logger:
            try: self.logger.error(category, message, extra or {})
            except Exception: pass
        print(f"[{category}] ERROR: {message} | {extra}")

    async def _add_sys_log(self, state, tag: str, message: str) -> None:
        try: await state.add_sys_log(tag, message)
        except Exception: pass

    def _position_to_dict(self, pos: Any) -> Dict[str, Any]:
        if not pos: return {}
        if isinstance(pos, dict): return pos
        data = {}
        for key in ["symbol","side","qty","entry","tp","tp2","sl","pnl","pnl_net","setup_type","args_text","opened_at","open_ts","atr","mark_price","tp1_hit","breakeven"]:
            if hasattr(pos, key): data[key] = getattr(pos, key)
        return data

    def _get_futures_position(self, router) -> Dict[str, Any]:
        try:
            if hasattr(router, "get_futures_position"): return self._position_to_dict(router.get_futures_position())
            return self._position_to_dict(getattr(router, "fut_position", None))
        except Exception as e:
            self._log_error("TRADE_MANAGER", f"_get_futures_position failed: {e}")
            return {}

    def _get_spot_positions(self, router) -> Dict[str, Dict[str, Any]]:
        try:
            raw = router.get_all_spot_positions() if hasattr(router, "get_all_spot_positions") else getattr(router, "spot_positions", {})
            if isinstance(raw, dict): return {safe_str(k).upper(): self._position_to_dict(v) for k, v in raw.items()}
            if isinstance(raw, list):
                out = {}
                for item in raw:
                    p = self._position_to_dict(item)
                    if p.get("symbol"): out[p["symbol"].upper()] = p
                return out
            return {}
        except Exception as e:
            self._log_error("TRADE_MANAGER", f"_get_spot_positions failed: {e}")
            return {}

    def _get_cached_state_price(self, symbol: str, snapshot: Dict[str, Any]) -> float:
        symbol = safe_str(symbol).upper()
        m = snapshot.get("market", {})
        p = safe_float(m.get("prices", {}).get(symbol), 0.0)
        if p <= 0: p = safe_float((m.get("ta_data", {}).get(symbol) or {}).get("price"), 0.0)
        if p <= 0: p = safe_float(self._price_cache.get(symbol), 0.0)
        return p

    async def _fetch_bitget_futures_price(self, symbol: str) -> float:
        url = "https://api.bitget.com/api/v2/mix/market/ticker"
        params = {"symbol": symbol.upper(), "productType": "USDT-FUTURES"}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200: return 0.0
                    payload = await resp.json()
            if safe_str(payload.get("code")) != "00000": return 0.0
            data = payload.get("data")
            if isinstance(data, list): data = data[0] if data else {}
            for k in ["markPrice", "lastPr", "last", "close", "price"]:
                val = safe_float(data.get(k), 0.0)
                if val > 0:
                    self._price_cache[symbol.upper()] = val
                    return val
            return 0.0
        except Exception: return 0.0

    async def _get_futures_price(self, symbol: str, snapshot: Dict[str, Any]) -> float:
        c = self._get_cached_state_price(symbol, snapshot)
        l = 0.0  # [FIX] Запрос отключен. Цена берется безопасно из кэша StateManager
        if l > 0:
            if c > 0 and (abs(l - c) / c * 100.0) >= 1.0:
                now = time.time()
                if now - self._price_diff_warn_ts.get(symbol, 0) >= 60:
                    self._price_diff_warn_ts[symbol] = now
                    self._log_warning("TRADE_MANAGER", "price drift", {"symbol": symbol, "state": c, "live": l})
            return l
        return c

    def _get_ta_item(self, symbol: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        item = snapshot.get("market", {}).get("ta_data", {}).get(symbol.upper(), {})
        return item if isinstance(item, dict) else {}

    def _safe_register_close(self, risk_manager, symbol: str, market: str, pnl_net: float, reason: str = "CLOSE") -> None:
        if not risk_manager: return
        for args in [(symbol, market, pnl_net, reason), (symbol, market, pnl_net), (symbol, market)]:
            try:
                risk_manager.register_close(*args)
                return
            except Exception: continue

    def _safe_position_event(self, event: str, payload: Dict[str, Any]) -> None:
        engine = self.position_state_engine
        if not engine: return
        ev_u = safe_str(event).upper()
        d = payload if isinstance(payload, dict) else {}
        sym, mkt = safe_str(d.get("symbol")).upper(), safe_str(d.get("market")).upper()
        px, pnl_n = safe_float(d.get("price", d.get("exit_price")), 0.0), safe_float(d.get("pnl_net"), 0.0)
        res = safe_str(d.get("reason") or d.get("event") or ev_u, ev_u)

        if ev_u == "CLOSED" and hasattr(engine, "close"):
            try: engine.close(sym, mkt, {"reason": res, "exit_price": px, "pnl_net": pnl_n, "pnl": safe_float(d.get("pnl"), pnl_n), "data": d.get("data", d)})
            except Exception as e: self._log_error("TRADE_MANAGER", f"PositionStateEngine.close failed: {e}")
            return
        for m_name in ["record_event","on_event","handle_event","update_event","update_from_event"]:
            m = getattr(engine, m_name, None)
            if callable(m):
                try: m(ev_u, d); return
                except Exception:
                    try: m(d); return
                    except Exception: continue

    def _safe_position_update_obj(self, pos: Any, market: str, current_price: float = 0.0) -> None:
        engine = self.position_state_engine
        if not engine or not pos: return
        try:
            if hasattr(engine, "update_from_position"): engine.update_from_position(pos, market, current_price=current_price)
        except Exception as e:
            self._log_error("TRADE_MANAGER", f"update_from_position failed: {e}")

    def _safe_log_trade(self, trade_logger, data: Dict[str, Any], fallback_pos: Dict[str, Any], market: str) -> None:
        if not trade_logger or not hasattr(trade_logger, "log_trade"): return
        try:
            trade_logger.log_trade(
                symbol=safe_str(data.get("symbol") or fallback_pos.get("symbol")).upper(),
                side=safe_str(data.get("side") or fallback_pos.get("side")).upper(),
                market=market,
                entry=safe_float(data.get("entry") or fallback_pos.get("entry")),
                tp=safe_float(data.get("tp") or fallback_pos.get("tp")),
                exit_price=safe_float(data.get("exit_price") or data.get("price")),
                pnl=safe_float(data.get("pnl")),
                pnl_net=safe_float(data.get("pnl_net")),
                reason=safe_str(data.get("reason"), "CLOSE"),
                hold_sec=int(safe_float(data.get("hold_sec"))),
                setup_type=safe_str(data.get("setup_type") or fallback_pos.get("setup_type")),
                args_text=safe_str(data.get("args_text") or fallback_pos.get("args_text"))
            )
        except Exception as e:
            self._log_error("TRADE_MANAGER", f"trade_logger failed: {e}")

    async def _handle_futures_result(self, state, result, symbol: str, price: float, fallback_pos: Dict[str, Any], trade_logger=None, risk_manager=None) -> None:
        if not result or not isinstance(result, dict) or result.get("code") != "00000": return
        data = result.get("data") or {}
        reason, pnl_n = safe_str(data.get("reason"), "EVENT"), safe_float(data.get("pnl_net"), 0.0)
        px = safe_float(data.get("exit_price") or data.get("price"), price)

        if data.get("event_only"):
            await self._add_sys_log(state, "🟡 [FUT EVENT]", f"{symbol} {reason} @ {px:.8f}")
            self._log_info("FUT EVENT", reason, {"symbol": symbol, "price": px, "pnl_net": pnl_n})
            self._safe_position_event(reason, {"symbol": symbol, "market": "FUT", "event": reason, "price": px, "pnl_net": pnl_n, "data": data})
        elif data.get("closed") or reason in {"SL", "TP1", "TP2", "BU", "BE", "TIMEOUT", "PROFIT_TIMEOUT", "FADE", "SETUP_DIED", "STALL", "LIQ", "AGGRESSIVE_BE", "SMART_TIMEOUT_TRAIL"}:
            await self._add_sys_log(state, "🔴 [FUT CLOSED]", f"{symbol} CLOSED {reason} @ {px:.8f}")
            self._log_info("FUT CLOSED", reason, {"symbol": symbol, "price": px, "pnl_net": pnl_n})
            try:
                self._vortex_diag_finalize_close(data, fallback_pos, "FUT")
            except Exception:
                pass
            self._safe_log_trade(trade_logger, data, fallback_pos, "FUT")
            self._safe_register_close(risk_manager, symbol, "fut", pnl_n, reason)
            self._safe_position_event("CLOSED", {"symbol": symbol, "market": "FUT", "reason": reason, "price": px, "pnl_net": pnl_n, "data": data})

    async def process_futures(self, state, router, trade_logger=None, risk_manager=None, open_close_lock=None) -> None:
        pos = self._get_futures_position(router)
        if not pos: return
        symbol = safe_str(pos.get("symbol")).upper()
        dashboard = await state.get_dashboard_state()
        price = await self._get_futures_price(symbol, dashboard)
        if price <= 0: return

        try:
            self._vortex_diag_update_position(pos, "FUT", price, dashboard)
        except Exception:
            pass

        try: self._safe_position_update_obj(router.get_futures_position(), "FUT", current_price=price)
        except Exception as e: self._log_error("TRADE_MANAGER", f"update_obj failed: {e}")

        ta_item = self._get_ta_item(symbol, dashboard)
        guide_dec = self.guide.evaluate(pos, price, ta_item=ta_item)
        action, reason = safe_str(guide_dec.get("action")).upper(), safe_str(guide_dec.get("reason"))

        if action == "CLOSE":
            lock = open_close_lock
            try:
                if lock:
                    async with lock:
                        res = router.close_futures_position(price, reason=reason)
                        await self._handle_futures_result(state, res, symbol, price, pos, trade_logger, risk_manager)
                else:
                    res = router.close_futures_position(price, reason=reason)
                    await self._handle_futures_result(state, res, symbol, price, pos, trade_logger, risk_manager)
            except Exception as e:
                self._log_error("TRADE_MANAGER", f"close_futures_position failed: {e}", {"trace": traceback.format_exc()})
            return

        if action == "MOVE_SL":
            new_sl = safe_float(guide_dec.get("new_sl"), 0.0)
            if new_sl > 0 and hasattr(router, "update_futures_sl"):
                try:
                    res = router.update_futures_sl(new_sl, reason=reason)
                    if res: await self._handle_futures_result(state, res, symbol, price, pos, trade_logger, risk_manager)
                except Exception as e:
                    self._log_error("TRADE_MANAGER", f"update_futures_sl failed: {e}")

        try:
            res = await router.check_futures_position(price) if asyncio.iscoroutinefunction(router.check_futures_position) else router.check_futures_position(price)
            await self._handle_futures_result(state, res, symbol, price, pos, trade_logger, risk_manager)
        except Exception as e:
            self._log_error("TRADE_MANAGER", f"check_futures_position failed: {e}", {"trace": traceback.format_exc()})

    async def process_spot(self, state, router, trade_logger=None, risk_manager=None) -> None:
        positions = self._get_spot_positions(router)
        if not positions: return
        dashboard = await state.get_dashboard_state()
        for symbol, pos in list(positions.items()):
            price = self._get_cached_state_price(symbol, dashboard)
            if price <= 0: continue

            try:
                self._vortex_diag_update_position(pos, "SPOT", price, dashboard)
            except Exception:
                pass
            
            try: self._safe_position_update_obj(router.get_spot_position(symbol), "SPOT", current_price=price)
            except Exception as e: self._log_error("TRADE_MANAGER", f"spot update_obj failed: {e}")
            
            try:
                res = router.check_spot_position(symbol, price)
                if res and res.get("code") == "00000":
                    data = res.get("data") or {}
                    reason, pnl_n = safe_str(data.get("reason")), safe_float(data.get("pnl_net"))
                    px = safe_float(data.get("exit_price"), price)
                    if data.get("event_only"):
                        await self._add_sys_log(state, "🟡 [SPOT EVENT]", f"{symbol} {reason}")
                        self._safe_position_event(reason, {"symbol": symbol, "market": "SPOT", "event": reason, "price": px, "pnl_net": pnl_n, "data": data})
                    elif data.get("closed") or reason in {"SL","TP1","TP2","BU","BE","TIMEOUT","FADE","STALL"}:
                        await self._add_sys_log(state, "🔴 [SPOT CLOSED]", f"{symbol} {reason}")
                        try:
                            self._vortex_diag_finalize_close(data, pos, "SPOT")
                        except Exception:
                            pass
                        self._safe_log_trade(trade_logger, data, pos, "SPOT")
                        self._safe_register_close(risk_manager, symbol, "spot", pnl_n, reason)
                        self._safe_position_event("CLOSED", {"symbol": symbol, "market": "SPOT", "reason": reason, "price": px, "pnl_net": pnl_n, "data": data})
            except Exception as e:
                self._log_error("TRADE_MANAGER", f"check_spot_position failed for {symbol}: {e}")


# --- VORTEX v1.8.10_fix TRADE OUTCOME RECORDER COMPAT ---
try:
    from trade_outcome_recorder import TradeOutcomeRecorder

    if not hasattr(TradeManager, "_vortex_v1810_outcome_wrapped"):
        _vortex_tm_safe_log_trade_original_v1810 = TradeManager._safe_log_trade

        def _vortex_tm_safe_log_trade_v1810(self, trade_logger, data, fallback_pos, market):
            result = _vortex_tm_safe_log_trade_original_v1810(self, trade_logger, data, fallback_pos, market)

            try:
                d = data if isinstance(data, dict) else {}
                fp = fallback_pos if isinstance(fallback_pos, dict) else {}
                reason = safe_str(d.get("reason"), "CLOSE").upper()

                if reason == "OPEN":
                    return result

                recorder = getattr(self, "outcome_recorder", None)
                if recorder is None:
                    recorder = TradeOutcomeRecorder(logger=getattr(self, "logger", None))
                    self.outcome_recorder = recorder

                recorder.record_close(
                    data=d,
                    fallback_pos=fp,
                    market=market,
                )

            except Exception as exc:
                try:
                    self._log_warning("ANALYTICS", "trade outcome record failed", {
                        "symbol": safe_str((data or {}).get("symbol") or (fallback_pos or {}).get("symbol")).upper(),
                        "market": market,
                        "error": str(exc),
                    })
                except Exception:
                    pass

            return result

        TradeManager._safe_log_trade = _vortex_tm_safe_log_trade_v1810
        TradeManager._vortex_v1810_outcome_wrapped = True

except Exception:
    pass
# --- END VORTEX v1.8.10_fix TRADE OUTCOME RECORDER COMPAT ---



# --- VORTEX v1.8.19d TRADE DIAGNOSTICS LAYER ---
try:
    from trade_diagnostics import TradeDiagnosticsRecorder
    def _vortex_diag_get_recorder_v1819d(self):
        recorder=getattr(self,"trade_diagnostics_recorder",None)
        if recorder is None:
            recorder=TradeDiagnosticsRecorder(logger=getattr(self,"logger",None))
            self.trade_diagnostics_recorder=recorder
        return recorder
    def _vortex_diag_update_position_v1819d(self,pos,market,current_price,snapshot=None):
        _vortex_diag_get_recorder_v1819d(self).update_position(pos=pos if isinstance(pos,dict) else {},market=market,current_price=current_price,snapshot=snapshot if isinstance(snapshot,dict) else {})
    def _vortex_diag_finalize_close_v1819d(self,data,fallback_pos,market):
        return _vortex_diag_get_recorder_v1819d(self).finalize_close(data=data if isinstance(data,dict) else {},fallback_pos=fallback_pos if isinstance(fallback_pos,dict) else {},market=market)
    TradeManager._vortex_diag_get_recorder=_vortex_diag_get_recorder_v1819d
    TradeManager._vortex_diag_update_position=_vortex_diag_update_position_v1819d
    TradeManager._vortex_diag_finalize_close=_vortex_diag_finalize_close_v1819d
except Exception:
    pass
# --- END VORTEX v1.8.19d TRADE DIAGNOSTICS LAYER ---


# --- VORTEX v1.8.19e MULTI FUTURES TRADE MANAGER ---
try:
    async def _tm_process_futures_multi(self,state,router,trade_logger=None,risk_manager=None,open_close_lock=None):
        try:
            positions=router.get_all_futures_positions() if hasattr(router,'get_all_futures_positions') else {}
            positions=positions or {}
            if not positions:
                pos=self._get_futures_position(router)
                if not pos: return
                p=self._position_to_dict(pos); sym=safe_str(p.get('symbol')).upper()
                if not sym: return
                positions={sym:pos}
            dashboard=await state.get_dashboard_state()
            for symbol,raw_pos in list(positions.items()):
                pos=self._position_to_dict(raw_pos); symbol=safe_str(pos.get('symbol') or symbol).upper()
                if not symbol: continue
                price=await self._get_futures_price(symbol,dashboard)
                if price<=0: continue
                try: self._vortex_diag_update_position(pos,'FUT',price,dashboard)
                except Exception: pass
                try: self._safe_position_update_obj(raw_pos,'FUT',current_price=price)
                except Exception as e: self._log_error('TRADE_MANAGER',f'multi futures update_obj failed: {e}')
                ta_item=self._get_ta_item(symbol,dashboard)
                guide_dec=self.guide.evaluate(pos,price,ta_item=ta_item)
                action,reason=safe_str(guide_dec.get('action')).upper(),safe_str(guide_dec.get('reason'))
                if action=='CLOSE':
                    try:
                        res=router.close_futures_position_for_symbol(symbol,price,reason=reason) if hasattr(router,'close_futures_position_for_symbol') else router.close_futures_position(price,reason)
                        await self._handle_futures_result(state,res,symbol,price,pos,trade_logger,risk_manager)
                    except Exception as e: self._log_error('TRADE_MANAGER',f'multi close_futures_position failed: {e}',{'trace':traceback.format_exc()})
                    continue
                try:
                    res=router.check_futures_position_for_symbol(symbol,price) if hasattr(router,'check_futures_position_for_symbol') else router.check_futures_position(price)
                    await self._handle_futures_result(state,res,symbol,price,pos,trade_logger,risk_manager)
                except Exception as e: self._log_error('TRADE_MANAGER',f'multi check_futures_position failed for {symbol}: {e}',{'trace':traceback.format_exc()})
        except Exception as exc:
            self._log_error('TRADE_MANAGER',f'process_futures_multi critical crash: {exc}',{'trace':traceback.format_exc()})
    TradeManager.process_futures=_tm_process_futures_multi
except Exception:
    pass
# --- END VORTEX v1.8.19e MULTI FUTURES TRADE MANAGER ---
