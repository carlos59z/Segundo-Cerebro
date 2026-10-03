def _init_agents():
    from memory.database import init_db
    init_db()


def test_office_shape(client, monkeypatch):
    import api.fund as fmod
    _init_agents()
    monkeypatch.setattr(fmod, "get_price", lambda sym: 100.0)
    r = client.get("/api/fund/office")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"agents", "messages", "fund", "tickers", "server_time"}
    assert len(d["agents"]) == 7
    a = next(x for x in d["agents"] if x["id"] == "trading")
    for k in ("id", "name", "role", "avatar", "status", "last_active",
              "tasks_completed", "task"):
        assert k in a
    assert a["task"] is None or "title" in a["task"]
    for k in ("capital", "equity", "daily_pnl", "drawdown", "trades",
              "win_rate", "open_positions", "daily_stop_hit", "phase",
              "target", "strategy"):
        assert k in d["fund"]
    assert d["fund"]["phase"] in ("aggressive", "moderate")
    assert d["fund"]["target"] == 5000.0
    assert set(d["tickers"]) == {"BTC", "ETH", "DIA", "TSLA", "USDJPY"}
    assert all(v == 100.0 for v in d["tickers"].values())


def test_office_ticker_failure_is_isolated(client, monkeypatch):
    import api.fund as fmod
    _init_agents()

    def boom(sym):
        if sym == "BTC":
            raise RuntimeError("yfinance caido")
        return 50.0

    monkeypatch.setattr(fmod, "get_price", boom)
    r = client.get("/api/fund/office")
    assert r.status_code == 200
    d = r.json()
    assert d["tickers"]["BTC"] is None
    assert d["tickers"]["ETH"] == 50.0
    assert len(d["agents"]) == 7
    assert "equity" in d["fund"]


def test_office_messages_latest_first_and_chat_visible(client, monkeypatch):
    import api.fund as fmod
    from memory.database import get_db
    _init_agents()
    monkeypatch.setattr(fmod, "get_price", lambda sym: 1.0)
    db = get_db()
    db.execute("INSERT INTO messages (from_agent, to_agent, content, "
               "message_type, created_at) VALUES "
               "('scout', 'analytics', 'primero', 'info', '2026-10-02 10:00:00')")
    db.execute("INSERT INTO messages (from_agent, to_agent, content, "
               "message_type, created_at) VALUES "
               "('analytics', 'user', 'segundo', 'chat', '2026-10-02 11:00:00')")
    db.commit()
    db.close()
    d = client.get("/api/fund/office").json()
    assert len(d["messages"]) == 2
    assert d["messages"][0]["content"] == "segundo"
    assert d["messages"][0]["to_agent"] == "user"
    assert d["messages"][1]["content"] == "primero"


def test_office_task_shows_latest_per_agent(client, monkeypatch):
    import api.fund as fmod
    from memory.database import get_db
    _init_agents()
    monkeypatch.setattr(fmod, "get_price", lambda sym: 1.0)
    db = get_db()
    db.execute("INSERT INTO tasks (agent_id, title, status) VALUES "
               "('trading', 'vieja', 'completed')")
    db.execute("INSERT INTO tasks (agent_id, title, status) VALUES "
               "('trading', 'nueva', 'pending')")
    db.commit()
    db.close()
    d = client.get("/api/fund/office").json()
    t = next(x for x in d["agents"] if x["id"] == "trading")["task"]
    assert t["title"] == "nueva"


def test_static_and_office_page(client):
    r = client.get("/office")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    r2 = client.get("/static/lib/three.min.js")
    assert r2.status_code == 200
    r3 = client.get("/api/fund/status")
    assert r3.status_code == 200


