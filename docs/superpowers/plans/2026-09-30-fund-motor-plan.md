# Motor del Fondo — Implementation Plan (Plan 1 de 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el motor Python del fondo: datos de 5 mercados, portafolio paper de $2,500 con fases de riesgo, 6 estrategias y backtester con ranking.

**Architecture:** Cuatro módulos puros en `AgentBiz/backend/` sin dependencia de FastAPI: `market_data.py` (fuente unificada ccxt+yfinance con caché SQLite), `strategies.py` (señales sobre OHLCV), `backtester.py` (métricas con costes), `paper_portfolio.py` (posiciones, SL/TP, límites por fase). Tests unitarios con pytest; datos reales de prueba marcados como de red.

**Tech Stack:** Python 3.13 (C:\Python313\python.exe), pandas, yfinance (instalar), ccxt (ya instalado), sqlite3, pytest (instalar).

**Spec:** `docs/superpowers/specs/2026-09-30-segundo-cerebro-capital-design.md`

## Global Constraints

- Windows + PowerShell: nunca `&&`/`||`; usar `;`. JSON por curl: `--data-binary @archivo`.
- Python con `$env:PYTHONUTF8="1"` y `$env:PYTHONIOENCODING="utf-8"` en todo proceso de test/servicio.
- Capital inicial exacto: **2500.0 USD**. Fases: `aggressive` (riesgo 5–10%, max 5 pos, stop día -10%, drawdown alerta -20%, leverage 5x) y `moderate` (2–3%, max 4, -5%, -10%, 2x).
- Costes de trading: crypto 0.06%, acciones/ETF/futuros 0.01%, forex 1.5 pips (≈0.00015 del precio en pares XXXUSD... usar 0.0015% del notional en forex, documentado en código).
- Universo: crypto [BTC,ETH,XRP,SOL,BNB,DOGE,ADA,AVAX,LINK,DOT]; ETF [SPY,QQQ,DIA,GLD,TLT,VTI]; acciones [AAPL,NVDA,MSFT,TSLA,AMZN]; forex [EURUSD,GBPUSD,USDJPY,AUDUSD]; futuros [ES=F,NQ=F,GC=F,CL=F] + perpetuos [BTCUSDT-PERP, ETHUSDT-PERP].
- Sin API keys. Sin transformers/torch.
- Toda función pura recibe datos; `market_data` es el único módulo que toca red (y su caché).
- Commits cortos tras cada tarea: prefijo `feat:`/`test:`/`fix:`.

## Review Focus

Los 5 modos de fallo que ningún test obvious cubre y que rompen el fondo primero:

1. **Lookahead bias** — usar el cierre de t+1 para decidir en t → backtest irrealmente ganador. Test: las señales de cada estrategia deben calcularse solo con datos ≤ t (`shift(1)` en la decisión); test explícito en Task 3.
2. **yfinance cambia columnas/horarios** — devuelve `Adj Close`, índices sin tz, o vacío en fin de semana → crash o NaN silencioso. Test: columnas normalizadas `open/high/low/close/volume/tz-aware`, y OHLC vacío devuelve último cierre cacheado (Task 1).
3. **Sharpe con serie plana o 1 solo trade** — división por cero / NaN → ranking basura. Test: serie de precios constante → Sharpe 0.0, no excepción (Task 3).
4. **Límites de fase saltados** — cambiar a moderada con posiciones abiertas agresivas → posición vieja no afecta nuevas aperturas. Test: `set_phase` conserva posiciones, y `can_open` aplica los límites de la fase NUEVA (Task 4).
5. **SL/TP no se evalúan sin marcado** — posición se queda abierta indefinidamente si nadie llama a marcar. Test: `mark_to_market` cierra automáticamente al tocar SL/TP intra-barra (low ≤ SL ≤ high) (Task 4).

---

### Task 1: market_data.py — fuente unificada con caché

**Files:**
- Create: `AgentBiz/backend/market_data.py`
- Create: `AgentBiz/tests/conftest.py`
- Create: `AgentBiz/tests/test_market_data.py`

