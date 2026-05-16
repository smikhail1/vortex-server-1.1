import json
import time
from pathlib import Path

class PolicyRecommendationEngine:
    def __init__(
        self,
        outcome_summary_path="_runtime/outcome_summary.json",
        output_path="_runtime/policy_recommendations.json",
    ):
        self.summary_path = Path(outcome_summary_path)
        self.output_path = Path(output_path)

    def build(self):
        if not self.summary_path.exists():
            return {"status": "missing_summary"}

        summary = json.loads(self.summary_path.read_text(encoding="utf-8"))
        by_setup = summary.get("by_setup", {})

        recommendations = {}

        for setup, stats in by_setup.items():
            count = stats.get("count", 0)
            avg_pnl = stats.get("avg_pnl_net", 0.0)
            bu_count = stats.get("bu_count", 0)

            rec = {
                "confidence": "low",
                "analytics_only": True,
                "count": count,
            }

            if "momentum" in setup.lower():
                if count >= 3 and avg_pnl < 0 and bu_count >= 1:
                    rec.update({
                        "recommended_be_delay_sec": 240,
                        "recommended_tp0_extension_pct": 0.35,
                        "recommendation": "delay_be_for_momentum",
                        "confidence": "medium",
                        "reason": "BU exits underperform and avg pnl negative"
                    })

            elif "trend" in setup.lower():
                if avg_pnl < 0:
                    rec.update({
                        "recommendation": "keep_protective_be",
                        "recommended_be_delay_sec": 60,
                        "confidence": "low",
                        "reason": "trend setups still require protection"
                    })

            recommendations[setup] = rec

        payload = {
            "schema": "vortex.policy_recommendations.v1",
            "schema_version": "1.8.15",
            "generated_at": time.time(),
            "recommendations": recommendations,
            "notes": [
                "analytics_only",
                "no execution changes",
                "shadow policy recommendations"
            ]
        }

        self.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return payload

if __name__ == "__main__":
    p = PolicyRecommendationEngine().build()
    print(json.dumps(p, ensure_ascii=False, indent=2))

