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

    def analyze_spot(self, current, macro_filter="allow_all", planner_idea=None):
        # ИНТЕГРАЦИЯ ПЛАНЕРА
        if planner_idea and planner_idea.get("ready"):
            return self._result(
                should_open=True,
                signal="BUY",
                score=planner_idea.get("score", 80),
                setup_type="planner_spot",
                args=[f"Planner Tier {planner_idea.get('tier')}", str(planner_idea.get("action_hint"))],
                threshold=0,
                extra={
                    "trigger_price": current.get("price", 0.0) * 0.9999, # Мгновенное подтверждение
                    "invalidation_price": planner_idea.get("invalid_level", 0.0),
                    "tp_base": planner_idea.get("tp_base", current.get("price", 0.0) * 1.1)
                }
            )
            
        res = self.analyze_futures(current, macro_filter)
        if res.get("signal") == "SHORT": 
            res["should_open"] = False
            res["signal"] = None
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

# --- VORTEX v1.8.1 STRATEGY FUTURES/SPOT UPGRADE ---
try:
    _vortex_old_analyze_futures = SwingStrategy.analyze_futures
    _vortex_old_analyze_spot = SwingStrategy.analyze_spot

    def _vortex_analyze_futures_v181(self, current, macro_filter="allow_all"):
        d = current or {}

        base = _vortex_old_analyze_futures(self, current, macro_filter)
        if isinstance(base, dict) and base.get("should_open"):
            return base

        try:
            thresh = int(getattr(CONFIG.trading, "futures_min_score_to_open", 7))
            adx = safe_float(d.get("adx"), 0.0)
            rsi = safe_float(d.get("rsi_main"), 50.0)
            slope = safe_float(d.get("rsi_slope"), 0.0)
            vol_ratio = safe_float(d.get("vol_ratio"), 0.0)
            trend_4h = safe_str(d.get("trend_4h")).lower()
            price = safe_float(d.get("price"), 0.0)
            ema20 = safe_float(d.get("ema20"), 0.0)
            ema50 = safe_float(d.get("ema50"), 0.0)

            if macro_filter == "block_shorts":
                return base

            score = 0
            args = [f"ADX:{adx}"]

            if adx >= 20:
                score += 2
                args.append("trend strength ok")
            if trend_4h in {"down", "bear", "bearish"}:
                score += 3
                args.append("4H Trend Down")
            if rsi < 50:
                score += 1
                args.append("RSI Bearish")
            if slope < -0.25:
                score += 1
                args.append("RSI Slope Down")
            if vol_ratio > 1.10:
                score += 1
                args.append("Volume OK")
            if price > 0 and ema20 > 0 and price < ema20:
                score += 1
                args.append("below EMA20")
            if price > 0 and ema50 > 0 and price < ema50:
                score += 1
                args.append("below EMA50")

            if adx < 15:
                return self._result(blocked_reason=f"flat market (ADX:{adx})", threshold=thresh)

            if score >= thresh:
                return self._result(
                    should_open=True,
                    signal="SHORT",
                    score=score,
                    setup_type="trend_short_v1.8.1",
                    args=args,
                    threshold=thresh,
                )

            if isinstance(base, dict):
                return base
            return self._result(should_open=False, score=score, setup_type="trend_short_v1.8.1", args=args, threshold=thresh)

        except Exception as exc:
            if isinstance(base, dict):
                return base
            return self._result(blocked_reason=f"futures wrapper error: {exc}")

    def _vortex_analyze_spot_v181(self, current, macro_filter="allow_all", planner_idea=None):
        d = current or {}

        if isinstance(planner_idea, dict):
            try:
                price = safe_float(d.get("price"), 0.0)
                score = safe_float(planner_idea.get("score"), 0.0)
                ready = bool(planner_idea.get("ready"))
                tier = safe_str(planner_idea.get("tier"), "")
                action_hint = safe_str(planner_idea.get("action_hint"), "")
                invalid = safe_float(planner_idea.get("invalid_level"), 0.0)
                tp_base = safe_float(planner_idea.get("tp_base"), 0.0)
                rsi = safe_float(d.get("rsi_main"), 50.0)
                vol_ratio = safe_float(d.get("vol_ratio"), 1.0)
                atr = safe_float(d.get("atr"), 0.0)

                if macro_filter == "block_longs":
                    return self._result(
                        should_open=False,
                        signal="BUY",
                        score=int(score),
                        setup_type="planner_spot_v1.8.1",
                        blocked_reason="macro filter blocks spot longs",
                    )

                if ready and price > 0 and score >= 70:
                    if invalid > 0 and price <= invalid:
                        return self._result(
                            should_open=False,
                            signal="BUY",
                            score=int(score),
                            setup_type="planner_spot_v1.8.1",
                            blocked_reason="price below planner invalid level",
                        )

                    if rsi >= 82:
                        return self._result(
                            should_open=False,
                            signal="BUY",
                            score=int(score),
                            setup_type="planner_spot_v1.8.1",
                            blocked_reason="spot overheated RSI",
                        )

                    if vol_ratio < 0.60:
                        return self._result(
                            should_open=False,
                            signal="BUY",
                            score=int(score),
                            setup_type="planner_spot_v1.8.1",
                            blocked_reason="spot volume too weak",
                        )

                    trigger = safe_float(
                        planner_idea.get("trigger_price")
                        or planner_idea.get("entry_zone_high")
                        or price * 1.0005,
                        price,
                    )

                    if tp_base <= 0:
                        tp_base = price + atr * safe_float(getattr(CONFIG.strategy, "spot_tp_atr_mult", 3.0), 3.0)

                    return self._result(
                        should_open=True,
                        signal="BUY",
                        score=int(min(score, 100)),
                        setup_type="planner_spot_v1.8.1",
                        args=[
                            f"Planner Tier {tier}",
                            action_hint,
                            f"planner_score={score}",
                            "validated_by_spot_strategy",
                        ],
                        threshold=0,
                        extra={
                            "trigger_price": trigger,
                            "invalidation_price": invalid,
                            "tp_base": tp_base,
                            "planner_score": score,
                            "planner_tier": tier,
                        },
                    )
            except Exception as exc:
                return self._result(blocked_reason=f"planner spot validation error: {exc}")

        return _vortex_old_analyze_spot(self, current, macro_filter, planner_idea=planner_idea)

    SwingStrategy.analyze_futures = _vortex_analyze_futures_v181
    SwingStrategy.analyze_spot = _vortex_analyze_spot_v181

except Exception:
    pass
# --- END VORTEX v1.8.1 STRATEGY FUTURES/SPOT UPGRADE ---
