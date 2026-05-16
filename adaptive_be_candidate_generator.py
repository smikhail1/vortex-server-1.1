import json
import time
from pathlib import Path

def load_json(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def score_candidate(setup, stats, delay_sec):
    setup_l = str(setup).lower()
    count = int(stats.get("count", 0) or 0)
    bu = int(stats.get("bu_count", 0) or 0)
    stall = int(stats.get("stall_count", 0) or 0)
    sl = int(stats.get("sl_count", 0) or 0)
    avg_pnl = float(stats.get("avg_pnl_net", 0.0) or 0.0)
    winrate = float(stats.get("winrate_pct", 0.0) or 0.0)
    avg_hold = float(stats.get("avg_hold_sec", 0.0) or 0.0)
    adaptive_delay_pct = float(stats.get("adaptive_delay_pct", 0.0) or 0.0)

    score = 0.0
    reasons = []

    if count < 3:
        score -= 30
        reasons.append("low_sample_size")
    if bu > 0:
        score += 20
        reasons.append("bu_exists")
    if avg_pnl < 0:
        score += 15
        reasons.append("avg_pnl_negative")
    else:
        score += 5
        reasons.append("avg_pnl_positive_or_flat")
    if adaptive_delay_pct > 0:
        score += min(20, adaptive_delay_pct)
        reasons.append("shadow_delay_detected")
    if stall > 0 and winrate >= 40:
        score += 10
        reasons.append("stall_or_winrate_supports_more_room")
    if sl > bu and "trend" in setup_l:
        score -= 15
        reasons.append("trend_has_sl_risk_keep_protection")

    if "momentum" in setup_l:
        if delay_sec in (240, 360):
            score += 15
            reasons.append("momentum_prefers_medium_delay")
        elif delay_sec >= 600:
            score += 3
            reasons.append("momentum_long_delay_experimental")
        else:
            score += 5
            reasons.append("momentum_short_delay_conservative")
    elif "trend" in setup_l:
        if delay_sec <= 60:
            score += 12
            reasons.append("trend_prefers_fast_protection")
        elif delay_sec >= 240:
            score -= 10
            reasons.append("trend_delay_too_loose")

    if avg_hold > 600 and bu > 0:
        score += 8
        reasons.append("long_hold_bu_noise_possible")

    confidence = "low"
    if count >= 8 and score >= 45:
        confidence = "high"
    elif count >= 4 and score >= 30:
        confidence = "medium"

    return {
        "delay_sec": delay_sec,
        "score": round(score, 4),
        "confidence": confidence,
        "reasons": sorted(set(reasons)),
        "activation": {
            "mode": "shadow_only",
            "after_tp0": "momentum" in setup_l,
            "min_hold_sec": delay_sec,
            "requires_positive_pnl": True,
            "requires_no_sl_pressure": "trend" in setup_l,
        },
    }

def delays_for(setup):
    setup_l = str(setup).lower()
    if "momentum" in setup_l:
        return [120, 240, 360, 600]
    if "trend" in setup_l:
        return [30, 60, 120, 240]
    return [60, 120, 240]

def build():
    summary = load_json("_runtime/outcome_summary.json")
    replay = load_json("_runtime/shadow_adaptive_replay.json")
    by_setup = summary.get("by_setup") or {}
    candidates = {}

    for setup, stats in by_setup.items():
        variants = [score_candidate(setup, stats, d) for d in delays_for(setup)]
        best = sorted(variants, key=lambda x: x["score"], reverse=True)[0] if variants else None
        candidates[setup] = {
            "sample": {
                "count": stats.get("count", 0),
                "avg_pnl_net": stats.get("avg_pnl_net", 0.0),
                "winrate_pct": stats.get("winrate_pct", 0.0),
                "bu_count": stats.get("bu_count", 0),
                "stall_count": stats.get("stall_count", 0),
                "sl_count": stats.get("sl_count", 0),
                "adaptive_delay_pct": stats.get("adaptive_delay_pct", 0.0),
            },
            "best_candidate": best,
            "candidates": variants,
        }

    payload = {
        "schema": "vortex.adaptive_be_candidates.v1",
        "schema_version": "1.8.17",
        "generated_at": time.time(),
        "source": {
            "outcome_rows": summary.get("rows", 0),
            "shadow_rows": (replay.get("summary") or {}).get("count", 0),
        },
        "candidates": candidates,
        "notes": ["analytics_only", "candidate_generation_only", "execution_unchanged"],
    }

    Path("_runtime/adaptive_be_candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload

if __name__ == "__main__":
    p = build()
    print(json.dumps({
        "schema_version": p["schema_version"],
        "source": p["source"],
        "setups": {
            k: {"sample": v["sample"], "best_candidate": v["best_candidate"]}
            for k, v in p["candidates"].items()
        }
    }, ensure_ascii=False, indent=2))

