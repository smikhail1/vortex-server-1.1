import json
import time
from pathlib import Path
from typing import Dict, Any, List


class ShadowPolicySimulator:
    """
    VORTEX v1.8.18 Shadow Policy Simulator.

    Analytics-only.
    Compares real outcomes against candidate BE-delay policies.
    Does NOT change execution, risk, strategy, confirmation, or trade management.
    """

    def __init__(
        self,
        outcomes_path: str = "_runtime/trade_outcomes.jsonl",
        candidates_path: str = "_runtime/adaptive_be_candidates.json",
        output_path: str = "_runtime/shadow_policy_simulation.json",
    ) -> None:
        self.outcomes_path = Path(outcomes_path)
        self.candidates_path = Path(candidates_path)
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _load_outcomes(self) -> List[Dict[str, Any]]:
        if not self.outcomes_path.exists():
            return []
        rows = []
        for line in self.outcomes_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
        return rows

    def _candidate_delays(self, setup: str, candidates: Dict[str, Any]) -> List[int]:
        setup_block = (candidates.get("candidates") or {}).get(setup) or {}
        vals = []
        for item in setup_block.get("candidates") or []:
            try:
                vals.append(int(item.get("delay_sec")))
            except Exception:
                pass
        vals = sorted(set(vals))
        if vals:
            return vals
        setup_l = setup.lower()
        if "momentum" in setup_l:
            return [120, 240, 360, 600]
        if "trend" in setup_l:
            return [30, 60, 120, 240]
        return [60, 120, 240]

    def _simulate_row_for_delay(self, row: Dict[str, Any], delay_sec: int) -> Dict[str, Any]:
        real_pnl = float(row.get("pnl_net", 0.0) or 0.0)
        reason = str(row.get("close_reason", "")).upper()
        setup = str(row.get("setup_type") or "UNKNOWN")
        hold_sec = int(row.get("hold_sec", 0) or 0)

        shadow = row.get("adaptive_be_shadow")
        be_diag = row.get("breakeven_diagnostics")
        shadow = shadow if isinstance(shadow, dict) else {}
        be_diag = be_diag if isinstance(be_diag, dict) else {}

        is_be = reason in {"BU", "BE", "BREAKEVEN"}
        would_delay_base = bool(shadow.get("would_have_delayed_be", False))
        is_momentum = "momentum" in setup.lower()
        is_trend = "trend" in setup.lower()

        simulated_pnl = real_pnl
        simulated_reason = reason
        applied = False
        model = "real"

        if is_be and is_momentum:
            # If the policy delay is longer than observed hold, the BE would not have triggered yet.
            # We estimate the position had more room. This is a conservative synthetic estimate.
            if hold_sec < delay_sec or would_delay_base:
                applied = True
                model = "momentum_delay_be"
                simulated_reason = f"BE_DELAY_{delay_sec}_SHADOW"
                penalty_recovery = abs(real_pnl) if real_pnl < 0 else 0.0
                continuation_bonus = 0.025
                if hold_sec >= 300:
                    continuation_bonus += 0.015
                if hold_sec >= 600:
                    continuation_bonus += 0.02
                simulated_pnl = real_pnl + penalty_recovery + continuation_bonus

        elif is_be and is_trend:
            # Trend candidates are defensive. Delaying too much is penalized.
            if delay_sec > 120:
                applied = True
                model = "trend_over_delay_penalty"
                simulated_reason = f"BE_DELAY_{delay_sec}_RISK_SHADOW"
                simulated_pnl = real_pnl - 0.03
            elif hold_sec < delay_sec and real_pnl < 0:
                applied = True
                model = "trend_short_delay_small_recovery"
                simulated_reason = f"BE_DELAY_{delay_sec}_SHADOW"
                simulated_pnl = real_pnl + min(abs(real_pnl), 0.015)

        delta = simulated_pnl - real_pnl
        return {
            "symbol": row.get("symbol"),
            "setup_type": setup,
            "real_reason": reason,
            "simulated_reason": simulated_reason,
            "real_pnl_net": round(real_pnl, 8),
            "simulated_pnl_net": round(simulated_pnl, 8),
            "delta": round(delta, 8),
            "hold_sec": hold_sec,
            "delay_sec": delay_sec,
            "applied": applied,
            "model": model,
            "confidence": "medium" if applied and is_momentum else "low",
        }

    def _stats(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not rows:
            return {
                "count": 0,
                "applied_count": 0,
                "real_pnl": 0.0,
                "simulated_pnl": 0.0,
                "delta": 0.0,
                "improved_count": 0,
                "worse_count": 0,
                "flat_count": 0,
                "avg_delta": 0.0,
            }

        real = sum(float(r.get("real_pnl_net", 0.0) or 0.0) for r in rows)
        sim = sum(float(r.get("simulated_pnl_net", 0.0) or 0.0) for r in rows)
        improved = sum(1 for r in rows if float(r.get("delta", 0.0) or 0.0) > 0)
        worse = sum(1 for r in rows if float(r.get("delta", 0.0) or 0.0) < 0)
        flat = len(rows) - improved - worse
        applied = sum(1 for r in rows if bool(r.get("applied")))

        return {
            "count": len(rows),
            "applied_count": applied,
            "real_pnl": round(real, 8),
            "simulated_pnl": round(sim, 8),
            "delta": round(sim - real, 8),
            "improved_count": improved,
            "worse_count": worse,
            "flat_count": flat,
            "avg_delta": round((sim - real) / len(rows), 8) if rows else 0.0,
        }

    def build(self) -> Dict[str, Any]:
        outcomes = self._load_outcomes()
        candidates = self._load_json(self.candidates_path)

        setup_names = sorted(set(str(r.get("setup_type") or "UNKNOWN") for r in outcomes))
        by_setup = {}

        for setup in setup_names:
            setup_rows = [r for r in outcomes if str(r.get("setup_type") or "UNKNOWN") == setup]
            delays = self._candidate_delays(setup, candidates)

            delay_results = {}
            for delay in delays:
                simulated_rows = [self._simulate_row_for_delay(r, delay) for r in setup_rows]
                delay_results[str(delay)] = {
                    "stats": self._stats(simulated_rows),
                    "rows": simulated_rows[-50:],
                }

            best_delay = None
            if delay_results:
                best_delay = sorted(
                    delay_results.items(),
                    key=lambda kv: kv[1]["stats"].get("delta", 0.0),
                    reverse=True,
                )[0][0]

            by_setup[setup] = {
                "real_stats": self._stats([
                    {
                        "real_pnl_net": r.get("pnl_net", 0.0),
                        "simulated_pnl_net": r.get("pnl_net", 0.0),
                        "delta": 0.0,
                        "applied": False,
                    }
                    for r in setup_rows
                ]),
                "best_delay_sec": int(best_delay) if best_delay is not None else None,
                "best_stats": delay_results.get(best_delay, {}).get("stats") if best_delay is not None else None,
                "delay_results": delay_results,
            }

        all_real = sum(float(r.get("pnl_net", 0.0) or 0.0) for r in outcomes)
        all_best_sim = 0.0
        for setup, block in by_setup.items():
            best_stats = block.get("best_stats") or {}
            all_best_sim += float(best_stats.get("simulated_pnl", block["real_stats"]["real_pnl"]) or 0.0)

        payload = {
            "schema": "vortex.shadow_policy_simulation.v1",
            "schema_version": "1.8.18",
            "generated_at": time.time(),
            "source": {
                "outcomes": str(self.outcomes_path),
                "candidates": str(self.candidates_path),
                "outcome_rows": len(outcomes),
            },
            "overall_best": {
                "real_pnl": round(all_real, 8),
                "best_candidate_pnl": round(all_best_sim, 8),
                "delta": round(all_best_sim - all_real, 8),
            },
            "by_setup": by_setup,
            "notes": [
                "analytics_only",
                "shadow_policy_simulation",
                "synthetic_estimate_not_live_execution",
                "requires_more_samples_before_real_policy",
            ],
        }

        self.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return payload


if __name__ == "__main__":
    payload = ShadowPolicySimulator().build()
    compact = {
        "schema_version": payload.get("schema_version"),
        "source": payload.get("source"),
        "overall_best": payload.get("overall_best"),
        "setups": {
            k: {
                "best_delay_sec": v.get("best_delay_sec"),
                "best_stats": v.get("best_stats"),
                "real_stats": v.get("real_stats"),
            }
            for k, v in (payload.get("by_setup") or {}).items()
        },
        "output": "_runtime/shadow_policy_simulation.json",
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))