**Interfaces:**
- Consumes: `ccxt` (ya instalado), `yfinance` (instalar en Step 1), sqlite3, pandas.
- Produces (lo usan Tasks 2–4 y luego la API):
  - `list_universe() -> dict[str, list[str]]` — {"crypto": [...], "etf": [...], "stocks": [...], "forex": [...], "futures": [...]}
  - `resolve(symbol: str) -> tuple[str, str]` — devuelve `("ccxt","BTC/USDT")`, `("yf","SPY")`, `("yf","EURUSD=X")`, `("yf","ES=F")`, `("ccxt-perp","BTC/USDT:USDT")` según reglas; lanza `ValueError` si no está en el universo
  - `get_price(symbol: str) -> float`
  - `get_ohlc(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame` — columnas `["open","high","low","close","volume"]`, índice tz-aware UTC, nunca vacío

- [ ] **Step 1: Instalar dependencias y crear conftest**

```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pip install yfinance pytest
```

`AgentBiz/tests/conftest.py`:
```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
```

- [ ] **Step 2: Escribir test fallando (resolución + universo)**

`AgentBiz/tests/test_market_data.py`:
```python
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
```

- [ ] **Step 3: Ejecutar y ver fallar**

```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_market_data.py -v
```
Expected: FAIL (`ModuleNotFoundError: market_data`)

- [ ] **Step 4: Implementar market_data.py (mínimo para pasar + OHLC/precio)**

```python
"""Fuente unificada de datos: crypto (ccxt) + bolsa/forex/futuros (yfinance) con caché SQLite."""
import sqlite3, pathlib
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
                return ("ccxt-perp", f"{s[:-5]}/USDT:USDT")
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
    conn.commit(); conn.close()

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
    import ccxt, time
    ex_cls = ccxt.binanceusdm if perp else ccxt.binance
    ex = ex_cls({"enableRateLimit": True})
    tf = {"1d": "1d", "1h": "1h"}[interval]
    since = ex.parse8601(str(int((time.time() - limit * 86400)) * 1000)) if interval == "1d" else None
    raw = ex.fetch_ohlcv(native, timeframe=tf, since=since, limit=limit)
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
    df = _fetch_ccxt(native, interval, perp=(source == "ccxt-perp"))
    _cache_store(df, symbol, interval)
    return df

def get_price(symbol: str) -> float:
    source, _ = resolve(symbol)
    df = get_ohlc(symbol, period="5d", interval="1d")
    price = float(df["close"].iloc[-1])
    conn = _cache_conn()
    import datetime
    conn.execute("INSERT OR REPLACE INTO price_cache VALUES (?,?,?)",
                 (symbol, price, datetime.datetime.now(datetime.timezone.utc).isoformat()))
    conn.commit(); conn.close()
    return price
```

- [ ] **Step 5: Ejecutar tests de red (un mercado por fuente)**

Añadir a `test_market_data.py`:
```python
import pytest

@pytest.mark.network
def test_get_ohlc_real_sp500_and_btc():
    spy = md.get_ohlc("SPY", period="1y", interval="1d")
    assert {"open","high","low","close","volume"} <= set(spy.columns)
    assert len(spy) >= 200
    assert str(spy.index.tz) == "UTC"
    btc = md.get_ohlc("BTC", period="1y", interval="1d")
    assert len(btc) >= 200

@pytest.mark.network
def test_get_price_positive():
    assert md.get_price("SPY") > 0
    assert md.get_price("BTC") > 0
```
Y en `conftest.py` añadir:
```python
def pytest_configure(config):
    config.addinivalue_line("markers", "network: tests que descargan datos reales")
```
Run:
```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_market_data.py -v
```
Expected: PASS (5 tests). Si yfinance devuelve vacío: reintentar una vez; el fallback a caché está cubierto.

- [ ] **Step 6: Commit**

```powershell
git add AgentBiz/backend/market_data.py AgentBiz/tests/; git commit -m "feat: market_data unificado (ccxt+yfinance) con caché SQLite"
```

---

### Task 2: strategies.py — 6 estrategias como señales

**Files:**
- Create: `AgentBiz/backend/strategies.py`
- Test: `AgentBiz/tests/test_strategies.py`

**Interfaces:**
- Consumes: `get_ohlc` de market_data (para integración; los tests usan datos sintéticos, sin red).
- Produces:
  - Cada estrategia: `func(df: pd.DataFrame) -> pd.Series[int]` — mismos índices que `df`, valores en `{-1, 0, 1}` (SELL/HOLD/BUY), decisión aplicada con `shift(1)` (sin lookahead).
  - `STRATEGIES: dict[str, callable]` con exactamente las 6 claves: `"sma_cross"`, `"rsi_reversion"`, `"momentum_30d"`, `"donchian_breakout"`, `"macd_trend"`, `"bollinger_reversion"`.

