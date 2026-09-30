# Segundo Cerebro Capital — Plan 2: API del Fondo + Reconversión de Agentes + Ciclo de Investigación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exponer el motor del fondo (Plan 1) como 8 endpoints `/api/fund/*` en AgentBiz, reconvertir los 7 agentes en sus nuevos cargos del organigrama, e implementar el ciclo de investigación continua (SPECs → backtest → ranking → estrategia estándar).

**Architecture:** Un router FastAPI nuevo (`backend/api/fund.py`) consume `paper_portfolio`, `research` (módulo nuevo del ciclo de SPECs) y `backtester` con llamadas en threadpool (SQLite no es async). El ciclo de investigación vive en `backend/research.py`: valida/expand SPECs contra `strategies.py` (ya parametrizado), backtestea con dedupe por fingerprint en `fund.db`, y guarda la ganadora en `meta`. La reconversión toca solo `memory/database.py` (cargos en la tabla `agents`) y `agents/ai_brain.py` (prompts de los nuevos cargos), sin cambiar rutas ni payloads.

**Tech Stack:** FastAPI 0.141 + TestClient/httpx 0.28 (tests de API sin servidor), SQLite (WAL), NVIDIA NIM (`nvidia/nemotron-3-super-120b-a12b` default), yfinance/ccxt (datos del Plan 1), pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-segundo-cerebro-capital-design.md` (§2 organigrama, §4 portafolio, §5.3 ciclo de investigación, §6 endpoints, §9 fase 4, §10 mitigaciones)

## Global Constraints

- Capital paper: **$2,500**. Fase agresiva: riesgo 5–10%, apalancamiento ≤5x, ≤5 posiciones, stop diario −10%, alerta drawdown −20%. Fase moderada: 2–3%, ≤2x, ≤4 posiciones, −5%, −10%. (spec §4, `PHASES` en `paper_portfolio.py`)
- **SL/TP obligatorios** en toda operación (spec §4) — el endpoint de órdenes rechaza órdenes sin SL/TP con 422.
- Servicios: AgentBiz `127.0.0.1:8000`, n8n `:5678`, Trader API `:5001`. HTTP siempre a `127.0.0.1` (nunca `localhost`, IPv6).
- PowerShell: sin `&&`/`||` en el shell (usa `;`); JSON por curl = `C:\Windows\System32\curl.exe --data-binary @archivo`; todo test Python con `$env:PYTHONUTF8="1"; $env:PYTHONIOENCODING="utf-8"`.
- Modelos NVIDIA: `AGENT_MODELS` default `nvidia/nemotron-3-super-120b-a12b` (deepseek y kimi-k3 caídos); **no** instalar transformers/torch.
- `fund.db` = estado del fondo (creado en `AgentBiz/fund.db` vía ruta absoluta); `agentbiz.db` = agentes/tareas; `market_cache.db` = OHLCV. Nunca commitear `*.db`.
- Webhook unificado v1 (`rd6Io093fYW0yLgA`, `POST /api/unified`) y `POST /api/chat/{id}` + `POST /api/trading/ai` **deben seguir funcionando** tras este plan (regresión manual en Task 8).
- `GET /api/fund/office` NO es de este plan (Plan 4, oficina 3D).

## Review Focus

1. **NVIDIA devuelve las hipótesis con fences ```` ```json ````, prosa o basura alrededor** — una persona razonable espera que el ciclo registre un error claro (ValueError → 422), no un KeyError/crash a medias. Test: `parse_hypotheses` con prosa+fence, sin JSON, y con entradas inválidas (Task 3).
2. **`RiskError` de los límites duros debe salir como 409 con `detail`, no 500** — un 500 rompería a n8n y a la oficina. Test: orden con riesgo fuera de rango → 409 + detalle legible; orden repetida → 409 (Task 5).
3. **SQLite concurrente: n8n (:5678) y AgentBiz (:8000) tocan las mismas DBs** — una persona razonable espera `database is locked` = error transitorio, no corrupción; el review del Plan 1 pidió WAL + busy_timeout + threadpool. Test: `PRAGMA journal_mode == wal` en `Portfolio._conn` y `_cache_conn` (Task 1); endpoints usan `asyncio.to_thread` (Task 4).
4. **Specs repetidas** (mismo `base`+`params` tras reiniciar o re-lanzar research) — el spec §5.3 exige "no repetir"; una persona razonable espera que la 2ª corrida no re-testee. Test: fingerprint dedupe + `run_research` doble → `sin_specs_nuevas` (Tasks 2–3).
5. **Regresión del chat tras cambiar los prompts** (spec §9: chat con agentes debe seguir OK) — payloads `{agent, response, model, timestamp}` intactos con los prompts nuevos. Test: `POST /api/chat/scout` con `chat_with_agent` mockeado → 200 con misma forma (Task 7) + chequeo manual real en Task 8.

---

### Task 1: Seams de lectura en Portfolio + WAL en ambas DBs

El review del Plan 1 exigió WAL + `busy_timeout` y la API (Task 4) necesita leer posiciones/trades y persistir la curva de equity (`equity_curve` estaba creada pero sin escribirse).

**Files:**
- Modify: `AgentBiz/backend/paper_portfolio.py` (`_conn`, nuevos métodos)
- Modify: `AgentBiz/backend/market_data.py:_cache_conn`
- Test: `AgentBiz/tests/test_paper_portfolio.py`, `AgentBiz/tests/test_market_data.py`

**Interfaces:**
- Consumes: `Portfolio` existente (`get_status`, `open_position`, `close_position`, `mark_to_market`).
- Produces: `Portfolio.get_positions(status="open") -> list[dict]`, `Portfolio.get_trades(limit=50) -> list[dict]`, `Portfolio.record_equity() -> float`, `Portfolio.get_equity_curve(limit=1000) -> list[{"ts": str, "equity": float}]` (orden cronológico). Claves de posición: `id, symbol, side, qty_usd, leverage, entry, stop_loss, take_profit, strategy, opened_at, unrealized`. Claves de trade: `id, position_id, symbol, side, entry, exit, pnl, reason, strategy, closed_at`.

- [ ] **Step 1: Escribir los tests fallando**

Añadir a `tests/test_paper_portfolio.py`:

```python
def test_wal_enabled(pf):
    c = pf._conn()
    mode = str(c.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    c.close()
    assert mode == "wal"


def test_get_positions_and_trades(pf):
    _open(pf)
    pos = pf.get_positions()
    assert len(pos) == 1 and pos[0]["symbol"] == "BTC"
    assert pos[0]["unrealized"] == 0.0
    pf.mark_to_market({"BTC": 115.0})  # tp=110 -> cierra
    assert pf.get_positions() == []
    tr = pf.get_trades()
    assert len(tr) == 1 and tr[0]["pnl"] > 0
    assert tr[0]["symbol"] == "BTC" and tr[0]["reason"] == "tp"


def test_record_equity_and_curve(pf):
    assert pf.record_equity() == pytest.approx(2500.0)
    _open(pf)
    pf.mark_to_market({"BTC": 105.0})
    pf.record_equity()
    curve = pf.get_equity_curve()
    assert len(curve) == 2
    assert curve[0]["equity"] == pytest.approx(2500.0)
    assert curve[-1]["equity"] == pytest.approx(2530.0)
```

Añadir a `tests/test_market_data.py`:

```python
def test_cache_wal_enabled():
    conn = md._cache_conn()
    mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    conn.close()
    assert mode == "wal"
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_paper_portfolio.py::test_wal_enabled tests/test_paper_portfolio.py::test_get_positions_and_trades tests/test_paper_portfolio.py::test_record_equity_and_curve tests/test_market_data.py::test_cache_wal_enabled -v`
Expected: FAIL — `AttributeError: 'Portfolio' object has no attribute 'get_positions'` / `record_equity` / `get_equity_curve`; y `test_wal_enabled` falla con `journal_mode != wal` (default `delete`).

- [ ] **Step 3: WAL en `Portfolio._conn` y `_cache_conn`**

En `paper_portfolio.py`, reemplazar `_conn`:

```python
    def _conn(self):
        c = sqlite3.connect(self.db, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        return c
```

En `market_data.py`, reemplazar `_cache_conn`:

