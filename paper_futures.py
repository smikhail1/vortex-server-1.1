import time

class PaperFutures:
    def __init__(self):
        self.balance = 100.0
        self.pos     = None
        self.trail_active = False

    def get_balance(self): return self.balance
    def get_position(self): return self.pos

    def open_position(self, symbol, side, qty, price, tp, sl, atr):
        self.trail_active = False
        self.pos = type("Pos", (), {
            "symbol":    symbol,
            "side":      side,
            "qty":       qty,
            "entry":     price,
            "tp":        tp,
            "tp2":       price + atr * 5 if side == "long" else price - atr * 5,
            "sl":        sl,
            "atr":       atr,
            "open_time": time.time(),
            "pnl":       0.0,
            "breakeven": False,
            "tp1_hit":   False,
            "trail_sl":  sl,
        })()
        return {"code": "00000"}

    def check_stops(self, current_price):
        if not self.pos:
            return None
        p = self.pos

        diff    = (current_price - p.entry) if p.side == "long" else (p.entry - current_price)
        p.pnl   = diff * p.qty

        # брейкивен после TP1
        if not p.breakeven and not p.tp1_hit:
            if p.side == "long" and current_price >= p.tp:
                p.breakeven = True
                p.sl        = p.entry
                p.tp1_hit   = True
            elif p.side == "short" and current_price <= p.tp:
                p.breakeven = True
                p.sl        = p.entry
                p.tp1_hit   = True

        # трейлинг стоп на вторую половину (после TP1)
        if p.tp1_hit:
            if p.side == "long":
                new_trail = current_price - p.atr * 1.5
                if new_trail > p.trail_sl:
                    p.trail_sl = new_trail
                    p.sl       = p.trail_sl
            else:
                new_trail = current_price + p.atr * 1.5
                if new_trail < p.trail_sl:
                    p.trail_sl = new_trail
                    p.sl       = p.trail_sl

        reason = None
        if p.side == "long":
            if current_price <= p.sl:
                reason = "BU" if p.breakeven else "SL"
            elif p.tp1_hit and current_price >= p.tp2:
                reason = "TP2"
            elif not p.tp1_hit and current_price >= p.tp:
                reason = "TP1"
        else:
            if current_price >= p.sl:
                reason = "BU" if p.breakeven else "SL"
            elif p.tp1_hit and current_price <= p.tp2:
                reason = "TP2"
            elif not p.tp1_hit and current_price <= p.tp:
                reason = "TP1"

        if reason:
            return self.close_position(current_price, reason)
        return None

    def close_position(self, current_price, reason="MANUAL"):
        if not self.pos:
            return None
        p   = self.pos
        diff = (current_price - p.entry) if p.side == "long" else (p.entry - current_price)
        pnl  = diff * p.qty
        self.balance += pnl
        res  = {"code": "00000", "data": {"pnl": pnl, "reason": reason}}
        self.pos = None
        self.trail_active = False
        return res
