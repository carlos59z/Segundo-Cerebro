import numpy as np
import pandas as pd
import pytest
import backtester as bt


def _df(closes):
    n = len(closes)
    return pd.DataFrame({"open": closes, "high": closes, "low": closes,
                         "close": closes, "volume": np.full(n, 1.0)},
                        index=pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC"))


def test_flat_series_sharpe_zero_not_nan():
    df = _df(np.full(60, 100.0))
    sig = pd.Series(0, index=df.index)
    m = bt.run_backtest(df, sig, cost_rate=0.0001)
    assert m["sharpe"] == 0.0
    assert m["total_return"] == 0.0
    assert m["n_trades"] == 0


def test_costs_reduce_return():
    closes = np.linspace(100, 140, 60)
    df = _df(closes)
    sig = pd.Series([1, 0, -1, 0] * 15, index=df.index)
    cheap = bt.run_backtest(df, sig, cost_rate=0.0)
    dear = bt.run_backtest(df, sig, cost_rate=0.01)
    assert cheap["total_return"] > dear["total_return"]
    assert dear["total_return"] < cheap["total_return"] - 0.05


def test_win_rate_and_trades_count():
    closes = np.array([100, 101, 102, 101, 100, 101, 103, 104, 103, 105] * 3, dtype=float)
    df = _df(closes)
    sig = pd.Series([0, 1, 0, -1, 0, 1, 0, -1, 0, 1] * 3, index=df.index)
    m = bt.run_backtest(df, sig, cost_rate=0.0001)
    assert m["n_trades"] >= 2
    assert 0.0 <= m["win_rate"] <= 1.0


def test_no_lookahead_backtest():
    closes = np.linspace(100, 150, 80)
    df = _df(closes)
    sig = pd.Series(0, index=df.index)
    sig.iloc[-3:] = 1
    m = bt.run_backtest(df, sig, 0.0)
    ret = df["close"].pct_change().fillna(0)
    expected = (1 + ret.iloc[-3]) * (1 + ret.iloc[-2]) * (1 + ret.iloc[-1]) - 1
    # la posicion solo gana los retornos desde su aparicion: nada retroactivo
    assert abs(m["total_return"] - expected) < 1e-5
    earlier = pd.Series(0, index=df.index)
    earlier.iloc[40:] = 1
    m2 = bt.run_backtest(df, earlier, 0.0)
    assert m2["total_return"] > m["total_return"]


def test_cost_table_complete():
    assert set(bt.COSTS) == {"crypto", "stocks", "etf", "futures", "forex"}


@pytest.mark.network
def test_rank_universe_smoke():
    rows = bt.rank_universe(phase="aggressive")
    assert len(rows) > 30
    assert all("sharpe" in r and "eligible" in r for r in rows[:10])


def test_win_rate_per_round_trip():
    closes = np.array([100.0, 100.0, 99.0, 101.0, 101.0])
    df = _df(closes)
    sig = pd.Series([0, 1, 1, 1, 0], index=df.index)
    m = bt.run_backtest(df, sig, 0.0)
    # un viaje completo ganador (con dia rojo dentro) = 100% win rate, no 1/3
    assert m["win_rate"] == 1.0
    assert m["n_trades"] == 2