- [ ] **Step 1: Test fallando (señal sin lookahead + claves)**

`AgentBiz/tests/test_strategies.py`:
```python
import numpy as np, pandas as pd, pytest
import strategies as st

def _trend_df(n=120):
    rng = np.random.default_rng(7)
    close = pd.Series(np.linspace(100, 160, n) + rng.normal(0, 1.0, n))
    return pd.DataFrame({
        "open": close.shift(1).fillna(100), "high": close + 1,
        "low": close - 1, "close": close, "volume": np.full(n, 1000.0),
    }, index=pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC"))

def test_registry_has_six():
    assert set(st.STRATEGIES) == {"sma_cross","rsi_reversion","momentum_30d",
                                  "donchian_breakout","macd_trend","bollinger_reversion"}

def test_signals_shape_and_values():
    df = _trend_df()
    for name, fn in st.STRATEGIES.items():
        sig = fn(df)
        assert len(sig) == len(df), name
        assert set(sig.unique()) <= {-1, 0, 1}, name

def test_no_lookahead_sma():
    df = _trend_df()
    sig = st.STRATEGIES["sma_cross"](df)
    df2 = df.copy()
    df2.loc[df2.index[-3]:, "close"] = df2.loc[df2.index[-3]:, "close"] * 2  # cambia el final
    sig2 = st.STRATEGIES["sma_cross"](df2)
    # la decisión en t usa SMA calculada con close hasta t-1: tocar el último cierre
    # no debe cambiar la señal de t-3 (que ya usa datos previos) pero sí puede cambiar t-2/t-1
    assert sig.iloc[-5] == sig2.iloc[-5]
```

- [ ] **Step 2: Ejecutar y ver fallar**

```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_strategies.py -v
```
Expected: FAIL (`ModuleNotFoundError: strategies`)

- [ ] **Step 3: Implementar strategies.py**

```python
"""6 estrategias puras sobre OHLCV. Senales {-1,0,1} SIN lookahead (decision con shift(1))."""
import pandas as pd

def _sma_cross(df):
    s20, s50 = df["close"].rolling(20).mean(), df["close"].rolling(50).mean()
    raw = np_sign(s20 - s50)
    return raw.shift(1).fillna(0).astype(int)

def _rsi(df, n=14):
    d = df["close"].diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
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

def np_sign(s: pd.Series) -> pd.Series:
    return (s > 0).astype(int) - (s < 0).astype(int)

STRATEGIES = {
    "sma_cross": _sma_cross,
    "rsi_reversion": _rsi_reversion,
    "momentum_30d": _momentum_30d,
    "donchian_breakout": _donchian_breakout,
    "macd_trend": _macd_trend,
    "bollinger_reversion": _bollinger_reversion,
}
```

- [ ] **Step 4: Ejecutar y ver pasar**

```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_strategies.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```powershell
git add AgentBiz/backend/strategies.py AgentBiz/tests/test_strategies.py; git commit -m "feat: 6 estrategias sin lookahead"
```

---

### Task 3: backtester.py — métricas con costes y ranking

**Files:**
- Create: `AgentBiz/backend/backtester.py`
- Test: `AgentBiz/tests/test_backtester.py`

**Interfaces:**
- Consumes: `STRATEGIES` (Task 2), `get_ohlc`/`list_universe` (Task 1, solo en `rank_universe`).
- Produces:
  - `run_backtest(df: pd.DataFrame, signals: pd.Series, cost_rate: float) -> dict` con claves exactas: `total_return`, `annualized`, `sharpe`, `max_drawdown`, `win_rate`, `profit_factor`, `n_trades`
  - `COSTS: dict[str, float]` — `{"crypto": 0.0006, "stocks": 0.0001, "etf": 0.0001, "futures": 0.0001, "forex": 0.000015}`
  - `rank_universe(phase: str = "aggressive", period: str = "1y") -> list[dict]` — filas `{symbol, strategy, sharpe, total_return, max_drawdown, win_rate, n_trades, eligible}` ordenadas por Sharpe desc; `eligible` según fase: aggressive → `sharpe and max_drawdown >= -0.35`; moderate → `sharpe and max_drawdown >= -0.15 and sharpe >= 0.5`

- [ ] **Step 1: Test fallando (Sharpe conocido + plana + lookahead + costes)**

`AgentBiz/tests/test_backtester.py`:
```python
import numpy as np, pandas as pd
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
    sig = pd.Series(1, index=df.index)  # siempre larga
    cheap = bt.run_backtest(df, sig, cost_rate=0.0)
    dear = bt.run_backtest(df, sig, cost_rate=0.01)
    assert cheap["total_return"] > dear["total_return"]
    assert dear["total_return"] < cheap["total_return"] - 0.05

