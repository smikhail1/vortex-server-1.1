from strategy import SwingStrategy

def test_fee_guard():
    s = SwingStrategy()
    # Просто проверяем, что объект создается и метод расчета доступен
    price, atr = 100.0, 2.0
    ladder = s.calculate_futures_trade(price, "LONG", atr, "test")
    assert ladder["tp"] > price
    assert ladder["sl"] < price
    print("OK: test_fee_guard")

if __name__ == "__main__":
    test_fee_guard()
