import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from entry_candidate_journal import build_candidate_record, log_entry_candidate


def test_record_build_and_write():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "entry_candidates.jsonl"

        rec = log_entry_candidate(
            args=(),
            kwargs={
                "symbol": "TESTUSDT",
                "side": "LONG",
                "setup_type": "momentum_long",
                "args_text": "momentum ok | EA:B/74 ALLOW_SHADOW",
            },
            policy={
                "allow": True,
                "code": "ALLOW_ENTRY_SAFETY",
                "reason": "entry passed safety policy",
            },
            result={
                "code": "00000",
                "msg": None,
            },
            final_action="OPEN_ATTEMPT",
            out_path=str(out),
        )

        assert rec["symbol"] == "TESTUSDT"
        assert rec["ea"]["grade"] == "B"
        assert rec["ea"]["score"] == 74
        assert rec["policy_code"] == "ALLOW_ENTRY_SAFETY"
        assert rec["final_action"] == "OPEN_ATTEMPT"

        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        loaded = json.loads(lines[0])
        assert loaded["symbol"] == "TESTUSDT"


if __name__ == "__main__":
    test_record_build_and_write()
    print("OK: smoke_entry_candidate_journal")
