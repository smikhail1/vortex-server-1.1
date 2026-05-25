import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import entry_candidate_journal as journal


def test_dedup_write_suppresses_repeats():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        out = td / "entry_candidates.jsonl"

        kwargs = {
            "symbol": "TESTUSDT",
            "side": "LONG",
            "setup_type": "momentum_long",
            "args_text": "momentum ok | EA:C/65 SHADOW_ONLY",
        }
        policy = {
            "allow": False,
            "code": "BLOCK_EA_C",
            "reason": "EA grade C is not allowed for live futures",
        }
        result = {
            "code": "BLOCK_ENTRY_SAFETY_POLICY",
            "msg": "EA grade C is not allowed for live futures",
        }

        for _ in range(5):
            journal.log_entry_candidate(
                args=(),
                kwargs=kwargs,
                policy=policy,
                result=result,
                final_action="BLOCKED",
                out_path=str(out),
            )

        rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1, f"expected 1 written row, got {len(rows)}"

        summary = json.loads((td / "entry_candidate_dedup_summary.json").read_text(encoding="utf-8"))
        assert summary["total_seen"] == 5
        assert summary["total_written"] == 1
        assert summary["total_suppressed"] == 4
        assert summary["unique_keys"] == 1


if __name__ == "__main__":
    test_dedup_write_suppresses_repeats()
    print("OK: smoke_entry_candidate_dedup")
