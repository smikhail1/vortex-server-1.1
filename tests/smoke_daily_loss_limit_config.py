from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main_text = (ROOT / "main.py").read_text(encoding="utf-8")
risk_text = (ROOT / "risk_manager.py").read_text(encoding="utf-8")
config_text = (ROOT / "config.py").read_text(encoding="utf-8")

assert "daily_loss_limit_usdt: float = -5.0" in config_text
assert "daily_loss_limit_usdt: float = CONFIG.risk.daily_loss_limit_usdt" in risk_text
assert "daily_loss_limit_usdt=CONFIG.risk.daily_loss_limit_usdt" in main_text
assert "daily_loss_limit_usdt: float = -10.0" not in risk_text

print("OK: smoke_daily_loss_limit_config")
