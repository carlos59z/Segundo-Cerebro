import pandas as pd
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
    # frescura: si el cache cubriera una caida de yfinance, esta linea falla
    assert (pd.Timestamp.now(tz="UTC") - spy.index[-1]).days <= 10
    btc = md.get_ohlc("BTC", period="1y", interval="1d")
    assert len(btc) >= 200
    assert (pd.Timestamp.now(tz="UTC") - btc.index[-1]).days <= 10


@pytest.mark.network
def test_get_price_positive():
    assert md.get_price("SPY") > 0
    assert md.get_price("BTC") > 0


def test_yf_fallback_returns_cached_when_fetch_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(md, "DB_PATH", str(tmp_path / "cache.db"))
    seed = pd.DataFrame({"open": [1.0, 1.0], "high": [1.0, 1.0],
                         "low": [1.0, 1.0], "close": [1.0, 1.0],
                         "volume": [1.0, 1.0]},
                        index=pd.date_range("2026-09-01", periods=2))
    md._cache_store(seed, "SPY", "1d")

    def boom(*a, **k):
        raise RuntimeError("yfinance caido")

    monkeypatch.setattr(md, "_fetch_yf", boom)
    out = md.get_ohlc("SPY")
    assert len(out) == 2
    assert list(out.columns)[:4] == ["open", "high", "low", "close"]


def test_yf_fallback_raises_when_no_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(md, "DB_PATH", str(tmp_path / "empty.db"))

    def boom(*a, **k):
        raise RuntimeError("yfinance caido")

    monkeypatch.setattr(md, "_fetch_yf", boom)
    with pytest.raises(RuntimeError):
        md.get_ohlc("SPY")


def test_ccxt_fallback_returns_cached_when_fetch_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(md, "DB_PATH", str(tmp_path / "ccxt.db"))
    seed = pd.DataFrame({"open": [100.0, 100.0], "high": [101.0, 101.0],
                         "low": [99.0, 99.0], "close": [100.0, 100.0],
                         "volume": [10.0, 10.0]},
                        index=pd.date_range("2026-09-01", periods=2))
    md._cache_store(seed, "BTC", "1d")

    def boom(*a, **k):
        raise RuntimeError("binance caido")

    monkeypatch.setattr(md, "_fetch_ccxt", boom)
    out = md.get_ohlc("BTC")
    assert len(out) == 2
