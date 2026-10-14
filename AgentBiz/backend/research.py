"""Ciclo de investigación: SPECs -> backtest -> ranking -> estrategia estandar (fund.db)."""
import hashlib
import json
import sqlite3
import datetime
import itertools

from strategies import STRATEGIES, validate_params
from backtester import run_backtest, _eligible, COSTS
from market_data import get_ohlc, list_universe
from robustness import robustness_gate

INCUBATION_DAYS = 30
INCUBATION_MAX_DD = -0.10


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
        # retest: refresca created_at para no retestear en cada ciclo
        c.execute("UPDATE research_specs SET created_at=? WHERE fingerprint=?",
                  (_now(), fp))
        c.commit()
    finally:
        c.close()
    return fp


def known_fingerprints(db_path, with_age=False):
    c = _conn(db_path)
    try:
        rows = c.execute(
            "SELECT fingerprint, created_at FROM research_specs").fetchall()
    finally:
        c.close()
    if not with_age:
        return {r[0] for r in rows}
    return {r[0]: {"created_at": r[1]} for r in rows}


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


def candidate_robustness(dfs_by_symbol, sig_fn, cost_by_symbol,
                         min_pass_ratio: float = 0.5):
    """Gate de robustez del candidato sobre los simbolos evaluados.

    passed si el gate individual (walk-forward + Monte Carlo) pasa en al
    menos `min_pass_ratio` de los simbolos y el retorno OOS medio no es
    destructivo. Replica el filtro de robustez del fondo del video.
    """
    reports = {}
    passed_n = 0
    oos_returns = []
    for sym, df in dfs_by_symbol.items():
        cost = cost_by_symbol.get(sym, COSTS["crypto"])
        g = robustness_gate(df, sig_fn, cost)
        reports[sym] = g
        if g["passed"]:
            passed_n += 1
        oos_returns.append(g["oos"]["oos_return"])
    n = len(reports)
    if n == 0:
        return {"passed": False, "symbols": 0, "passed_symbols": 0,
                "mean_oos_return": 0.0, "reports": {}}
    mean_oos = float(sum(oos_returns) / n)
    passed = (passed_n / n) >= min_pass_ratio and mean_oos >= 0.0
    return {"passed": bool(passed), "symbols": n, "passed_symbols": passed_n,
            "mean_oos_return": round(mean_oos, 6), "reports": reports}


def update_incubation(db_path, curve=None):
    """Gradua (o rechaza) la estrategia en incubacion segun su equity real.

    curve: lista de (ts, equity). Si se omite, se toma del standard payload
    solo el estado; sin curva no hay graduacion.
    """
    std = get_standard(db_path)
    if not std or std.get("status") != "incubating":
        return {"status": "sin_incubacion", "standard": std}
    started = std.get("incubated_at")
    if not started or curve is None or len(curve) < 2:
        return {"status": "en_incubacion", "standard": std}
    started_dt = datetime.datetime.fromisoformat(started)
    last_dt = datetime.datetime.fromisoformat(curve[-1][0])
    days = (last_dt - started_dt).total_seconds() / 86400.0
    if days < INCUBATION_DAYS:
        return {"status": "en_incubacion", "days": round(days, 2), "standard": std}
    equities = [e for _, e in curve if e is not None]
    peak = equities[0]
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        dd = (e - peak) / peak if peak else 0.0
        max_dd = min(max_dd, dd)
    if max_dd >= INCUBATION_MAX_DD:
        std["status"] = "standard"
        std["graduated_at"] = _now()
        set_standard(db_path, std)
        return {"status": "graduada", "max_drawdown": round(max_dd, 6),
                "days": round(days, 2), "standard": std}
    std["status"] = "failed"
    std["failed_at"] = _now()
    set_standard(db_path, std)
    return {"status": "rechazada", "max_drawdown": round(max_dd, 6),
            "days": round(days, 2), "standard": std}


def parse_hypotheses(raw):
    text = (raw or "").strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    # decodifica el primer array JSON valido (inmune a prosa y arrays extra)
    decoder = json.JSONDecoder()
    data = None
    idx = text.find("[")
    while idx != -1:
        try:
            candidate, _ = decoder.raw_decode(text[idx:])
        except ValueError:
            idx = text.find("[", idx + 1)
            continue
        if isinstance(candidate, list):
            data = candidate
            break
        idx = text.find("[", idx + 1)
    if data is None:
        raise ValueError("no se encontro JSON en la respuesta del modelo")
    out = [x for x in data if isinstance(x, dict) and "base" in x]
    if not out:
        raise ValueError("ninguna SPEC valida en la respuesta")
    return out


