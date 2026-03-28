import csv, os, time

LOG_FILE = "trades.csv"

def init_logger():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(["time","type","symbol","pnl","reason","duration_min","balance_fut","balance_spot"])

def log_trade(type_, symbol, pnl, reason, duration, bal_fut=0, bal_spot=0):
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            time.strftime("%Y-%m-%d %H:%M:%S"),
            type_, symbol,
            round(pnl, 4),
            reason,
            round(duration / 60, 1),
            round(bal_fut, 2),
            round(bal_spot, 2)
        ])