def test_win_rate_and_trades_count():
    closes = np.array([100,101,102,101,100,101,103,104,103,105]*3, dtype=float)
    df = _df(closes)
    sig = pd.Series([0,1,0,-1,0,1,0,-1,0,1]*3, index=df.index)
    m = bt.run_backtest(df, sig, cost_rate=0.0001)
    assert m["n_trades"] >= 2
    assert 0.0 <= m["win_rate"] <= 1.0

def test_no_lookahead_backtest():
    closes = np.linspace(100, 150, 80)
    df = _df(closes)
    sig = pd.Series(1, index=df.index)
    m1 = bt.run_backtest(df, sig, 0.0)
    df2 = df.copy(); df2.iloc[-1, df2.columns.get_loc("close")] *= 2
    m2 = bt.run_backtest(df2, sig, 0.0)
    # el retorno del penúltimo día no depende del último cierre (decisión shifteada)
    assert abs(m1["total_return"] - m2["total_return"]) < 0.02

def test_cost_table_complete():
    assert set(bt.COSTS) == {"crypto","stocks","etf","futures","forex"}
```

- [ ] **Step 2: Ejecutar y ver fallar**

```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_backtester.py -v
```
Expected: FAIL (`ModuleNotFoundError: backtester`)

- [ ] **Step 3: Implementar backtester.py**

```python
"""Backtest long/short con costes y ranking por fase."""
import math
import pandas as pd

COSTS = {"crypto": 0.0006, "stocks": 0.0001, "etf": 0.0001, "futures": 0.0001, "forex": 0.000015}

def run_backtest(df: pd.DataFrame, signals: pd.Series, cost_rate: float) -> dict:
    close = df["close"].astype(float)
    pos = signals.reindex(close.index).fillna(0).shift(0)
    # posicion real = señal decidida con datos hasta t-1 ya viene shifteada en strategies;
    # aquí la posición se toma desde t (ejecución al cierre de t)
    ret = close.pct_change().fillna(0)
    pos_ret = pos.shift(0) * ret
    trades = int((pos.diff().abs() > 0).sum())
    turnover = pos.diff().abs().fillna(0)
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
    active = pos[pos != 0]
    leg_ret = (net[pos != 0])
    wins = int((leg_ret > 0).sum())
    total_active = int(len(leg_ret))
    win_rate = wins / total_active if total_active else 0.0
    gross_win = float(leg_ret[leg_ret > 0].sum()) if total_active else 0.0
    gross_loss = float(-leg_ret[leg_ret < 0].sum()) if total_active else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss > 1e-12 else (math.inf if gross_win > 0 else 0.0)
    if profit_factor is math.inf:
        profit_factor = 99.0
    _ = active
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
    if m["n_trades"] < 2 or m["sharpe"] is None:
        return False
    if phase == "aggressive":
        return m["max_drawdown"] >= -0.35
    return m["max_drawdown"] >= -0.15 and m["sharpe"] >= 0.5

def rank_universe(phase: str = "aggressive", period: str = "1y") -> list[dict]:
    from market_data import list_universe, get_ohlc, resolve
    from strategies import STRATEGIES
    rows = []
    for market, symbols in list_universe().items():
        cost = COSTS[market if market in COSTS else "crypto"]
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
```

- [ ] **Step 4: Ejecutar y ver pasar**

```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_backtester.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Test de integración de red (ranking real, marcar `network`)**

Añadir a `test_backtester.py`:
```python
import pytest

@pytest.mark.network
def test_rank_universe_smoke():
    rows = bt.rank_universe(phase="aggressive")
    assert len(rows) > 30  # 6 estrategias x ~27 simbolos (o menos si alguna fuente falla)
    assert all("sharpe" in r and "eligible" in r for r in rows[:10])
```
Run:
```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_backtester.py -v
```
Expected: PASS (6 tests). Esta prueba tarda ~1-3 min (descarga de 5 fuentes).

