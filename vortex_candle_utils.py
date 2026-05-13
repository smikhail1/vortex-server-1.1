from __future__ import annotations

from typing import Any, Dict, List


def parse_bitget_candles_payload(payload: Any) -> List[Dict[str, float]]:
    """
    Stable Bitget candle parser for VORTEX.

    Accepts:
      {"code":"00000","data":[["ts","open","high","low","close","baseVol","quoteVol"], ...]}
      [["ts","open","high","low","close","baseVol","quoteVol"], ...]
      [{"ts":..., "open":..., "high":..., "low":..., "close":..., "volume":...}, ...]

    Returns candles sorted ASC by timestamp:
      {"ts": int, "open": float, "high": float, "low": float, "close": float, "volume": float, "quote_volume": float}
    """
    data = payload

    if isinstance(payload, dict):
        data = payload.get("data", payload.get("result", payload.get("rows", [])))

    if isinstance(data, dict):
        for key in ("list", "items", "candles", "rows", "data"):
            if isinstance(data.get(key), list):
                data = data.get(key)
                break

    if not isinstance(data, list):
        return []

    out = []

    for c in data:
        try:
            if isinstance(c, dict):
                ts = c.get("ts", c.get("time", c.get("timestamp", c.get("openTime"))))
                o = c.get("open", c.get("o"))
                h = c.get("high", c.get("h"))
                l = c.get("low", c.get("l"))
                close = c.get("close", c.get("c"))
                vol = c.get("volume", c.get("baseVolume", c.get("baseVol", c.get("vol", 0))))
                qv = c.get("quote_volume", c.get("quoteVolume", c.get("quoteVol", c.get("turnover", 0))))
            elif isinstance(c, (list, tuple)) and len(c) >= 5:
                ts = c[0]
                o = c[1]
                h = c[2]
                l = c[3]
                close = c[4]
                vol = c[5] if len(c) > 5 else 0
                qv = c[6] if len(c) > 6 else 0
            else:
                continue

            item = {
                "ts": int(float(ts)),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(close),
                "volume": float(vol or 0.0),
                "quote_volume": float(qv or 0.0),
            }

            if item["high"] <= 0 or item["low"] <= 0 or item["close"] <= 0:
                continue

            out.append(item)
        except Exception:
            continue

    out.sort(key=lambda x: x.get("ts", 0))
    return out


def parse_bitget_candles_data(data: Any) -> List[Dict[str, float]]:
    return parse_bitget_candles_payload(data)
