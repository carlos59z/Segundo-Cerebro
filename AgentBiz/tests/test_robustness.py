import numpy as np
import pandas as pd
import robustness


def _mk_df(n=500, seed=7, drift=0.004, vol=0.005):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = 100 * np.cumprod(1 + rets)
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.full(n, 1000.0),
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def _always_long(df):
    return pd.Series(1, index=df.index)


def test_walk_forward_returns_metrics():
    df = _mk_df()
    r = robustness.walk_forward(df, _always_long, cost=0.0006, train=180, test=60)
    assert set(r) >= {"windows", "oos_return", "bh_return", "oos_sharpe", "win_vs_bh"}
    assert r["windows"] == 5  # 500 barras: start en 0,60,120,180,240
    assert r["oos_return"] == r["oos_return"]  # no NaN
    assert 0 <= r["win_vs_bh"] <= r["windows"]


def test_walk_forward_ventanas_sin_solape():
    df = _mk_df(n=400)
    r = robustness.walk_forward(df, _always_long, cost=0.0, train=100, test=50)
    assert r["windows"] == 6
    assert isinstance(r["oos_return"], float)


def test_monte_carlo_distribucion():
    rng = np.random.default_rng(1)
    rets = rng.normal(0.0005, 0.01, 500)
    r = robustness.monte_carlo(rets, n_sims=200, horizon=60, seed=42)
    assert set(r) >= {"p5_return", "median_return", "prob_loss"}
    assert r["prob_loss"] >= 0.0
    assert r["p5_return"] <= r["median_return"]


def test_gate_pasa_estrategia_sane():
    df = _mk_df(n=600, drift=0.002)  # tendencia alcista fuerte
    gate = robustness.robustness_gate(df, _always_long, cost=0.0006)
    assert gate["passed"] is True
    assert gate["oos"]["oos_return"] > 0


def test_gate_falla_estrategia_invertida_en_bajista():
    df = _mk_df(n=600, drift=-0.003, vol=0.005)  # tendencia bajista fuerte
    # long en bajista: debe fallar el gate
    gate_long = robustness.robustness_gate(df, _always_long, cost=0.0006)
    assert gate_long["passed"] is False


def test_gate_umbral_mc():
    # ruido puro con deriva negativa: MC debe mostrar prob_loss alta
    df = _mk_df(n=400, drift=-0.002, vol=0.01, seed=99)
    gate = robustness.robustness_gate(df, _always_long, cost=0.0006)
    assert gate["monte_carlo"]["prob_loss"] > 0.5
    assert gate["passed"] is False
