"""Backtest long/short con costes por operacion y ranking por fase."""
import math
import pandas as pd

COSTS = {"crypto": 0.0006, "stocks": 0.0001, "etf": 0.0001, "futures": 0.0001, "forex": 0.000015}


def run_backtest(df: pd.DataFrame, signals: pd.Series, cost_rate: float) -> dict:
    close = df["close"].astype(float)
    pos = signals.reindex(close.index).fillna(0)
    ret = close.pct_change().fillna(0)
    pos_ret = pos * ret
    diff = pos.diff().abs()
    turnover = diff.fillna(abs(float(pos.iloc[0])) if len(pos) else 0.0)
    costs = turnover * cost_rate
    net = pos_ret - costs
    equity = (1 + net).cumprod()
    total = float(equity.iloc[-1] - 1)
    n = len(net)
    annualized = float((1 + total) ** (252 / max(n, 1)) - 1) if n else 0.0
    vol = float(net.std())
    sharpe = 0.0
    if vol > 1e-12 and not math.isnan(vol):
        sharpe = float(net.mean() / vol * math.sqrt(252))
    peak = equity.cummax()
    dd = float(((equity - peak) / peak).min()) if n else 0.0
    trades = int((turnover > 0).sum())
    leg_ret = net[pos != 0]
    wins = int((leg_ret > 0).sum())
    total_active = int(len(leg_ret))
    win_rate = wins / total_active if total_active else 0.0
    gross_win = float(leg_ret[leg_ret > 0].sum()) if total_active else 0.0
    gross_loss = float(-leg_ret[leg_ret < 0].sum()) if total_active else 0.0
    if gross_loss > 1e-12:
        profit_factor = gross_win / gross_loss
    elif gross_win > 0:
        profit_factor = 99.0
    else:
        profit_factor = 0.0
    return {
        "total_return": round(total, 6),
        "annualized": round(annualized, 6),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(dd, 6),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(min(profit_factor, 99.0), 4),
        "n_trades": trades,
    }


def _eligible(m: dict, phase: str) -> bool:
    if m["n_trades"] < 2:
        return False
    if phase == "aggressive":
        return m["max_drawdown"] >= -0.35
    return m["max_drawdown"] >= -0.15 and m["sharpe"] >= 0.5


def rank_universe(phase: str = "aggressive", period: str = "1y") -> list[dict]:
    from market_data import list_universe, get_ohlc
    from strategies import STRATEGIES
    rows = []
    for market, symbols in list_universe().items():
        cost = COSTS.get(market, COSTS["crypto"])
        for sym in symbols:
            try:
                df = get_ohlc(sym, period=period, interval="1d")
            except Exception:
                continue
            for name, fn in STRATEGIES.items():
                try:
                    m = run_backtest(df, fn(df), cost)
                except Exception:
                    continue
                m.update({"symbol": sym, "market": market, "strategy": name,
                          "eligible": _eligible(m, phase)})
                rows.append(m)
    rows.sort(key=lambda r: r["sharpe"], reverse=True)
    return rows
