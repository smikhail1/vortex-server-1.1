from vortex_candle_utils import parse_bitget_candles_payload, parse_bitget_candles_data
import asyncio
from typing import Dict, List, Optional
from config import CONFIG
from market_regime import MarketRegimeEvaluator
from validators import safe_float, safe_str

class TAService:
    def __init__(self, state_manager, candle_service=None, logger=None) -> None:
        self.state = state_manager
        self.candle_service = candle_service
        self.logger = logger
        self.regime = MarketRegimeEvaluator()

    @staticmethod
    def _ema(values, period):
        clean = [float(x) for x in values if x > 0]
        if not clean: return 0.0
        k = 2 / (period + 1)
        res = clean[0]
        for v in clean[1:]: res = v * k + res * (1 - k)
        return res

    @staticmethod
    def _rsi(closes, period=14):
        if len(closes) < period + 1: return 50.0
        g, l = [], []
        for i in range(1, len(closes[-(period+1):])):
            d = closes[i] - closes[i-1]
            g.append(max(0, d)); l.append(abs(min(0, d)))
        ag, al = sum(g)/period, sum(l)/period
        if al == 0: return 100.0 if ag > 0 else 50.0
        return 100.0 - (100.0 / (1.0 + (ag/al)))

    @staticmethod
    def _calculate_adx(candles, period=14):
        if len(candles) < period * 2: return 25.0
        trs, p_dm, m_dm = [], [], []
        t = candles[-(period*2):]
        for i in range(1, len(t)):
            h, l, ph, pl, pc = safe_float(t[i]['high']), safe_float(t[i]['low']), safe_float(t[i-1]['high']), safe_float(t[i-1]['low']), safe_float(t[i-1]['close'])
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
            up, dn = h-ph, pl-l
            p_dm.append(up if up > dn and up > 0 else 0.0)
            m_dm.append(dn if dn > up and dn > 0 else 0.0)
        atr_v = sum(trs[-period:])/period
        if atr_v <= 0: return 25.0
        p_di = 100 * (sum(p_dm[-period:])/period) / atr_v
        m_di = 100 * (sum(m_dm[-period:])/period) / atr_v
        return 100 * abs(p_di - m_di) / (p_di + m_di if (p_di + m_di) > 0 else 1.0)

    def _build_symbol_ta(self, symbol, c30, c4h, live_price=0.0):
        if not c30: return None
        cl = [safe_float(x.get("close")) for x in c30 if safe_float(x.get("close")) > 0]
        if not cl: return None
        price = safe_float(live_price) or cl[-1]
        
        adx = self._calculate_adx(c30)
        rsi = self._rsi(cl)
        rsi_slope = rsi - self._rsi(cl[:-1])
        
        # Wick Analysis
        last = c30[-1]
        body = abs(safe_float(last['close']) - safe_float(last['open']))
        u_sh = safe_float(last['high']) - max(safe_float(last['close']), safe_float(last['open']))
        l_sh = min(safe_float(last['close']), safe_float(last['open'])) - safe_float(last['low'])

        base = {
            "price": price, "adx": round(adx, 2), "rsi_main": round(rsi, 2), "rsi_slope": round(rsi_slope, 2),
            "ema10": self._ema(cl[-30:], 10), "ema20": self._ema(cl[-50:], 20), "ema50": self._ema(cl[-100:], 50),
            "vol_ratio": self._volume_ratio(c30), "atr_pct": (self._atr(c30)/price*100) if price > 0 else 0.0,
            "wick_long_danger": u_sh > (body * 2.0) if body > 0 else False,
            "wick_short_danger": l_sh > (body * 2.0) if body > 0 else False,
            "trend_4h": self._trend_from_4h(c4h)
        }
        base.update({"atr": self._atr(c30), "recent_high": max(x['high'] for x in c30[-20:]), "recent_low": min(x['low'] for x in c30[-20:])})
        return base

    @staticmethod
    def _atr(c, p=14):
        if len(c)<2: return 0.0
        trs = [max(c[i]['high']-c[i]['low'], abs(c[i]['high']-c[i-1]['close']), abs(c[i]['low']-c[i-1]['close'])) for i in range(1, len(c[-p-1:]))]
        return sum(trs)/len(trs) if trs else 0.0

    @staticmethod
    def _volume_ratio(c, p=20):
        if len(c)<3: return 1.0
        last = safe_float(c[-1].get('quote_volume') or c[-1].get('volume'))
        prev = [safe_float(x.get('quote_volume') or x.get('volume')) for x in c[-p-1:-1]]
        avg = sum(prev)/len(prev) if prev else 1.0
        return last/avg if avg > 0 else 1.0

    def _trend_from_4h(self, c4):
        cl = [x['close'] for x in c4 if x['close']>0]
        if len(cl)<20: return "neutral"
        e20, e50 = self._ema(cl, 20), self._ema(cl, 50)
        return "up" if e20 > e50 else "down" if e20 < e50 else "neutral"

    async def loop(self) -> None:
        while True:
            try:
                dash = await self.state.get_dashboard_state()
                prices = dash.get("market", {}).get("prices", {})
                pools = set(list(dash.get("system", {}).get("fut_pool", [])) + list(dash.get("system", {}).get("spot_pool", [])))
                ta_data = {}
                for sym in pools:
                    sn = self.candle_service.get_symbol_snapshot(sym, "fut") or self.candle_service.get_symbol_snapshot(sym, "spot")
                    if sn:
                        item = self._build_symbol_ta(sym, sn.get("candles_30m", []), sn.get("candles_4h", []), live_price=prices.get(sym, 0))
                        if item: ta_data[sym] = item
                await self.state.update_ta_data(ta_data)
            except Exception as e: await self.state.add_sys_log("❌ [TA]", str(e))
            await asyncio.sleep(CONFIG.loops.ta_sec)
