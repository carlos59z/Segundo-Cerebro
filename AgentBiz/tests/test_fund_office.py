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
