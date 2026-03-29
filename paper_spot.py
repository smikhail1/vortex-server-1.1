import time

class PaperSpot:
    def __init__(self):
        self.balance   = 100.0
        self.positions = {}

    def get_balance(self): return self.balance
    def get_all_positions(self): return self.positions
    def get_position(self, symbol): return self.positions.get(symbol)

    def open_position(self, symbol, qty, price, tp, atr):
        sl = price - atr * 2
        self.positions[symbol] = type("Pos", (), {
            "symbol":    symbol,
            "qty":       qty,
            "entry":     price,
            "tp":        tp,
            "tp2":       price + atr * 7,
            "sl":        sl,
            "atr":       atr,
            "open_time": time.time(),
            "pnl":       0.0,
            "tp1_hit":   False,
            "trail_sl":  sl,
        })()
        return {"code": "00000"}

    def check_stops(self, symbol, current_price):
        pos = self.positions.get(symbol)
        if not pos:
            return None

        pos.pnl = (current_price - pos.entry) * pos.qty

        # TP1 достигнут — переходим на трейлинг
        if not pos.tp1_hit and current_price >= pos.tp:
            pos.tp1_hit = True
            pos.sl      = pos.entry  # брейкивен

        if pos.tp1_hit:
            new_trail = current_price - pos.atr * 2
            if new_trail > pos.trail_sl:
                pos.trail_sl = new_trail
                pos.sl       = pos.trail_sl

        reason = None
        if current_price <= pos.sl:
            reason = "BU" if pos.tp1_hit else "SL"
        elif pos.tp1_hit and current_price >= pos.tp2:
            reason = "TP2"
        elif not pos.tp1_hit and current_price >= pos.tp:
            reason = "TP1"

        if reason:
            pnl = pos.pnl
            self.balance += pnl
            del self.positions[symbol]
            return {"code": "00000", "data": {"pnl": pnl, "reason": reason}}
        return None
