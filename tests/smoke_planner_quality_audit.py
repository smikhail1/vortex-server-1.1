#!/usr/bin/env python3
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.planner_audit import SCHEMA, build_planner_audit


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    api = (ROOT / "api_server.py").read_text(encoding="utf-8")
    html = (ROOT / "web" / "market_analytics.html").read_text(encoding="utf-8")
    tool = (ROOT / "tools" / "planner_audit.py").read_text(encoding="utf-8")

    require('/api/analytics/planner-audit' in api, "planner audit endpoint missing")
    require("handle_planner_audit_1824f" in api, "planner audit handler missing")
    require("vortex.planner_audit.api.v1" in api, "planner audit schema marker missing")
    require("Planner Advisor Audit" in html, "Planner Advisor Audit block missing")
    require("read_only" in tool, "read_only marker missing")
    require("router." not in tool, "planner audit must not call router")
    require("block_longs" not in tool and "block_shorts" not in tool, "planner audit must not add hard blocks")

    dashboard = {
        "planner": {"spot_planner": {"spot_ideas": [{
            "symbol": "INJUSDT",
            "tier": "A",
            "score": 82,
            "readiness": "HIGH",
            "status": "В зоне",
            "rr_ratio": 1.83,
            "current_price": 5.18,
            "accumulation_zone": {"top": 5.25, "bottom": 5.10},
            "avg_entry": 5.17,
            "invalidation": 4.92,
            "tp_base": 5.55,
            "tp_bull": 6.05,
            "setup_type": "spot_pullback",
        }]}},
        "macro_regime": {"regime": "mixed_neutral", "recommendation": {"long_permission": "selective"}},
    }
    liquidity = {"items": [{"symbol": "INJUSDT", "available": True, "liquidity_bias": "mild_long"}]}
    result = build_planner_audit(dashboard=dashboard, liquidity_payload=liquidity)
    require(result["schema"] == SCHEMA, "wrong schema")
    require(result["read_only"] is True, "audit is not read-only")
    require(result["items_len"] == 1, "planner idea missing")
    item = result["items"][0]
    require(item["advisor_status"] == "WAIT_CONFIRMATION", "in-zone idea should wait for confirmation")
    require(item["rr_grade"] == "good", "RR grading mismatch")
    require(item["zone_grade"] == "in_zone", "zone grading mismatch")
    require(item["zone_quality"] == item["zone_grade"], "zone_quality alias mismatch")
    require(item["zone_quality"] is not None, "zone_quality must not be None")
    require(item["liquidity_alignment"] == "supportive", "liquidity shadow mapping mismatch")
    print("OK: smoke_planner_quality_audit")


if __name__ == "__main__":
    main()