- [ ] **Step 6: Commit**

```powershell
git add AgentBiz/backend/backtester.py AgentBiz/tests/test_backtester.py; git commit -m "feat: backtester con costes, Sharpe y ranking por fase"
```

---

### Task 4: paper_portfolio.py — portafolio $2,500 con fases

**Files:**
- Create: `AgentBiz/backend/paper_portfolio.py`
- Test: `AgentBiz/tests/test_paper_portfolio.py`

**Interfaces:**
- Consumes: stdlib (sqlite3, dataclasses, datetime) — sin red.
- Produces (los usarán la API y la oficina 3D):
  - `PHASES = {"aggressive": {...}, "moderate": {...}}` con claves `risk_pct` (min,max), `max_positions`, `max_leverage`, `daily_loss_stop`, `drawdown_alert`
  - `class Portfolio(db_path: str, capital: float = 2500.0, phase: str = "aggressive")`
    - `open_position(symbol, side, qty_usd, leverage, entry, stop_loss, take_profit, strategy) -> dict` — lanza `RiskError(str)` si `can_open` falla
    - `can_open(risk_pct: float) -> tuple[bool, str]`
    - `close_position(position_id, price, reason) -> dict` (realiza PnL)
    - `mark_to_market(prices: dict[str, float]) -> list[dict]` — actualiza equity; cierra posiciones cuyo SL/TP toca el rango (usa high/low si se pasa `ranges`, ver implementación: acepta `bars: dict[str, tuple[low, high]]` opcional)
    - `set_phase(phase: str)` — cambia límites; conserva posiciones; resetea `daily_pnl` NO el equity
    - `get_status() -> dict` — `capital, equity, cash, open_positions, daily_pnl, drawdown, phase, trades, win_rate, daily_stop_hit`
  - `class RiskError(Exception)`

- [ ] **Step 1: Test fallando (límites, SL/TP, cambio de fase)**

`AgentBiz/tests/test_paper_portfolio.py`:
```python
import pytest, pathlib
import paper_portfolio as pp

@pytest.fixture
def pf(tmp_path):
    return pp.Portfolio(str(tmp_path / "t.db"), capital=2500.0, phase="aggressive")

def _open(p, symbol="BTC", entry=100.0):
    return p.open_position(symbol, "long", qty_usd=300.0, leverage=2.0,
                           entry=entry, stop_loss=95.0, take_profit=110.0,
                           strategy="sma_cross")

def test_initial_state(pf):
    s = pf.get_status()
    assert s["capital"] == 2500.0 and s["equity"] == 2500.0
    assert s["phase"] == "aggressive" and s["open_positions"] == 0

def test_max_positions_enforced(pf):
    for i in range(5):
        pf.open_position(f"SYM{i}", "long", 200.0, 1.0, 100.0, 95.0, 110.0, "s")
    ok, why = pf.can_open(0.05)
    assert not ok and "5" in why

def test_phase_change_keeps_positions_and_tightens_limits(pf):
    _open(pf)
    pf.set_phase("moderate")
    s = pf.get_status()
    assert s["phase"] == "moderate" and s["open_positions"] == 1
    # moderate: max 4 posiciones -> con 1 abierta aún puede abrir, pero con 5 sería imposible
    ok, _ = pf.can_open(0.02)
    assert ok
    # riesgo fuera de rango de moderada (2-3%) rechazado
    ok2, why2 = pf.can_open(0.09)
    assert not ok2

def test_sl_hit_closes_with_loss(pf):
    pos = _open(pf, entry=100.0)
    # barra que toca el stop 95
    pf.mark_to_market({}, bars={"BTC": (94.0, 99.0)})
    s = pf.get_status()
    assert s["open_positions"] == 0
    assert s["equity"] < 2500.0
    assert s["trades"] == 1 and s["win_rate"] == 0.0

def test_tp_hit_closes_with_profit(pf):
    _open(pf, entry=100.0)
    pf.mark_to_market({}, bars={"BTC": (101.0, 112.0)})
    s = pf.get_status()
    assert s["open_positions"] == 0 and s["equity"] > 2500.0
    assert s["win_rate"] == 1.0

def test_daily_loss_stop_blocks_new(pf):
    # simular pérdida diaria directamente vía barra hostil varias veces
    pos = _open(pf, entry=100.0)
    pf.mark_to_market({}, bars={"BTC": (90.0, 91.0)})  # SL 95 tocado, pérdida ~15 USD... pequeño
    # forzar daily_pnl a -260 (=-10.4%) para disparar stop
    pf._force_daily_pnl(-260.0)
    ok, why = pf.can_open(0.05)
    assert not ok and "diaria" in why.lower()

def test_risk_error_raised(pf):
    with pytest.raises(pp.RiskError):
        pf.open_position("X", "long", 10_000.0, 50.0, 100.0, 1.0, 200.0, "s")
```

