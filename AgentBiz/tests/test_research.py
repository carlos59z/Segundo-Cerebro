import pandas as pd
import pytest
import research
import strategies as st


def _db(tmp_path):
    p = str(tmp_path / "fund.db")
    research.init_research_db(p)
    return p


@pytest.fixture
def db(tmp_path):
    return _db(tmp_path)


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
    idx = pd.date_range("2025-01-01", periods=120, freq="D", tz="UTC")
    close = pd.Series(np.concatenate([up, down, up, down]), index=idx)
    df = pd.DataFrame({"open": close.shift(1).fillna(100), "high": close + 1,
                       "low": close - 1, "close": close, "volume": 1000.0},
                      index=idx)
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
