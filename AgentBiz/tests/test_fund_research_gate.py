import numpy as np
import pandas as pd
import research


def _mk_df(n=600, seed=7, drift=0.004, vol=0.005):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = 100 * np.cumprod(1 + rets)
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.full(n, 1000.0),
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def _long(df):
    return pd.Series(1, index=df.index)


def _short(df):
    return pd.Series(-1, index=df.index)


def test_candidate_robustness_pasa_en_alcistas():
    dfs = {"BTC": _mk_df(seed=7), "ETH": _mk_df(seed=8)}
    r = research.candidate_robustness(dfs, _long, {"BTC": 0.0006, "ETH": 0.0006})
    assert r["passed"] is True
    assert r["symbols"] == 2
    assert r["passed_symbols"] >= 1


def test_candidate_robustness_falla_en_bajistas():
    dfs = {"BTC": _mk_df(seed=7, drift=-0.004), "ETH": _mk_df(seed=8, drift=-0.004)}
    r = research.candidate_robustness(dfs, _long, {"BTC": 0.0006, "ETH": 0.0006})
    assert r["passed"] is False


def test_candidate_robustness_sin_simbolos():
    r = research.candidate_robustness({}, _long, {})
    assert r["passed"] is False and r["symbols"] == 0


def test_update_incubation_gradua_tras_30_dias(tmp_path):
    db = str(tmp_path / "f.db")
    research.init_research_db(db)
    research.set_standard(db, {
        "fingerprint": "abc", "nombre": "x", "base": "sma_cross",
        "status": "incubating", "incubated_at": "2026-09-01T00:00:00+00:00",
    })
    curve = [("2026-09-01T00:00:00+00:00", 2500.0),
             ("2026-10-02T00:00:00+00:00", 2550.0),
             ("2026-10-12T00:00:00+00:00", 2600.0)]
    r = research.update_incubation(db, curve)
    assert r["status"] == "graduada"
    std = research.get_standard(db)
    assert std["status"] == "standard"
    assert "graduated_at" in std


def test_update_incubation_rechaza_si_drawdown_excesivo(tmp_path):
    db = str(tmp_path / "f.db")
    research.init_research_db(db)
    research.set_standard(db, {
        "fingerprint": "abc", "nombre": "x", "base": "sma_cross",
        "status": "incubating", "incubated_at": "2026-09-01T00:00:00+00:00",
    })
    curve = [("2026-09-01T00:00:00+00:00", 2500.0),
             ("2026-10-02T00:00:00+00:00", 2200.0),   # -12% dd
             ("2026-10-12T00:00:00+00:00", 2250.0)]
    r = research.update_incubation(db, curve)
    assert r["status"] == "rechazada"
    assert research.get_standard(db)["status"] == "failed"


def test_update_incubation_en_curso_si_no_pasaron_30_dias(tmp_path):
    db = str(tmp_path / "f.db")
    research.init_research_db(db)
    research.set_standard(db, {
        "fingerprint": "abc", "nombre": "x", "base": "sma_cross",
        "status": "incubating", "incubated_at": "2026-10-01T00:00:00+00:00",
    })
    curve = [("2026-10-01T00:00:00+00:00", 2500.0),
             ("2026-10-12T00:00:00+00:00", 2510.0)]
    r = research.update_incubation(db, curve)
    assert r["status"] == "en_incubacion"
    assert research.get_standard(db)["status"] == "incubating"


def test_update_incubation_sin_standard(tmp_path):
    db = str(tmp_path / "f.db")
    research.init_research_db(db)
    r = research.update_incubation(db, [])
    assert r["status"] == "sin_incubacion"
