import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from validators import safe_float, safe_str


class TradeSnapshotRecorder:
    """
    VORTEX v1.8.9d Planner/Futures Context Enrichment.
    Analytics-only, append-only JSONL recorder.
    """

    def __init__(self, path: str = "_runtime/trade_snapshots.jsonl", logger=None) -> None:
        self.path = Path(path)
        self.logger = logger
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _safe_dict(self, value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _filtered(self, data: Dict[str, Any], keys) -> Dict[str, Any]:
        data = self._safe_dict(data)
        return {k: data.get(k) for k in keys if k in data}

    def _parse_args_metrics(self, text: str) -> Dict[str, float]:
        text = safe_str(text)
        out: Dict[str, float] = {}
        for key, pattern in {
            "range_pct": r"range=([-+]?\d+(?:\.\d+)?)%",
            "change_pct": r"change=([-+]?\d+(?:\.\d+)?)%",
            "volume_ratio": r"vol=([-+]?\d+(?:\.\d+)?)",
            "score": r"score=([-+]?\d+(?:\.\d+)?)",
        }.items():
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                out[key] = safe_float(m.group(1), 0.0)
        return out

    def _derive_signal(self, analysis: Dict[str, Any], side: str) -> str:
        explicit = safe_str(analysis.get("signal")).upper()
        if explicit:
            return explicit
        side_u = safe_str(side).upper()
        if side_u:
            return "LONG" if side_u == "BUY" else side_u
        setup = safe_str(analysis.get("setup_type")).lower()
        if "short" in setup:
            return "SHORT"
        if "long" in setup or "spot" in setup:
            return "LONG"
        return ""

    def _derive_trend(self, current: Dict[str, Any], analysis: Dict[str, Any], side: str) -> str:
        explicit = safe_str(current.get("trend") or analysis.get("trend")).upper()
        if explicit:
            return explicit
        ema20 = safe_float(current.get("ema20"), 0.0)
        ema50 = safe_float(current.get("ema50"), 0.0)
        price = safe_float(current.get("price"), 0.0)
        if ema20 > 0 and ema50 > 0:
            if ema20 < ema50 and price <= ema20:
                return "BEARISH"
            if ema20 > ema50 and price >= ema20:
                return "BULLISH"
            if ema20 < ema50:
                return "BEARISH_PULLBACK"
            if ema20 > ema50:
                return "BULLISH_PULLBACK"
        signal = self._derive_signal(analysis, side)
        if signal == "SHORT":
            return "BEARISH_DERIVED"
        if signal == "LONG":
            return "BULLISH_DERIVED"
        return ""

    # v1.8.9e RSI/VOLUME DIAGNOSTICS
    def _value_source(self, current: Dict[str, Any], key: str, parsed: Dict[str, float] = None, parsed_key: str = None) -> str:
        try:
            if key in current and safe_float(current.get(key), 0.0) != 0.0:
                return "current"
            if parsed is not None and parsed_key and safe_float(parsed.get(parsed_key), 0.0) != 0.0:
                return "args_text"
            if key in current:
                return "current_zero_or_empty"
            return "missing"
        except Exception:
            return "error"

    def _rsi_status(self, current: Dict[str, Any]) -> str:
        try:
            if "rsi" not in current:
                return "missing_from_ta"
            val = safe_float(current.get("rsi"), 0.0)
            if val == 0.0:
                return "zero_or_not_computed"
            if val < 5.0 or val > 95.0:
                return "extreme_value"
            return "ok"
        except Exception:
            return "error"

    def _ta_snapshot(self, current: Dict[str, Any], analysis: Dict[str, Any], side: str) -> Dict[str, Any]:
        current = self._safe_dict(current)
        analysis = self._safe_dict(analysis)
        parsed = self._parse_args_metrics(safe_str(analysis.get("args_text") or current.get("args_text")))

        price = safe_float(current.get("price"), 0.0)
        atr = safe_float(current.get("atr"), 0.0)

        raw_trend = safe_str(current.get("trend"))
        raw_signal = safe_str(current.get("signal"))
        raw_timeframe = safe_str(current.get("timeframe"))

        volume_ratio = safe_float(current.get("volume_ratio"), 0.0) or safe_float(parsed.get("volume_ratio"), 0.0)
        change_pct = safe_float(current.get("change_pct"), 0.0) or safe_float(parsed.get("change_pct"), 0.0)
        range_pct = safe_float(current.get("range_pct"), 0.0) or safe_float(parsed.get("range_pct"), 0.0)

        rsi_source = self._value_source(current, "rsi")
        rsi_status = self._rsi_status(current)
        volume_source = self._value_source(current, "volume")
        volume_ratio_source = self._value_source(current, "volume_ratio", parsed, "volume_ratio")
        change_pct_source = self._value_source(current, "change_pct", parsed, "change_pct")
        range_pct_source = self._value_source(current, "range_pct", parsed, "range_pct")

        trend = self._derive_trend(current, analysis, side)
        signal = self._derive_signal(analysis, side)
        timeframe = raw_timeframe or "runtime_mixed"

        derived = []
        if trend and not raw_trend:
            derived.append("trend")
        if signal and not raw_signal:
            derived.append("signal")
        if timeframe and not raw_timeframe:
            derived.append("timeframe")
        if volume_ratio and not safe_float(current.get("volume_ratio"), 0.0):
            derived.append("volume_ratio")
        if change_pct and not safe_float(current.get("change_pct"), 0.0):
            derived.append("change_pct")
        if range_pct and not safe_float(current.get("range_pct"), 0.0):
            derived.append("range_pct")

        return {
            "price": price,
            "atr": atr,
            "atr_pct": round((atr / price * 100.0), 6) if price > 0 and atr > 0 else 0.0,
            "rsi": safe_float(current.get("rsi"), 0.0),
            "ema20": safe_float(current.get("ema20"), 0.0),
            "ema50": safe_float(current.get("ema50"), 0.0),
            "ema_gap_pct": safe_float(current.get("ema_gap_pct"), 0.0),
            "adx": safe_float(current.get("adx"), 0.0),
            "volume": safe_float(current.get("volume"), 0.0),
            "volume_ratio": volume_ratio,
            "change_pct": change_pct,
            "range_pct": range_pct,
            "trend": trend,
            "signal": signal,
            "timeframe": timeframe,
            "raw_trend": raw_trend,
            "raw_signal": raw_signal,
            "raw_timeframe": raw_timeframe,
            "derived_fields": sorted(set(derived)),
            "source_keys": sorted(list(current.keys()))[:120],
            "parsed_from_args": parsed,
            "rsi_source": rsi_source,
            "rsi_status": rsi_status,
            "volume_source": volume_source,
            "volume_ratio_source": volume_ratio_source,
            "change_pct_source": change_pct_source,
            "range_pct_source": range_pct_source,
        }

    def _planner_context(self, market: str, side: str, setup_type: str, planner_idea: Dict[str, Any]) -> Dict[str, Any]:
        idea = self._safe_dict(planner_idea)
        market_u = safe_str(market).upper()
        side_u = safe_str(side).upper()
        if side_u == "BUY":
            side_u = "LONG"

        ctx = {
            "present": bool(idea),
            "type": "none",
            "alignment": "no_planner",
            "conflict": False,
            "notes": [],
        }
        if not idea:
            return ctx

        planner_setup = safe_str(idea.get("setup_type")).lower()
        planner_side = safe_str(idea.get("side") or idea.get("signal")).upper()

        if market_u == "FUT" and planner_setup.startswith("spot_"):
            ctx["type"] = "spot_planner_on_futures"
            ctx["notes"].append("spot planner context attached to futures trade")
        else:
            ctx["type"] = "market_planner"

        planner_bias = planner_side
        if not planner_bias:
            if "short" in planner_setup:
                planner_bias = "SHORT"
            elif "long" in planner_setup or "spot" in planner_setup or "pullback" in planner_setup:
                planner_bias = "LONG"

        ctx["planner_bias"] = planner_bias
        ctx["trade_bias"] = side_u

        if planner_bias and side_u:
            if planner_bias == side_u:
                ctx["alignment"] = "aligned"
            else:
                ctx["alignment"] = "opposite"
                ctx["conflict"] = True
                ctx["notes"].append(f"planner_bias={planner_bias} trade_bias={side_u}")

        if market_u == "FUT" and side_u == "SHORT" and planner_setup.startswith("spot_"):
            ctx["alignment"] = "context_conflict" if not ctx["conflict"] else ctx["alignment"]
            ctx["conflict"] = True
            ctx["notes"].append("futures short while spot planner idea exists")

        return ctx

    def _data_quality(self, current: Dict[str, Any], analysis: Dict[str, Any], planner_idea: Dict[str, Any], ta: Dict[str, Any], planner_ctx: Dict[str, Any]) -> Dict[str, Any]:
        missing = []
        warnings = []
        derived = ta.get("derived_fields", []) or []

        for key in ["price", "atr", "atr_pct", "adx", "volume_ratio", "change_pct", "range_pct"]:
            if safe_float(ta.get(key), 0.0) == 0.0:
                missing.append(key)
        if safe_float(ta.get("rsi"), 0.0) == 0.0:
            missing.append("rsi")
        if not planner_idea:
            missing.append("planner")
        if not safe_str(ta.get("trend")):
            missing.append("trend")
        if not safe_str(ta.get("signal")):
            missing.append("signal")
        if not safe_str(ta.get("timeframe")):
            missing.append("timeframe")
        if planner_ctx.get("conflict"):
            warnings.append("planner_trade_conflict")
        if "volume_ratio" in derived:
            warnings.append("volume_ratio_parsed_from_args")

        if ta.get("rsi_status") in {"missing_from_ta", "zero_or_not_computed"}:
            warnings.append("rsi_not_available")

        if ta.get("volume_ratio_source") == "missing":
            warnings.append("volume_ratio_missing")
        elif ta.get("volume_ratio_source") == "args_text":
            warnings.append("volume_ratio_parsed_from_args")

        score = max(0, 100 - len(set(missing)) * 8 - len(set(derived)) * 3 - len(set(warnings)) * 5)
        return {
            "score": score,
            "missing_fields": sorted(set(missing)),
            "derived_fields": sorted(set(derived)),
            "warnings": sorted(set(warnings)),
            "has_planner": bool(planner_idea),
            "planner_conflict": bool(planner_ctx.get("conflict")),
            "current_keys_count": len(list(current.keys())) if isinstance(current, dict) else 0,
            "analysis_keys_count": len(list(analysis.keys())) if isinstance(analysis, dict) else 0,
            "version": "v1.8.9e",
        }

    def record_open(
        self, *, symbol: str, market: str, side: str, result: Dict[str, Any],
        current: Dict[str, Any], analysis: Dict[str, Any], watch: Dict[str, Any],
        planner_idea: Optional[Dict[str, Any]] = None, ladder: Optional[Dict[str, Any]] = None,
        risk_status: Optional[Dict[str, Any]] = None, macro_filter: Any = None,
        order: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = self._safe_dict(result)
        data = self._safe_dict(result.get("data"))
        current = self._safe_dict(current)
        analysis = self._safe_dict(analysis)
        watch = self._safe_dict(watch)
        planner_idea = self._safe_dict(planner_idea)
        ladder = self._safe_dict(ladder)
        risk_status = self._safe_dict(risk_status)
        order = self._safe_dict(order)

        setup_type = safe_str(analysis.get("setup_type"))
        ta = self._ta_snapshot(current, analysis, side)
        planner_ctx = self._planner_context(market, side, setup_type, planner_idea)
        dq = self._data_quality(current, analysis, planner_idea, ta, planner_ctx)

        ts = time.time()
        snapshot = {
            "schema": "vortex.trade_snapshot.v1",
            "schema_version": "1.8.9e",
            "event": "OPEN",
            "ts": ts,
            "ts_ms": int(ts * 1000),
            "symbol": safe_str(symbol).upper(),
            "market": safe_str(market).upper(),
            "side": safe_str(side).upper(),
            "entry": safe_float(data.get("entry") or order.get("entry") or current.get("price"), 0.0),
            "qty": safe_float(data.get("qty") or order.get("qty"), 0.0),
            "setup_type": setup_type,
            "args_text": safe_str(analysis.get("args_text")),
            "macro_filter": macro_filter,
            "ta": ta,
            "data_quality": dq,
            "analysis": self._filtered(analysis, ["should_open", "setup_type", "args_text", "score", "signal", "side", "blocked_reason", "confirmation_status", "confirmation_reason", "trigger_price", "invalidation_price"]),
            "watch": self._filtered(watch, ["symbol", "market", "side", "status", "setup_type", "score", "trigger_price", "confirmed", "confirmation_reason", "confirmation_status", "priority"]),
            "planner": self._filtered(planner_idea, ["symbol", "side", "setup_type", "score", "rank", "reason", "tp_base", "sl_base", "entry_zone", "trend", "signal", "market_regime"]),
            "planner_context": planner_ctx,
            "planner_present": bool(planner_idea),
            "ladder": {"tp0": safe_float(ladder.get("tp0"), 0.0), "tp": safe_float(ladder.get("tp"), 0.0), "tp2": safe_float(ladder.get("tp2"), 0.0), "sl": safe_float(ladder.get("sl"), 0.0), "leverage": safe_float(ladder.get("leverage"), 0.0)},
            "risk": self._filtered(risk_status, ["block_new_entries", "block_reason", "daily_realized_pnl", "daily_loss_limit_usdt", "day", "max_open_futures_positions", "max_open_spot_positions"]),
            "order": order,
            "result_code": safe_str(result.get("code")),
        }

        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n")
            if self.logger:
                self.logger.info("ANALYTICS", "trade snapshot recorded", {
                    "symbol": snapshot["symbol"], "market": snapshot["market"], "side": snapshot["side"],
                    "setup_type": snapshot["setup_type"], "quality_score": dq.get("score"),
                    "missing_fields": dq.get("missing_fields"), "derived_fields": dq.get("derived_fields"),
                    "warnings": dq.get("warnings"), "planner_alignment": planner_ctx.get("alignment"),
                    "planner_conflict": planner_ctx.get("conflict"), "path": str(self.path),
                })
        except Exception as exc:
            if self.logger:
                try:
                    self.logger.warning("ANALYTICS", "trade snapshot write failed", {"symbol": snapshot["symbol"], "market": snapshot["market"], "error": str(exc)})
                except Exception:
                    pass
        # --- VORTEX v1.8.19d ENTRY ARGUMENT RECORDER HOOK ---
        try:
            from entry_argument_recorder import EntryArgumentRecorder
            EntryArgumentRecorder(logger=self.logger).record(snapshot)
        except Exception as exc:
            if self.logger:
                try:
                    self.logger.warning("ANALYTICS", "entry argument record failed", {"symbol": snapshot.get("symbol"), "error": str(exc)})
                except Exception:
                    pass
        # --- END VORTEX v1.8.19d ENTRY ARGUMENT RECORDER HOOK ---
        return snapshot

