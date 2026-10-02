def _open(**over):
    body = {"action": "open", "symbol": "BTC", "side": "long", "qty_usd": 300.0,
            "leverage": 2.0, "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0,
            "strategy": "sma_cross"}
    body.update(over)
    return body


def test_suite_env_is_isolated_from_dotenv():
    import os
    assert os.environ.get("EXECUTION_MODE") == "paper"
    assert os.environ.get("AUTO_TRADER") == "0"


def test_paper_mode_never_calls_broker(client, monkeypatch):
    import api.fund as fmod

    def boom(*a, **k):
        raise AssertionError("broker no debe llamarse en modo paper")

    monkeypatch.setattr(fmod, "place_order", boom)
    r = client.post("/api/fund/orders", json=_open())
    assert r.status_code == 200
    d = r.json()
    assert d["execution"] == {"mode": "paper", "broker": None, "order_id": None}
    assert d["position"]["entry"] == 100.0


def test_testnet_order_uses_broker_fill_price(client, monkeypatch):
    import api.fund as fmod
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")
    monkeypatch.setattr(fmod, "place_order",
                        lambda *a, **k: {"order_id": "42", "fill_price": 98.5,
                                         "protection_ok": True})
    r = client.post("/api/fund/orders", json=_open(market_type="futures"))
    assert r.status_code == 200
    d = r.json()
    assert d["position"]["entry"] == 98.5
    assert d["execution"] == {"mode": "testnet", "broker": "binance-testnet",
                              "order_id": "42"}
    pf = client.get("/api/fund/portfolio").json()
    assert pf["status"]["open_positions"] == 1


def test_testnet_broker_failure_is_502_and_no_position(client, monkeypatch):
    import api.fund as fmod
    from broker_binance import BrokerError
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")

    def down(*a, **k):
        raise BrokerError("testnet caido")

    monkeypatch.setattr(fmod, "place_order", down)
    r = client.post("/api/fund/orders", json=_open(market_type="futures"))
    assert r.status_code == 502
    assert "broker" in r.json()["detail"]
    pf = client.get("/api/fund/portfolio").json()
    assert pf["positions"] == []


def test_spot_constraints_422_before_review(client, monkeypatch):
    import api.fund as fmod
    calls = []

    async def review(order):
        calls.append(order)
        return {"decision": "aprueba", "reason": ""}

    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")
    monkeypatch.setattr(fmod, "risk_review", review)
    r = client.post("/api/fund/orders", json=_open(side="short", review=True))
    assert r.status_code == 422
    assert "short" in r.json()["detail"]
    assert calls == []
    bad_lev = client.post("/api/fund/orders", json=_open(leverage=3.0, review=True))
    assert bad_lev.status_code == 422
    assert calls == []


def test_close_testnet_records_broker_fill(client, monkeypatch):
    import api.fund as fmod
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")
    monkeypatch.setattr(fmod, "place_order",
                        lambda *a, **k: {"order_id": "7", "fill_price": 100.0,
                                         "protection_ok": True})
    client.post("/api/fund/orders", json=_open(market_type="futures"))
    monkeypatch.setattr(
        fmod, "close_sync",
        lambda *a: {"closed": True, "fill_price": 105.0, "reason": "x"})
    r = client.post("/api/fund/orders",
                    json={"action": "close", "position_id": 1, "price": 104.0,
                          "symbol": "BTC", "market_type": "futures"})
    assert r.status_code == 200
    assert r.json()["trade"]["pnl"] == 30.0
    assert r.json()["execution"]["mode"] == "testnet"


def test_testnet_preflight_blocks_before_broker(client, monkeypatch):
    import api.fund as fmod
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")
    calls = []
    monkeypatch.setattr(fmod, "place_order", lambda *a, **k: calls.append(1))
    r = client.post("/api/fund/orders",
                    json=_open(market_type="futures", qty_usd=3000.0))
    assert r.status_code == 409
    assert calls == []
    pf = client.get("/api/fund/portfolio").json()
    assert pf["positions"] == []


def test_post_fill_risk_error_compensates(client, monkeypatch):
    import api.fund as fmod
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")
    monkeypatch.setattr(fmod, "place_order",
                        lambda *a, **k: {"order_id": "9", "fill_price": 95.0,
                                         "protection_ok": True})
    closes = []
    monkeypatch.setattr(
        fmod, "close_on_exchange",
        lambda *a: (closes.append(a) or
                    {"closed": True, "fill_price": 95.0, "reason": "broker close"}))
    msgs = []
    monkeypatch.setattr(fmod, "send_telegram", msgs.append)
    r = client.post("/api/fund/orders",
                    json=_open(leverage=1.0, stop_loss=90.5))
    assert r.status_code == 409
    assert closes and closes[0][0] == "BTC"
    assert msgs and "post-fill" in msgs[0]
    pf = client.get("/api/fund/portfolio").json()
    assert pf["positions"] == []
