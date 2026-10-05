# -*- coding: utf-8 -*-
"""Tests de viking_memory: sin red, cliente siempre inyectado."""


def _fake_client(health_ok=True):
    class FakeClient:
        def __init__(self):
            self.initialized = False
        def initialize(self):
            self.initialized = True
        def health(self):
            if not health_ok:
                raise RuntimeError("connection refused")
            return {"status": "ok"}
    return FakeClient()


def test_connect_con_cliente_sano_habilita():
    from agents.viking_memory import VikingMemory
    m = VikingMemory(client=_fake_client())
    assert m.connect() is True
    assert m.enabled is True
    assert m.reason == ""


def test_connect_con_health_fallido_deshabilita_con_razon():
    from agents.viking_memory import VikingMemory
    m = VikingMemory(client=_fake_client(health_ok=False))
    assert m.connect() is False
    assert m.enabled is False
    assert "connection refused" in m.reason


def test_sin_servidor_local_no_explota(monkeypatch):
    # URL a un puerto sin servidor: connect() degrada sin lanzar,
    # aun cuando openviking_sdk este instalado (Task 5)
    monkeypatch.setenv("OPENVIKING_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("OPENVIKING_API_KEY", "test-key")
    from agents.viking_memory import VikingMemory
    m = VikingMemory()
    ok = m.connect()
    assert ok is False
    assert m.enabled is False
    assert m.reason
