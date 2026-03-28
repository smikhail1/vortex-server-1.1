import time
class SpotPosition:
    def __init__(self, symbol, qty_usd, entry_price, sl, tp):
        self.symbol = symbol; self.qty_usd = qty_usd; self.qty_coins = qty_usd / entry_price
        self.entry_price = entry_price; self.sl = sl; self.tp = tp
        self.open_time = time.time(); self.breakeven_triggered = False; self.pnl = 0.0

class PaperSpot:
    def __init__(self):
        self.balance = 100.0; self.positions = {}
    def get_balance(self): return self.balance
    def get_all_positions(self): return self.positions
    def get_position(self, symbol): return self.positions.get(symbol)
    def open_position(self, symbol, qty_usd, entry_price, sl_dummy, atr):
        if symbol in self.positions: return {"code": "1"}
        tp_dist = entry_price * 0.012
        sl_dist = max(atr * 2, entry_price * 0.015)
        self.positions[symbol] = SpotPosition(symbol, qty_usd, entry_price, entry_price - sl_dist, entry_price + tp_dist)
        return {"code": "00000"}
    def check_stops(self, symbol, current_price):
        if symbol not in self.positions: return None
        pos = self.positions[symbol]
        pos.pnl = (current_price - pos.entry_price) * pos.qty_coins
        if (current_price - pos.entry_price) / pos.entry_price >= 0.006 and not pos.breakeven_triggered:
            pos.sl = pos.entry_price * 1.0025; pos.breakeven_triggered = True
        reason = "BU" if current_price <= pos.sl and pos.breakeven_triggered else ("SL" if current_price <= pos.sl else ("TP" if current_price >= pos.tp else None))
        if reason:
            final_pnl = (current_price - pos.entry_price) * pos.qty_coins
            self.balance += final_pnl
            del self.positions[symbol]
            return {"code": "00000", "data": {"pnl": final_pnl, "reason": reason}}
        return None
