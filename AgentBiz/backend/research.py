"""Ciclo de investigación: SPECs -> backtest -> ranking -> estrategia estandar (fund.db)."""
import hashlib
import json
import sqlite3
import datetime
import itertools

from strategies import STRATEGIES, validate_params
from backtester import run_backtest, _eligible, COSTS
from market_data import get_ohlc, list_universe


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
                results.append({"fp": fp, "nombre": spec["nombre"],
                                "base": spec["base"], **m})
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
        scored.append((mean_sharpe, mean_ret, fp, rows[0]["nombre"], rows[0]["base"]))
    scored.sort(reverse=True)
    best_sharpe, best_ret, best_fp, best_nombre, best_base = scored[0]
    payload = {"fingerprint": best_fp, "nombre": best_nombre, "base": best_base,
               "score_sharpe": round(best_sharpe, 4),
               "score_return": round(best_ret, 6), "phase": phase,
               "tested_at": _now(), "runs": len(by_spec[best_fp])}
    set_standard(db_path, payload)
    return {"status": "ok", "tested": len(new_specs), "runs": len(results),
            "standard": payload}