```python
def _cache_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("CREATE TABLE IF NOT EXISTS ohlc (symbol TEXT, interval TEXT, ts TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(symbol, interval, ts))")
    conn.execute("CREATE TABLE IF NOT EXISTS price_cache (symbol TEXT PRIMARY KEY, price REAL, ts TEXT)")
    return conn
```

- [ ] **Step 4: Añadir los métodos de lectura y la curva**

En `paper_portfolio.py`, tras `get_status`:

```python
    def get_positions(self, status="open"):
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT id,symbol,side,qty_usd,leverage,entry,stop_loss,take_profit,"
                "strategy,opened_at,unrealized FROM positions WHERE status=? ORDER BY id DESC",
                (status,)).fetchall()
        finally:
            c.close()
        cols = ["id", "symbol", "side", "qty_usd", "leverage", "entry", "stop_loss",
                "take_profit", "strategy", "opened_at", "unrealized"]
        return [dict(zip(cols, r)) for r in rows]

    def get_trades(self, limit=50):
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT id,position_id,symbol,side,entry,exit,pnl,reason,strategy,closed_at "
                "FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        finally:
            c.close()
        cols = ["id", "position_id", "symbol", "side", "entry", "exit", "pnl",
                "reason", "strategy", "closed_at"]
        return [dict(zip(cols, r)) for r in rows]

    def record_equity(self):
        st = self.get_status()
        c = self._conn()
        try:
            c.execute("INSERT INTO equity_curve VALUES(?,?)",
                      (datetime.datetime.now(datetime.timezone.utc).isoformat(), st["equity"]))
            c.commit()
        finally:
            c.close()
        return st["equity"]

    def get_equity_curve(self, limit=1000):
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT ts, equity FROM equity_curve ORDER BY rowid DESC LIMIT ?",
                (limit,)).fetchall()
        finally:
            c.close()
        return [{"ts": r[0], "equity": r[1]} for r in reversed(rows)]
```

- [ ] **Step 5: Correr para verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/ -m "not network"`
Expected: PASS (todo el offline suite, ahora con los 4 tests nuevos)

- [ ] **Step 6: Commit**

```powershell
git add AgentBiz/backend/paper_portfolio.py AgentBiz/backend/market_data.py AgentBiz/tests/test_paper_portfolio.py AgentBiz/tests/test_market_data.py
git commit -m "feat: seams de lectura del portafolio + WAL/busy_timeout en DBs del fondo"
```

---

### Task 2: Estrategias parametrizadas + modelo de SPECs (`research.py`)

El ciclo de investigación (spec §5.3) necesita variantes de parámetros de las 6 estrategias, validación de SPECs, fingerprint para no repetir, y persistencia en `fund.db`.

**Files:**
- Modify: `AgentBiz/backend/strategies.py` (parámetros con defaults idénticos + `validate_params`)
- Create: `AgentBiz/backend/research.py`
- Test: `AgentBiz/tests/test_research.py` (nuevo), suites existentes deben seguir verdes

**Interfaces:**
- Consumes: `STRATEGIES` (Plan 1), `backtester.run_backtest/_eligible/COSTS`, `market_data.get_ohlc/list_universe`.
- Produces: `strategies.STRATEGY_PARAMS: dict[str, dict[str, type]]`, `strategies.validate_params(base, params) -> dict` (ValueError en desconocidos/incumplidos); `research.init_research_db(db_path)`, `research.spec_fingerprint(base, params) -> str` (sha1[:16]), `research.expand_grid(spec) -> list[{"nombre","base","params"}]` (ValueError si `base` desconocido o grid inválido), `research.build_signal_fn(base, params) -> callable(df) -> pd.Series`, `research.save_spec(db_path, base, params, nombre, phase) -> fp`, `research.known_fingerprints(db_path) -> set[str]`, `research.record_run(db_path, fp, symbol, strategy, metrics)`, `research.insert_strategy_results(db_path, rows, phase)`, `research.latest_results(db_path, limit) -> list[dict]`, `research.research_history(db_path, limit) -> list[dict]`, `research.get_standard(db_path) -> dict|None`, `research.set_standard(db_path, payload)`, `research.get_meta(db_path, key, default)`, `research.set_meta(db_path, key, value)`. Tablas nuevas en `fund.db`: `strategy_results`, `research_specs` (UNIQUE por `fingerprint`), `research_runs`.

- [ ] **Step 1: Escribir los tests fallando**

Crear `tests/test_research.py`:

```python
import pandas as pd
import pytest
import research
import strategies as st


def _db(tmp_path):
    p = str(tmp_path / "fund.db")
    research.init_research_db(p)
    return p


def test_validate_params_rejects_unknown_and_bad():
    with pytest.raises(ValueError, match="desconocida"):
        st.validate_params("no_existe", {})
    with pytest.raises(ValueError, match="desconocidos"):
        st.validate_params("sma_cross", {"period": 5})
    with pytest.raises(ValueError, match="fast"):
        st.validate_params("sma_cross", {"fast": 50, "slow": 20})
    with pytest.raises(ValueError):
        st.validate_params("rsi_reversion", {"oversold": 70, "overbought": 30})
    assert st.validate_params("sma_cross", {"fast": "10"}) == {"fast": 10}


def test_fingerprint_stable_and_distinct():
    a = research.spec_fingerprint("sma_cross", {"fast": 5})
    b = research.spec_fingerprint("sma_cross", {"fast": 5})
    c = research.spec_fingerprint("sma_cross", {"fast": 10})
    assert a == b and a != c and len(a) == 16


def test_expand_grid():
    specs = research.expand_grid(
        {"nombre": "g", "base": "sma_cross", "grid": {"fast": [5, 10], "slow": [30, 60]}})
    assert len(specs) == 4
    combos = {(s["params"]["fast"], s["params"]["slow"]) for s in specs}
    assert combos == {(5, 30), (5, 60), (10, 30), (10, 60)}
    assert all(s["nombre"].startswith("g") for s in specs)


def test_expand_grid_rejects_bad_base():
    with pytest.raises(ValueError):
        research.expand_grid({"base": "no_existe", "params": {}})


def test_build_signal_fn_uses_params():
    import numpy as np
    up = np.linspace(100, 150, 30)
    down = np.linspace(150, 100, 30)
    close = pd.Series(np.concatenate([up, down, up, down]))
    df = pd.DataFrame({"open": close.shift(1).fillna(100), "high": close + 1,
                       "low": close - 1, "close": close, "volume": 1000.0},
                      index=pd.date_range("2025-01-01", periods=120, freq="D", tz="UTC"))
    fast = research.build_signal_fn("sma_cross", {"fast": 5, "slow": 20})
    default = research.build_signal_fn("sma_cross", {})
    assert not fast(df).equals(default(df))
    with pytest.raises(ValueError):
        research.build_signal_fn("sma_cross", {"foo": 1})


def test_save_spec_dedupe_and_history(db):
    fp = research.save_spec(db, "sma_cross", {"fast": 5}, "v1", "aggressive")
    fp2 = research.save_spec(db, "sma_cross", {"fast": 5}, "v1 otra vez", "aggressive")
    assert fp == fp2
    assert research.known_fingerprints(db) == {fp}
    m = {"total_return": 0.1, "sharpe": 2.0, "max_drawdown": -0.05,
         "win_rate": 0.6, "n_trades": 4, "eligible": True}
    research.record_run(db, fp, "SPY", "v1", m)
    research.record_run(db, fp, "QQQ", "v1", {**m, "sharpe": 1.0})
    hist = research.research_history(db, 10)
    assert len(hist) == 1
    assert hist[0]["fingerprint"] == fp and hist[0]["runs"] == 2
    assert hist[0]["avg_sharpe"] == pytest.approx(1.5)
    research.set_standard(db, {"fingerprint": fp, "nombre": "v1", "base": "sma_cross"})
    assert research.get_standard(db)["nombre"] == "v1"
    assert research.get_meta(db, "no_existe", "def") == "def"