def known_params_summary(db_path, max_vals=15):
    """Valores ya explorados por base, para empujar al LLM fuera de lo conocido."""
    c = _conn(db_path)
    try:
        rows = c.execute("SELECT base, params_json FROM research_specs").fetchall()
    finally:
        c.close()
    agg = {}
    for base, pj in rows:
        try:
            params = json.loads(pj)
        except (TypeError, ValueError):
            continue
        slot = agg.setdefault(base, {})
        for k, v in params.items():
            if isinstance(v, (int, float)):
                slot.setdefault(k, set()).add(v)
    parts = []
    for base, slot in sorted(agg.items()):
        kv = ", ".join(
            f"{k}={sorted(vals)[:max_vals]}" for k, vals in sorted(slot.items()))
        parts.append(f"{base}: {kv}")
    return "; ".join(parts)


def generate_hypotheses(phase="aggressive", n=3, db_path="fund.db"):
    from agents.ai_brain import ask_nvidia_sync, AGENT_SYSTEM_PROMPTS
    explored = known_params_summary(db_path)
    prompt = (
        f"Genera {n} hipotesis de estrategias para el fondo en fase {phase}. "
        "Responde SOLO con un array JSON, sin texto fuera del array. Cada elemento: "
        '{"nombre": "...", "base": "<una de las bases listadas>", "params": {<parametros>}, '
        '"grid": {<parametros opcionales con listas de valores para variar>}}. '
        "Bases validas: sma_cross, rsi_reversion, momentum_30d, donchian_breakout, "
        "macd_trend, bollinger_reversion. "
        "Parametros validos: sma_cross: fast, slow; rsi_reversion: period, oversold, overbought; "
        "momentum_30d: window, threshold; donchian_breakout: channel, atr_period; "
        "macd_trend: fast, slow, signal_period; bollinger_reversion: window, devs. "
        "IMPORTANTE: ya se exploraron estos valores (NO los repitas, propone valores "
        f"diferentes y racionales): {explored}"
    )
    raw = ask_nvidia_sync(prompt, system=AGENT_SYSTEM_PROMPTS["analytics"],
                          temperature=0.6, max_tokens=1500, agent_id="analytics")
    return parse_hypotheses(raw)


# grillas deterministas del "algo maker" (minería continua del fondo del video)
MINING_GRIDS = [
    {"nombre": "mineria sma", "base": "sma_cross",
     "grid": {"fast": [5, 8, 11, 15], "slow": [20, 30, 50, 100]}},
    {"nombre": "mineria rsi", "base": "rsi_reversion",
     "grid": {"period": [7, 14], "oversold": [20, 25, 30], "overbought": [70, 75, 80]}},
    {"nombre": "mineria momentum", "base": "momentum_30d",
     "grid": {"window": [10, 20, 30, 60], "threshold": [0.03, 0.05, 0.08]}},
    {"nombre": "mineria donchian", "base": "donchian_breakout",
     "grid": {"channel": [10, 15, 20, 30, 55], "atr_period": [14, 21]}},
    {"nombre": "mineria macd", "base": "macd_trend",
     "grid": {"fast": [8, 12], "slow": [21, 26], "signal_period": [5, 9]}},
    {"nombre": "mineria bollinger", "base": "bollinger_reversion",
     "grid": {"window": [15, 20, 25], "devs": [1.5, 2.0, 2.5]}},
]


def mine_specs():
    """Grillas deterministas para el ciclo de mineria (sin LLM)."""
    return [dict(g) for g in MINING_GRIDS]


