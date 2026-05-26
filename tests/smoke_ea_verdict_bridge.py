from pathlib import Path
import json
import tempfile
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ea_verdict_bridge import build_ea_verdict_index, find_ea_verdict
from strategy_observer import build_symbol_observation


class DummyStrategy:
    def analyze_futures(self, ta, macro_filter="allow_all"):
        return {
            "should_open": True,
            "signal": "SHORT",
            "score": 8,
            "setup_type": "trend_short_v1.8.1",
            "args_text": "ADX:30 | 4H Trend Down",
            "threshold": 7,
        }


def test_bridge_builds_from_dedup_state():
    now = time.time()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        state = {
            "keys": {
                "x": {
                    "seen_count": 5,
                    "suppressed_count": 4,
                    "last_record": {
                        "ts": now,
                        "symbol": "ALGOUSDT",
                        "side": "SHORT",
                        "setup_type": "trend_short_v1.8.1",
                        "args_text": "EA:B/76 ALLOW_SHADOW",
                        "ea": {"present": True, "grade": "B", "score": 76, "label": "ALLOW_SHADOW", "raw": "EA:B/76 ALLOW_SHADOW"},
                        "policy_allow": False,
                        "policy_code": "BLOCK_SETUP_DISABLED",
                        "policy_reason": "setup disabled",
                    },
                }
            }
        }
        p = td / "state.json"
        p.write_text(json.dumps(state), encoding="utf-8")

        bridge = build_ea_verdict_index(dedup_state_path=p, entry_candidates_path=td / "missing.jsonl")
        v = find_ea_verdict(bridge, symbol="ALGOUSDT", side="SHORT", setup_type="trend_short_v1.8.1", max_age_sec=3600)

        assert v is not None
        assert v["ea"]["grade"] == "B"
        assert v["ea"]["score"] == 76
        assert v["policy"]["code"] == "BLOCK_SETUP_DISABLED"


def test_strategy_observer_uses_bridge_when_args_has_no_ea():
    now = time.time()
    bridge = {
        "schema": "vortex.ea_verdict_bridge.v1",
        "index": {
            "ALGOUSDT|SHORT|trend_short_v1.8.1": {
                "ts": now,
                "symbol": "ALGOUSDT",
                "side": "SHORT",
                "setup_type": "trend_short_v1.8.1",
                "source": "test",
                "ea": {"present": True, "grade": "B", "score": 76, "label": "ALLOW_SHADOW", "raw": "EA:B/76 ALLOW_SHADOW"},
                "policy": {"allow": False, "code": "BLOCK_SETUP_DISABLED", "reason": "setup disabled"},
            }
        },
        "by_symbol": {
            "ALGOUSDT": [
                {
                    "ts": now,
                    "symbol": "ALGOUSDT",
                    "side": "SHORT",
                    "setup_type": "trend_short_v1.8.1",
                    "source": "test",
                    "ea": {"present": True, "grade": "B", "score": 76, "label": "ALLOW_SHADOW", "raw": "EA:B/76 ALLOW_SHADOW"},
                    "policy": {"allow": False, "code": "BLOCK_SETUP_DISABLED", "reason": "setup disabled"},
                }
            ]
        },
    }

    obs = build_symbol_observation(
        symbol="ALGOUSDT",
        ta={"price": 1, "adx": 30, "trend_4h": "down", "ema20": 1, "ema50": 2, "atr": 0.1},
        strategy=DummyStrategy(),
        ea_bridge=bridge,
    )

    assert obs["ea"]["present"] is True
    assert obs["ea"]["grade"] == "B"
    assert obs["policy"]["code"] == "BLOCK_SETUP_DISABLED"
    assert obs["state"] == "READY_BLOCKED_BY_POLICY"
    assert obs["ea_bridge"]["matched"] is True


if __name__ == "__main__":
    test_bridge_builds_from_dedup_state()
    test_strategy_observer_uses_bridge_when_args_has_no_ea()
    print("OK: smoke_ea_verdict_bridge")
