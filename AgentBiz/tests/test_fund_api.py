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