def run_research(db_path="fund.db", phase=None, period="1y",
                 specs=None, refresh_days=0):
    """Ciclo completo. specs explícitas => minería determinista (sin LLM).

    refresh_days > 0: retestea SPECs cuya creacion tiene mas de N dias
    (la minería continua del "algo maker"; 0 = dedupe histórico estricto).
    """
    import statistics
    init_research_db(db_path)
    if phase is None:
        phase = get_meta(db_path, "phase", "aggressive")
        if phase not in ("aggressive", "moderate"):
            phase = "aggressive"
    hypotheses = specs if specs is not None else generate_hypotheses(
        phase, db_path=db_path)
    if refresh_days > 0:
        known_ages = known_fingerprints(db_path, with_age=True)
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(days=refresh_days))
    else:
        known = known_fingerprints(db_path)
        known_ages = None
    new_specs = []
    for h in hypotheses:
        try:
            variants = expand_grid(h)
        except ValueError:
            continue  # hipotesis invalida: se salta, no aborta ni consume el ciclo
        for concrete in variants:
            fp = spec_fingerprint(concrete["base"], concrete["params"])
            if known_ages is not None:
                info = known_ages.get(fp)
                if info is not None:
                    try:
                        created = datetime.datetime.fromisoformat(info["created_at"])
                    except (TypeError, ValueError):
                        continue
                    if created > cutoff:
                        continue  # aun fresca: se salta
                    # vencida: se retestea (el fingerprint se re-guarda con fecha nueva)
                known_ages[fp] = {"created_at": _now()}
            elif fp in known:
                continue
            new_specs.append((fp, concrete))
            if known_ages is None:
                known.add(fp)
    if not new_specs:
        return {"status": "sin_specs_nuevas", "tested": 0, "runs": 0,
                "standard": get_standard(db_path)}
    universe = list_universe()
    dfs = {}
    for market, symbols in universe.items():
        for sym in symbols:
            try:
                dfs[sym] = get_ohlc(sym, period=period, interval="1d")
            except Exception:
                continue
    if not dfs:
        # sin datos: NO se guardan las SPECs, para no consumirlas sin probar
        return {"status": "sin_datos", "tested": len(new_specs), "runs": 0,
                "standard": get_standard(db_path)}
    for fp, concrete in new_specs:
        save_spec(db_path, concrete["base"], concrete["params"],
                  concrete["nombre"], phase)
    results = []
    for fp, spec in new_specs:
        try:
            sig_fn = build_signal_fn(spec["base"], spec["params"])
        except ValueError:
            continue
        for market, symbols in universe.items():
            cost = COSTS.get(market, COSTS["crypto"])
            for sym in symbols:
                df = dfs.get(sym)
                if df is None:
                    continue
                try:
                    m = run_backtest(df, sig_fn(df), cost)
                except Exception:
                    continue
                m["eligible"] = _eligible(m, phase)
                record_run(db_path, fp, sym, spec["nombre"], m)
                results.append({"fp": fp, "nombre": spec["nombre"],
                                "base": spec["base"], "symbol": sym, **m})
    by_spec = {}
    for r in results:
        if r["n_trades"] >= 2 and r["eligible"]:
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
    # gate de robustez (walk-forward OOS + Monte Carlo) antes de promover
    rows_best = by_spec[best_fp]
    best_base_name = rows_best[0]["base"]
    # reconstruir params desde el fingerprint de new_specs
    params_best = None
    for fp_c, concrete in new_specs:
        if fp_c == best_fp:
            params_best = concrete["params"]
            break
    if params_best is None:
        params_best = {}
    try:
        sig_best = build_signal_fn(best_base_name, params_best)
    except ValueError:
        sig_best = None
    eligible_syms = {r["symbol"] for r in rows_best}
    dfs_best = {s: dfs[s] for s in eligible_syms if s in dfs}
    cost_by_sym = {}
    for market, symbols in universe.items():
        for s in symbols:
            cost_by_sym[s] = COSTS.get(market, COSTS["crypto"])
    robust = (candidate_robustness(dfs_best, sig_best, cost_by_sym)
              if sig_best is not None else {"passed": False, "symbols": 0,
                                            "passed_symbols": 0,
                                            "mean_oos_return": 0.0, "reports": {}})
    if not robust["passed"]:
        # NO se promueve: se conserva la estrategia actual (rechazo tipo incubadora)
        return {"status": "sin_candidato_robusto", "tested": len(new_specs),
                "runs": len(results), "robustness": {k: v for k, v in robust.items()
                                                     if k != "reports"},
                "standard": get_standard(db_path)}
    payload = {"fingerprint": best_fp, "nombre": best_nombre, "base": best_base,
               "score_sharpe": round(best_sharpe, 4),
               "score_return": round(best_ret, 6), "phase": phase,
               "tested_at": _now(), "runs": len(by_spec[best_fp]),
               "status": "incubating", "incubated_at": _now(),
               "robustness": {k: v for k, v in robust.items() if k != "reports"}}
    set_standard(db_path, payload)
    return {"status": "ok", "tested": len(new_specs), "runs": len(results),
            "robustness": payload["robustness"], "standard": payload}