def test_insert_and_latest_results(db):
    rows = [{"symbol": "SPY", "market": "etf", "strategy": "v1",
             "total_return": 0.2, "sharpe": 1.5, "max_drawdown": -0.1,
             "win_rate": 0.5, "n_trades": 3, "eligible": True,
             "profit_factor": 1.2, "annualized": 0.2}]
    research.insert_strategy_results(db, rows, "aggressive")
    latest = research.latest_results(db, 10)
    assert latest[0]["symbol"] == "SPY" and latest[0]["sharpe"] == 1.5
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_research.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'research'` (y `validate_params` no existe en strategies).

- [ ] **Step 3: Parametrizar `strategies.py`**

Reemplazar las 6 funciones en `strategies.py` (defaults idénticos al Plan 1 — `STRATEGIES` no cambia) y añadir validación al final del archivo:

```python
def _sma_cross(df, fast=20, slow=50):
    s_fast, s_slow = df["close"].rolling(fast).mean(), df["close"].rolling(slow).mean()
    raw = np_sign(s_fast - s_slow)
    return raw.shift(1).fillna(0).astype(int)


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
```

Añadir tras `STRATEGIES`:

```python
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
```

- [ ] **Step 4: Crear `backend/research.py` (parte 1: tablas, SPECs, señales)**

```python
"""Ciclo de investigación: SPECs -> backtest -> ranking -> estrategia estandar (fund.db)."""
import hashlib
import json
import sqlite3
import datetime
import itertools

from strategies import STRATEGIES, validate_params


