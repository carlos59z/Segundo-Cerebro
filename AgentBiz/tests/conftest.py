import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))


def pytest_configure(config):
    config.addinivalue_line("markers", "network: tests que descargan datos reales")


import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    import memory.database as mdb
    monkeypatch.setattr(mdb, "DB_PATH", str(tmp_path / "agents.db"))
    import api.fund as fmod
    monkeypatch.setattr(fmod, "FUND_DB", str(tmp_path / "fund.db"))
    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as c:
        yield c
