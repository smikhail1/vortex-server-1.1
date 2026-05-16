import json
import time
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from validators import safe_float, safe_str


class OutcomeIntelligenceAggregator:
    """
    VORTEX v1.8.14a Outcome Intelligence Aggregator.

    Analytics-only aggregator.
    Reads _runtime/trade_outcomes.jsonl and writes _runtime/outcome_summary.json.
    """

    def __init__(
        self,
        outcomes_path: str = "_runtime/trade_outcomes.jsonl",
        summary_path: str = "_runtime/outcome_summary.json",
        logger=None,
    ) -> None:
        self.outcomes_path = Path(outcomes_path)
        self.summary_path = Path(summary_path)
        self.logger = logger
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_rows(self) -> List[Dict[str, Any]]:
        if not self.outcomes_path.exists():
            return []

        rows: List[Dict[str, Any]] = []
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

    def _avg(self, vals: List[float]) -> float:
        vals = [safe_float(v, 0.0) for v in vals]
        if not vals:
            return 0.0
        return round(sum(vals) / len(vals), 8)

    def _sum(self, vals: List[float]) -> float:
        return round(sum(safe_float(v, 0.0) for v in vals), 8)

    def _bucket_stats(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not rows:
            return {
                "count": 0,
                "wins": 0,
                "losses": 0,
                "flats": 0,
                "winrate_pct": 0.0,
                "avg_pnl_net": 0.0,
                "sum_pnl_net": 0.0,
                "avg_pnl_pct_est": 0.0,
                "avg_hold_sec": 0.0,
                "bu_count": 0,
                "sl_count": 0,
                "stall_count": 0,
                "tp_count": 0,
                "tp2_count": 0,
                "adaptive_delay_count": 0,
                "adaptive_delay_pct": 0.0,
                "avg_potential_fee_loss_avoided": 0.0,
            }

        count = len(rows)
        wins = sum(1 for r in rows if safe_str(r.get("result")).upper() == "WIN")
        losses = sum(1 for r in rows if safe_str(r.get("result")).upper() == "LOSS")
        flats = sum(1 for r in rows if safe_str(r.get("result")).upper() == "FLAT")

        reasons = [safe_str(r.get("close_reason")).upper() for r in rows]
        adaptive_delay = 0
        fee_avoid = []

        for r in rows:
            shadow = r.get("adaptive_be_shadow")
            if isinstance(shadow, dict):
                if bool(shadow.get("would_have_delayed_be", False)):
                    adaptive_delay += 1
                fee_avoid.append(safe_float(shadow.get("potential_fee_loss_avoided"), 0.0))

        return {
            "count": count,
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "winrate_pct": round((wins / count) * 100.0, 4) if count else 0.0,
            "avg_pnl_net": self._avg([r.get("pnl_net") for r in rows]),
            "sum_pnl_net": self._sum([r.get("pnl_net") for r in rows]),
            "avg_pnl_pct_est": self._avg([r.get("pnl_pct_est") for r in rows]),
            "avg_hold_sec": self._avg([r.get("hold_sec") for r in rows]),
            "bu_count": sum(1 for x in reasons if x in {"BU", "BE", "BREAKEVEN"}),
            "sl_count": sum(1 for x in reasons if x == "SL"),
            "stall_count": sum(1 for x in reasons if x == "STALL"),
            "tp_count": sum(1 for x in reasons if x in {"TP", "TP1"}),
            "tp2_count": sum(1 for x in reasons if x == "TP2"),
            "adaptive_delay_count": adaptive_delay,
            "adaptive_delay_pct": round((adaptive_delay / count) * 100.0, 4) if count else 0.0,
            "avg_potential_fee_loss_avoided": self._avg(fee_avoid),
        }

    def _group_by(self, rows: List[Dict[str, Any]], keys: Tuple[str, ...]) -> Dict[str, Any]:
        buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for r in rows:
            parts = []
            for k in keys:
                if k == "close_reason_group":
                    value = r.get("close_reason_group") or (r.get("close_intelligence") or {}).get("close_reason_group")
                elif k == "setup_family":
                    shadow = r.get("adaptive_be_shadow")
                    value = shadow.get("setup_family") if isinstance(shadow, dict) else ""
                else:
                    value = r.get(k)
                parts.append(safe_str(value, "UNKNOWN") or "UNKNOWN")

            buckets["|".join(parts)].append(r)

        return {k: self._bucket_stats(v) for k, v in sorted(buckets.items())}

    def build_summary(self) -> Dict[str, Any]:
        rows = self._read_rows()
        generated_at = time.time()

        summary = {
            "schema": "vortex.outcome_summary.v1",
            "schema_version": "1.8.14a",
            "generated_at": generated_at,
            "generated_at_ms": int(generated_at * 1000),
            "source": str(self.outcomes_path),
            "rows": len(rows),
            "overall": self._bucket_stats(rows),
            "by_setup": self._group_by(rows, ("setup_type",)),
            "by_close_reason": self._group_by(rows, ("close_reason",)),
            "by_setup_and_reason": self._group_by(rows, ("setup_type", "close_reason")),
            "by_setup_and_reason_group": self._group_by(rows, ("setup_type", "close_reason_group")),
            "by_setup_family": self._group_by(rows, ("setup_family",)),
            "adaptive_be": {
                "delay_recommended": self._bucket_stats([
                    r for r in rows
                    if isinstance(r.get("adaptive_be_shadow"), dict)
                    and bool(r["adaptive_be_shadow"].get("would_have_delayed_be", False))
                ]),
                "no_delay_recommended": self._bucket_stats([
                    r for r in rows
                    if isinstance(r.get("adaptive_be_shadow"), dict)
                    and not bool(r["adaptive_be_shadow"].get("would_have_delayed_be", False))
                ]),
            },
            "notes": [
                "analytics_only",
                "summary is rebuilt from trade_outcomes.jsonl",
                "runtime files are ignored by git",
            ],
        }

        self.summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        if self.logger:
            try:
                self.logger.info("ANALYTICS", "outcome summary updated", {
                    "rows": summary["rows"],
                    "overall_count": summary["overall"]["count"],
                    "overall_avg_pnl_net": summary["overall"]["avg_pnl_net"],
                    "overall_winrate_pct": summary["overall"]["winrate_pct"],
                    "path": str(self.summary_path),
                })
            except Exception:
                pass

        return summary


def build_outcome_summary(
    outcomes_path: str = "_runtime/trade_outcomes.jsonl",
    summary_path: str = "_runtime/outcome_summary.json",
    logger=None,
) -> Dict[str, Any]:
    return OutcomeIntelligenceAggregator(
        outcomes_path=outcomes_path,
        summary_path=summary_path,
        logger=logger,
    ).build_summary()


if __name__ == "__main__":
    summary = build_outcome_summary()
    print(json.dumps({
        "schema_version": summary.get("schema_version"),
        "rows": summary.get("rows"),
        "overall": summary.get("overall"),
        "summary_path": "_runtime/outcome_summary.json",
    }, ensure_ascii=False, indent=2))

