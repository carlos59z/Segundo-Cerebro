"""Fuente unificada de datos: crypto (ccxt) + bolsa/forex/futuros (yfinance) con caché SQLite."""
import sqlite3
import pathlib
import datetime
import pandas as pd

DB_PATH = pathlib.Path(__file__).with_name("market_cache.db")

UNIVERSE = {
    "crypto": ["BTC", "ETH", "XRP", "SOL", "BNB", "DOGE", "ADA", "AVAX", "LINK", "DOT"],
    "etf": ["SPY", "QQQ", "DIA", "GLD", "TLT", "VTI"],
    "stocks": ["AAPL", "NVDA", "MSFT", "TSLA", "AMZN"],
    "forex": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"],
    "futures": ["ES=F", "NQ=F", "GC=F", "CL=F"],
}
PERP = ["BTCUSDT-PERP", "ETHUSDT-PERP"]


def list_universe():
    u = {k: list(v) for k, v in UNIVERSE.items()}
    u["crypto"] += PERP
    return u


def resolve(symbol: str):
    s = symbol.upper()
    for sym in UNIVERSE["crypto"] + PERP:
        if s == sym.upper():
            if s.endswith("-PERP"):
                base = s[:-5]
                if base.endswith("USDT"):
                    base = base[:-4]
                return ("ccxt-perp", f"{base}/USDT:USDT")
            return ("ccxt", f"{s}/USDT")
    for sym in UNIVERSE["forex"]:
        if s == sym:
            return ("yf", f"{s}=X")
    for m in ("etf", "stocks", "futures"):
        if s in UNIVERSE[m]:
            return ("yf", s)
    raise ValueError(f"Simbolo fuera del universo: {symbol}")


def _cache_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS ohlc (symbol TEXT, interval TEXT, ts TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(symbol, interval, ts))")
    conn.execute("CREATE TABLE IF NOT EXISTS price_cache (symbol TEXT PRIMARY KEY, price REAL, ts TEXT)")
    return conn


def _cache_store(df, symbol, interval):
    conn = _cache_conn()
    for ts, row in df.iterrows():
        conn.execute("INSERT OR REPLACE INTO ohlc VALUES (?,?,?,?,?,?,?,?)",
                     (symbol, interval, str(ts), row["open"], row["high"], row["low"], row["close"], row["volume"]))
    conn.commit()
    conn.close()


def _cache_load(symbol, interval) -> pd.DataFrame:
    conn = _cache_conn()
    df = pd.read_sql_query(
        "SELECT ts, open, high, low, close, volume FROM ohlc WHERE symbol=? AND interval=? ORDER BY ts",
        conn, params=(symbol, interval))
    conn.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")[["open", "high", "low", "close", "volume"]]


def _fetch_yf(native: str, period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(native, period=period, interval=interval, auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance sin datos para {native}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()
    df.index = pd.DatetimeIndex(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df


def _fetch_ccxt(native: str, interval: str, perp: bool, limit: int = 1000) -> pd.DataFrame:
    import ccxt
    import time
    ex_cls = ccxt.binanceusdm if perp else ccxt.binance
    ex = ex_cls({"enableRateLimit": True})
    tf = {"1d": "1d", "1h": "1h"}[interval]
    if interval == "1d":
        since = ex.parse8601(str(int((time.time() - limit * 86400)) * 1000))
        raw = ex.fetch_ohlcv(native, timeframe=tf, since=since, limit=limit)
    else:
        raw = ex.fetch_ohlcv(native, timeframe=tf, limit=limit)
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts")


def get_ohlc(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    source, native = resolve(symbol)
    if source == "yf":
        try:
            df = _fetch_yf(native, period, interval)
            _cache_store(df, symbol, interval)
            return df
        except Exception:
            cached = _cache_load(symbol, interval)
            if not cached.empty:
                return cached
            raise
    try:
        df = _fetch_ccxt(native, interval, perp=(source == "ccxt-perp"))
        _cache_store(df, symbol, interval)
        return df
    except Exception:
        cached = _cache_load(symbol, interval)
        if not cached.empty:
            return cached
        raise


def get_price(symbol: str) -> float:
    df = get_ohlc(symbol, period="5d", interval="1d")
    price = float(df["close"].iloc[-1])
    conn = _cache_conn()
    conn.execute("INSERT OR REPLACE INTO price_cache VALUES (?,?,?)",
                 (symbol, price, datetime.datetime.now(datetime.timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    return price