def test_chat_saves_response_into_messages(client, monkeypatch):
    import api.main as main_mod
    from memory.database import init_db, get_db
    init_db()

    async def fake_chat(agent_id, message):
        return "respuesta del agente"

    monkeypatch.setattr(main_mod, "chat_with_agent", fake_chat)
    r = client.post("/api/chat/trading", json={"query": "hola"})
    assert r.status_code == 200
    assert r.json()["response"] == "respuesta del agente"
    db = get_db()
    row = db.execute(
        "SELECT * FROM messages WHERE message_type='chat' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    db.close()
    assert row is not None
    assert row["from_agent"] == "trading"
    assert row["to_agent"] == "user"
    assert row["content"] == "respuesta del agente"


def test_office_ticker_is_cached_for_60s(client, monkeypatch):
    import api.fund as fmod
    _init_agents()
    calls = []
    def counting(sym):
        calls.append(sym)
        return 42.0
    monkeypatch.setattr(fmod, "get_price", counting)
    r1 = client.get("/api/fund/office")
    assert r1.json()["tickers"]["BTC"] == 42.0
    n_after_first = len(calls)
    r2 = client.get("/api/fund/office")
    assert r2.json()["tickers"]["BTC"] == 42.0
    assert len(calls) == n_after_first, (
        "segunda llamada no uso cache: %d llamadas extra" % (len(calls) - n_after_first))


def test_office_ticker_expires_after_ttl(client, monkeypatch):
    import api.fund as fmod
    _init_agents()
    calls = []
    def counting(sym):
        calls.append(sym)
        return 40.0 + len(calls)
    monkeypatch.setattr(fmod, "get_price", counting)
    now = [1000.0]
    monkeypatch.setattr(fmod, "_office_now", lambda: now[0])
    r1 = client.get("/api/fund/office")
    assert r1.json()["tickers"]["BTC"] == 41.0
    assert len(calls) == 5
    r2 = client.get("/api/fund/office")
    assert r2.json()["tickers"]["BTC"] == 41.0
    assert len(calls) == 5, "dentro del TTL no debe refetchar"
    now[0] += fmod._OFFICE_TICKER_TTL + 1
    r3 = client.get("/api/fund/office")
    assert r3.json()["tickers"]["BTC"] == 46.0, "tras el TTL debe refetchar"
    assert len(calls) == 10


def test_office_ticker_serves_stale_when_refresh_in_flight(client, monkeypatch):
    import api.fund as fmod
    _init_agents()
    calls = []
    def counting(sym):
        calls.append(sym)
        return 42.0
    monkeypatch.setattr(fmod, "get_price", counting)
    now = [1000.0]
    monkeypatch.setattr(fmod, "_office_now", lambda: now[0])
    assert client.get("/api/fund/office").json()["tickers"]["BTC"] == 42.0
    assert len(calls) == 5
    now[0] += fmod._OFFICE_TICKER_TTL + 1
    lock = fmod._office_lock("BTC")
    lock.acquire()
    try:
        r = client.get("/api/fund/office")
        assert r.json()["tickers"]["BTC"] == 42.0, (
            "con refresh en vuelo debe servir el precio viejo, no null")
        assert calls.count("BTC") == 1, (
            "no debe refetchar BTC mientras otro hilo tiene el lock")
    finally:
        lock.release()
    r2 = client.get("/api/fund/office")
    assert calls.count("BTC") == 2, "al liberarse el lock debe refetchar BTC"


def test_office_ticker_null_when_cold_miss_already_in_flight(client, monkeypatch):
    import api.fund as fmod
    _init_agents()
    def counting(sym):
        return 42.0
    monkeypatch.setattr(fmod, "get_price", counting)
    now = [1000.0]
    monkeypatch.setattr(fmod, "_office_now", lambda: now[0])
    lock = fmod._office_lock("BTC")
    lock.acquire()
    try:
        r = client.get("/api/fund/office")
        assert r.status_code == 200
        assert r.json()["tickers"]["BTC"] is None, (
            "sin cache y con refresh en vuelo debe devolver null, no bloquear")
    finally:
        lock.release()


def test_office_ticker_failure_uses_backoff(client, monkeypatch):
    import api.fund as fmod
    _init_agents()
    calls = []
    def boom(sym):
        calls.append(sym)
        raise RuntimeError("yfinance caido")
    monkeypatch.setattr(fmod, "get_price", boom)
    now = [1000.0]
    monkeypatch.setattr(fmod, "_office_now", lambda: now[0])
    r1 = client.get("/api/fund/office")
    assert r1.status_code == 200
    assert r1.json()["tickers"]["BTC"] is None
    assert len(calls) == 5, "primer intento por simbolo"
    r2 = client.get("/api/fund/office")
    assert r2.json()["tickers"]["BTC"] is None
    assert len(calls) == 5, "dentro del backoff no debe reintentar"
    now[0] += fmod._OFFICE_TICKER_FAIL_TTL + 1
    r3 = client.get("/api/fund/office")
    assert len(calls) == 10, "tras el backoff debe reintentar"


def test_office_ticker_serves_stale_on_failure(client, monkeypatch):
    import api.fund as fmod
    _init_agents()
    state = {"fail": False}
    def flaky(sym):
        if state["fail"]:
            raise RuntimeError("temporal")
        return 77.0
    monkeypatch.setattr(fmod, "get_price", flaky)
    now = [1000.0]
    monkeypatch.setattr(fmod, "_office_now", lambda: now[0])
    r1 = client.get("/api/fund/office")
    assert r1.json()["tickers"]["BTC"] == 77.0
    now[0] += fmod._OFFICE_TICKER_TTL + 1
    state["fail"] = True
    r2 = client.get("/api/fund/office")
    assert r2.json()["tickers"]["BTC"] == 77.0, (
        "si el refresh falla pero hay precio viejo, servirlo")


def test_office_html_references_only_local_assets(client):
    r = client.get("/office")
    assert r.status_code == 200
    html = r.text
    assert "/static/lib/three.min.js" in html
    assert "https://" not in html, "CDN externo prohibido (spec §4)"
    assert "http://" not in html, "CDN externo prohibido (spec §4)"