- [ ] **Step 2: Ejecutar y ver fallar**

```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_paper_portfolio.py -v
```
Expected: FAIL (`ModuleNotFoundError: paper_portfolio`)

- [ ] **Step 3: Implementar paper_portfolio.py**

```python
"""Portafolio paper de $2,500 con limites por fase y cierre automatico SL/TP."""
import sqlite3, datetime

PHASES = {
    "aggressive": {"risk_pct": (0.05, 0.10), "max_positions": 5, "max_leverage": 5.0,
                   "daily_loss_stop": -0.10, "drawdown_alert": -0.20},
    "moderate":   {"risk_pct": (0.02, 0.03), "max_positions": 4, "max_leverage": 2.0,
                   "daily_loss_stop": -0.05, "drawdown_alert": -0.10},
}

class RiskError(Exception):
    pass

class Portfolio:
    def __init__(self, db_path, capital=2500.0, phase="aggressive"):
        self.db = db_path
        self.phase = phase if phase in PHASES else "aggressive"
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.db)

    def _init_db(self):
        c = self._conn()
        c.execute("""CREATE TABLE IF NOT EXISTS positions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT,
            qty_usd REAL, leverage REAL, entry REAL, stop_loss REAL, take_profit REAL,
            strategy TEXT, opened_at TEXT, status TEXT DEFAULT 'open')""")
        c.execute("""CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT, position_id INTEGER, symbol TEXT,
            side TEXT, entry REAL, exit REAL, pnl REAL, reason TEXT, strategy TEXT,
            closed_at TEXT, qty_usd REAL, leverage REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS equity_curve(
            ts TEXT, equity REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value REAL)""")
        cur = c.execute("SELECT value FROM meta WHERE key='capital'")
        row = cur.fetchone()
        if row is None:
            c.execute("INSERT INTO meta VALUES('capital', ?)", (2500.0,))
            c.execute("INSERT INTO meta VALUES('daily_pnl', 0.0)")
        c.commit(); c.close()

    def _meta(self, key):
        c = self._conn()
        try:
            row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return float(row[0]) if row else 0.0
        finally:
            c.close()

    def _set_meta(self, key, value):
        c = self._conn()
        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, float(value)))
        c.commit(); c.close()

    def _force_daily_pnl(self, v):
        self._set_meta("daily_pnl", v)

    def get_status(self):
        c = self._conn()
        try:
            open_n = c.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
            trades = c.execute("SELECT pnl FROM trades").fetchall()
        finally:
            c.close()
        pnls = [t[0] for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        capital = self._meta("capital")
        realized = sum(pnls)
        equity = capital + realized
        peak = max(self._meta("peak_equity"), equity) if self._meta("peak_equity") else equity
        self._set_meta("peak_equity", peak)
        drawdown = (equity - peak) / peak if peak else 0.0
        return {
            "capital": round(capital, 2), "equity": round(equity, 2),
            "cash": round(equity, 2), "open_positions": open_n,
            "daily_pnl": round(self._meta("daily_pnl"), 2),
            "drawdown": round(drawdown, 6), "phase": self.phase,
            "trades": len(pnls),
            "win_rate": round(wins / len(pnls), 4) if pnls else 0.0,
            "daily_stop_hit": self._meta("daily_pnl") <= PHASES[self.phase]["daily_loss_stop"] * self._meta("capital"),
        }

    def can_open(self, risk_pct):
        rules = PHASES[self.phase]
        if not (rules["risk_pct"][0] <= risk_pct <= rules["risk_pct"][1]):
            return False, f"riesgo {risk_pct:.0%} fuera de rango de fase {self.phase} ({rules['risk_pct'][0]:.0%}-{rules['risk_pct'][1]:.0%})"
        st = self.get_status()
        if st["open_positions"] >= rules["max_positions"]:
            return False, f"maximo {rules['max_positions']} posiciones abiertas"
        if st["daily_stop_hit"]:
            return False, "stop de pérdida diaria activo"
        return True, "ok"

    def open_position(self, symbol, side, qty_usd, leverage, entry, stop_loss, take_profit, strategy):
        risk_pct = abs(entry - stop_loss) / entry * leverage
        ok, why = self.can_open(risk_pct)
        if not ok:
            raise RiskError(why)
        if leverage > PHASES[self.phase]["max_leverage"]:
            raise RiskError(f"apalancamiento {leverage}x excede max {PHASES[self.phase]['max_leverage']}x")
        if qty_usd * leverage > self.get_status()["equity"]:
            raise RiskError("margen total excede equity")
        c = self._conn()
        try:
            cur = c.execute(
                "INSERT INTO positions(symbol,side,qty_usd,leverage,entry,stop_loss,take_profit,strategy,opened_at,status) "
                "VALUES(?,?,?,?,?,?,?,?,?, 'open')",
                (symbol, side, qty_usd, leverage, entry, stop_loss, take_profit, strategy,
                 datetime.datetime.utcnow().isoformat()))
            c.commit()
            return {"id": cur.lastrowid, "symbol": symbol, "side": side, "entry": entry}
        finally:
            c.close()

    def close_position(self, position_id, price, reason):
        c = self._conn()
        try:
            row = c.execute("SELECT * FROM positions WHERE id=? AND status='open'", (position_id,)).fetchone()
            if not row:
                raise RiskError(f"posicion {position_id} no abierta")
            _, symbol, side, qty_usd, leverage, entry, sl, tp, strat, _, _ = row
            sign = 1 if side == "long" else -1
            pnl = sign * (price - entry) / entry * qty_usd * leverage
            c.execute("UPDATE positions SET status='closed' WHERE id=?", (position_id,))
            c.execute("INSERT INTO trades(position_id,symbol,side,entry,exit,pnl,reason,strategy,closed_at,qty_usd,leverage) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (position_id, symbol, side, entry, price, pnl, reason, strat,
                       datetime.datetime.utcnow().isoformat(), qty_usd, leverage))
            c.commit()
        finally:
            c.close()
        self._set_meta("capital", self._meta("capital"))
        self._set_meta("daily_pnl", self._meta("daily_pnl") + pnl)
        return {"pnl": round(pnl, 2), "reason": reason, "symbol": symbol}

    def mark_to_market(self, prices, bars=None):
        """Cierra posiciones cuyo SL/TP toca la barra (low<=SL<=high o low<=TP<=high)."""
        closed = []
        bars = bars or {}
        c = self._conn()
        try:
            rows = c.execute("SELECT id,symbol,side,entry,stop_loss,take_profit FROM positions WHERE status='open'").fetchall()
        finally:
            c.close()
        for pid, symbol, side, entry, sl, tp in rows:
            low, high = bars.get(symbol, (None, None))
            if low is None:
                px = prices.get(symbol)
                if px is None:
                    continue
                if (side == "long" and (px <= sl or px >= tp)) or (side == "short" and (px >= sl or px <= tp)):
                    exit_px = sl if (px <= sl if side == "long" else px >= sl) else tp
                    closed.append(self.close_position(pid, exit_px, "sl" if exit_px == sl else "tp"))
                continue
            if side == "long":
                if low <= sl:
                    closed.append(self.close_position(pid, sl, "sl"))
                elif high >= tp:
                    closed.append(self.close_position(pid, tp, "tp"))
            else:
                if high >= sl:
                    closed.append(self.close_position(pid, sl, "sl"))
                elif low <= tp:
                    closed.append(self.close_position(pid, tp, "tp"))
        return closed

    def set_phase(self, phase):
        if phase not in PHASES:
            raise RiskError(f"fase desconocida: {phase}")
        self.phase = phase
        self._set_meta("daily_pnl", 0.0)
        return self.get_status()
```

