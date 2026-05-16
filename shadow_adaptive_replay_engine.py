import json
import time
from pathlib import Path
from typing import Dict, Any, List

class ShadowAdaptiveReplayEngine:
    """
    VORTEX v1.8.16a
    Shadow Adaptive Replay Engine

    Analytics-only replay evaluator.
    Does NOT modify execution.
    """

    def __init__(
        self,
        outcomes_path="_runtime/trade_outcomes.jsonl",
        replay_path="_runtime/shadow_adaptive_replay.json",
    ):
        self.outcomes_path = Path(outcomes_path)
        self.replay_path = Path(replay_path)

    def _load_rows(self) -> List[Dict[str, Any]]:
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

    def _estimate_shadow_outcome(self, row: Dict[str, Any]) -> Dict[str, Any]:
        pnl_net = float(row.get("pnl_net", 0.0))
        hold_sec = int(row.get("hold_sec", 0) or 0)
        reason = str(row.get("close_reason", "")).upper()

        adaptive = row.get("adaptive_be_shadow") or {}
        would_delay = bool(adaptive.get("would_have_delayed_be", False))

        setup = str(row.get("setup_type", "unknown"))

        simulated_delta = 0.0
        simulated_reason = reason
        confidence = "low"

        if would_delay and reason in {"BU", "BE", "BREAKEVEN"}:
            simulated_delta = abs(pnl_net) * 2.5 + 0.05

            if "momentum" in setup.lower():
                simulated_delta += 0.03
                confidence = "medium"

            simulated_reason = "STALL_SHADOW"

        simulated_shadow_pnl = round(pnl_net + simulated_delta, 8)

        return {
            "symbol": row.get("symbol"),
            "setup_type": setup,
            "real_reason": reason,
            "shadow_reason": simulated_reason,
            "real_pnl_net": round(pnl_net, 8),
            "shadow_pnl_net": simulated_shadow_pnl,
            "delta": round(simulated_shadow_pnl - pnl_net, 8),
            "would_delay_be": would_delay,
            "hold_sec": hold_sec,
            "confidence": confidence,
        }

    def build(self):
        rows = self._load_rows()

        replay_rows = [
            self._estimate_shadow_outcome(r)
            for r in rows
        ]

        total_real = round(sum(r["real_pnl_net"] for r in replay_rows), 8)
        total_shadow = round(sum(r["shadow_pnl_net"] for r in replay_rows), 8)

        improved = [
            r for r in replay_rows
            if r["delta"] > 0
        ]

        payload = {
            "schema": "vortex.shadow_adaptive_replay.v1",
            "schema_version": "1.8.16a",
            "generated_at": time.time(),
            "summary": {
                "count": len(replay_rows),
                "total_real_pnl_net": total_real,
                "total_shadow_pnl_net": total_shadow,
                "shadow_delta": round(total_shadow - total_real, 8),
                "improved_count": len(improved),
                "improved_pct": round(
                    (len(improved) / len(replay_rows) * 100.0),
                    4
                ) if replay_rows else 0.0,
            },
            "replay_rows": replay_rows[-100:],
            "notes": [
                "analytics_only",
                "shadow_replay",
                "execution_unchanged",
            ]
        }

        self.replay_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        return payload


if __name__ == "__main__":
    p = ShadowAdaptiveReplayEngine().build()
    print(json.dumps({
        "schema_version": p["schema_version"],
        "summary": p["summary"],
    }, ensure_ascii=False, indent=2))

