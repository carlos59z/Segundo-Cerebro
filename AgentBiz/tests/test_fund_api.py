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
