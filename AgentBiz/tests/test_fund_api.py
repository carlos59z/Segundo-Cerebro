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


def test_risk_review_fails_closed(monkeypatch):
    import asyncio
    import agents.ai_brain as ab

    async def fake_error(prompt, **kw):
        return "Error NVIDIA: 503"

    monkeypatch.setattr(ab, "ask_nvidia", fake_error)
    res = asyncio.run(ab.risk_review({"symbol": "BTC"}))
    assert res["decision"] == "rechaza"

    async def fake_aprueba(prompt, **kw):
        return "APRUEBA: sena fuerte"

    monkeypatch.setattr(ab, "ask_nvidia", fake_aprueba)
    res2 = asyncio.run(ab.risk_review({"symbol": "BTC"}))
    assert res2["decision"] == "aprueba"

    async def fake_rechaza(prompt, **kw):
        return "RECHAZA: sena debil"

    monkeypatch.setattr(ab, "ask_nvidia", fake_rechaza)
    res3 = asyncio.run(ab.risk_review({"symbol": "BTC"}))
    assert res3["decision"] == "rechaza"


def test_phase_change_preserves_open_positions(client):
    r0 = client.post("/api/fund/orders", json=_open_order())
    assert r0.status_code == 200
    before = client.get("/api/fund/portfolio").json()
    r = client.post("/api/fund/phase", json={"phase": "moderate"})
    assert r.status_code == 200
    after = client.get("/api/fund/portfolio").json()
    assert after["status"]["phase"] == "moderate"
    assert len(before["positions"]) == 1
    assert len(after["positions"]) == 1
    assert after["positions"][0]["id"] == before["positions"][0]["id"]
    assert after["positions"][0]["entry"] == before["positions"][0]["entry"]


def test_chat_with_agent_hardens_system_prompt(monkeypatch):
    import asyncio
    import agents.ai_brain as ab
    captured = {}

    async def fake_ask(prompt, system="", **kw):
        captured["system"] = system
        captured["max_tokens"] = kw.get("max_tokens")
        return "ok"

    monkeypatch.setattr(ab, "ask_nvidia", fake_ask)
    res = asyncio.run(ab.chat_with_agent("social", "hola"))
    assert res == "ok"
    assert "SOLO con la respuesta final" in captured["system"]
    assert captured["max_tokens"] >= 1000


def test_mark_updates_unrealized_and_curve(client, monkeypatch):
    import api.fund as fmod
    r0 = client.post("/api/fund/orders", json=_open_order())
    assert r0.status_code == 200
    before = client.get("/api/fund/performance").json()
    monkeypatch.setattr(fmod, "get_price", lambda sym: 105.0)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    d = r.json()
    assert d["marked"] == 1 and d["open"] == 1 and d["closed"] == []
    pf = client.get("/api/fund/portfolio").json()
    assert abs(pf["positions"][0]["unrealized"] - 30.0) < 0.01
    after = client.get("/api/fund/performance").json()
    assert len(after["curve"]) == len(before["curve"]) + 1
    assert after["equity"] == 2530.0


def test_mark_closes_position_at_sl(client, monkeypatch):
    import api.fund as fmod
    client.post("/api/fund/orders", json=_open_order())  # entry 100, sl 95, tp 110
    monkeypatch.setattr(fmod, "get_price", lambda sym: 90.0)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    d = r.json()
    assert d["open"] == 0 and len(d["closed"]) == 1
    pf = client.get("/api/fund/portfolio").json()
    assert pf["status"]["open_positions"] == 0
    tr = pf["trades"][0]
    assert tr["reason"] == "sl" and tr["exit"] == 95.0


def test_mark_without_positions_records_curve(client):
    before = client.get("/api/fund/performance").json()
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    d = r.json()
    assert d["marked"] == 0 and d["closed"] == []
    after = client.get("/api/fund/performance").json()
    assert len(after["curve"]) == len(before["curve"]) + 1


def test_mark_tolerates_price_failure(client, monkeypatch):
    import api.fund as fmod
    client.post("/api/fund/orders", json=_open_order())

    def boom(sym):
        raise RuntimeError("sin red")

    monkeypatch.setattr(fmod, "get_price", boom)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    assert r.json()["marked"] == 0
    pf = client.get("/api/fund/portfolio").json()
    assert pf["status"]["open_positions"] == 1
