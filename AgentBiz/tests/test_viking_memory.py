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


def _enabled_memory(fake_client):
    from agents.viking_memory import VikingMemory
    m = VikingMemory(client=fake_client)
    m.connect()
    return m


def test_retrieve_devuelve_contexto_y_acota_por_subtree():
    from agents.viking_memory import MEMORY_ROOT
    calls = {}

    class C:
        def initialize(self): pass
        def health(self): return {"status": "ok"}
        def find(self, query=None, limit=None, target_uri=None):
            calls.update(query=query, limit=limit, target_uri=target_uri)
            return [{"uri": "viking://memories/agents/scout/n1.md",
                     "content": "Senal BTC detectada en 64k"}]
    m = _enabled_memory(C())
    out = m.retrieve("scout", "btc")
    assert "Senal BTC detectada en 64k" in out
    assert calls["target_uri"] == f"{MEMORY_ROOT}/scout"
    assert calls["limit"] == 3


def test_retrieve_soporta_formato_dict_del_servidor():
    class C:
        def initialize(self): pass
        def health(self): return {"status": "ok"}
        def find(self, **kw):
            return {"nodes": [{"text": "titulo", "abstract": "resumen L0 util"}]}
    m = _enabled_memory(C())
    assert "resumen L0 util" in m.retrieve("trading", "senal")


def test_retrieve_sin_nodos_devuelve_vacio():
    class C:
        def initialize(self): pass
        def health(self): return {"status": "ok"}
        def find(self, **kw): return []
    m = _enabled_memory(C())
    assert m.retrieve("scout", "nada") == ""


def test_retrieve_acota_a_MAX_CONTEXT_CHARS():
    from agents.viking_memory import MAX_CONTEXT_CHARS
    class C:
        def initialize(self): pass
        def health(self): return {"status": "ok"}
        def find(self, **kw):
            return [{"content": "x" * 4000}]
    m = _enabled_memory(C())
    assert len(m.retrieve("scout", "q")) <= MAX_CONTEXT_CHARS


def test_retrieve_deshabilitado_o_con_fallo_devuelve_vacio():
    from agents.viking_memory import VikingMemory
    m1 = VikingMemory()           # nunca conectado
    assert m1.retrieve("scout", "q") == ""

    class Boom:
        def initialize(self): pass
        def health(self): return {"status": "ok"}
        def find(self, **kw): raise RuntimeError("server exploded")
    m2 = _enabled_memory(Boom())
    assert m2.retrieve("scout", "q") == ""   # degrada, no lanza
