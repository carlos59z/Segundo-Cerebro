import pytest
import market_data as md


def test_universe_has_five_markets():
    u = md.list_universe()
    assert set(u) == {"crypto", "etf", "stocks", "forex", "futures"}
    assert "BTC" in u["crypto"] and "SPY" in u["etf"] and "EURUSD" in u["forex"] and "ES=F" in u["futures"]


def test_resolve_rules():
    assert md.resolve("BTC") == ("ccxt", "BTC/USDT")
    assert md.resolve("SPY") == ("yf", "SPY")
    assert md.resolve("EURUSD") == ("yf", "EURUSD=X")
    assert md.resolve("ES=F") == ("yf", "ES=F")
    assert md.resolve("BTCUSDT-PERP") == ("ccxt-perp", "BTC/USDT:USDT")
    with pytest.raises(ValueError):
        md.resolve("NOEXISTE")


@pytest.mark.network
def test_get_ohlc_real_sp500_and_btc():
    spy = md.get_ohlc("SPY", period="1y", interval="1d")
    assert {"open", "high", "low", "close", "volume"} <= set(spy.columns)
    assert len(spy) >= 200
    assert str(spy.index.tz) == "UTC"
    btc = md.get_ohlc("BTC", period="1y", interval="1d")
    assert len(btc) >= 200


@pytest.mark.network
def test_get_price_positive():
    assert md.get_price("SPY") > 0
    assert md.get_price("BTC") > 0
