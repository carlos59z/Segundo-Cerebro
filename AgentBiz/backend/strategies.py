"""6 estrategias puras sobre OHLCV. Senales {-1,0,1} SIN lookahead (decision con shift(1))."""
import pandas as pd


def np_sign(s: pd.Series) -> pd.Series:
    return (s > 0).astype(int) - (s < 0).astype(int)


def _sma_cross(df, fast=20, slow=50):
    s_fast, s_slow = df["close"].rolling(fast).mean(), df["close"].rolling(slow).mean()
    raw = np_sign(s_fast - s_slow)
    return raw.shift(1).fillna(0).astype(int)


def _rsi(df, n=14):
    d = df["close"].diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, 1e-10)
    return 100 - 100 / (1 + rs)


def _rsi_reversion(df, period=14, oversold=30, overbought=70):
    r = _rsi(df, n=period)
    sig = pd.Series(0, index=df.index)
    sig[r < oversold] = 1
    sig[r > overbought] = -1
    return sig.shift(1).fillna(0).astype(int)


def _momentum_30d(df, window=30, threshold=0.05):
    mom = df["close"].pct_change(window)
    sig = pd.Series(0, index=df.index)
    sig[mom > threshold] = 1
    sig[mom < -threshold] = -1
    return sig.shift(1).fillna(0).astype(int)


def _donchian_breakout(df, channel=20, atr_period=14):
    hi, lo = df["high"].rolling(channel).max(), df["low"].rolling(channel).min()
    atr = (df["high"] - df["low"]).rolling(atr_period).mean()
    sig = pd.Series(0, index=df.index)
    sig[df["close"] > hi.shift(1)] = 1
    sig[df["close"] < lo.shift(1)] = -1
    sig[atr.fillna(0) <= 0] = 0
    return sig.shift(1).fillna(0).astype(int)


def _macd_trend(df, fast=12, slow=26, signal_period=9):
    e_fast = df["close"].ewm(span=fast).mean()
    e_slow = df["close"].ewm(span=slow).mean()
    macd = e_fast - e_slow
    signal = macd.ewm(span=signal_period).mean()
    raw = np_sign(macd - signal)
    return raw.shift(1).fillna(0).astype(int)


def _bollinger_reversion(df, window=20, devs=2.0):
    m, s = df["close"].rolling(window).mean(), df["close"].rolling(window).std()
    z = (df["close"] - m) / s.replace(0, float("nan"))
    sig = pd.Series(0, index=df.index)
    sig[z < -devs] = 1
    sig[z > devs] = -1
    return sig.shift(1).fillna(0).astype(int)


STRATEGIES = {
    "sma_cross": _sma_cross,
    "rsi_reversion": _rsi_reversion,
    "momentum_30d": _momentum_30d,
    "donchian_breakout": _donchian_breakout,
    "macd_trend": _macd_trend,
    "bollinger_reversion": _bollinger_reversion,
}

STRATEGY_PARAMS = {
    "sma_cross": {"fast": int, "slow": int},
    "rsi_reversion": {"period": int, "oversold": int, "overbought": int},
    "momentum_30d": {"window": int, "threshold": float},
    "donchian_breakout": {"channel": int, "atr_period": int},
    "macd_trend": {"fast": int, "slow": int, "signal_period": int},
    "bollinger_reversion": {"window": int, "devs": float},
}


def validate_params(base, params):
    if base not in STRATEGY_PARAMS:
        raise ValueError(f"estrategia base desconocida: {base}")
    unknown = set(params) - set(STRATEGY_PARAMS[base])
    if unknown:
        raise ValueError(f"parametros desconocidos para {base}: {sorted(unknown)}")
    casted = {k: STRATEGY_PARAMS[base][k](v) for k, v in params.items()}
    if base == "sma_cross" and casted.get("fast", 20) >= casted.get("slow", 50):
        raise ValueError("sma_cross: fast debe ser menor que slow")
    if base == "macd_trend" and casted.get("fast", 12) >= casted.get("slow", 26):
        raise ValueError("macd_trend: fast debe ser menor que slow")
    if base == "rsi_reversion" and casted.get("oversold", 30) >= casted.get("overbought", 70):
        raise ValueError("rsi_reversion: oversold debe ser menor que overbought")
    return casted
