"""6 estrategias puras sobre OHLCV. Senales {-1,0,1} SIN lookahead (decision con shift(1))."""
import pandas as pd


def np_sign(s: pd.Series) -> pd.Series:
    return (s > 0).astype(int) - (s < 0).astype(int)


def _sma_cross(df):
    s20, s50 = df["close"].rolling(20).mean(), df["close"].rolling(50).mean()
    raw = np_sign(s20 - s50)
    return raw.shift(1).fillna(0).astype(int)


def _rsi(df, n=14):
    d = df["close"].diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, 1e-10)
    return 100 - 100 / (1 + rs)


def _rsi_reversion(df):
    r = _rsi(df)
    sig = pd.Series(0, index=df.index)
    sig[r < 30] = 1
    sig[r > 70] = -1
    return sig.shift(1).fillna(0).astype(int)


def _momentum_30d(df):
    mom = df["close"].pct_change(30)
    sig = pd.Series(0, index=df.index)
    sig[mom > 0.05] = 1
    sig[mom < -0.05] = -1
    return sig.shift(1).fillna(0).astype(int)


def _donchian_breakout(df):
    hi, lo = df["high"].rolling(20).max(), df["low"].rolling(20).min()
    atr = (df["high"] - df["low"]).rolling(14).mean()
    sig = pd.Series(0, index=df.index)
    sig[df["close"] > hi.shift(1)] = 1
    sig[df["close"] < lo.shift(1)] = -1
    sig[atr.fillna(0) <= 0] = 0
    return sig.shift(1).fillna(0).astype(int)


def _macd_trend(df):
    e12, e26 = df["close"].ewm(span=12).mean(), df["close"].ewm(span=26).mean()
    macd = e12 - e26
    signal = macd.ewm(span=9).mean()
    raw = np_sign(macd - signal)
    return raw.shift(1).fillna(0).astype(int)


def _bollinger_reversion(df):
    m, s = df["close"].rolling(20).mean(), df["close"].rolling(20).std()
    z = (df["close"] - m) / s.replace(0, float("nan"))
    sig = pd.Series(0, index=df.index)
    sig[z < -2] = 1
    sig[z > 2] = -1
    return sig.shift(1).fillna(0).astype(int)


STRATEGIES = {
    "sma_cross": _sma_cross,
    "rsi_reversion": _rsi_reversion,
    "momentum_30d": _momentum_30d,
    "donchian_breakout": _donchian_breakout,
    "macd_trend": _macd_trend,
    "bollinger_reversion": _bollinger_reversion,
}
