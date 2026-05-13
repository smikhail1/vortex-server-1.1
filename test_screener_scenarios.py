import asyncio

from market_screener import MarketScreener
from validators import (
    is_ascii_asset_code,
    is_tradable_universe_symbol,
    normalize_symbol,
    split_usdt_symbol,
)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def scenario_fallback_filters_work() -> None:
    screener = MarketScreener(
        fallback_symbols=[
            "BTCUSDT",
            "ETHUSDT",
            "USDCUSDT",
            "FDUSDUSDT",
            "BTCUPUSDT",
            "SOLUSDT",
            "XRPUSDT",
            "币安人生USDT",
            "USD1USDT",
            "XAUTUSDT",
        ]
    )

    universe = screener._fallback_universe(limit=20)

    assert_true("BTCUSDT" in universe, "BTCUSDT must survive fallback")
    assert_true("ETHUSDT" in universe, "ETHUSDT must survive fallback")
    assert_true("SOLUSDT" in universe, "SOLUSDT must survive fallback")

    assert_true("USDCUSDT" not in universe, "USDCUSDT must be excluded")
    assert_true("FDUSDUSDT" not in universe, "FDUSDUSDT must be excluded")
    assert_true("BTCUPUSDT" not in universe, "leveraged token must be excluded")
    assert_true("币安人生USDT" not in universe, "non-ascii symbol must be excluded")
    assert_true("USD1USDT" not in universe, "USD1 must be excluded")
    assert_true("XAUTUSDT" not in universe, "XAUT must be excluded")

    print("OK: scenario_fallback_filters_work")


async def scenario_symbol_normalization() -> None:
    assert_true(normalize_symbol("btc/usdt") == "BTCUSDT", "symbol normalization failed")
    assert_true(normalize_symbol("eth-usdt") == "ETHUSDT", "symbol normalization failed")
    assert_true(normalize_symbol(" sol_usdt ") == "SOLUSDT", "symbol normalization failed")
    print("OK: scenario_symbol_normalization")


async def scenario_ascii_asset_filter() -> None:
    assert_true(is_ascii_asset_code("BTC"), "BTC should pass ascii filter")
    assert_true(is_ascii_asset_code("FET"), "FET should pass ascii filter")
    assert_true(not is_ascii_asset_code("币安人生"), "non-ascii should fail")
    assert_true(not is_ascii_asset_code("A"), "too short base asset should fail")
    print("OK: scenario_ascii_asset_filter")


async def scenario_tradable_symbol_filter() -> None:
    assert_true(is_tradable_universe_symbol("BTCUSDT"), "BTCUSDT should be tradable")
    assert_true(not is_tradable_universe_symbol("USDCUSDT"), "USDCUSDT should be excluded")
    assert_true(not is_tradable_universe_symbol("FDUSDUSDT"), "FDUSDUSDT should be excluded")
    assert_true(not is_tradable_universe_symbol("BTCUPUSDT"), "BTCUPUSDT should be excluded")
    assert_true(not is_tradable_universe_symbol("ETHDOWNUSDT"), "ETHDOWNUSDT should be excluded")
    assert_true(not is_tradable_universe_symbol("XAUTUSDT"), "XAUTUSDT should be excluded")
    assert_true(not is_tradable_universe_symbol("USD1USDT"), "USD1USDT should be excluded")
    print("OK: scenario_tradable_symbol_filter")


async def scenario_split_symbol() -> None:
    base, quote = split_usdt_symbol("BTCUSDT")
    assert_true(base == "BTC", "base asset parse failed")
    assert_true(quote == "USDT", "quote asset parse failed")
    print("OK: scenario_split_symbol")


async def run_all() -> None:
    await scenario_fallback_filters_work()
    await scenario_symbol_normalization()
    await scenario_ascii_asset_filter()
    await scenario_tradable_symbol_filter()
    await scenario_split_symbol()
    print("ALL SCREENER TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(run_all())