import pandas as pd
import pytest
import research


def _trend_df(n=300, seed=21):
    import numpy as np
    rng = np.random.default_rng(seed)
    segs = [np.linspace(100, 160, 60), np.linspace(160, 130, 40),
            np.linspace(130, 220, 80), np.linspace(220, 190, 30),
            np.linspace(190, 280, 90)]
    close = np.concatenate(segs) * (1 + rng.normal(0, 0.002, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": 1000.0}, index=idx)


def test_mine_specs_genera_grids_validos():
    specs = research.mine_specs()
    assert len(specs) >= 6  # al menos una grilla por base
    bases = {s["base"] for s in specs}
    assert bases == {"sma_cross", "rsi_reversion", "momentum_30d",
                     "donchian_breakout", "macd_trend", "bollinger_reversion"}
    # todos expanden a variantes validas
    total = sum(len(research.expand_grid(s)) for s in specs)
    assert total >= 30


def test_run_research_acepta_specs_explicitas_sin_llm(tmp_path, monkeypatch):
    db = str(tmp_path / "m.db")
    fake = _trend_df()
    monkeypatch.setattr(research, "get_ohlc",
                        lambda sym, period="1y", interval="1d": fake)
    # el LLM no debe tocarse: si se llama, el test falla
    monkeypatch.setattr(research, "generate_hypotheses",
                        lambda phase, n=3: (_ for _ in ()).throw(
                            AssertionError("no debe usar LLM en mineria")))
    specs = [{"nombre": "mineria sma", "base": "sma_cross",
              "grid": {"fast": [5], "slow": [20]}}]
    out = research.run_research(db_path=db, phase="aggressive", specs=specs)
    assert out["status"] == "ok"
    assert out["tested"] == 1


def test_mine_refresh_retestea_specs_viejas(tmp_path, monkeypatch):
    db = str(tmp_path / "fresh.db")
    fake = _trend_df()
    monkeypatch.setattr(research, "get_ohlc",
                        lambda sym, period="1y", interval="1d": fake)
    monkeypatch.setattr(research, "generate_hypotheses",
                        lambda phase, n=3: (_ for _ in ()).throw(
                            AssertionError("no LLM")))
    specs = [{"nombre": "mineria sma", "base": "sma_cross",
              "grid": {"fast": [5], "slow": [20]}}]
    out1 = research.run_research(db_path=db, phase="aggressive", specs=specs)
    assert out1["status"] == "ok"
    # misma spec, sin refresh: dedupe
    out2 = research.run_research(db_path=db, phase="aggressive", specs=specs)
    assert out2["status"] == "sin_specs_nuevas"
    # con refresh_days=0 cae en fecha de creacion reciente; con refresh agresivo
    # (ya vencida por timestamp antiguo) debe retestear
    import sqlite3, datetime
    c = sqlite3.connect(db)
    old = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.timedelta(days=40)).isoformat()
    c.execute("UPDATE research_specs SET created_at=?", (old,))
    c.commit()
    c.close()
    out3 = research.run_research(db_path=db, phase="aggressive",
                                 specs=specs, refresh_days=14)
    assert out3["status"] == "ok"  # retesteada
    assert out3["tested"] == 1


def test_known_fingerprints_con_edad(tmp_path):
    db = str(tmp_path / "age.db")
    research.init_research_db(db)
    fp = research.save_spec(db, "sma_cross", {"fast": 5}, "v1", "aggressive")
    ages = research.known_fingerprints(db, with_age=True)
    assert fp in ages
    assert "created_at" in ages[fp]
