import asyncio
import time
import json
from typing import Any, Dict, List

from aiohttp import web
import aiohttp_cors

from config import CONFIG
from validators import safe_float, safe_int, safe_str
from trade_history import build_history, build_stats

SERVER_STARTED_AT = time.time()
PUMP_SHORT_ADVISOR_PATH = "_runtime/pump_short_advisor_latest.json"
DEVICE_REPORTS_PATH = "_runtime/advisor_device_reports.jsonl"
DEVICE_REPORTS_LATEST_PATH = "_runtime/advisor_device_reports_latest.json"
ADVISOR_ACCESS_KEYS_PATH = "_runtime/advisor_access_keys.json"
ADVISOR_ACCESS_LOG_PATH = "_runtime/advisor_access.jsonl"
ADVISOR_ACCESS_LATEST_PATH = "_runtime/advisor_access_latest.json"
ADVISOR_DEVICE_BINDINGS_PATH = "_runtime/advisor_device_bindings.json"


def _format_uptime_human_21li(seconds: int) -> str:
    try:
        seconds = max(0, int(seconds))
    except Exception:
        seconds = 0

    if seconds < 60:
        return f"{seconds}с"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}м"

    hours = minutes // 60
    rest_minutes = minutes % 60
    if hours < 24:
        return f"{hours}ч {rest_minutes}м"

    days = hours // 24
    rest_hours = hours % 24
    return f"{days}д {rest_hours}ч"




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
            self.app.router.add_get("/api/context-fusion", self.handle_context_fusion),
            self.app.router.add_get("/api/macro-regime", self.handle_macro_regime),
            self.app.router.add_get("/api/analytics/market-pulse", self.handle_market_pulse_1824b),
            self.app.router.add_get("/api/analytics/coin-liquidity", self.handle_coin_liquidity_1824e),
            self.app.router.add_get("/analytics/market", self.handle_market_analytics_page_1824b),
            self.app.router.add_get("/api/advisor/pump-short", self.handle_pump_short_advisor),
            self.app.router.add_get("/advisor/pump-short", self.handle_pump_short_advisor_page),
            self.app.router.add_post("/api/advisor/device-report", self.handle_advisor_device_report),
            self.app.router.add_get("/api/advisor/device-report/latest", self.handle_advisor_device_report_latest),
            self.app.router.add_get("/api/advisor/access/latest", self.handle_advisor_access_latest),
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

        # Build daily realized/open PnL.
        # Realized PnL is calculated from trades_state.json closed trades.
        # Open PnL is calculated from current dashboard live positions.
        import json as _json
        import time as _time
        from pathlib import Path as _Path

        now_ts = _time.time()
        lt = _time.localtime(now_ts)
        today_start_ts = _time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))

        today_realized_fut = 0.0
        today_realized_spot = 0.0

        try:
            st_path = _Path("trades_state.json")
            if st_path.exists():
                st = _json.loads(st_path.read_text(encoding="utf-8"))
                for closed_trade in st.get("closed", []) or []:
                    closed_at = safe_float(closed_trade.get("closed_at", 0.0))
                    if closed_at < today_start_ts:
                        continue

                    pnl_net = safe_float(closed_trade.get("pnl_net", 0.0))
                    market = str(closed_trade.get("market", "")).upper()

                    if market in {"FUT", "FUTURES"}:
                        today_realized_fut += pnl_net
                    elif market == "SPOT":
                        today_realized_spot += pnl_net
        except Exception:
            today_realized_fut = 0.0
            today_realized_spot = 0.0

        today_open_fut = sum(safe_float(p.get("pnl_net", 0.0)) for p in fut_positions.values())
        today_open_spot = sum(safe_float(p.get("pnl_net", 0.0)) for p in spot_positions.values())

        dashboard["today"] = {
            "today_realized_fut": round(today_realized_fut, 4),
            "today_realized_spot": round(today_realized_spot, 4),
            "today_total_realized": round(today_realized_fut + today_realized_spot, 4),
            "today_open_fut": round(today_open_fut, 4),
            "today_open_spot": round(today_open_spot, 4),
            "today_total_open": round(today_open_fut + today_open_spot, 4),
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

        dashboard["context_fusion"] = self._read_context_fusion_payload()
        dashboard["macro_regime"] = self._read_macro_regime_payload()

        return dashboard



    def _advisor_fingerprint_21mg(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        VORTEX v1.8.23-b2:
        Stable advisor fingerprint.

        Binding must not depend on screen/mode/type/touch/X-Advisor-Device,
        because device-report and pump-short can send different values.

        For this read-only advisor:
        - one access key is already dedicated to one device;
        - userAgent is stable enough between device-report and pump-short;
        - screen/mode/type remain useful for logs only.
        """
        import hashlib as _hashlib

        payload = payload if isinstance(payload, dict) else {}

        ua = safe_str(payload.get("userAgent"), "")[:260]

        stable_source = {
            "userAgent": ua,
        }

        if not ua:
            return {
                "hash": "",
                "source": stable_source,
                "screen": {
                    "width": safe_int(payload.get("width"), 0),
                    "height": safe_int(payload.get("height"), 0),
                },
            }

        raw = json.dumps(stable_source, ensure_ascii=False, sort_keys=True)

        return {
            "hash": _hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "source": stable_source,
            "screen": {
                "width": safe_int(payload.get("width"), 0),
                "height": safe_int(payload.get("height"), 0),
            },
        }

    def _load_advisor_device_bindings_21mg(self) -> Dict[str, Any]:
        from pathlib import Path as _Path
        import time as _time

        path = _Path(ADVISOR_DEVICE_BINDINGS_PATH)
        if not path.exists():
            return {
                "schema": "vortex.advisor.device_bindings.v1",
                "schema_version": "1.8.21m-g",
                "created_at": int(_time.time()),
                "bindings": {},
            }

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if not isinstance(data.get("bindings"), dict):
                    data["bindings"] = {}
                return data
        except Exception:
            pass

        return {
            "schema": "vortex.advisor.device_bindings.v1",
            "schema_version": "1.8.21m-g",
            "created_at": int(_time.time()),
            "bindings": {},
        }

    def _save_advisor_device_bindings_21mg(self, data: Dict[str, Any]) -> None:
        from pathlib import Path as _Path
        import time as _time

        path = _Path(ADVISOR_DEVICE_BINDINGS_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)

        data["schema"] = "vortex.advisor.device_bindings.v1"
        data["schema_version"] = "1.8.21m-g"
        data["updated_at"] = int(_time.time())

        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def _check_or_bind_advisor_device_21mg(self, auth: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        import time as _time

        if not auth.get("allowed"):
            return auth

        raw_key = safe_str(auth.get("key"), "").strip()
        key_hash = safe_str(auth.get("key_hash"), "").strip() or self._advisor_key_hash_1823a(raw_key)
        if not raw_key:
            auth["allowed"] = False
            auth["reason"] = "missing_key"
            return auth

        fp = self._advisor_fingerprint_21mg(payload)
        if not fp.get("hash"):
            auth["allowed"] = False
            auth["reason"] = "missing_fingerprint"
            return auth

        data = self._load_advisor_device_bindings_21mg()
        bindings = data.get("bindings")
        if not isinstance(bindings, dict):
            bindings = {}
            data["bindings"] = bindings

        now = int(_time.time())
        existing = bindings.get(key_hash)

        if not existing:
            bindings[key_hash] = {
                "key_label": safe_str(auth.get("label"), ""),
                "fingerprint": fp.get("hash"),
                "fingerprint_source": fp.get("source"),
                "first_seen": now,
                "last_seen": now,
                "last_screen": fp.get("screen"),
                "last_payload": {
                    "type": safe_str(payload.get("type"), ""),
                    "mode": safe_str(payload.get("mode"), ""),
                    "width": safe_int(payload.get("width"), 0),
                    "height": safe_int(payload.get("height"), 0),
                    "dpr": safe_float(payload.get("dpr"), 1.0),
                    "touch": bool(payload.get("touch")),
                    "userAgent": safe_str(payload.get("userAgent"), "")[:260],
                },
            }
            self._save_advisor_device_bindings_21mg(data)
            auth["binding"] = "created"
            auth["device_fingerprint"] = fp.get("hash")
            return auth

        expected = safe_str(existing.get("fingerprint"), "")
        if expected and expected != fp.get("hash"):
            auth["allowed"] = False
            auth["reason"] = "device_mismatch"
            auth["binding"] = "mismatch"
            auth["device_fingerprint"] = fp.get("hash")
            auth["bound_fingerprint"] = expected
            return auth

        existing["last_seen"] = now
        existing["last_screen"] = fp.get("screen")
        existing["last_payload"] = {
            "type": safe_str(payload.get("type"), ""),
            "mode": safe_str(payload.get("mode"), ""),
            "width": safe_int(payload.get("width"), 0),
            "height": safe_int(payload.get("height"), 0),
            "dpr": safe_float(payload.get("dpr"), 1.0),
            "touch": bool(payload.get("touch")),
            "userAgent": safe_str(payload.get("userAgent"), "")[:260],
        }
        bindings[key_hash] = existing
        self._save_advisor_device_bindings_21mg(data)

        auth["binding"] = "matched"
        auth["device_fingerprint"] = fp.get("hash")
        return auth


    def _load_advisor_access_keys_21md(self) -> Dict[str, Any]:
        from pathlib import Path as _Path
        path = _Path(ADVISOR_ACCESS_KEYS_PATH)
        try:
            if not path.exists():
                return {"available": False, "keys": [], "error": "missing_access_keys"}
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"available": False, "keys": [], "error": "invalid_keys_json"}
            keys = data.get("keys") if isinstance(data.get("keys"), list) else []
            return {"available": True, "keys": keys, "error": None}
        except Exception as exc:
            return {"available": False, "keys": [], "error": f"read_failed: {safe_str(exc)}"}

    def _advisor_key_hash_1823a(self, raw_key: str) -> str:
        # v1.8.23-a advisor auth hardening: never use raw advisor keys as device-binding ids.
        import hashlib as _hashlib
        return _hashlib.sha256(safe_str(raw_key, "").strip().encode("utf-8")).hexdigest()

    def _advisor_device_payload_from_request_1823a(self, request: web.Request) -> Dict[str, Any]:
        return {
            "device": safe_str(request.headers.get("X-Advisor-Device"), ""),
            "type": safe_str(request.headers.get("X-Advisor-Type"), ""),
            "mode": safe_str(request.headers.get("X-Advisor-Mode"), ""),
            "width": safe_int(request.headers.get("X-Advisor-Screen-W"), 0),
            "height": safe_int(request.headers.get("X-Advisor-Screen-H"), 0),
            "screen": safe_str(request.headers.get("X-Advisor-Screen"), ""),
            "dpr": safe_float(request.headers.get("X-Advisor-Dpr"), 1.0),
            "touch": safe_str(request.headers.get("X-Advisor-Touch"), "").lower() in {"1", "true", "yes", "y"},
            "userAgent": safe_str(request.headers.get("User-Agent"), "")[:260],
        }

    def _advisor_security_headers_1823a(self, html: bool = False) -> Dict[str, str]:
        headers = {
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
        }
        if html:
            headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; "
                "img-src 'self' data:; "
                "base-uri 'none'; "
                "form-action 'none'; "
                "frame-ancestors 'none'"
            )
        return headers

    def _advisor_json_response_1823a(self, payload: Dict[str, Any], status: int = 200) -> web.Response:
        return web.json_response(payload, status=status, headers=self._advisor_security_headers_1823a(False))

    def _advisor_auth_from_request_21md(self, request: web.Request) -> Dict[str, Any]:
        keys_data = self._load_advisor_access_keys_21md()
        if "key" in request.query:
            return {
                "allowed": False,
                "reason": "query_key_disabled",
                "key": "",
                "key_hash": "",
                "label": "",
                "keys_available": keys_data.get("available"),
                "keys_error": keys_data.get("error"),
            }

        raw_key = ""
        auth = safe_str(request.headers.get("Authorization"), "").strip()
        if auth.lower().startswith("bearer "):
            raw_key = auth[7:].strip()
        if not raw_key:
            raw_key = safe_str(request.headers.get("X-Advisor-Key"), "").strip()

        if not raw_key:
            return {"allowed": False, "reason": "missing_key", "key": "", "key_hash": "", "label": "", "keys_available": keys_data.get("available"), "keys_error": keys_data.get("error")}

        key_hash = self._advisor_key_hash_1823a(raw_key)
        for item in keys_data.get("keys") or []:
            if not isinstance(item, dict):
                continue
            if safe_str(item.get("key"), "").strip() == raw_key:
                if item.get("enabled", True) is False:
                    return {"allowed": False, "reason": "disabled_key", "key": raw_key, "key_hash": key_hash, "label": safe_str(item.get("label"), ""), "keys_available": keys_data.get("available"), "keys_error": keys_data.get("error")}
                return {"allowed": True, "reason": "allowed", "key": raw_key, "key_hash": key_hash, "label": safe_str(item.get("label"), "Device"), "keys_available": keys_data.get("available"), "keys_error": keys_data.get("error")}

        return {"allowed": False, "reason": "bad_key", "key": raw_key, "key_hash": key_hash, "label": "", "keys_available": keys_data.get("available"), "keys_error": keys_data.get("error")}

    def _advisor_client_ip_21md(self, request: web.Request) -> str:
        forwarded = safe_str(request.headers.get("X-Forwarded-For"), "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return safe_str(getattr(request, "remote", None), "")

    def _advisor_access_response_21md(self, auth: Dict[str, Any]) -> web.Response:
        reason = auth.get("reason")
        if reason == "device_mismatch":
            message = "Цей ключ вже привʼязаний до іншого пристрою. Вам потрібен окремий ключ — зверніться до адміністратора."
        elif reason == "query_key_disabled":
            message = "Ключ у URL вимкнено. Введіть ключ на сторінці або використовуйте Authorization: Bearer."
        else:
            message = "Доступ заборонено. Немає дійсного ключа пристрою."
        return self._advisor_json_response_1823a({
            "ok": False,
            "available": False,
            "error": "advisor_access_denied",
            "reason": reason,
            "message": message,
        }, status=403)

    def _log_advisor_access_21md(self, request: web.Request, auth: Dict[str, Any], payload: Dict[str, Any] = None) -> Dict[str, Any]:
        from pathlib import Path as _Path
        import time as _time
        payload = payload if isinstance(payload, dict) else {}
        entry = {
            "ts": _time.time(),
            "allowed": bool(auth.get("allowed")),
            "reason": safe_str(auth.get("reason"), ""),
            "binding": safe_str(auth.get("binding"), ""),
            "label": safe_str(auth.get("label"), ""),
            "ip": self._advisor_client_ip_21md(request),
            "path": safe_str(request.path, ""),
            "method": safe_str(request.method, ""),
            "type": safe_str(payload.get("type"), ""),
            "mode": safe_str(payload.get("mode"), ""),
            "width": safe_int(payload.get("width"), 0),
            "height": safe_int(payload.get("height"), 0),
            "dpr": safe_float(payload.get("dpr"), 1.0),
            "touch": bool(payload.get("touch")),
            "userAgent": safe_str(payload.get("userAgent"), "")[:260],
        }
        path = _Path(ADVISOR_ACCESS_LOG_PATH)
        latest_path = _Path(ADVISOR_ACCESS_LATEST_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-500:]
            parsed = []
            for line in lines:
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        parsed.append(item)
                except Exception:
                    pass
            devices_by_key = {}
            denied = []
            for item in parsed:
                if item.get("allowed"):
                    key = f"{item.get('label')}:{item.get('type')}:{item.get('width')}x{item.get('height')}:{item.get('touch')}"
                    devices_by_key[key] = item
                else:
                    denied.append(item)
            latest = {
                "available": True,
                "schema": "vortex.advisor.access_log.v1",
                "schema_version": "1.8.21m-d",
                "updated_at": entry["ts"],
                "last": entry,
                "devices": sorted(devices_by_key.values(), key=lambda x: x.get("ts", 0), reverse=True)[:30],
                "denied_recent": denied[-30:],
            }
            latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            pass

        status = "allowed" if entry["allowed"] else "denied"
        line = (
            f"[ADVISOR_ACCESS] {status} label='{entry['label']}' reason='{entry['reason']}' binding='{entry['binding']}' "
            f"type='{entry['type']}' screen={entry['width']}x{entry['height']} touch={entry['touch']} "
            f"ip={entry['ip']} path={entry['path']}"
        )
        print(line, flush=True)
        try:
            if getattr(self, "logger", None):
                self.logger.info("ADVISOR_ACCESS", line, entry)
        except Exception:
            pass
        return entry

    def _read_advisor_access_latest_21md(self) -> Dict[str, Any]:
        from pathlib import Path as _Path
        path = _Path(ADVISOR_ACCESS_LATEST_PATH)
        try:
            if not path.exists():
                return {"available": False, "schema_version": "1.8.21m-d", "devices": [], "denied_recent": [], "last": None, "error": "missing_access_log"}
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"available": False, "schema_version": "1.8.21m-d", "devices": [], "denied_recent": [], "last": None, "error": "invalid_access_log_json"}
            return data
        except Exception as exc:
            return {"available": False, "schema_version": "1.8.21m-d", "devices": [], "denied_recent": [], "last": None, "error": f"read_failed: {safe_str(exc)}"}


    def _read_pump_short_advisor_payload(self) -> Dict[str, Any]:
        from pathlib import Path as _Path
        path = _Path(PUMP_SHORT_ADVISOR_PATH)
        fallback = {"available": False, "schema": "vortex.pump_short_advisor.api.v1", "schema_version": "1.8.21m-b", "source": str(path), "items": [], "important": [], "phase_counts": {}, "symbols_count": 0, "error": None}
        try:
            if not path.exists():
                fallback["error"] = "missing_pump_short_advisor_latest"
                return fallback
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                fallback["error"] = "invalid_json_root"
                return fallback
            data["api_schema"] = "vortex.pump_short_advisor.api.v1"
            data["api_schema_version"] = "1.8.21m-b"
            data["available"] = True
            data["error"] = None
            return data
        except Exception as exc:
            fallback["error"] = f"read_failed: {safe_str(exc)}"
            return fallback

    def _read_advisor_device_report_latest(self) -> Dict[str, Any]:
        from pathlib import Path as _Path
        path = _Path(DEVICE_REPORTS_LATEST_PATH)
        try:
            if not path.exists():
                return {"available": False, "schema_version": "1.8.21m-c", "devices": [], "last": None, "error": "missing_device_report"}
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"available": False, "devices": [], "last": None, "error": "invalid_device_report_json"}
        except Exception as exc:
            return {"available": False, "schema_version": "1.8.21m-c", "devices": [], "last": None, "error": f"read_failed: {safe_str(exc)}"}

    def _write_advisor_device_report(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from pathlib import Path as _Path
        import time as _time
        report = {"ts": _time.time(), "type": safe_str(payload.get("type"), "unknown"), "mode": safe_str(payload.get("mode"), "unknown"), "width": safe_int(payload.get("width"), 0), "height": safe_int(payload.get("height"), 0), "dpr": safe_float(payload.get("dpr"), 1.0), "touch": bool(payload.get("touch")), "userAgent": safe_str(payload.get("userAgent"), "")[:260]}
        path = _Path(DEVICE_REPORTS_PATH); latest_path = _Path(DEVICE_REPORTS_LATEST_PATH); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f: f.write(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n")
        devices=[]
        try:
            parsed=[]
            for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
                try:
                    item=json.loads(line)
                    if isinstance(item, dict): parsed.append(item)
                except Exception: pass
            by_key={}
            for item in parsed:
                by_key[f"{item.get('type')}:{item.get('width')}x{item.get('height')}:{item.get('touch')}"] = item
            devices = sorted(by_key.values(), key=lambda x: x.get("ts",0), reverse=True)[:20]
        except Exception:
            devices=[report]
        latest={"available": True, "schema": "vortex.advisor.device_report.v1", "schema_version": "1.8.21m-c", "updated_at": report["ts"], "last": report, "devices": devices}
        latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return latest

    def _read_macro_regime_payload(self) -> Dict[str, Any]:
        # VORTEX v1.8.21l-h: expose macro_regime runtime snapshot to Android dashboard.
        from pathlib import Path as _Path

        path = _Path("_runtime/macro_regime_latest.json")

        fallback = {
            "available": False,
            "schema": "vortex.macro_regime.api.v1",
            "schema_version": "1.8.21l-h",
            "source": str(path),
            "regime": None,
            "confidence": None,
            "recommendation": {},
            "reasons": [],
            "warnings": [],
            "heatmap": {},
            "ichimoku_breadth": {},
            "futures_pressure": {},
            "vortex_pressure": {},
            "error": None,
        }

        try:
            if not path.exists():
                fallback["error"] = "missing_macro_regime_latest"
                return fallback

            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                fallback["error"] = "invalid_macro_regime_json_root"
                return fallback

            return {
                "available": True,
                "schema": "vortex.macro_regime.api.v1",
                "schema_version": "1.8.21l-h",
                "source": str(path),
                "snapshot_schema": data.get("schema"),
                "snapshot_schema_version": data.get("schema_version"),
                "ts": data.get("ts"),
                "regime": data.get("regime"),
                "confidence": data.get("confidence"),
                "recommendation": data.get("recommendation") if isinstance(data.get("recommendation"), dict) else {},
                "reasons": data.get("reasons") if isinstance(data.get("reasons"), list) else [],
                "warnings": data.get("warnings") if isinstance(data.get("warnings"), list) else [],
                "heatmap": data.get("heatmap") if isinstance(data.get("heatmap"), dict) else {},
                "ichimoku_breadth": data.get("ichimoku_breadth") if isinstance(data.get("ichimoku_breadth"), dict) else {},
                "futures_pressure": data.get("futures_pressure") if isinstance(data.get("futures_pressure"), dict) else {},
                "vortex_pressure": data.get("vortex_pressure") if isinstance(data.get("vortex_pressure"), dict) else {},
                "error": None,
            }

        except Exception as exc:
            fallback["error"] = f"read_failed: {safe_str(exc)}"
            return fallback


    def _read_context_fusion_payload(self) -> Dict[str, Any]:
        """
        VORTEX v1.8.21k-e:
        Expose context_fusion runtime snapshot to Android dashboard.

        Safe contract:
        - missing file -> available=false
        - invalid JSON -> available=false
        - valid file -> available=true, summary/symbols included
        - never raises into /api/dashboard
        """
        from pathlib import Path as _Path

        path = _Path("_runtime/context_fusion_latest.json")

        fallback = {
            "available": False,
            "schema": "vortex.context_fusion.api.v1",
            "schema_version": "1.8.21k-e",
            "source": str(path),
            "summary": {},
            "symbols": [],
            "important": [],
            "error": None,
        }

        try:
            if not path.exists():
                fallback["error"] = "missing_context_fusion_latest"
                return fallback

            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                fallback["error"] = "invalid_context_fusion_json_root"
                return fallback

            summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
            symbols = data.get("symbols") if isinstance(data.get("symbols"), list) else []
            important = data.get("important") if isinstance(data.get("important"), list) else []

            return {
                "available": True,
                "schema": "vortex.context_fusion.api.v1",
                "schema_version": "1.8.21k-e",
                "source": str(path),
                "snapshot_schema": data.get("schema"),
                "snapshot_schema_version": data.get("schema_version"),
                "ts": data.get("ts"),
                "summary": summary,
                "symbols": symbols,
                "important": important,
                "error": None,
            }

        except Exception as exc:
            fallback["error"] = f"read_failed: {safe_str(exc)}"
            return fallback

    async def handle_context_fusion(self, request: web.Request) -> web.Response:
        return web.json_response(self._read_context_fusion_payload())

    async def handle_macro_regime(self, request: web.Request) -> web.Response:
        return web.json_response(self._read_macro_regime_payload())

    async def handle_pump_short_advisor(self, request: web.Request) -> web.Response:
        payload = self._advisor_device_payload_from_request_1823a(request)
        auth = self._advisor_auth_from_request_21md(request)
        auth = self._check_or_bind_advisor_device_21mg(auth, payload)
        self._log_advisor_access_21md(request, auth, payload)
        if not auth.get("allowed"):
            return self._advisor_access_response_21md(auth)
        return self._advisor_json_response_1823a(self._read_pump_short_advisor_payload())

    async def handle_pump_short_advisor_page(self, request: web.Request) -> web.Response:
        from pathlib import Path as _Path
        headers = self._advisor_security_headers_1823a(html=True)
        path = _Path("web/pump_short_advisor.html")
        if not path.exists():
            return web.Response(text="<html><body><h1>Радник після пампу</h1><p>HTML-файл не знайдено.</p></body></html>", content_type="text/html", charset="utf-8", headers=headers)
        return web.Response(text=path.read_text(encoding="utf-8"), content_type="text/html", charset="utf-8", headers=headers)

    async def handle_advisor_device_report(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        auth = self._advisor_auth_from_request_21md(request)
        auth = self._check_or_bind_advisor_device_21mg(auth, payload)
        self._log_advisor_access_21md(request, auth, payload)

        if not auth.get("allowed"):
            return self._advisor_access_response_21md(auth)

        payload["access_label"] = auth.get("label")
        data = self._write_advisor_device_report(payload)
        return self._advisor_json_response_1823a({
            "ok": True,
            "access": {
                "allowed": True,
                "label": auth.get("label"),
                "reason": auth.get("reason"),
            },
            "device_report": data,
        })

    async def handle_advisor_device_report_latest(self, request: web.Request) -> web.Response:
        auth = self._advisor_auth_from_request_21md(request)
        if not auth.get("allowed"):
            self._log_advisor_access_21md(request, auth, {})
            return self._advisor_access_response_21md(auth)
        return self._advisor_json_response_1823a(self._read_advisor_device_report_latest())

    async def handle_advisor_access_latest(self, request: web.Request) -> web.Response:
        auth = self._advisor_auth_from_request_21md(request)
        if not auth.get("allowed"):
            self._log_advisor_access_21md(request, auth, {})
            return self._advisor_access_response_21md(auth)
        return self._advisor_json_response_1823a(self._read_advisor_access_latest_21md())

    # --- VORTEX v1.8.24-b MARKET ANALYTICS PAGE ---
    def _market_pulse_count_1824b(self, items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
        from collections import Counter

        values = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            value = safe_str(item.get(key), "").strip()
            if value:
                values.append(value)
        return dict(Counter(values))

    def _market_pulse_watch_summary_1824b(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        from collections import Counter

        rows = [x for x in (items or []) if isinstance(x, dict)]
        reasons = Counter()
        trigger_crossed = 0
        would_confirm_now = 0
        entry_confirmed = 0
        invalidated = 0

        for item in rows:
            check = item.get("confirm_check") if isinstance(item.get("confirm_check"), dict) else {}
            reason = safe_str(check.get("reason") or item.get("confirmation_reason"), "").strip()
            if reason:
                reasons[reason] += 1

            crossed = bool(item.get("trigger_crossed") or check.get("trigger_crossed"))
            would = bool(check.get("would_confirm_now")) or reason == "would_confirm_now"
            confirmed = bool(item.get("entry_confirmed") or item.get("confirmed"))
            is_invalid = bool(check.get("invalidated")) or reason == "invalidated"

            trigger_crossed += int(crossed)
            would_confirm_now += int(would)
            entry_confirmed += int(confirmed)
            invalidated += int(is_invalid)

        return {
            "len": len(rows),
            "status_counts": self._market_pulse_count_1824b(rows, "status"),
            "stage_counts": self._market_pulse_count_1824b(rows, "confirmation_stage"),
            "setup_types": self._market_pulse_count_1824b(rows, "setup_type"),
            "sides": self._market_pulse_count_1824b(rows, "side"),
            "trigger_crossed": trigger_crossed,
            "would_confirm_now": would_confirm_now,
            "entry_confirmed": entry_confirmed,
            "invalidated": invalidated,
            "confirm_reasons": dict(reasons),
        }

    def _market_pulse_near_entries_1824b(self, items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        out = []
        for item in items or []:
            if not isinstance(item, dict):
                continue

            check = item.get("confirm_check") if isinstance(item.get("confirm_check"), dict) else {}
            price = safe_float(item.get("price") or item.get("current_price"), 0.0)
            trigger = safe_float(
                check.get("required_price")
                or item.get("required_price")
                or item.get("trigger_price")
                or item.get("trigger"),
                0.0,
            )
            if price <= 0 or trigger <= 0:
                continue

            reason = safe_str(check.get("reason") or item.get("confirmation_reason"), "")
            would = bool(check.get("would_confirm_now")) or reason == "would_confirm_now"
            out.append({
                "symbol": safe_str(item.get("symbol"), "").upper(),
                "market": safe_str(item.get("market"), "").lower(),
                "side": safe_str(item.get("side"), "").upper(),
                "setup_type": safe_str(item.get("setup_type"), ""),
                "score": safe_int(item.get("score"), 0),
                "price": price,
                "trigger": trigger,
                "dist_pct": round(((price - trigger) / trigger) * 100.0, 4),
                "reason": reason or "waiting_trigger",
                "stage": safe_str(item.get("confirmation_stage"), ""),
                "trigger_crossed": bool(item.get("trigger_crossed") or check.get("trigger_crossed")),
                "would_confirm_now": would,
                "invalidated": bool(check.get("invalidated")) or reason == "invalidated",
            })

        out.sort(key=lambda x: (not bool(x.get("would_confirm_now")), abs(safe_float(x.get("dist_pct"), 9999.0))))
        return out[:max(0, int(limit))]

    def _market_pulse_context_fusion_1824b(self, fusion: Dict[str, Any]) -> Dict[str, Any]:
        fusion = fusion if isinstance(fusion, dict) else {}
        summary = fusion.get("summary") if isinstance(fusion.get("summary"), dict) else {}
        ichi = summary.get("ichimoku_summary") if isinstance(summary.get("ichimoku_summary"), dict) else {}
        cloud = ichi.get("cloud_state_counts") if isinstance(ichi.get("cloud_state_counts"), dict) else {}
        long_support = ichi.get("long_support_counts") if isinstance(ichi.get("long_support_counts"), dict) else {}
        short_support = ichi.get("short_support_counts") if isinstance(ichi.get("short_support_counts"), dict) else {}

        return {
            "available": bool(fusion.get("available")),
            "heatmap_bias": summary.get("heatmap_bias"),
            "heatmap_net_bias_score": safe_float(summary.get("heatmap_net_bias_score"), 0.0),
            "final_view_counts": summary.get("final_view_counts") if isinstance(summary.get("final_view_counts"), dict) else {},
            "ichimoku": {
                "above_cloud": safe_int(cloud.get("above_cloud"), 0),
                "below_cloud": safe_int(cloud.get("below_cloud"), 0),
                "inside_cloud": safe_int(cloud.get("inside_cloud"), 0),
                "long_supportive": safe_int(long_support.get("supportive"), 0),
                "long_against": safe_int(long_support.get("against"), 0),
                "short_supportive": safe_int(short_support.get("supportive"), 0),
                "short_against": safe_int(short_support.get("against"), 0),
            },
        }

    def _market_pulse_regime_1824b(self, macro: Dict[str, Any]) -> Dict[str, Any]:
        macro = macro if isinstance(macro, dict) else {}
        recommendation = macro.get("recommendation") if isinstance(macro.get("recommendation"), dict) else {}
        return {
            "available": bool(macro.get("available")),
            "regime": macro.get("regime"),
            "confidence": safe_int(macro.get("confidence"), 0),
            "risk_mode": recommendation.get("risk_mode"),
            "long_permission": recommendation.get("long_permission"),
            "short_permission": recommendation.get("short_permission"),
            "reasons": macro.get("reasons") if isinstance(macro.get("reasons"), list) else [],
            "warnings": macro.get("warnings") if isinstance(macro.get("warnings"), list) else [],
            "heatmap": macro.get("heatmap") if isinstance(macro.get("heatmap"), dict) else {},
            "ichimoku_breadth": macro.get("ichimoku_breadth") if isinstance(macro.get("ichimoku_breadth"), dict) else {},
            "futures_pressure": macro.get("futures_pressure") if isinstance(macro.get("futures_pressure"), dict) else {},
            "vortex_pressure": macro.get("vortex_pressure") if isinstance(macro.get("vortex_pressure"), dict) else {},
        }

    def _market_pulse_pump_1824b(self, pump: Dict[str, Any]) -> Dict[str, Any]:
        pump = pump if isinstance(pump, dict) else {}
        if not pump.get("available"):
            return {"available": False, "reason": pump.get("error") or "no_runtime_file"}

        items = pump.get("items") if isinstance(pump.get("items"), list) else []
        important = pump.get("important") if isinstance(pump.get("important"), list) else []
        fields = (
            "symbol", "phase", "score", "pump_pct_24h", "pump_pct_6h", "rsi14",
            "volume_ratio", "breakdown_distance_pct", "waiting_for", "context_4h",
        )
        return {
            "available": True,
            "symbols_count": safe_int(pump.get("symbols_count"), len(items)),
            "items_len": len(items),
            "important_len": len(important),
            "phase_counts": pump.get("phase_counts") if isinstance(pump.get("phase_counts"), dict) else {},
            "top_important": [
                {field: item.get(field) for field in fields}
                for item in important[:15]
                if isinstance(item, dict)
            ],
        }

    def _market_pulse_human_summary_1824b(
        self,
        regime: Dict[str, Any],
        futures_summary: Dict[str, Any],
        near_futures: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        value = safe_str(regime.get("regime"), "mixed_neutral").lower()
        ready = safe_int(futures_summary.get("would_confirm_now"), 0)
        invalidated = safe_int(futures_summary.get("invalidated"), 0)

        if "risk_off" in value or "bear" in value:
            title = "Осторожный рынок с медвежьим уклоном"
            main_text = "Рынок сейчас находится в защитном режиме. LONG-сделки снижены, SHORT разрешён выборочно. Кандидаты оцениваются строго, без форсирования входов."
        elif "risk_on" in value or "bull" in value:
            title = "Рынок в режиме risk-on"
            main_text = "Фон поддерживает активный отбор. LONG-сценарии получают больше поддержки, но каждый вход всё равно должен пройти подтверждение и защитные фильтры."
        else:
            title = "Смешанный рынок без чёткого преимущества"
            main_text = "Рынок неоднородный: часть монет поддерживает LONG, часть SHORT. VORTEX ждёт более ясного подтверждения перед входом."

        if ready > 0:
            why = f"Есть кандидаты, готовые к decision-loop: {ready}. Нужно проверить события confirmed -> decision и итог open/reject."
            recommendation = "Следить за decision-loop. Не форсировать вход вручную."
        else:
            why = f"Готовых futures-входов сейчас нет: would_confirm_now = 0. Кандидаты ждут trigger или buffer; invalidated: {invalidated}. Это режим ожидания подтверждения, а не ошибка."
            recommendation = "Ждать подтверждения. Не форсировать входы."

        return {
            "title": title,
            "status": value,
            "main_text": main_text,
            "why_no_trade": why,
            "what_to_watch": [safe_str(x.get("symbol"), "") for x in near_futures[:5] if x.get("symbol")],
            "recommendation": recommendation,
        }


    # --- VORTEX v1.8.24-e COIN LIQUIDITY SHADOW API ---
    def _read_coin_liquidity_payload_1824e(self) -> Dict[str, Any]:
        import json as _json
        from pathlib import Path as _Path

        path = _Path("_runtime/coin_liquidity_latest.json")
        fallback = {
            "available": False,
            "read_only": True,
            "schema": "vortex.coin_liquidity.shadow.v1",
            "reason": "no_runtime_file",
            "items": [],
            "errors": [],
        }
        try:
            if not path.exists():
                return fallback
            data = _json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                fallback["reason"] = "invalid_runtime_json_root"
                return fallback
            data["read_only"] = True
            data.setdefault("available", bool(data.get("items")))
            data.setdefault("items", [])
            data.setdefault("errors", [])
            return data
        except Exception as exc:
            fallback["reason"] = f"runtime_read_error:{exc}"
            return fallback

    def _market_pulse_coin_liquidity_1824e(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from collections import Counter

        payload = payload if isinstance(payload, dict) else {}
        items = [x for x in (payload.get("items") or []) if isinstance(x, dict)]
        items.sort(key=lambda x: safe_float(x.get("confidence"), 0.0), reverse=True)
        counts = Counter(safe_str(x.get("liquidity_bias"), "unknown") for x in items)
        return {
            "available": bool(payload.get("available")),
            "read_only": True,
            "stale": bool(payload.get("stale")),
            "age_sec": safe_float(payload.get("age_sec"), 0.0),
            "items_len": len(items),
            "bias_counts": dict(counts),
            "top_items": items[:20],
            "errors": (payload.get("errors") or [])[:10],
        }

    async def handle_coin_liquidity_1824e(self, request: web.Request) -> web.Response:
        payload = self._read_coin_liquidity_payload_1824e()
        return web.json_response({
            "ok": True,
            "schema": "vortex.coin_liquidity.api.v1",
            "read_only": True,
            "available": bool(payload.get("available")),
            "data": payload,
        }, headers={"Cache-Control": "no-store"})
    # --- END VORTEX v1.8.24-e COIN LIQUIDITY SHADOW API ---

    async def _build_market_pulse_payload_1824b(self) -> Dict[str, Any]:
        dashboard = await self._build_dashboard_payload()
        health = await self.state.get_health_state(mode=self.mode)
        health = health if isinstance(health, dict) else {}

        now_ts = time.time()
        uptime_sec = int(max(0, now_ts - SERVER_STARTED_AT))
        health_out = {
            "status": health.get("status"),
            "mode": health.get("mode") or self.mode,
            "uptime": _format_uptime_human_21li(uptime_sec),
            "market_age_sec": safe_float(health.get("market_age_sec"), 9999.0),
            "ta_age_sec": safe_float(health.get("ta_age_sec"), 9999.0),
        }
        health_out["fresh"] = health_out["market_age_sec"] <= 10.0 and health_out["ta_age_sec"] <= 15.0

        raw_items = dashboard.get("terminal", {}).get("watchlist_mini", []) or []
        items = self._dedupe_watchlist_items(raw_items)
        futures = [x for x in items if safe_str(x.get("market"), "").lower() == "fut"]
        spot = [x for x in items if safe_str(x.get("market"), "").lower() == "spot"]
        futures_summary = self._market_pulse_watch_summary_1824b(futures)
        spot_summary = self._market_pulse_watch_summary_1824b(spot)
        near_futures = self._market_pulse_near_entries_1824b(futures, 15)
        near_spot = self._market_pulse_near_entries_1824b(spot, 10)

        macro = dashboard.get("macro_regime") if isinstance(dashboard.get("macro_regime"), dict) else self._read_macro_regime_payload()
        regime = self._market_pulse_regime_1824b(macro)
        fusion = self._market_pulse_context_fusion_1824b(dashboard.get("context_fusion") or {})
        risk = self.risk_manager.get_status() if self.risk_manager else {}
        risk = risk if isinstance(risk, dict) else {}

        return {
            "ok": True,
            "schema": "vortex.market_pulse.api.v1",
            "schema_version": "1.8.24-b",
            "ts": now_ts,
            "health": health_out,
            "portfolio": dashboard.get("portfolio") if isinstance(dashboard.get("portfolio"), dict) else {},
            "positions": dashboard.get("positions") if isinstance(dashboard.get("positions"), dict) else {"fut": {}, "spot": {}},
            "risk": risk,
            "market_regime": regime,
            "context_fusion": fusion,
            "watchlist": {"futures": futures_summary, "spot": spot_summary},
            "near_entries": {"futures": near_futures, "spot": near_spot},
            "pump_advisor": self._market_pulse_pump_1824b(self._read_pump_short_advisor_payload()),
            "coin_liquidity": self._market_pulse_coin_liquidity_1824e(self._read_coin_liquidity_payload_1824e()),
            "recent_events": {"available": False, "reason": "not_implemented_in_api"},
            "human_summary": self._market_pulse_human_summary_1824b(regime, futures_summary, near_futures),
        }

    async def handle_market_pulse_1824b(self, request: web.Request) -> web.Response:
        payload = await self._build_market_pulse_payload_1824b()
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def handle_market_analytics_page_1824b(self, request: web.Request) -> web.Response:
        from pathlib import Path as _Path

        path = _Path("web/market_analytics.html")
        headers = {
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        }
        if not path.exists():
            return web.Response(text="<html><body><h1>VORTEX MARKET PULSE</h1><p>HTML file not found.</p></body></html>", content_type="text/html", charset="utf-8", headers=headers, status=404)
        return web.Response(text=path.read_text(encoding="utf-8"), content_type="text/html", charset="utf-8", headers=headers)
    # --- END VORTEX v1.8.24-b MARKET ANALYTICS PAGE ---

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
        payload = await self.state.get_health_state(mode=self.mode)

        # VORTEX v1.8.21l-i-r3:
        # Android compatibility: current app reads "uptime".
        # Therefore "uptime" must be a human-readable duration, not just "active".
        try:
            if not isinstance(payload, dict):
                payload = {}

            now_ts = time.time()
            uptime_sec = int(max(0, now_ts - SERVER_STARTED_AT))
            uptime_human = _format_uptime_human_21li(uptime_sec)

            payload["started_at"] = int(SERVER_STARTED_AT)
            payload["uptime_sec"] = uptime_sec
            payload["uptime_human"] = uptime_human
            payload["uptime"] = uptime_human
            payload["server_time"] = int(now_ts)
        except Exception:
            # Never break /api/health because of uptime formatting.
            pass

        return web.json_response(payload)

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
        if self.mode != "PAPER" or not CONFIG.trading.allow_manual_trades or self.router is None:
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
        if self.mode != "PAPER" or not CONFIG.trading.allow_force_close or self.router is None:
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
        if self.mode != "PAPER" or not CONFIG.trading.allow_manual_trades or self.router is None:
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
        if self.mode != "PAPER" or not CONFIG.trading.allow_force_close or self.router is None:
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
        if self.mode != "PAPER" or not CONFIG.trading.allow_force_close or self.router is None:
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