import requests, time

class MarketScreener:
    """
    Живой скринер монет.
    Сканирует весь рынок каждые 60 сек.
    Монета попадает в пул только если есть реальный триггер.
    Монета выбрасывается из пула если триггер исчез.
    """
    def __init__(self):
        self.baseline_vol  = {}   # базовый объём для каждой монеты
        self.btc_change    = 0.0  # движение BTC за последний цикл
        self.watchlist     = {}   # {symbol: {"score": X, "added_at": T, "confirmed": 0}}
        self.last_scan     = 0

    def _fetch_tickers(self):
        r = requests.get(
            "https://api.bitget.com/api/v2/mix/market/tickers"
            "?productType=USDT-FUTURES", timeout=6
        ).json()
        return {t["symbol"]: t for t in r.get("data", [])
                if t["symbol"].endswith("USDT")}

    def _update_btc(self, tickers):
        btc = tickers.get("BTCUSDT", {})
        try:
            self.btc_change = float(btc.get("priceChangePercent", 0))
        except Exception:
            self.btc_change = 0.0

    def _score_ticker(self, sym, t):
        """Быстрая оценка тикера без запроса свечей"""
        try:
            price   = float(t.get("lastPr", 0))
            change  = float(t.get("priceChangePercent", 0))
            vol     = float(t.get("quoteVolume", 0))
            high24  = float(t.get("high24h", price))
            low24   = float(t.get("low24h", price))
            funding = float(t.get("fundingRate", 0))
        except Exception:
            return None

        # минимальный объём $500k
        if vol < 500_000 or price <= 0:
            return None

        # флэт — не интересен
        rng = high24 - low24
        rng_pct = rng / price * 100 if price > 0 else 0
        if rng_pct < 1.0:
            return None

        score  = 0
        args   = []
        signal = "neutral"

        # обновляем базовый объём (скользящее среднее)
        prev_vol = self.baseline_vol.get(sym, vol)
        vol_ratio = vol / prev_vol if prev_vol > 0 else 1.0
        self.baseline_vol[sym] = prev_vol * 0.8 + vol * 0.2

        # 1. Аномальный объём
        if vol_ratio > 2.0:
            score += 3; args.append(f"Объём ×{vol_ratio:.1f} 🔥")
        elif vol_ratio > 1.5:
            score += 2; args.append(f"Объём ×{vol_ratio:.1f}")

        # 2. Движение сильнее BTC
        btc = self.btc_change
        if abs(btc) > 0.3 and abs(change) > abs(btc):
            ratio = abs(change) / abs(btc)
            same_dir = (change > 0) == (btc > 0)
            if ratio > 2.0 and same_dir:
                score += 2; args.append(f"Лидер ×{ratio:.1f}")
            elif ratio > 1.3 and same_dir:
                score += 1; args.append(f"Сильнее BTC ×{ratio:.1f}")

        # 3. Рост без объёма = слабость = шорт кандидат
        if change > 1.0 and vol_ratio < 0.7:
            score += 2; args.append("Рост без объёма ⚠️")
            signal = "short"
        elif change > 0:
            signal = "long"
        else:
            signal = "short"

        # 4. У хая/лоя дня — пробой уровня
        pos = (price - low24) / rng if rng > 0 else 0.5
        if pos > 0.92:
            score += 2; args.append("Хай дня 🔝"); signal = "long"
        elif pos < 0.08:
            score += 2; args.append("Лой дня 🔻"); signal = "short"

        # 5. Фандинг экстремальный
        if funding > 0.001:
            score += 1; args.append(f"Фандинг {funding*100:.3f}%")
        elif funding < -0.001:
            score += 1; args.append(f"Фандинг {funding*100:.3f}%")

        if score < 3:
            return None

        return {
            "symbol":  sym,
            "score":   score,
            "signal":  signal,
            "change":  change,
            "vol":     vol,
            "vol_ratio": vol_ratio,
            "args":    args,
        }

    def update_watchlist(self):
        """
        Основной метод — вызывается из main.py.
        Возвращает актуальный список символов для пула.
        """
        now = time.time()
        # не спамим биржу — не чаще раза в 60 сек
        if now - self.last_scan < 60:
            return list(self.watchlist.keys())

        self.last_scan = now

        try:
            tickers = self._fetch_tickers()
            self._update_btc(tickers)

            found = {}
            for sym, t in tickers.items():
                if sym in ("BTCUSDT", "ETHUSDT"):
                    # BTC/ETH всегда в базовом пуле, не в скринере
                    self.baseline_vol[sym] = float(t.get("quoteVolume", 0))
                    continue
                res = self._score_ticker(sym, t)
                if res:
                    found[sym] = res

            # обновляем watchlist
            # добавляем новых кандидатов
            for sym, info in found.items():
                if sym not in self.watchlist:
                    self.watchlist[sym] = {
                        "score":      info["score"],
                        "signal":     info["signal"],
                        "added_at":   now,
                        "confirmed":  0,
                        "args":       info["args"],
                    }
                else:
                    # монета подтверждается повторно
                    self.watchlist[sym]["score"]     = info["score"]
                    self.watchlist[sym]["confirmed"] += 1
                    self.watchlist[sym]["args"]      = info["args"]

            # удаляем монеты которые не подтверждаются
            to_remove = []
            for sym in list(self.watchlist.keys()):
                if sym not in found:
                    # монета не прошла фильтр — удаляем
                    to_remove.append(sym)
                elif now - self.watchlist[sym]["added_at"] > 3600:
                    # монета в пуле больше часа без входа — удаляем
                    to_remove.append(sym)
            for sym in to_remove:
                del self.watchlist[sym]

            # топ-6 по score
            top = sorted(self.watchlist.items(),
                         key=lambda x: x[1]["score"], reverse=True)[:6]
            return [s for s, _ in top]

        except Exception:
            return list(self.watchlist.keys())[:6]

    def get_info(self, symbol):
        return self.watchlist.get(symbol, {})
