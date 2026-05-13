from typing import Dict, List, Optional
from config import CONFIG
from validators import safe_bool, safe_float, safe_str
try: from momentum_engine import MomentumEngine
except: MomentumEngine = None

class SwingStrategy:
    def __init__(self):
        self.momentum = MomentumEngine() if MomentumEngine else None

    def _result(self, should_open=False, signal=None, score=0, setup_type=None, args=None, blocked_reason=None, threshold=0, extra=None):
        return {"should_open": bool(should_open), "signal": signal, "score": int(score), "setup_type": setup_type, "args_text": " | ".join(args or []), "blocked_reason": blocked_reason, "threshold": int(threshold), **(extra or {})}

    def analyze_futures(self, current, macro_filter="allow_all"):
        d = current or {}
        thresh = int(CONFIG.trading.futures_min_score_to_open)
        adx = safe_float(d.get("adx"), 25.0) # По умолчанию нейтрально
        rsi, slope = safe_float(d.get("rsi_main"), 50.0), safe_float(d.get("rsi_slope"), 0.0)

        # 1. Momentum Check (Priority)
        if self.momentum:
            m_sig = self.momentum.evaluate_futures(d, market_regime="trend" if adx > 20 else "range")
            if m_sig.active and m_sig.confirmed:
                if macro_filter == "block_longs" and m_sig.side == "LONG": pass
                else: return self._result(should_open=True, signal=m_sig.side, score=m_sig.score, setup_type=m_sig.setup_type, args=[m_sig.reason], threshold=thresh)

        # 2. Hard Blocks
        if adx < 15: return self._result(blocked_reason=f"flat market (ADX:{adx})", threshold=thresh)
        if d.get("wick_long_danger") and slope < -0.1: return self._result(blocked_reason="wick rejection", threshold=thresh)

        # 3. Standard Scoring
        score = 0
        args = [f"ADX:{adx}"]
        if adx > 28: score += 2; args.append("trend strength ok")
        if d.get("trend_4h") == "up": score += 3; args.append("4H Trend Up")
        if rsi > 50: score += 1; args.append("RSI Bullish")
        if slope > 0.3: score += 1; args.append("RSI Slope Up")
        if safe_float(d.get("vol_ratio")) > 1.15: score += 1; args.append("Volume OK")

        signal = "LONG" if score >= thresh else None
        if signal == "LONG" and macro_filter == "block_longs":
            return self._result(should_open=False, signal="LONG", score=score, blocked_reason="macro filter", threshold=thresh)

        should_open = signal is not None
        return self._result(should_open=should_open, signal=signal, score=score, setup_type="trend_follow_v1.7", args=args, threshold=thresh)

    def analyze_spot(self, current, macro_filter="allow_all"):
        res = self.analyze_futures(current, macro_filter)
        if res.get("signal") == "SHORT": res["should_open"] = False; res["signal"] = None
        return res

    
    def calculate_futures_trade(self, price, side, atr, setup_type="", args_text=""):
        price = float(price)
        atr = float(atr)
        
        # Гибридный подход: Микро-тейк (TP0), Основной (TP1), Туземун (TP2)
        if side.lower() == "long":
            tp0 = price + (atr * 0.6)
            tp = price + (atr * 2.0)
            tp2 = price + (atr * 3.5)
            sl = price - (atr * 1.5)
        else:
            tp0 = price - (atr * 0.6)
            tp = price - (atr * 2.0)
            tp2 = price - (atr * 3.5)
            sl = price + (atr * 1.5)
            
        return {
            "price": round(price, 8),
            "qty": 0,  # Будет рассчитано в Risk Manager
            "leverage": 3.0,
            "tp0": round(tp0, 8), # Фронт-лоад тейк
            "tp": round(tp, 8),   # Основной
            "tp2": round(tp2, 8), # Дальний
            "sl": round(sl, 8),
            "atr": round(atr, 8),
            "setup_type": setup_type,
            "args_text": args_text
        }

    
    def calculate_spot_ladder(self, price, atr, setup_type="", args_text=""):
        price = float(price)
        atr = float(atr)
        return {
            "price": round(price, 8),
            "qty": 0,
            "tp": round(price + (atr * 3.0), 8),
            "atr": round(atr, 8),
            "setup_type": setup_type,
            "args_text": args_text
        }

def apply_exchange_intel_filters_to_analysis(ans, ex=None): return ans