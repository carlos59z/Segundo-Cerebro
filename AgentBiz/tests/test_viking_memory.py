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
# añadir al final de AgentBiz/tests/test_viking_memory.py

class SessionRecorder:
    """Cliente falso que graba las llamadas de sesion."""
    def __init__(self, fail_create=False):
        self.calls = []
        self.sessions = {}
        self.fail_create = fail_create
    def initialize(self): pass
    def health(self): return {"status": "ok"}
    def create_session(self, session_id=None, options=None):
        if self.fail_create:
            raise RuntimeError("session already exists")
        self.calls.append(("create", session_id))
        return {"session_id": session_id}
    def session(self, session_id=None):
        rec = self
        class S:
            def add_message(self, role=None, content=None, peer_id=None, parts=None):
                rec.calls.append(("msg", role, peer_id, (content or "")[:40]))
            def commit(self, options=None):
                rec.calls.append(("commit", session_id))
        return S()


def test_save_ok_crea_sesion_mensajes_y_commit():
    from agents.viking_memory import VikingMemory
    c = SessionRecorder()
    m = VikingMemory(client=c); m.connect()
    ok = m.save("scout", "analiza btc", "BTC mantiene soporte en 64k con volumen alto.")
    assert ok is True
    roles = [x[1] for x in c.calls if x[0] == "msg"]
    assert roles == ["user", "assistant"]
    assert any(x[0] == "commit" for x in c.calls)
    assistant = [x for x in c.calls if x[0] == "msg" and x[1] == "assistant"][0]
    assert assistant[2] == "scout"


def test_save_segunda_vez_no_vuelve_a_crear_sesion():
    from agents.viking_memory import VikingMemory
    c = SessionRecorder()
    m = VikingMemory(client=c); m.connect()
    m.save("scout", "q1", "Respuesta larga y util del primer turno.")
    m.save("scout", "q2", "Respuesta larga y util del segundo turno.")
    creates = [x for x in c.calls if x[0] == "create"]
    assert len(creates) == 1
    assert len([x for x in c.calls if x[0] == "commit"]) == 2


def test_save_tolera_sesion_ya_existente_en_el_servidor():
    from agents.viking_memory import VikingMemory
    c = SessionRecorder(fail_create=True)
    m = VikingMemory(client=c); m.connect()
    ok = m.save("scout", "q", "Respuesta larga a pesar de sesion existente.")
    assert ok is True
    assert any(x[0] == "commit" for x in c.calls)


def test_save_no_archiva_mensajes_de_error_del_llm():
    from agents.viking_memory import VikingMemory, ERROR_PREFIXES
    for prefix in ERROR_PREFIXES:
        c = SessionRecorder()
        m = VikingMemory(client=c); m.connect()
        assert m.save("scout", "q", prefix + " detalle") is False, prefix
        assert not [x for x in c.calls if x[0] in ("create", "commit")]


def test_save_no_archiva_respuestas_cortas():
    from agents.viking_memory import VikingMemory
    c = SessionRecorder()
    m = VikingMemory(client=c); m.connect()
    assert m.save("scout", "q", "ok") is False
    assert not [x for x in c.calls if x[0] == "commit"]


def test_save_deshabilitado_o_con_fallo_devuelve_false():
    from agents.viking_memory import VikingMemory
    assert VikingMemory().save("scout", "q", "Respuesta larga suficiente aqui.") is False

    class Boom(SessionRecorder):
        def session(self, session_id=None):
            raise RuntimeError("write rejected")
    c = Boom()
    m = VikingMemory(client=c); m.connect()
    assert m.save("scout", "q", "Respuesta larga suficiente aqui.") is False


# --- Task 4: flujo de chat_with_agent ---

import asyncio


def _run_chat(agent_id, message, fake_mem, monkeypatch):
    import agents.ai_brain as ab
    monkeypatch.setattr(ab, "memory_viking", fake_mem)
    captured = {}

    async def fake_ask(prompt, system="", model=None, max_tokens=1000,
                       temperature=0.7, agent_id=None, user_label=None):
        captured["prompt"] = prompt
        captured["user_label"] = user_label
        return "Respuesta larga y completa del agente para el usuario."
    monkeypatch.setattr(ab, "ask_nvidia", fake_ask)
    return asyncio.run(ab.chat_with_agent(agent_id, message)), captured


def test_chat_inyecta_contexto_de_memoria(monkeypatch):
    class M:
        enabled = True
        def retrieve(self, agent_id, query):
            return "[viking] hallazgo previo: soporte en 64k"
        def save(self, agent_id, user_msg, response): return True
    out, cap = _run_chat("scout", "que ves en btc?", M(), monkeypatch)
    assert "hallazgo previo: soporte en 64k" in cap["prompt"]
    assert "que ves en btc?" in cap["prompt"]


def test_chat_sin_contexto_usa_prompt_original(monkeypatch):
    class M:
        enabled = True
        def retrieve(self, agent_id, query): return ""
        def save(self, agent_id, user_msg, response): return True
    out, cap = _run_chat("scout", "hola", M(), monkeypatch)
    assert cap["prompt"] == "hola"


def test_chat_sin_memoria_o_con_timeout_sigue_normal(monkeypatch):
    class M:
        enabled = False
        def retrieve(self, a, q): raise AssertionError("no debe llamar")
        def save(self, *x): return False
    out, cap = _run_chat("scout", "pregunta normal", M(), monkeypatch)
    assert cap["prompt"] == "pregunta normal"
    assert "Respuesta larga" in out


def test_memoria_solo_save_recibe_pregunta_original(monkeypatch):
    # el user_label evita que el prompt enriquecido contamine SQLite
    class M:
        enabled = True
        def retrieve(self, a, q): return "contexto largo de viking"
        def save(self, *x): return True
    out, cap = _run_chat("trading", "senal de hoy", M(), monkeypatch)
    assert cap["user_label"] == "senal de hoy"


def test_chat_dispara_save_en_background(monkeypatch):
    class M:
        enabled = True
        called = None
        def retrieve(self, a, q): return ""
        def save(self, agent_id, user_msg, response):
            M.called = (agent_id, user_msg, response)
            return True
    import agents.ai_brain as ab

    async def main():
        monkeypatch.setattr(ab, "memory_viking", M())
        async def fake_ask(prompt, **kw):
            return "Respuesta larga suficiente para guardarse bien."
        monkeypatch.setattr(ab, "ask_nvidia", fake_ask)
        out = await ab.chat_with_agent("scout", "pregunta")
        pending = list(getattr(ab.chat_with_agent, "_pending", []))
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return out, M.called
    out, called = asyncio.run(main())
    assert called is not None
    assert called[0] == "scout"
    assert called[1] == "pregunta"


def test_recuperacion_de_contexto_respetando_timeout(monkeypatch):
    # retrieve que se cuelga > RETRIEVE_TIMEOUT_S no bloquea el chat
    import agents.ai_brain as ab
    from agents import viking_memory as vm

    class Slow:
        enabled = True
        def retrieve(self, a, q):
            import time; time.sleep(vm.RETRIEVE_TIMEOUT_S + 1)
            return "tarde"
        def save(self, *x): return True
    monkeypatch.setattr(ab, "memory_viking", Slow())
    captured = {}
    async def fake_ask(prompt, **kw):
        captured["prompt"] = prompt
        return "Respuesta larga del agente tras espera acotada."
    monkeypatch.setattr(ab, "ask_nvidia", fake_ask)
    out = asyncio.run(ab.chat_with_agent("scout", "rapido"))
    assert captured["prompt"] == "rapido"   # contexto descartado, chat normal
