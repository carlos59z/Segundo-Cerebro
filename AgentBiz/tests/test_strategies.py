import numpy as np
import pandas as pd
import pytest
import strategies as st


def _trend_df(n=120):
    rng = np.random.default_rng(7)
    close = pd.Series(np.linspace(100, 160, n) + rng.normal(0, 1.0, n))
    return pd.DataFrame({
        "open": close.shift(1).fillna(100), "high": close + 1,
        "low": close - 1, "close": close, "volume": np.full(n, 1000.0),
    }, index=pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC"))


def test_registry_has_six():
    assert set(st.STRATEGIES) == {"sma_cross", "rsi_reversion", "momentum_30d",
                                  "donchian_breakout", "macd_trend", "bollinger_reversion"}


def test_signals_shape_and_values():
    df = _trend_df()
    for name, fn in st.STRATEGIES.items():
        sig = fn(df)
        assert len(sig) == len(df), name
        assert set(sig.unique()) <= {-1, 0, 1}, name


def test_no_lookahead_sma():
    n = 60
    df = pd.DataFrame({
        "open": np.full(n, 100.0), "high": np.full(n, 101.0),
        "low": np.full(n, 99.0), "close": np.full(n, 100.0),
        "volume": np.full(n, 1000.0),
    }, index=pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC"))
    sig = st.STRATEGIES["sma_cross"](df)
    assert sig.iloc[-1] == 0
    df2 = df.copy()
    df2.iloc[-1, df2.columns.get_loc("close")] = 500.0
    sig2 = st.STRATEGIES["sma_cross"](df2)
    # la decision en t usa solo datos hasta t-1: el cierre de hoy no cambia la senal de hoy
    assert sig2.iloc[-1] == 0