- [ ] **Step 4: Ejecutar y ver pasar**

```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_paper_portfolio.py -v
```
Expected: PASS (8 tests). Si `test_risk_error_raised` falla porque `can_open` deja pasar qty 10000: revisar el cálculo `qty_usd * leverage > equity` en `open_position`.

- [ ] **Step 5: Commit**

```powershell
git add AgentBiz/backend/paper_portfolio.py AgentBiz/tests/test_paper_portfolio.py; git commit -m "feat: portafolio paper con fases, SL/TP y stop diario"
```

---

### Task 5: prueba de humo end-to-end del motor (sin API)

**Files:**
- Create: `AgentBiz/fund_smoke.py` (script manual, no servicio)
- Test: `AgentBiz/tests/test_fund_smoke.py` (solo el orquestador offline)

**Interfaces:**
- Consumes: Tasks 1–4 (`rank_universe`, `Portfolio`, `STRATEGIES`).
- Produces: evidencia de que el motor completo corre: ranking real + simulación de 5 operaciones.

- [ ] **Step 1: Test del orquestador offline**

`AgentBiz/tests/test_fund_smoke.py`:
```python
import pandas as pd, numpy as np
import paper_portfolio as pp

def _mini_backtest_and_trade(tmp_path):
    # estrategia gana -> portfolio abre y cierra en profit
    pf = pp.Portfolio(str(tmp_path / "s.db"))
    pos = pf.open_position("BTC", "long", 500.0, 2.0, 100.0, 95.0, 110.0, "sma_cross")
    pf.mark_to_market({}, bars={"BTC": (101.0, 111.0)})
    st = pf.get_status()
    assert st["trades"] == 1 and st["equity"] > 2500.0

def test_smoke(tmp_path):
    _mini_backtest_and_trade(tmp_path)
```
Run:
```powershell
$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_fund_smoke.py -v
```
Expected: PASS (1 test)

