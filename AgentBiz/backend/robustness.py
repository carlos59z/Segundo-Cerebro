"""Robustez de estrategias: walk-forward out-of-sample + Monte Carlo.

Gate obligatorio antes de promover una estrategia a estandar/incubadora:
un backtest in-sample bonito no basta (ver walk-forward SMA -28% OOS).
"""
import math
import numpy as np
import pandas as pd


def walk_forward(df: pd.DataFrame, sig_fn, cost: float,
                 train: int = 180, test: int = 60) -> dict:
    """Ventanas OOS sin solape: entrena en `train` barras, evalua en `test`."""
    from backtester import run_backtest
    rets, bhs, sharpes = [], [], []
    start = 0
    while start + train + test <= len(df):
        test_df = df.iloc[start + train:start + train + test]
        sig = sig_fn(test_df)
        m = run_backtest(test_df, sig, cost)
        rets.append(m["total_return"])
        bhs.append(float(test_df["close"].iloc[-1] / test_df["close"].iloc[0] - 1))
        sharpes.append(m["sharpe"])
        start += test
    if not rets:
        return {"windows": 0, "oos_return": 0.0, "bh_return": 0.0,
                "oos_sharpe": 0.0, "win_vs_bh": 0}
    oos = float((1 + pd.Series(rets)).prod() - 1)
    bh = float((1 + pd.Series(bhs)).prod() - 1)
    return {
        "windows": len(rets),
        "oos_return": round(oos, 6),
        "bh_return": round(bh, 6),
        "oos_sharpe": round(float(np.mean(sharpes)), 4),
        "win_vs_bh": sum(1 for r, b in zip(rets, bhs) if r > b),
    }


def monte_carlo(net_returns, n_sims: int = 500, horizon: int = 60,
                seed: int = 42) -> dict:
    """Bootstrap de rendimientos diarios: distribucion de retorno a `horizon` dias."""
    arr = np.asarray(list(net_returns), dtype=float)
    if arr.size < 2:
        return {"p5_return": 0.0, "median_return": 0.0, "prob_loss": 0.0}
    rng = np.random.default_rng(seed)
    finals = np.empty(n_sims)
    h = min(horizon, arr.size)
    for i in range(n_sims):
        sample = rng.choice(arr, size=h, replace=True)
        finals[i] = float((1 + sample).prod() - 1)
    return {
        "p5_return": round(float(np.percentile(finals, 5)), 6),
        "median_return": round(float(np.median(finals)), 6),
        "prob_loss": round(float((finals < 0).mean()), 4),
    }


def robustness_gate(df: pd.DataFrame, sig_fn, cost: float,
                    min_oos_return: float = 0.0,
                    max_prob_loss: float = 0.60,
                    train: int = 180, test: int = 60) -> dict:
    """Veredicto combinado. passed solo si OOS no-destructivo y MC razonable.

    Si la serie es mas corta que train+test, las ventanas se adaptan
    (minimos 60/20) en vez de fallar siempre por falta de datos.
    """
    if train + test > len(df):
        train = max(60, len(df) // 3)
        test = max(20, len(df) // 8)
    oos = walk_forward(df, sig_fn, cost, train=train, test=test)
    from backtester import run_backtest
    m = run_backtest(df, sig_fn(df), cost)
    # net returns aproximados para MC: equity diaria implicita via pos*ret - costes
    close = df["close"].astype(float)
    pos = sig_fn(df).reindex(close.index).fillna(0)
    ret = close.pct_change().fillna(0)
    turnover = pos.diff().abs().fillna(abs(float(pos.iloc[0])) if len(pos) else 0.0)
    net = pos * ret - turnover * cost
    mc = monte_carlo(net.tolist())
    passed = (
        oos["windows"] >= 2
        and oos["oos_return"] >= min_oos_return
        and mc["prob_loss"] <= max_prob_loss
    )
    return {"passed": bool(passed), "oos": oos, "monte_carlo": mc,
            "in_sample_sharpe": m["sharpe"]}
