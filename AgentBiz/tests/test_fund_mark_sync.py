def _open(client, **over):
    body = {"action": "open", "symbol": "BTC", "side": "long", "qty_usd": 300.0,
            "leverage": 2.0, "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0,
            "strategy": "sma_cross"}
    body.update(over)
    return client.post("/api/fund/orders", json=body)


def test_mark_sync_calls_close_sync_per_closed_position(client, monkeypatch):
    import api.fund as fmod
    _open(client)
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")
    calls = []

    def fake_sync(symbol, side, qty_usd, leverage, entry):
        calls.append({"symbol": symbol, "side": side, "qty_usd": qty_usd,
                      "leverage": leverage, "entry": entry})
        return {"closed": True, "fill_price": 95.0, "reason": "x",
                "market_type": "spot"}

    monkeypatch.setattr(fmod, "close_sync", fake_sync)
    monkeypatch.setattr(fmod, "get_price", lambda s: 94.0)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    d = r.json()
    assert len(d["closed"]) == 1
    assert d["broker_sync_failed"] == []
    assert calls and calls[0]["symbol"] == "BTC"
    assert calls[0]["entry"] == 100.0
    pf = client.get("/api/fund/portfolio").json()
    assert len(pf["trades"]) == 1


def test_mark_sync_failure_keeps_close_and_reports(client, monkeypatch):
    import api.fund as fmod
    from broker_binance import BrokerError
    _open(client)
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")

    def down(*a, **k):
        raise BrokerError("testnet caido")

    monkeypatch.setattr(fmod, "close_sync", down)
    monkeypatch.setattr(fmod, "get_price", lambda s: 94.0)
    msgs = []
    monkeypatch.setattr(fmod, "send_telegram", msgs.append)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    d = r.json()
    assert len(d["closed"]) == 1
    assert d["broker_sync_failed"] == ["BTC"]
    assert msgs and "BTC" in msgs[0]
    pf = client.get("/api/fund/portfolio").json()
    assert len(pf["trades"]) == 1


def test_mark_paper_mode_skips_sync(client, monkeypatch):
    import api.fund as fmod
    _open(client)

    def boom(*a, **k):
        raise AssertionError("close_sync no debe llamarse en paper")

    monkeypatch.setattr(fmod, "close_sync", boom)
    monkeypatch.setattr(fmod, "get_price", lambda s: 94.0)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    assert r.json()["broker_sync_failed"] == []
