import json
from datetime import datetime, timedelta, timezone

import risk_committee as rc


def _mk_pf(tmp_path, daily_pnl=0.0, equity_series=None, trades=None,
           open_count=0):
    """Portfolio falso con estado controlado."""
    class FakePF:
        phase = "aggressive"

        def get_status(self):
            return {"equity": equity_series[-1] if equity_series else 2500.0,
                    "daily_pnl": daily_pnl,
                    "open_positions": open_count}

        def get_equity_curve(self, limit=1000):
            if equity_series is None:
                return []
            return [{"ts": (datetime(2026, 1, 1) + timedelta(days=i)).isoformat(),
                     "equity": v} for i, v in enumerate(equity_series)]

        def get_trades(self, limit=50):
            return trades or []

    return FakePF()


def test_mantener_portafolio_sano(tmp_path):
    pf = _mk_pf(tmp_path, equity_series=[2500, 2520, 2550, 2600],
                daily_pnl=10.0,
                trades=[{"pnl": 20}, {"pnl": -5}, {"pnl": 15}, {"pnl": 30}])
    out = rc.evaluate(str(tmp_path / "f.db"), pf=pf)
    assert out["mode"] == "mantener"
    assert out["limits"]["max_positions"] == 5
    assert out["limits"]["max_leverage"] == 5.0
    assert out["reasons"] == []


def test_reducir_por_racha_perdedora(tmp_path):
    trades = [{"pnl": -10}, {"pnl": -20}, {"pnl": -15}, {"pnl": 40}]
    pf = _mk_pf(tmp_path, equity_series=[2500, 2520, 2480, 2460],
                daily_pnl=-5.0, trades=trades)
    out = rc.evaluate(str(tmp_path / "f.db"), pf=pf)
    assert out["mode"] == "reducir"
    assert out["limits"]["max_positions"] == 4  # 5 - 1
    assert out["limits"]["max_leverage"] == 3.0
    assert any("racha" in r for r in out["reasons"])


def test_reducir_por_drawdown_medio(tmp_path):
    # alerta aggressive es -20%; -12% esta en el 60% de la alerta -> reducir
    pf = _mk_pf(tmp_path, equity_series=[2500, 2500, 2200],
                daily_pnl=0.0, trades=[{"pnl": 5}])
    out = rc.evaluate(str(tmp_path / "f.db"), pf=pf)
    assert out["mode"] == "reducir"


def test_defensivo_por_drawdown_alerta(tmp_path):
    # -22% supera la alerta -20%
    pf = _mk_pf(tmp_path, equity_series=[2500, 2500, 1950],
                daily_pnl=-30.0, trades=[{"pnl": -50}])
    out = rc.evaluate(str(tmp_path / "f.db"), pf=pf)
    assert out["mode"] == "defensivo"
    assert out["limits"]["max_positions"] == 2
    assert out["limits"]["max_leverage"] == 2.0
    assert out["limits"]["risk_pct"] == (0.025, 0.05)  # 50% de la banda
    assert any("drawdown" in r for r in out["reasons"])


def test_defensivo_por_daily_loss_stop(tmp_path):
    # aggressive daily_loss_stop = -10%; -11% -> defensivo aunque DD sea bajo
    pf = _mk_pf(tmp_path, equity_series=[2500, 2500, 2480, 2400],
                daily_pnl=-275.0, trades=[])
    out = rc.evaluate(str(tmp_path / "f.db"), pf=pf)
    assert out["mode"] == "defensivo"
    assert any("daily" in r for r in out["reasons"])


def test_historial_se_acumula(tmp_path):
    db = str(tmp_path / "h.db")
    pf = _mk_pf(tmp_path, equity_series=[2500, 2500, 1950])
    rc.evaluate(db, pf=pf)
    rc.evaluate(db, pf=pf)
    hist = rc.history(db)
    assert len(hist) == 2
    assert hist[0]["mode"] == "defensivo"


def test_orders_bloqueado_en_defensivo(client, monkeypatch):
    import api.fund as fmod

    def fake_evaluate(db_path, pf=None):
        return {"mode": "defensivo", "reasons": ["drawdown -22%"],
                "limits": {"max_positions": 2, "max_leverage": 2.0,
                           "risk_pct": (0.025, 0.05)}, "ts": "x"}

    monkeypatch.setattr(rc, "evaluate", fake_evaluate)
    monkeypatch.setattr(fmod, "risk_committee", rc)
    r = client.post("/api/fund/orders", json={
        "action": "open", "symbol": "BTC", "side": "long", "qty_usd": 100,
        "leverage": 1, "entry": 100000, "stop_loss": 95000,
        "take_profit": 120000, "strategy": "test"})
    assert r.status_code == 409
    assert "defensivo" in r.json()["detail"]


def test_orders_respeta_max_leverage_del_comite(client, monkeypatch):
    import api.fund as fmod

    def fake_evaluate(db_path, pf=None):
        return {"mode": "reducir", "reasons": ["racha perdedora"],
                "limits": {"max_positions": 4, "max_leverage": 2.0,
                           "risk_pct": (0.0375, 0.075)}, "ts": "x"}

    monkeypatch.setattr(rc, "evaluate", fake_evaluate)
    monkeypatch.setattr(fmod, "risk_committee", rc)
    r = client.post("/api/fund/orders", json={
        "action": "open", "symbol": "BTC", "side": "long", "qty_usd": 100,
        "leverage": 3, "entry": 100000, "stop_loss": 95000,
        "take_profit": 120000, "strategy": "test"})
    assert r.status_code == 409
    assert "apalancamiento" in r.json()["detail"]


def test_mark_incluye_comite(client, monkeypatch):
    import api.fund as fmod

    def fake_evaluate(db_path, pf=None):
        return {"mode": "mantener", "reasons": [],
                "limits": {"max_positions": 5, "max_leverage": 5.0,
                           "risk_pct": (0.05, 0.10)}, "ts": "x"}

    monkeypatch.setattr(rc, "evaluate", fake_evaluate)
    monkeypatch.setattr(fmod, "risk_committee", rc)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    assert r.json()["risk_committee"]["mode"] == "mantener"

