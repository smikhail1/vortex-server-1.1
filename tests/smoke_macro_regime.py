from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macro_regime_engine import build_macro_regime_snapshot, analyze_futures_pressure


def test_macro_regime_bullish_internal():
    heatmap = {"summary": {"bias": "strong_bullish", "net_bias_score": 35}}
    ichi = {"summary": {"symbols_count": 10, "available_count": 10, "cloud_state_counts": {"above_cloud": 8, "below_cloud": 1, "inside_cloud": 1}, "trend_bias_counts": {"bullish": 8, "bearish": 1, "neutral": 1}, "long_support_counts": {"supportive": 8}, "short_support_counts": {"supportive": 1}}}
    fusion = {"summary": {"final_view_counts": {"WATCH_ONLY": 8, "POLICY_BLOCKED": 1}, "strategy_summary": {"ready_allowed_count": 0, "ready_blocked_count": 1, "raw_ready_no_ea_count": 0, "ea_counts": {"B": 1}}}}
    tickers = {"available": True, "items": [{"fundingRate": "0.0001", "change24h": "0.03", "holdingAmount": "1000"}, {"fundingRate": "0.0002", "change24h": "0.01", "holdingAmount": "2000"}, {"fundingRate": "0.0000", "change24h": "-0.01", "holdingAmount": "1500"}]}
    snap = build_macro_regime_snapshot(heatmap_snapshot=heatmap, ichimoku_snapshot=ichi, context_fusion_snapshot=fusion, futures_tickers_payload=tickers)
    assert snap["regime"] in {"risk_on_bullish", "mild_risk_on"}
    assert snap["confidence"] >= 58
    assert snap["recommendation"]["short_permission"] == "reduced"


def test_macro_regime_bearish_internal():
    heatmap = {"summary": {"bias": "strong_bearish", "net_bias_score": -35}}
    ichi = {"summary": {"symbols_count": 10, "available_count": 10, "cloud_state_counts": {"above_cloud": 1, "below_cloud": 8, "inside_cloud": 1}, "trend_bias_counts": {"bullish": 1, "bearish": 8, "neutral": 1}, "long_support_counts": {"supportive": 1}, "short_support_counts": {"supportive": 8}}}
    fusion = {"summary": {"final_view_counts": {}, "strategy_summary": {}}}
    tickers = {"available": True, "items": [{"fundingRate": "-0.0001", "change24h": "-0.03"}, {"fundingRate": "-0.0002", "change24h": "-0.01"}, {"fundingRate": "0.0000", "change24h": "0.01"}]}
    snap = build_macro_regime_snapshot(heatmap_snapshot=heatmap, ichimoku_snapshot=ichi, context_fusion_snapshot=fusion, futures_tickers_payload=tickers)
    assert snap["regime"] in {"risk_off_bearish", "mild_risk_off"}
    assert snap["confidence"] <= 42
    assert snap["recommendation"]["long_permission"] == "reduced"


def test_futures_pressure_handles_unavailable():
    fp = analyze_futures_pressure({"available": False, "error": "x", "items": []})
    assert fp["available"] is False
    assert fp["pressure"] == "no_data"


if __name__ == "__main__":
    test_macro_regime_bullish_internal()
    test_macro_regime_bearish_internal()
    test_futures_pressure_handles_unavailable()
    print("OK: smoke_macro_regime")
