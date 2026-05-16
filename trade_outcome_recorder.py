import json
import time
from pathlib import Path
from typing import Any, Dict

from outcome_intelligence_aggregator import build_outcome_summary

from validators import safe_float, safe_str


class TradeOutcomeRecorder:
    """
    VORTEX v1.8.10_fix Trade Outcome Recorder.
    Analytics-only close-event recorder.
    """

    def __init__(self, path: str = "_runtime/trade_outcomes.jsonl", logger=None) -> None:
        self.path = Path(path)
        self.logger = logger
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _safe_dict(self, value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _result_label(self, pnl_net: float) -> str:
        if pnl_net > 0:
            return "WIN"
        if pnl_net < 0:
            return "LOSS"
        return "FLAT"

    # v1.8.11 CLOSE REASON INTELLIGENCE
    def _close_reason_intelligence(self, reason: str, pnl_net: float, fallback_pos: Dict[str, Any]) -> Dict[str, Any]:
        reason_u = safe_str(reason).upper()
        fp = self._safe_dict(fallback_pos)
        tp1_hit = bool(fp.get("tp1_hit", False))
        breakeven = bool(fp.get("breakeven", False))

        group = "unknown"
        detail = "unknown"
        lifecycle = "unknown"
        protection_effect = "unknown"

        if reason_u in {"TP2", "TP", "TP1"}:
            group = "profit_target"
            detail = reason_u.lower()
            lifecycle = "target_exit"
            protection_effect = "not_applicable"
        elif reason_u == "SL":
            group = "stop_loss"
            detail = "hard_stop_loss"
            lifecycle = "failed_setup"
            protection_effect = "not_applicable"
        elif reason_u in {"BU", "BE", "BREAKEVEN"}:
            group = "protective_exit"
            detail = "breakeven_exit"
            protection_effect = "protected_capital" if pnl_net >= 0 else "cost_or_fee_loss"
            if tp1_hit:
                lifecycle = "tp1_then_breakeven"
            elif breakeven:
                lifecycle = "breakeven_without_tp1_marker"
            else:
                lifecycle = "early_breakeven_or_fee_exit"
        elif reason_u == "STALL":
            group = "time_or_momentum_exit"
            detail = "stall_exit"
            lifecycle = "no_follow_through"
            protection_effect = "neutral_or_manual_logic"
        elif pnl_net > 0:
            group = "positive_exit"
            detail = reason_u.lower() or "positive_unknown"
            lifecycle = "positive_unknown"
            protection_effect = "unknown"
        elif pnl_net < 0:
            group = "negative_exit"
            detail = reason_u.lower() or "negative_unknown"
            lifecycle = "negative_unknown"
            protection_effect = "unknown"
        else:
            group = "flat_exit"
            detail = reason_u.lower() or "flat_unknown"
            lifecycle = "flat_unknown"
            protection_effect = "unknown"

        return {
            "close_reason_raw": reason_u,
            "close_reason_group": group,
            "close_reason_detail": detail,
            "trade_lifecycle": lifecycle,
            "protection_effect": protection_effect,
            "tp1_hit": tp1_hit,
            "breakeven": breakeven,
        }

    # v1.8.12a BREAKEVEN DIAGNOSTIC LAYER
    def _breakeven_diagnostics(self, *, reason: str, side: str, entry: float, exit_price: float, pnl_net: float, hold_sec: int, fallback_pos: Dict[str, Any]) -> Dict[str, Any]:
        fp = self._safe_dict(fallback_pos)
        reason_u = safe_str(reason).upper()
        side_u = safe_str(side).upper()
        tp = safe_float(fp.get("tp"), 0.0)
        tp2 = safe_float(fp.get("tp2"), 0.0)
        sl = safe_float(fp.get("sl"), 0.0)
        tp1_hit = bool(fp.get("tp1_hit", False))
        breakeven = bool(fp.get("breakeven", False)) or reason_u in {"BU", "BE", "BREAKEVEN"}

        exit_from_entry_pct = 0.0
        tp_distance_pct = 0.0
        sl_distance_pct = 0.0
        tp2_distance_pct = 0.0

        if entry > 0 and exit_price > 0:
            if side_u == "SHORT":
                exit_from_entry_pct = (entry - exit_price) / entry * 100.0
            else:
                exit_from_entry_pct = (exit_price - entry) / entry * 100.0

        if entry > 0 and tp > 0:
            tp_distance_pct = abs(tp - entry) / entry * 100.0
        if entry > 0 and tp2 > 0:
            tp2_distance_pct = abs(tp2 - entry) / entry * 100.0
        if entry > 0 and sl > 0:
            sl_distance_pct = abs(sl - entry) / entry * 100.0

        if reason_u in {"BU", "BE", "BREAKEVEN"}:
            if pnl_net < 0:
                be_quality = "fee_loss_or_noise_exit"
            elif pnl_net == 0:
                be_quality = "flat_protection"
            else:
                be_quality = "positive_protection"
        else:
            be_quality = "not_breakeven_exit"

        suspected_early_be = False
        if reason_u in {"BU", "BE", "BREAKEVEN"}:
            if hold_sec < 180:
                suspected_early_be = True
            if tp_distance_pct > 0 and abs(exit_from_entry_pct) < max(0.12, tp_distance_pct * 0.35):
                suspected_early_be = True

        return {
            "is_breakeven_exit": reason_u in {"BU", "BE", "BREAKEVEN"},
            "breakeven_flag": breakeven,
            "tp1_hit_before_exit": tp1_hit,
            "be_quality": be_quality,
            "suspected_early_be": suspected_early_be,
            "exit_from_entry_pct": round(exit_from_entry_pct, 6),
            "tp_distance_pct": round(tp_distance_pct, 6),
            "tp2_distance_pct": round(tp2_distance_pct, 6),
            "sl_distance_pct": round(sl_distance_pct, 6),
            "hold_sec": hold_sec,
            "diagnostic_note": "analytics_only_no_execution_change",
        }

    # v1.8.13a ADAPTIVE BE SHADOW EVALUATOR
    def _adaptive_be_shadow(self, *, reason: str, side: str, setup_type: str, pnl_net: float, hold_sec: int, be_diag: Dict[str, Any], fallback_pos: Dict[str, Any]) -> Dict[str, Any]:
        reason_u = safe_str(reason).upper()
        setup_l = safe_str(setup_type).lower()
        is_momentum = "momentum" in setup_l
        is_trend = "trend" in setup_l
        is_be_exit = reason_u in {"BU", "BE", "BREAKEVEN"}
        be_quality = safe_str(be_diag.get("be_quality"))
        suspected_early_be = bool(be_diag.get("suspected_early_be", False))
        exit_from_entry_pct = safe_float(be_diag.get("exit_from_entry_pct"), 0.0)
        tp_distance_pct = safe_float(be_diag.get("tp_distance_pct"), 0.0)
        current_be_trigger = is_be_exit
        adaptive_be_trigger = current_be_trigger
        recommendation = "keep_current_policy"
        confidence = "low"
        reasons = []
        if is_be_exit and is_momentum:
            if hold_sec < 600 or suspected_early_be or be_quality == "fee_loss_or_noise_exit":
                adaptive_be_trigger = False
                recommendation = "delay_be_for_momentum"
                confidence = "medium"
                reasons.append("momentum_setup_needs_more_room")
                if hold_sec < 600:
                    reasons.append("hold_sec_under_600")
                if suspected_early_be:
                    reasons.append("suspected_early_be")
                if be_quality == "fee_loss_or_noise_exit":
                    reasons.append("be_exit_created_fee_or_noise_loss")
        elif is_be_exit and is_trend:
            if be_quality == "fee_loss_or_noise_exit" and hold_sec < 300:
                adaptive_be_trigger = False
                recommendation = "delay_be_for_early_trend_noise"
                confidence = "medium"
                reasons.append("trend_be_too_early")
            else:
                adaptive_be_trigger = True
                recommendation = "keep_be_for_trend_protection"
                reasons.append("trend_setup_allows_protection")
        elif not is_be_exit:
            recommendation = "not_a_be_exit_observe_only"
            reasons.append("close_reason_not_breakeven")
        would_have_delayed_be = current_be_trigger and not adaptive_be_trigger
        potential_fee_loss_avoided = abs(pnl_net) if would_have_delayed_be and pnl_net < 0 else 0.0
        return {
            "mode": "shadow_only",
            "current_be_trigger": current_be_trigger,
            "adaptive_be_trigger": adaptive_be_trigger,
            "would_have_delayed_be": would_have_delayed_be,
            "recommendation": recommendation,
            "confidence": confidence,
            "reasons": sorted(list(set(reasons))),
            "setup_family": "momentum" if is_momentum else ("trend" if is_trend else "other"),
            "hold_sec": hold_sec,
            "exit_from_entry_pct": round(exit_from_entry_pct, 6),
            "tp_distance_pct": round(tp_distance_pct, 6),
            "potential_fee_loss_avoided": round(potential_fee_loss_avoided, 8),
            "note": "analytics_only_no_execution_change",
        }

    def record_close(self, *, data: Dict[str, Any], fallback_pos: Dict[str, Any], market: str) -> Dict[str, Any]:
        data = self._safe_dict(data)
        fallback_pos = self._safe_dict(fallback_pos)

        symbol = safe_str(data.get("symbol") or fallback_pos.get("symbol")).upper()
        side = safe_str(data.get("side") or fallback_pos.get("side")).upper()
        market_u = safe_str(market).upper()

        entry = safe_float(data.get("entry") or fallback_pos.get("entry"), 0.0)
        exit_price = safe_float(data.get("exit_price") or data.get("price"), 0.0)
        pnl = safe_float(data.get("pnl"), 0.0)
        pnl_net = safe_float(data.get("pnl_net"), pnl)
        reason = safe_str(data.get("reason"), "CLOSE")
        hold_sec = int(safe_float(data.get("hold_sec"), 0.0))
        close_intel = self._close_reason_intelligence(reason, pnl_net, fallback_pos)
        be_diag = self._breakeven_diagnostics(
            reason=reason,
            side=side,
            entry=entry,
            exit_price=exit_price,
            pnl_net=pnl_net,
            hold_sec=hold_sec,
            fallback_pos=fallback_pos,
        )
        adaptive_be_shadow = self._adaptive_be_shadow(
            reason=reason,
            side=side,
            setup_type=safe_str(data.get("setup_type") or fallback_pos.get("setup_type")),
            pnl_net=pnl_net,
            hold_sec=hold_sec,
            be_diag=be_diag,
            fallback_pos=fallback_pos,
        )

        opened_at = safe_float(fallback_pos.get("opened_at") or fallback_pos.get("open_ts"), 0.0)
        close_ts = time.time()
        if hold_sec <= 0 and opened_at > 0:
            hold_sec = max(0, int(close_ts - opened_at))

        pnl_pct = 0.0
        if entry > 0 and exit_price > 0:
            if side == "SHORT":
                pnl_pct = (entry - exit_price) / entry * 100.0
            else:
                pnl_pct = (exit_price - entry) / entry * 100.0

        snapshot = {
            "schema": "vortex.trade_outcome.v1",
            "schema_version": "1.8.13a",
            "event": "CLOSE",
            "ts": close_ts,
            "ts_ms": int(close_ts * 1000),
            "symbol": symbol,
            "market": market_u,
            "side": side,
            "setup_type": safe_str(data.get("setup_type") or fallback_pos.get("setup_type")),
            "args_text": safe_str(data.get("args_text") or fallback_pos.get("args_text")),
            "entry": entry,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_net": pnl_net,
            "pnl_pct_est": round(pnl_pct, 6),
            "result": self._result_label(pnl_net),
            "close_reason": reason,
            "close_intelligence": close_intel,
            "breakeven_diagnostics": be_diag,
            "adaptive_be_shadow": adaptive_be_shadow,
            "close_reason_group": close_intel.get("close_reason_group"),
            "trade_lifecycle": close_intel.get("trade_lifecycle"),
            "protection_effect": close_intel.get("protection_effect"),
            "hold_sec": hold_sec,
            "position": {
                "tp": safe_float(fallback_pos.get("tp"), 0.0),
                "tp2": safe_float(fallback_pos.get("tp2"), 0.0),
                "sl": safe_float(fallback_pos.get("sl"), 0.0),
                "atr": safe_float(fallback_pos.get("atr"), 0.0),
                "tp1_hit": bool(fallback_pos.get("tp1_hit", False)),
                "breakeven": bool(fallback_pos.get("breakeven", False)),
            },
            "raw_close_keys": sorted(list(data.keys()))[:120],
            "raw_position_keys": sorted(list(fallback_pos.keys()))[:120],
        }

        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n")

            if self.logger:
                self.logger.info("ANALYTICS", "trade outcome recorded", {
                    "symbol": symbol,
                    "market": market_u,
                    "side": side,
                    "setup_type": snapshot["setup_type"],
                    "result": snapshot["result"],
                    "reason": reason,
                    "pnl_net": pnl_net,
                    "pnl_pct_est": snapshot["pnl_pct_est"],
                    "hold_sec": hold_sec,
                    "close_reason_group": close_intel.get("close_reason_group"),
                    "trade_lifecycle": close_intel.get("trade_lifecycle"),
                    "protection_effect": close_intel.get("protection_effect"),
                    "be_quality": be_diag.get("be_quality"),
                    "suspected_early_be": be_diag.get("suspected_early_be"),
                    "exit_from_entry_pct": be_diag.get("exit_from_entry_pct"),
                    "adaptive_be_recommendation": adaptive_be_shadow.get("recommendation"),
                    "adaptive_be_delay": adaptive_be_shadow.get("would_have_delayed_be"),
                    "adaptive_be_confidence": adaptive_be_shadow.get("confidence"),
                    "path": str(self.path),
                })
            # v1.8.14a OUTCOME INTELLIGENCE AGGREGATOR HOOK
            try:
                build_outcome_summary(logger=self.logger)
            except Exception as agg_exc:
                if self.logger:
                    try:
                        self.logger.warning("ANALYTICS", "outcome summary update failed", {
                            "symbol": symbol,
                            "market": market_u,
                            "error": str(agg_exc),
                        })
                    except Exception:
                        pass

        except Exception as exc:
            if self.logger:
                try:
                    self.logger.warning("ANALYTICS", "trade outcome write failed", {
                        "symbol": symbol,
                        "market": market_u,
                        "error": str(exc),
                    })
                except Exception:
                    pass

        return snapshot