- [ ] **Step 2: Script manual de humo con datos reales**

`AgentBiz/fund_smoke.py`:
```python
"""Humo del motor: ranking real + 3 operaciones paper.  python fund_smoke.py"""
import os
os.environ.setdefault("PYTHONUTF8", "1")
from backtester import rank_universe
from paper_portfolio import Portfolio
from market_data import get_price

def main():
    print("== Ranking (agresivo) ==")
    rows = rank_universe(phase="aggressive")
    for r in rows[:5]:
        print(f"  {r['symbol']:14} {r['strategy']:18} sharpe={r['sharpe']:+.2f} "
              f"ret={r['total_return']:+.1%} dd={r['max_drawdown']:.1%} eligible={r['eligible']}")
    print("\n== Portfolio paper ==")
    pf = Portfolio("fund.db")
    px = get_price("BTC")
    pf.open_position("BTC", "long", 400.0, 2.0, px, px * 0.97, px * 1.06, "sma_cross")
    pf.mark_to_market({"BTC": px})
    print(pf.get_status())

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Ejecutar el humo**

```powershell
$env:PYTHONUTF8="1"; cd AgentBiz; C:\Python313\python.exe fund_smoke.py
```
Expected: top-5 del ranking con métricas + status del portfolio con 1 posición abierta, sin excepciones.

- [ ] **Step 4: Commit**

```powershell
git add AgentBiz/fund_smoke.py AgentBiz/tests/test_fund_smoke.py; git commit -m "test: humo end-to-end del motor del fondo"
```

---

## Self-Review (plan vs spec)

1. **Spec coverage:** Sección 3 (mercados) → Task 1 ✅; Sección 5.1-5.2 (estrategias/backtest) → Tasks 2-3 ✅; Sección 4 (portfolio/fases) → Task 4 ✅; Sección 5.3 (research cycle), 6 (endpoints), 7 (n8n), 8 (3D) → **Plan 2-4** (fuera de alcance declarado de este plan).
2. **Placeholders:** ninguno — todos los pasos llevan código o comandos exactos.
3. **Consistencia de tipos:** `run_backtest(df, signals, cost_rate) -> dict` coincide entre Task 3 test/implementación y Task 5; `Portfolio(...)`/`open_position(...)`/`mark_to_market(prices, bars)` idénticos entre Task 4 y 5; claves de `PHASES` iguales a la Global Constraints.
4. **Review Focus:** (1) lookahead → tests `test_no_lookahead_sma` + `test_no_lookahead_backtest`; (2) yfinance columnas/vacío → `test_get_ohlc_real_sp500_and_btc` + fallback caché en implementación; (3) Sharpe plano → `test_flat_series_sharpe_zero_not_nan`; (4) cambio de fase → `test_phase_change_keeps_positions_and_tightens_limits`; (5) SL/TP → `test_sl_hit_closes_with_loss` + `test_tp_hit_closes_with_profit`.