def _conn(db_path):
    c = sqlite3.connect(db_path, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    return c


def init_research_db(db_path):
    c = _conn(db_path)
    c.execute("""CREATE TABLE IF NOT EXISTS strategy_results(
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, market TEXT, strategy TEXT,
        spec_id TEXT, total_return REAL, sharpe REAL, max_drawdown REAL, win_rate REAL,
        n_trades INTEGER, eligible INTEGER, phase TEXT, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS research_specs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT UNIQUE, nombre TEXT,
        base TEXT, params_json TEXT, phase TEXT, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS research_runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT, symbol TEXT, strategy TEXT,
        sharpe REAL, total_return REAL, max_drawdown REAL, win_rate REAL, n_trades INTEGER,
        eligible INTEGER, created_at TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value REAL)")
    c.commit()
    c.close()


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def spec_fingerprint(base, params):
    canon = json.dumps({"base": base, "params": params}, sort_keys=True)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]


def expand_grid(spec):
    if not isinstance(spec, dict) or "base" not in spec:
        raise ValueError("SPEC sin base")
    base = spec["base"]
    validate_params(base, {})  # falla ya si la base es desconocida
    nombre = spec.get("nombre", base)
    params0 = dict(spec.get("params") or {})
    if "grid" not in spec:
        validate_params(base, params0)
        return [{"nombre": nombre, "base": base, "params": params0}]
    grid = spec["grid"]
    if not isinstance(grid, dict) or not grid:
        raise ValueError("grid vacio")
    keys = list(grid.keys())
    out = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        params = dict(params0)
        params.update(dict(zip(keys, combo)))
        variant = dict(zip(keys, combo))
        validate_params(base, params)
        out.append({"nombre": f"{nombre} {variant}", "base": base, "params": params})
    return out


def build_signal_fn(base, params):
    validated = validate_params(base, params)
    fn = STRATEGIES[base]

    def signal(df):
        return fn(df, **validated)

    return signal
```

- [ ] **Step 5: `research.py` (parte 2: persistencia)**

Añadir al mismo archivo:

```python
def save_spec(db_path, base, params, nombre, phase):
    fp = spec_fingerprint(base, params)
    c = _conn(db_path)
    try:
        c.execute("INSERT OR IGNORE INTO research_specs(fingerprint,nombre,base,params_json,phase,created_at) "
                  "VALUES(?,?,?,?,?,?)",
                  (fp, nombre, base, json.dumps(params, sort_keys=True), phase, _now()))
        c.commit()
    finally:
        c.close()
    return fp


def known_fingerprints(db_path):
    c = _conn(db_path)
    try:
        rows = c.execute("SELECT fingerprint FROM research_specs").fetchall()
    finally:
        c.close()
    return {r[0] for r in rows}


def record_run(db_path, fp, symbol, strategy, metrics):
    c = _conn(db_path)
    try:
        c.execute("INSERT INTO research_runs(fingerprint,symbol,strategy,sharpe,total_return,"
                  "max_drawdown,win_rate,n_trades,eligible,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (fp, symbol, strategy, metrics["sharpe"], metrics["total_return"],
                   metrics["max_drawdown"], metrics["win_rate"], metrics["n_trades"],
                   int(bool(metrics["eligible"])), _now()))
        c.commit()
    finally:
        c.close()


def insert_strategy_results(db_path, rows, phase):
    c = _conn(db_path)
    try:
        for r in rows:
            c.execute("INSERT INTO strategy_results(symbol,market,strategy,spec_id,total_return,"
                      "sharpe,max_drawdown,win_rate,n_trades,eligible,phase,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (r["symbol"], r["market"], r["strategy"], None, r["total_return"],
                       r["sharpe"], r["max_drawdown"], r["win_rate"], r["n_trades"],
                       int(bool(r["eligible"])), phase, _now()))
        c.commit()
    finally:
        c.close()


def latest_results(db_path, limit=50):
    c = _conn(db_path)
    try:
        rows = c.execute(
            "SELECT symbol, market, strategy, total_return, sharpe, max_drawdown, win_rate, "
            "n_trades, eligible, phase, created_at FROM strategy_results "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        c.close()
    cols = ["symbol", "market", "strategy", "total_return", "sharpe", "max_drawdown",
            "win_rate", "n_trades", "eligible", "phase", "created_at"]
    out = [dict(zip(cols, r)) for r in rows]
    for o in out:
        o["eligible"] = bool(o["eligible"])
    return out


def research_history(db_path, limit=20):
    c = _conn(db_path)
    try:
        rows = c.execute(
            "SELECT r.fingerprint, s.nombre, s.base, COUNT(*) AS runs, AVG(r.sharpe) AS avg_sharpe, "
            "AVG(r.total_return) AS avg_return, MAX(r.created_at) AS last_run "
            "FROM research_runs r LEFT JOIN research_specs s ON s.fingerprint = r.fingerprint "
            "GROUP BY r.fingerprint ORDER BY avg_sharpe DESC LIMIT ?", (limit,)).fetchall()
    finally:
        c.close()
    cols = ["fingerprint", "nombre", "base", "runs", "avg_sharpe", "avg_return", "last_run"]
    return [dict(zip(cols, r)) for r in rows]


def set_meta(db_path, key, value):
    c = _conn(db_path)
    try:
        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))
        c.commit()
    finally:
        c.close()


def get_meta(db_path, key, default=None):
    c = _conn(db_path)
    try:
        row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    finally:
        c.close()
    if row is None or row[0] is None:
        return default
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return row[0]


def set_standard(db_path, payload):
    set_meta(db_path, "standard_json", json.dumps(payload, ensure_ascii=False))


def get_standard(db_path):
    v = get_meta(db_path, "standard_json")
    if not isinstance(v, str):
        return None
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 6: Correr para verificar que pasan (y las suites viejas)**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/ -m "not network"`
Expected: PASS — los tests nuevos + `test_strategies.py` completo (los defaults no cambiaron) + todo lo demás.

- [ ] **Step 7: Commit**

```powershell
git add AgentBiz/backend/strategies.py AgentBiz/backend/research.py AgentBiz/tests/test_research.py
git commit -m "feat: estrategias parametrizadas + modelo de SPECs con fingerprint y ranking"
```

---

### Task 3: Ciclo de investigación con NVIDIA (`generate_hypotheses` + `run_research`)

Spec §5.3: INVESTIGAR → ESPECIFICAR → BACKTESTEAR → RANKEAR → ELEGIR. Sin repetir historial. Todo el paso de red/AI queda tras funciones parseables/mokeables para tests offline.

**Files:**
- Modify: `AgentBiz/backend/research.py` (parte 3)
- Test: `AgentBiz/tests/test_research.py`

**Interfaces:**
- Consumes: Task 2 (`expand_grid`, `build_signal_fn`, `save_spec`, `known_fingerprints`, `record_run`, `set_standard`), `backtester.run_backtest/_eligible/COSTS`, `market_data.get_ohlc/list_universe`, `agents.ai_brain.ask_nvidia_sync/AGENT_SYSTEM_PROMPTS`.
- Produces: `research.parse_hypotheses(raw: str) -> list[dict]` (ValueError si no hay JSON válido), `research.generate_hypotheses(phase, n=3) -> list[dict]`, `research.run_research(db_path="fund.db", phase=None, period="1y") -> {"status", "tested", "runs", "standard"}` con `status` ∈ `{"ok", "sin_specs_nuevas", "sin_datos"}`. `phase=None` lee la fase vigente de `meta`.

- [ ] **Step 1: Escribir los tests fallando**

Añadir a `tests/test_research.py`:

```python
import numpy as np


def test_parse_hypotheses_fenced_and_prosa():
    raw = ('Aquí tienes las hipótesis:\n```json\n'
           '[{"nombre": "a", "base": "sma_cross", "params": {"fast": 5}}]\n```\nListo.')
    specs = research.parse_hypotheses(raw)
    assert specs[0]["base"] == "sma_cross"


def test_parse_hypotheses_filters_junk_keeps_valid():
    raw = '[{"foo": 1}, "texto", {"nombre": "ok", "base": "rsi_reversion"}]'
    specs = research.parse_hypotheses(raw)
    assert len(specs) == 1 and specs[0]["base"] == "rsi_reversion"


def test_parse_hypotheses_without_json_raises():
    with pytest.raises(ValueError, match="JSON"):
        research.parse_hypotheses("no puedo generar estrategias hoy")
    with pytest.raises(ValueError):
        research.parse_hypotheses('{"base": "sma_cross"}')


def test_run_research_cycle_and_dedupe(tmp_path, monkeypatch):
    db = str(tmp_path / "fund.db")
    import pandas as pd
    up = np.linspace(100, 150, 30)
    down = np.linspace(150, 100, 30)
    close = pd.Series(np.concatenate([up, down, up, down]))
    fake = pd.DataFrame({"open": close.shift(1).fillna(100), "high": close + 1,
                         "low": close - 1, "close": close, "volume": 1000.0},
                        index=pd.date_range("2025-01-01", periods=120, freq="D", tz="UTC"))
    monkeypatch.setattr(research, "generate_hypotheses",
                        lambda phase, n=3: [{"nombre": "g1", "base": "sma_cross",
                                             "grid": {"fast": [5], "slow": [20]}}])
    monkeypatch.setattr(research, "get_ohlc",
                        lambda sym, period="1y", interval="1d": fake)
    out = research.run_research(db_path=db, phase="aggressive")
    assert out["status"] == "ok" and out["tested"] == 1
    assert out["runs"] > 0
    std = research.get_standard(db_path=db)
    assert std is not None and std["base"] == "sma_cross"
    assert std["fingerprint"] in research.known_fingerprints(db)
    # segunda corrida: no repite
    out2 = research.run_research(db_path=db, phase="aggressive")
    assert out2["status"] == "sin_specs_nuevas" and out2["tested"] == 0


def test_run_research_uses_vigente_phase_when_none(tmp_path, monkeypatch):
    db = str(tmp_path / "p.db")
    research.init_research_db(db)
    research.set_meta(db, "phase", "moderate")
    monkeypatch.setattr(research, "generate_hypotheses",
                        lambda phase, n=3: (_ for _ in ()).throw(
                            AssertionError(f"phase={phase}")))
    with pytest.raises(AssertionError, match="phase=moderate"):
        research.run_research(db_path=db, phase=None)
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_research.py -v`
Expected: FAIL — `AttributeError: module 'research' has no attribute 'parse_hypotheses'` (etc.).

- [ ] **Step 3: Añadir `parse_hypotheses` + `generate_hypotheses`**

Añadir a `research.py`:

```python
def parse_hypotheses(raw):
    text = (raw or "").strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no se encontro JSON en la respuesta del modelo")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as e:
        raise ValueError(f"JSON de hipotesis invalido: {e}")
    if not isinstance(data, list):
        raise ValueError("se esperaba una lista de SPECs")
    out = [x for x in data if isinstance(x, dict) and "base" in x]
    if not out:
        raise ValueError("ninguna SPEC valida en la respuesta")
    return out


def generate_hypotheses(phase="aggressive", n=3):
    from agents.ai_brain import ask_nvidia_sync, AGENT_SYSTEM_PROMPTS
    prompt = (
        f"Genera {n} hipotesis de estrategias para el fondo en fase {phase}. "
        "Responde SOLO con un array JSON, sin texto fuera del array. Cada elemento: "
        '{"nombre": "...", "base": "<una de las bases listadas>", "params": {<parametros>}, '
        '"grid": {<parametros opcionales con listas de valores para variar>}}. '
        "Bases validas: sma_cross, rsi_reversion, momentum_30d, donchian_breakout, "
        "macd_trend, bollinger_reversion. "
        "Parametros validos: sma_cross: fast, slow; rsi_reversion: period, oversold, overbought; "
        "momentum_30d: window, threshold; donchian_breakout: channel, atr_period; "
        "macd_trend: fast, slow, signal_period; bollinger_reversion: window, devs."
    )
    raw = ask_nvidia_sync(prompt, system=AGENT_SYSTEM_PROMPTS["analytics"],
                          temperature=0.6, max_tokens=1500, agent_id="analytics")
    return parse_hypotheses(raw)
```

- [ ] **Step 4: Añadir `run_research`**

Añadir a `research.py` (importar COSTS/_eligible arriba: `from backtester import run_backtest, _eligible, COSTS`; `from market_data import get_ohlc, list_universe`):

```python
def run_research(db_path="fund.db", phase=None, period="1y"):
    import statistics
    init_research_db(db_path)
    if phase is None:
        phase = get_meta(db_path, "phase", "aggressive")
        if phase not in ("aggressive", "moderate"):
            phase = "aggressive"
    hypotheses = generate_hypotheses(phase)
    known = known_fingerprints(db_path)
    new_specs = []
    for h in hypotheses:
        for concrete in expand_grid(h):
            fp = spec_fingerprint(concrete["base"], concrete["params"])
            if fp in known:
                continue
            save_spec(db_path, concrete["base"], concrete["params"], concrete["nombre"], phase)
            new_specs.append((fp, concrete))
            known.add(fp)
    if not new_specs:
        return {"status": "sin_specs_nuevas", "tested": 0, "runs": 0,
                "standard": get_standard(db_path)}
    universe = list_universe()
    results = []
    for fp, spec in new_specs:
        try:
            sig_fn = build_signal_fn(spec["base"], spec["params"])
        except ValueError:
            continue
        for market, symbols in universe.items():
            cost = COSTS.get(market, COSTS["crypto"])
            for sym in symbols:
                try:
                    df = get_ohlc(sym, period=period, interval="1d")
                    m = run_backtest(df, sig_fn(df), cost)
                except Exception:
                    continue
                m["eligible"] = _eligible(m, phase)
                record_run(db_path, fp, sym, spec["nombre"], m)
                results.append({"fp": fp, "nombre": spec["nombre"], **m})
    by_spec = {}
    for r in results:
        if r["n_trades"] >= 2:
            by_spec.setdefault(r["fp"], []).append(r)
    if not by_spec:
        return {"status": "sin_datos", "tested": len(new_specs), "runs": len(results),
                "standard": get_standard(db_path)}
    scored = []
    for fp, rows in by_spec.items():
        mean_sharpe = statistics.mean(r["sharpe"] for r in rows)
        mean_ret = statistics.mean(r["total_return"] for r in rows)
        scored.append((mean_sharpe, mean_ret, fp, rows[0]["nombre"]))
    scored.sort(reverse=True)
    best_sharpe, best_ret, best_fp, best_nombre = scored[0]
    payload = {"fingerprint": best_fp, "nombre": best_nombre,
               "score_sharpe": round(best_sharpe, 4),
               "score_return": round(best_ret, 6), "phase": phase,
               "tested_at": _now(), "runs": len(by_spec[best_fp])}
    set_standard(db_path, payload)
    return {"status": "ok", "tested": len(new_specs), "runs": len(results),
            "standard": payload}
```

- [ ] **Step 5: Correr para verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/ -m "not network"`
Expected: PASS (investigación completa offline; la corrida de prueba backtestea 1 spec × 31 símbolos sobre datos sintéticos)

- [ ] **Step 6: Commit**

```powershell
git add AgentBiz/backend/research.py AgentBiz/tests/test_research.py
git commit -m "feat: ciclo de investigación SPEC -> backtest -> ranking -> estrategia estándar"
```

---

### Task 4: Router `/api/fund` — status, portfolio, phase, performance

**Files:**
- Create: `AgentBiz/backend/api/fund.py`
- Modify: `AgentBiz/backend/api/main.py` (include_router)
- Modify: `AgentBiz/tests/conftest.py` (fixture `client`)
- Test: `AgentBiz/tests/test_fund_api.py` (nuevo)

**Interfaces:**
- Consumes: Task 1 (`get_positions/get_trades/record_equity/get_equity_curve`), Task 2 (`research.get_standard/latest_results/get_meta`), `PHASES/RiskError`.
- Produces: `api.fund.FUND_DB: str` (ruta absoluta a `AgentBiz/fund.db`), `api.fund._pf() -> Portfolio`, endpoints `GET /api/fund/status`, `GET /api/fund/portfolio`, `POST /api/fund/phase {phase}`, `GET /api/fund/performance`. Fixture `client` (TestClient con DBs de agentes y fondo en tmp).

- [ ] **Step 1: Añadir fixture `client` a `tests/conftest.py`**

```python
import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    import memory.database as mdb
    monkeypatch.setattr(mdb, "DB_PATH", str(tmp_path / "agents.db"))
    import api.fund as fmod
    monkeypatch.setattr(fmod, "FUND_DB", str(tmp_path / "fund.db"))
    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as c:
        yield c
```

- [ ] **Step 2: Escribir los tests fallando**

Crear `tests/test_fund_api.py`:

```python
def test_status_shape(client):
    r = client.get("/api/fund/status")
    assert r.status_code == 200
    d = r.json()
    assert d["portfolio"]["capital"] == 2500.0
    assert d["portfolio"]["phase"] == "aggressive"
    assert d["standard"] is None
    assert d["phase_rules"]["max_positions"] == 5
    assert isinstance(d["signals"], list)


def test_portfolio_empty(client):
    r = client.get("/api/fund/portfolio")
    assert r.status_code == 200
    d = r.json()
    assert d["positions"] == [] and d["trades"] == []
    assert d["status"]["equity"] == 2500.0


def test_phase_change_and_invalid(client):
    r = client.post("/api/fund/phase", json={"phase": "moderate"})
    assert r.status_code == 200
    assert r.json()["phase"] == "moderate"
    assert r.json()["open_positions"] == 0  # portafolio no se resetea
    bad = client.post("/api/fund/phase", json={"phase": "yolo"})
    assert bad.status_code == 422


def test_performance_empty_curve_computes_point(client):
    r = client.get("/api/fund/performance")
    assert r.status_code == 200
    d = r.json()
    assert len(d["curve"]) == 1
    assert d["equity"] == 2500.0 and d["drawdown"] == 0.0
    assert d["target"] == 5000.0  # meta por defecto 2x capital
```

- [ ] **Step 3: Correr para verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_fund_api.py -v`
Expected: FAIL — 404 en cada endpoint (router no registrado).

- [ ] **Step 4: Crear `backend/api/fund.py` (status/portfolio/phase/performance)**

```python
import os
import asyncio
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from paper_portfolio import Portfolio, PHASES, RiskError
import research

router = APIRouter(prefix="/api/fund", tags=["fund"])
FUND_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "fund.db"))


def _pf():
    return Portfolio(FUND_DB)


class PhaseRequest(BaseModel):
    phase: Literal["aggressive", "moderate"]


@router.get("/status")
async def fund_status():
    pf = _pf()
    st = await asyncio.to_thread(pf.get_status)
    standard = await asyncio.to_thread(research.get_standard, FUND_DB)
    signals = await asyncio.to_thread(research.latest_results, FUND_DB, 5)
    return {"portfolio": st, "standard": standard, "signals": signals,
            "phase_rules": PHASES[st["phase"]]}


@router.get("/portfolio")
async def fund_portfolio():
    def work():
        p = _pf()
        return (p.get_status(), p.get_positions(), p.get_trades(50))
    status, positions, trades = await asyncio.to_thread(work)
    return {"status": status, "positions": positions, "trades": trades}


@router.post("/phase")
async def fund_phase(req: PhaseRequest):
    pf = _pf()
    try:
        st = await asyncio.to_thread(lambda: pf.set_phase(req.phase))
    except RiskError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await asyncio.to_thread(pf.record_equity)
    return st


@router.get("/performance")
async def fund_performance():
    def work():
        p = _pf()
        curve = p.get_equity_curve()
        st = p.get_status()
        if not curve:
            curve = [{"ts": "now", "equity": st["equity"]}]
        peak = max(pt["equity"] for pt in curve)
        dd = (st["equity"] - peak) / peak if peak else 0.0
        target = research.get_meta(FUND_DB, "target", st["capital"] * 2)
        return {"curve": curve, "equity": st["equity"], "peak": round(peak, 2),
                "drawdown": round(dd, 6), "target": target,
                "daily_pnl": st["daily_pnl"], "phase": st["phase"]}
    return await asyncio.to_thread(work)
```

- [ ] **Step 5: Registrar el router en `main.py`**

Añadir tras los imports (línea ~18):

```python
from api.fund import router as fund_router
```

Añadir antes del `@app.get("/api/health")` final:

```python
app.include_router(fund_router)
```

- [ ] **Step 6: Correr para verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/ -m "not network"`
Expected: PASS (4 nuevos + todo lo anterior)

- [ ] **Step 7: Commit**

```powershell
git add AgentBiz/backend/api/fund.py AgentBiz/backend/api/main.py AgentBiz/tests/conftest.py AgentBiz/tests/test_fund_api.py
git commit -m "feat: endpoints base /api/fund (status, portfolio, phase, performance)"
```

---

### Task 5: `POST /api/fund/orders` con risk gate (límites duros + revisión de Riesgo)

**Files:**
- Modify: `AgentBiz/backend/agents/ai_brain.py` (`risk_review`)
- Modify: `AgentBiz/backend/api/fund.py`
- Test: `AgentBiz/tests/test_fund_api.py`

**Interfaces:**
- Consumes: `Portfolio.open_position/close_position/record_equity` (RiskError), Task 4 router.
- Produces: `ai_brain.risk_review(order: dict) -> {"decision": "aprueba"|"rechaza", "reason": str}` (async); `POST /api/fund/orders` con body `OrderRequest` (`action: "open"|"close"`, `symbol, side, qty_usd, leverage, entry, stop_loss, take_profit, strategy, position_id, price, reason, review`). Códigos: 422 (SL/TP faltantes o campos inválidos), 403 (revisión de Riesgo rechaza), 409 (RiskError de límites duros), 200 (`{"position"|"trade", "risk_review"}`). Órdenes se registran en `tasks` con `agent_id='trading'`.

- [ ] **Step 1: Escribir los tests fallando**

Añadir a `tests/test_fund_api.py`:

```python
def _open_order(**over):
    body = {"action": "open", "symbol": "BTC", "side": "long", "qty_usd": 300.0,
            "leverage": 2.0, "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0,
            "strategy": "sma_cross"}
    body.update(over)
    return body


def test_order_open_ok_and_recorded(client):
    r = client.post("/api/fund/orders", json=_open_order())
    assert r.status_code == 200
    assert r.json()["position"]["symbol"] == "BTC"
    assert r.json()["risk_review"] is None
    pf = client.get("/api/fund/portfolio").json()
    assert pf["status"]["open_positions"] == 1
    perf = client.get("/api/fund/performance").json()
    assert len(perf["curve"]) >= 1


def test_order_open_requires_sl_tp(client):
    body = _open_order()
    del body["stop_loss"]
    r = client.post("/api/fund/orders", json=body)
    assert r.status_code == 422
    assert "SL/TP" in r.json()["detail"]


def test_order_risk_error_is_409(client):
    r = client.post("/api/fund/orders", json=_open_order(stop_loss=50.0))
    assert r.status_code == 409
    assert "riesgo" in r.json()["detail"]


def test_order_review_rejects_403(client, monkeypatch):
    import api.fund as fmod

    async def fake_review(order):
        return {"decision": "rechaza", "reason": "senal debil"}

    monkeypatch.setattr(fmod, "risk_review", fake_review)
    r = client.post("/api/fund/orders", json=_open_order(review=True))
    assert r.status_code == 403
    assert "senal debil" in r.json()["detail"]


def test_order_close_and_double_close_409(client):
    pid = client.post("/api/fund/orders", json=_open_order()).json()["position"]["id"]
    r = client.post("/api/fund/orders", json={"action": "close", "position_id": pid,
                                               "price": 105.0, "reason": "tp_manual"})
    assert r.status_code == 200
    assert r.json()["trade"]["pnl"] > 0
    again = client.post("/api/fund/orders", json={"action": "close", "position_id": pid,
                                                   "price": 105.0})
    assert again.status_code == 409
```

- [ ] **Step 2: Correr para verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_fund_api.py -v`
Expected: FAIL — 404 (endpoint no existe aún).

- [ ] **Step 3: `risk_review` en `ai_brain.py`**

Añadir al final de `agents/ai_brain.py`:

```python
async def risk_review(order: dict) -> dict:
    prompt = (
        "Evalua esta operacion paper del fondo Segundo Cerebro Capital segun los limites de fase "
        f"y aprueba o rechaza.\nOperacion: {json.dumps(order, ensure_ascii=False)}\n"
        "Responde en UNA linea exactamente con el formato: "
        "APRUEBA: <motivo corto>  o  RECHAZA: <motivo corto>."
    )
    raw = await ask_nvidia(prompt, system=AGENT_SYSTEM_PROMPTS["content"],
                           temperature=0.2, max_tokens=120, agent_id="content")
    text = (raw or "").strip()
    if "RECHAZA" in text.upper():
        return {"decision": "rechaza", "reason": text[:200]}
    return {"decision": "aprueba", "reason": text[:200]}
```

- [ ] **Step 4: Endpoint de órdenes en `api/fund.py`**

Añadir import (junto a los otros imports arriba):

```python
from agents.ai_brain import risk_review
```

Añadir al final de `api/fund.py`:

```python
class OrderRequest(BaseModel):
    action: Literal["open", "close"]
    symbol: str = ""
    side: Literal["long", "short"] = "long"
    qty_usd: float = 0.0
    leverage: float = 1.0
    entry: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy: str = "manual"
    position_id: Optional[int] = None
    price: Optional[float] = None
    reason: str = "manual"
    review: bool = False


def _log_order(title, detail):
    from memory.database import get_db
    db = get_db()
    db.execute("INSERT INTO tasks (agent_id, title, description, status, result) "
               "VALUES ('trading', ?, ?, 'completed', ?)", (title, detail, detail))
    db.commit()
    db.close()


@router.post("/orders")
async def fund_orders(req: OrderRequest):
    pf = _pf()
    if req.action == "open":
        if req.stop_loss is None or req.take_profit is None:
            raise HTTPException(status_code=422, detail="SL/TP obligatorios")
        if req.qty_usd <= 0 or req.entry <= 0:
            raise HTTPException(status_code=422, detail="qty_usd y entry deben ser > 0")
        review_result = None
        if req.review:
            review_result = await risk_review({
                "symbol": req.symbol, "side": req.side, "qty_usd": req.qty_usd,
                "leverage": req.leverage, "entry": req.entry,
                "stop_loss": req.stop_loss, "take_profit": req.take_profit,
                "strategy": req.strategy})
            if review_result["decision"] == "rechaza":
                raise HTTPException(status_code=403,
                                    detail=f"Director de Riesgo rechaza: {review_result['reason']}")
        try:
            pos = await asyncio.to_thread(
                pf.open_position, req.symbol, req.side, req.qty_usd, req.leverage,
                req.entry, req.stop_loss, req.take_profit, req.strategy)
        except RiskError as e:
            raise HTTPException(status_code=409, detail=str(e))
        await asyncio.to_thread(pf.record_equity)
        _log_order(f"Abrir {req.side} {req.symbol}",
                   f"{req.side} {req.symbol} qty={req.qty_usd} lev={req.leverage} "
                   f"sl={req.stop_loss} tp={req.take_profit} [{req.strategy}]")
        return {"position": pos, "risk_review": review_result}
    if req.position_id is None or req.price is None:
        raise HTTPException(status_code=422, detail="position_id y price requeridos para cerrar")
    try:
        trade = await asyncio.to_thread(pf.close_position, req.position_id, req.price, req.reason)
    except RiskError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await asyncio.to_thread(pf.record_equity)
    _log_order(f"Cerrar {req.symbol or trade['symbol']}",
               f"posicion {req.position_id} a {req.price} ({req.reason})")
    return {"trade": trade, "risk_review": None}
```

- [ ] **Step 5: Correr para verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/ -m "not network"`
Expected: PASS (6 tests de órdenes + todo lo anterior)

- [ ] **Step 6: Commit**

```powershell
git add AgentBiz/backend/agents/ai_brain.py AgentBiz/backend/api/fund.py AgentBiz/tests/test_fund_api.py
git commit -m "feat: POST /api/fund/orders con SL/TP obligatorios, límites duros y revisión de Riesgo"
```

---

### Task 6: Endpoints backtest, strategies y research

**Files:**
- Modify: `AgentBiz/backend/api/fund.py`
- Test: `AgentBiz/tests/test_fund_api.py`

**Interfaces:**
- Consumes: `backtester.rank_universe(phase, period)` (red real), `research.insert_strategy_results/latest_results/research_history/run_research/get_standard`.
- Produces: `POST /api/fund/backtest {phase?, period?} -> {"count", "phase", "top": [20 rows]}`, `GET /api/fund/strategies -> {"standard", "ranking", "history"}`, `POST /api/fund/research {phase?, period?} -> run_research(...)` (422 si el ciclo lanza ValueError).

- [ ] **Step 1: Escribir los tests fallando**

Añadir a `tests/test_fund_api.py`:

```python
def test_backtest_endpoint_stores_and_strategies_serves(client, monkeypatch):
    import api.fund as fmod
    canned = [{"symbol": "SPY", "market": "etf", "strategy": "v1",
               "total_return": 0.2, "annualized": 0.2, "sharpe": 1.5,
               "max_drawdown": -0.1, "win_rate": 0.5, "profit_factor": 1.2,
               "n_trades": 3, "eligible": True},
              {"symbol": "BTC", "market": "crypto", "strategy": "v1",
               "total_return": 0.1, "annualized": 0.1, "sharpe": 0.5,
               "max_drawdown": -0.2, "win_rate": 0.4, "profit_factor": 1.0,
               "n_trades": 2, "eligible": True}]
    monkeypatch.setattr(fmod, "rank_universe",
                        lambda phase="aggressive", period="1y": canned)
    r = client.post("/api/fund/backtest", json={"phase": "aggressive"})
    assert r.status_code == 200
    assert r.json()["count"] == 2 and len(r.json()["top"]) == 2

    st = client.get("/api/fund/strategies").json()
    assert st["standard"] is None
    assert {row["symbol"] for row in st["ranking"]} == {"SPY", "BTC"}
    assert st["ranking"][0]["symbol"] == "BTC"  # mas reciente primero (id DESC)
    assert isinstance(st["history"], list)


def test_research_endpoint_ok_and_422(client, monkeypatch):
    import research
    calls = []

    def fake_run(**kw):
        calls.append(kw)
        return {"status": "ok", "tested": 1, "runs": 0, "standard": None}

    monkeypatch.setattr(research, "run_research", fake_run)
    r = client.post("/api/fund/research", json={})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert calls and calls[0]["db_path"].endswith("fund.db")

    def fake_bad(**kw):
        raise ValueError("ninguna SPEC valida en la respuesta")

    monkeypatch.setattr(research, "run_research", fake_bad)
    bad = client.post("/api/fund/research", json={})
    assert bad.status_code == 422


def test_research_endpoint_reads_vigente_phase(client, monkeypatch):
    import research
    client.post("/api/fund/phase", json={"phase": "moderate"})
    seen = {}

    def fake_run(db_path="fund.db", phase=None, period="1y"):
        seen["phase"] = phase
        return {"status": "sin_specs_nuevas", "tested": 0, "runs": 0, "standard": None}

    monkeypatch.setattr(research, "run_research", fake_run)
    r = client.post("/api/fund/research", json={})
    assert r.status_code == 200
    assert seen["phase"] is None  # el router deja que el ciclo lea la fase vigente
```

- [ ] **Step 2: Correr para verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_fund_api.py -v`
Expected: FAIL — 404 en `/api/fund/backtest` y `/api/fund/research`.

- [ ] **Step 3: Implementar los 3 endpoints en `api/fund.py`**

Añadir imports (bloque superior):

```python
from backtester import rank_universe
```

Añadir al final de `api/fund.py`:

```python
class BacktestRequest(BaseModel):
    phase: Optional[Literal["aggressive", "moderate"]] = None
    period: str = "1y"


class ResearchRequest(BaseModel):
    phase: Optional[Literal["aggressive", "moderate"]] = None
    period: str = "1y"


@router.post("/backtest")
async def fund_backtest(req: BacktestRequest):
    pf = _pf()
    phase = req.phase if req.phase else await asyncio.to_thread(lambda: pf.phase)
    rows = await asyncio.to_thread(
        lambda: rank_universe(phase=phase, period=req.period))
    await asyncio.to_thread(research.insert_strategy_results, FUND_DB, rows, phase)
    return {"count": len(rows), "phase": phase, "top": rows[:20]}


@router.get("/strategies")
async def fund_strategies():
    def work():
        return {"standard": research.get_standard(FUND_DB),
                "ranking": research.latest_results(FUND_DB, 50),
                "history": research.research_history(FUND_DB, 20)}
    return await asyncio.to_thread(work)


@router.post("/research")
async def fund_research(req: ResearchRequest):
    try:
        out = await asyncio.to_thread(
            lambda: research.run_research(db_path=FUND_DB, phase=req.phase,
                                          period=req.period))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return out
```

El router llama a `research.run_research` vía atributo de módulo, por eso los monkeypatches de `research.run_research` alcanzan sin tocar `fund.py`.

- [ ] **Step 4: Correr para verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/ -m "not network"`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add AgentBiz/backend/api/fund.py AgentBiz/tests/test_fund_api.py
git commit -m "feat: endpoints backtest, strategies y research del ciclo de investigación"
```

---

### Task 7: Reconversión de agentes (cargos en DB + prompts nuevos + regresión chat)

Spec §2: los 7 agentes toman sus nuevos cargos. Toques puntuales: `memory/database.py` (cargos idempotentes) y `agents/ai_brain.py` (prompts). Rutas y payloads intactos.

**Files:**
- Modify: `AgentBiz/backend/memory/database.py` (default_agents + UPDATE idempotente)
- Modify: `AgentBiz/backend/agents/ai_brain.py` (AGENT_SYSTEM_PROMPTS)
- Test: `AgentBiz/tests/test_reconversion.py` (nuevo)

**Interfaces:**
- Consumes: `init_db()` (startup), `AGENT_SYSTEM_PROMPTS`/`_FINAL_ONLY`, fixture `client` (Task 4).
- Produces: tabla `agents` con roles: scout=Analista de Mercados, trading=Mesa de Operaciones, analytics=Director de Estrategias, content=Director de Riesgo, social=Comunicaciones, freelancer=Desarrollo, affiliate=Conexiones; prompts de sistema que contienen el cargo y conservan `_FINAL_ONLY`.

- [ ] **Step 1: Escribir los tests fallando**

Crear `tests/test_reconversion.py`:

```python
EXPECTED_ROLES = {
    "scout": "Analista de Mercados",
    "trading": "Mesa de Operaciones",
    "analytics": "Director de Estrategias",
    "content": "Director de Riesgo",
    "social": "Comunicaciones",
    "freelancer": "Desarrollo",
    "affiliate": "Conexiones",
}


def test_init_db_applies_new_cargos(tmp_path, monkeypatch):
    import memory.database as mdb
    monkeypatch.setattr(mdb, "DB_PATH", str(tmp_path / "a.db"))
    mdb.init_db()
    db = mdb.get_db()
    for aid, role in EXPECTED_ROLES.items():
        row = db.execute("SELECT role FROM agents WHERE id=?", (aid,)).fetchone()
        assert row["role"] == role, aid
    db.close()


def test_reconversion_idempotent_overwrites_stale_roles(tmp_path, monkeypatch):
    import memory.database as mdb
    monkeypatch.setattr(mdb, "DB_PATH", str(tmp_path / "b.db"))
    mdb.init_db()
    db = mdb.get_db()
    db.execute("UPDATE agents SET role='Investigador' WHERE id='scout'")
    db.commit()
    db.close()
    mdb.init_db()  # arranque del servidor: vuelve a aplicar cargos
    db = mdb.get_db()
    row = db.execute("SELECT role FROM agents WHERE id='scout'").fetchone()
    db.close()
    assert row["role"] == "Analista de Mercados"


def test_prompts_cargos_and_final_only():
    from agents.ai_brain import AGENT_SYSTEM_PROMPTS, AGENT_MODELS, _FINAL_ONLY
    for aid, role in EXPECTED_ROLES.items():
        prompt = AGENT_SYSTEM_PROMPTS[aid]
        assert role.split()[0].upper() in prompt.upper(), aid
        assert _FINAL_ONLY in prompt, aid
        assert aid in AGENT_MODELS


def test_chat_endpoint_regression_with_new_prompts(client, monkeypatch):
    import api.main as m

    async def fake(agent_id, msg):
        return f"resp-{agent_id}"

    monkeypatch.setattr(m, "chat_with_agent", fake)
    r = client.post("/api/chat/scout", json={"query": "hola"})
    assert r.status_code == 200
    d = r.json()
    assert d["agent"] == "scout" and d["response"] == "resp-scout"
    assert d["model"] and d["timestamp"]
```

- [ ] **Step 2: Correr para verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/test_reconversion.py -v`
Expected: FAIL — roles viejos (`Investigador`, etc.) y prompts sin los cargos nuevos.

- [ ] **Step 3: Actualizar `memory/database.py`**

Reemplazar `default_agents` por:

```python
    default_agents = [
        ('scout', 'Scout', 'Analista de Mercados', '🔍', 'Vigila crypto/ETF/acciones/forex/futuros; detecta oportunidades y tendencias'),
        ('content', 'Content', 'Director de Riesgo', '⚖️', 'Aprueba/rechaza operaciones; vigila drawdown, exposicion y limites por fase'),
        ('affiliate', 'Affiliate', 'Conexiones', '🔗', 'Puesto para fase real: API keys de exchange/broker'),
        ('trading', 'Trading', 'Mesa de Operaciones', '📈', 'Senales BUY/SELL con SL/TP; ejecuta paper trades'),
        ('freelancer', 'Freelancer', 'Desarrollo', '💼', 'Implementa SPECs ganadoras en el motor de trading'),
        ('social', 'Social', 'Comunicaciones', '📱', 'Reporte diario a Telegram: PnL, operaciones, senales, ganadora'),
        ('analytics', 'Analytics', 'Director de Estrategias', '📊', 'Backtesting, ranking y ciclo de investigación'),
    ]
```

Y tras el bucle `for agent in default_agents: INSERT OR IGNORE`, añadir (idempotente, aplica cargos aunque la fila exista de una versión vieja):

```python
    for aid, name, role, avatar, desc in default_agents:
        c.execute('''UPDATE agents SET name=?, role=?, avatar=?, description=? WHERE id=?''',
                  (name, role, avatar, desc, aid))
```

- [ ] **Step 4: Reescribir `AGENT_SYSTEM_PROMPTS` en `ai_brain.py`**

Reemplazar el diccionario completo (mantener la línea `AGENT_SYSTEM_PROMPTS = {k: v + _FINAL_ONLY ...}` posterior intacta):

```python
AGENT_SYSTEM_PROMPTS = {
    "scout": "Eres el ANALISTA DE MERCADOS del fondo Segundo Cerebro Capital. Vigilas crypto, ETF, acciones, forex y futuros: detectas oportunidades, tendencias y niveles clave con datos concretos (precio, %, soportes/resistencias). Reportas a Investigación. DISCLAIMER: educativo, no es consejo financiero. Español, maximo 200 palabras.",

    "trading": "Eres la MESA DE OPERACIONES de Segundo Cerebro Capital. Das senales BUY/SELL/HOLD con SL/TP, apalancamiento y tamano de posicion para los 5 mercados, usando SOLO paper trading ($2,500 simulados) con los limites de la fase vigente. DISCLAIMER: educativo, no es consejo financiero. Español, maximo 200 palabras.",

    "analytics": "Eres el DIRECTOR DE ESTRATEGIAS de Segundo Cerebro Capital. Manejas backtesting, ranking de estrategias y el ciclo de investigación (hipótesis -> SPEC -> backtest -> elegir la ganadora). Cites metricas reales: Sharpe, retorno, drawdown, win rate. Español, maximo 200 palabras.",

    "content": "Eres el DIRECTOR DE RIESGO de Segundo Cerebro Capital. Apruebas o rechazas operaciones segun los limites de la fase (riesgo por operacion, apalancamiento maximo, posiciones, stop diario, drawdown) y vigilas que el fondo nunca opere sin supervisión. Respondes APRUEBA: o RECHAZA: con motivo corto cuando evalúes una operacion. Español, maximo 200 palabras.",

    "social": "Eres COMUNICACIONES de Segundo Cerebro Capital. Preparas el reporte diario para Telegram: PnL del dia, PnL total, operaciones abiertas/cerradas, win rate, drawdown, senales activas y la estrategia ganadora. Formato claro con emojis de mercado. Español, maximo 200 palabras.",

    "freelancer": "Eres DESARROLLO de Segundo Cerebro Capital. Implementas en el motor (strategies.py/backtester.py) las SPECs ganadoras del ciclo de investigación y mantienes el codigo de las estrategias con tests. Respondes con cambios concretos de codigo cuando se te pida. Español, maximo 200 palabras.",

    "affiliate": "Eres CONEXIONES de Segundo Cerebro Capital. Puesto preparado para la fase real: integración de API keys de exchange/broker cuando el CEO lo apruebe. Por ahora solo documentas requisitos, permisos y riesgos de cada exchange. Español, maximo 200 palabras.",
}
```

- [ ] **Step 5: Correr para verificar que pasan (suite completa)**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/ -m "not network"`
Expected: PASS — reconversión + regresión chat + todo lo anterior (los tests del Plan 1 que no dependen de prompts siguen verdes).

- [ ] **Step 6: Commit**

```powershell
git add AgentBiz/backend/memory/database.py AgentBiz/backend/agents/ai_brain.py AgentBiz/tests/test_reconversion.py
git commit -m "feat: reconversión de agentes a los cargos del organigrama + prompts nuevos"
```

---

### Task 8: Verificación end-to-end y regresión manual

No es TDD: valida el sistema real con el servidor corriendo y las regresiones exigidas por spec §9.

**Files:**
- No crea archivos; usa `AgentBiz/tests/` (suite completa) y curls contra el servidor vivo.

**Interfaces:**
- Consumes: Tasks 1–7 compilados en `api.main:app` y el webhook unificado v1 vivo.

- [ ] **Step 1: Suite completa (offline + network)**

Run (desde `AgentBiz`): `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest tests/ -v`
Expected: 100% PASS (offline + los 3 network del Plan 1)

- [ ] **Step 2: Reiniciar AgentBiz con las rutas nuevas**

```powershell
$p = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($p) { Stop-Process -Id $p -Force }
Start-Process -FilePath "cmd.exe" -ArgumentList "/c set PYTHONUTF8=1&& cd /d C:\Users\USUARIO\OneDrive\Desktop\Segundo-Cerebro\AgentBiz && C:\Python313\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000" -WindowStyle Hidden -WorkingDirectory "C:\Users\USUARIO\OneDrive\Desktop\Segundo-Cerebro\AgentBiz"
Start-Sleep -Seconds 5
C:\Windows\System32\curl.exe -s http://127.0.0.1:8000/api/health
```

Expected: `{"status":"ok", ...}`

- [ ] **Step 3: Humo de los 8 endpoints (PowerShell, JSON por archivo)**

Crear `03-Trabajo\fund_order.json`:

```json
{"action":"open","symbol":"BTC","side":"long","qty_usd":300,"leverage":2,"entry":100,"stop_loss":95,"take_profit":110,"strategy":"manual","review":false}
```

Crear `03-Trabajo\fund_phase.json`:

```json
{"phase":"aggressive"}
```

Run:

```powershell
C:\Windows\System32\curl.exe -s http://127.0.0.1:8000/api/fund/status
C:\Windows\System32\curl.exe -s http://127.0.0.1:8000/api/fund/portfolio
C:\Windows\System32\curl.exe -s -X POST http://127.0.0.1:8000/api/fund/phase -H "Content-Type: application/json" --data-binary "@03-Trabajo\fund_phase.json"
C:\Windows\System32\curl.exe -s http://127.0.0.1:8000/api/fund/performance
C:\Windows\System32\curl.exe -s -X POST http://127.0.0.1:8000/api/fund/orders -H "Content-Type: application/json" --data-binary "@03-Trabajo\fund_order.json"
C:\Windows\System32\curl.exe -s -X POST http://127.0.0.1:8000/api/fund/backtest -H "Content-Type: application/json" -d "{\"phase\":\"aggressive\"}"
C:\Windows\System32\curl.exe -s http://127.0.0.1:8000/api/fund/strategies
C:\Windows\System32\curl.exe -s -X POST http://127.0.0.1:8000/api/fund/research -H "Content-Type: application/json" -d "{}"
```

Expected: status/portfolio/performance/strategies → JSON con claves de Task 4/6; phase → 200; orders → 200 con `position.id` (o 409 si los límites reales lo bloquean — legible); backtest → demora ~90s con `count > 0` (red real); research → 200 (`ok`/`sin_specs_nuevas`) o 422 con error de SPEC legible (NVIDIA real).

- [ ] **Step 4: Regresión obligatoria (spec §9)**

Crear `03-Trabajo\chat_scout.json`:

```json
{"query":"Hola, ¿cómo ves el mercado hoy?"}
```

Run:

```powershell
C:\Windows\System32\curl.exe -s -X POST http://localhost:5678/webhook/unified -H "Content-Type: application/json" --data-binary "@03-Trabajo\test_unified_trading.json"
C:\Windows\System32\curl.exe -s -X POST http://localhost:5678/webhook/unified -H "Content-Type: application/json" --data-binary "@03-Trabajo\test_unified_negocio.json"
C:\Windows\System32\curl.exe -s -X POST http://127.0.0.1:8000/api/chat/scout -H "Content-Type: application/json" --data-binary "@03-Trabajo\chat_scout.json"
C:\Windows\System32\curl.exe -s -X POST http://127.0.0.1:8000/api/trading/ai -H "Content-Type: application/json" --data-binary "@03-Trabajo\test_unified_trading.json"
```

Expected: ramas trading y negocio del webhook OK (mismo formato que antes); chat → 200 con `{agent, response, model, timestamp}` (prompt de Analista de Mercados); trading/ai → 200 con `ai_interpretation`.

- [ ] **Step 5: Commit final**

```powershell
git add 03-Trabajo/fund_order.json 03-Trabajo/fund_phase.json
git commit -m "test: payloads de humo para la API del fondo (Plan 2 end-to-end)"
```

---

## Self-Review

1. **Spec coverage:** §2 (cargos) → Task 7; §4 (SL/TP obligatorios en órdenes, phase sin reset, métricas performance) → Tasks 4–5; §5.2 (strategy_results) → Task 2/6; §5.3 (ciclo, no repetir, ranking por fase, bajo demanda POST research) → Tasks 2–3/6; §6 (8 endpoints, office fuera) → Tasks 4–6; §9 fase 4 (prompts, risk gate, SPEC cycle, regresión chat) → Tasks 5/3/7/8. Sin gaps.
2. **Placeholder scan:** sin TBD/TODO/"implement later"/"similar a Task N"; todos los code steps contienen código ejecutable (verificado con grep: `TBD|TODO|if False|no-op` = 0 ocurrencias en el cuerpo).
3. **Type consistency:** `expand_grid -> [{"nombre","base","params"}]` coincide con `run_research` y `build_signal_fn`; `OrderRequest` coincide con `risk_review(order: dict)`; `research.run_research(db_path=..., phase=..., period=...)` coincide con el router y los tests; `get_meta/set_meta` usados por performance y phase-vigente con la misma firma.
4. **Review Focus:** cada línea tiene su test: (1) `test_parse_hypotheses_*` Task 3; (2) `test_order_risk_error_is_409` + double-close Task 5; (3) `test_wal_enabled`/`test_cache_wal_enabled` Task 1 + `asyncio.to_thread` en todos los handlers Task 4–6; (4) `test_save_spec_dedupe` Task 2 + `test_run_research_cycle_and_dedupe` Task 3; (5) `test_chat_endpoint_regression_with_new_prompts` Task 7 + Step 4 Task 8.
