EXPECTED_ROLES = {
    "scout": "Analista de Mercados",
    "trading": "Mesa de Operaciones",
    "analytics": "Director de Estrategias",
    "content": "Director de Riesgo",
    "social": "Comunicaciones",
    "freelancer": "Desarrollo",
    "affiliate": "Conexiones",
}


def test_init_db_applies_new_cargos(tmp_path, monkeypatch):
    import memory.database as mdb
    monkeypatch.setattr(mdb, "DB_PATH", str(tmp_path / "a.db"))
    mdb.init_db()
    db = mdb.get_db()
    for aid, role in EXPECTED_ROLES.items():
        row = db.execute("SELECT role FROM agents WHERE id=?", (aid,)).fetchone()
        assert row["role"] == role, aid
    db.close()


def test_reconversion_idempotent_overwrites_stale_roles(tmp_path, monkeypatch):
    import memory.database as mdb
    monkeypatch.setattr(mdb, "DB_PATH", str(tmp_path / "b.db"))
    mdb.init_db()
    db = mdb.get_db()
    db.execute("UPDATE agents SET role='Investigador' WHERE id='scout'")
    db.commit()
    db.close()
    mdb.init_db()  # arranque del servidor: vuelve a aplicar cargos
    db = mdb.get_db()
    row = db.execute("SELECT role FROM agents WHERE id='scout'").fetchone()
    db.close()
    assert row["role"] == "Analista de Mercados"


def test_prompts_cargos_and_final_only():
    from agents.ai_brain import AGENT_SYSTEM_PROMPTS, AGENT_MODELS, _FINAL_ONLY
    for aid, role in EXPECTED_ROLES.items():
        prompt = AGENT_SYSTEM_PROMPTS[aid]
        assert role.split()[0].upper() in prompt.upper(), aid
        assert _FINAL_ONLY in prompt, aid
        assert aid in AGENT_MODELS


def test_chat_endpoint_regression_with_new_prompts(client, monkeypatch):
    import api.main as m

    async def fake(agent_id, msg):
        return f"resp-{agent_id}"

    monkeypatch.setattr(m, "chat_with_agent", fake)
    r = client.post("/api/chat/scout", json={"query": "hola"})
    assert r.status_code == 200
    d = r.json()
    assert d["agent"] == "scout" and d["response"] == "resp-scout"
    assert d["model"] and d["timestamp"]
