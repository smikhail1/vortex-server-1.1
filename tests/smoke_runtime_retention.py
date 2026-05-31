from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tool = ROOT / "tools" / "runtime_retention.py"
text = tool.read_text(encoding="utf-8")

assert tool.exists()
assert 'parser.add_argument("--apply"' in text
assert "dry_run = not args.apply" in text
assert '"trades_state.json"' in text
assert '"risk_state.json"' in text
assert '".env"' in text
assert "tracked_files(root)" in text
assert "shutil.rmtree" in text
assert "futures_pipeline_probe_*" in text
assert "retain_tail" in text

print("OK: smoke_runtime_retention")
