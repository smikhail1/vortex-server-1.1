import time

class PaperFutures:
    def __init__(self):
        self.balance = 100.0
        self.pos = None

    def get_balance(self): return self.balance
    def get_position(self): return self.pos

    def open_position(self, symbol, side, qty, price, mark_price, lev, atr):
        sl_dist = atr * 3.0 
        tp_dist = atr * 5.0 
        
        sl = price - sl_dist if side == "long" else price + sl_dist
        tp = price + tp_dist if side == "long" else price - tp_dist
        
        self.pos = type('Pos', (), {
            'symbol': symbol, 'side': side, 'qty': qty, 'entry': price, 
            'sl': sl, 'tp': tp, 'open_time': time.time(), 
            'pnl': 0.0, 'breakeven': False
        })()
        return {"code": "00000"}
        
    def check_stops(self, current_price):
        if not self.pos: return None
        
        diff = (current_price - self.pos.entry) if self.pos.side == "long" else (self.pos.entry - current_price)
        self.pos.pnl = diff * self.pos.qty
        
        if self.pos.pnl > (self.pos.qty * current_price * 0.005) and not self.pos.breakeven:
            self.pos.sl = self.pos.entry
            self.pos.breakeven = True

        reason = None
        if self.pos.side == "long":
            if current_price <= self.pos.sl: reason = "BU" if self.pos.breakeven else "SL"
            elif current_price >= self.pos.tp: reason = "TP"
        else:
            if current_price >= self.pos.sl: reason = "BU" if self.pos.breakeven else "SL"
            elif current_price <= self.pos.tp: reason = "TP"
            
        if reason:
            return self.close_position(current_price, reason)
        return None
        
    def close_position(self, current_price, reason="MANUAL"):
        if not self.pos: return None
        res = {'code': '00000', 'data': {'pnl': self.pos.pnl, 'reason': reason}}
        self.balance += self.pos.pnl
        self.pos = None
        return res
