# OpenViking — Memoria de la oficina Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Los agentes de la oficina AgentBiz recuperan y guardan memoria de largo plazo en un servidor OpenViking local (NVIDIA NIM para embeddings+VLM), degradando transparente al flujo actual si el servidor falla.

**Architecture:** Módulo nuevo `agents/viking_memory.py` con un cliente `openviking_sdk.SyncHTTPClient` inyectable. `chat_with_agent` inyecta contexto recuperado (≤3 nodos, ≤1600 chars) en el prompt y guarda el turno vía sesión OpenViking (fire-and-forget con timeout). SQLite queda intacto para operación; cualquier fallo de OpenViking devuelve el chat a su comportamiento actual.

**Tech Stack:** Python 3.13 (cómo corre AgentBiz), FastAPI existente, `openviking-sdk` (PyPI), servidor OpenViking vía `uv tool install openviking`, NVIDIA NIM (`integrate.api.nvidia.com`) como provider OpenAI-compatible, pytest (suite existente: 160 con `-m "not network"`).

**Spec:** `docs/superpowers/specs/2026-10-05-openviking-oficina-design.md`

## Global Constraints

- La suite `C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q` debe terminar en verde tras cada task (base actual: 160 passed, 5 deselected).
- PowerShell 5.1: sin `&&`; UTF-8 vía `$env:PYTHONUTF8="1"` para todo test/print.
- El chat de la oficina nunca falla por OpenViking: toda llamada al servidor va con try/except y timeout de recuperación de 1,5 s (retrieve) / 2 s (save).
- No imprimir API keys en outputs, tests, logs ni mensajes de commit.
- Interfaz pública del módulo (la consumen tareas posteriores): `VikingMemory(client=None)`, `.connect() -> bool`, `.enabled: bool`, `.reason: str`, `.retrieve(agent_id: str, query: str) -> str`, `.save(agent_id: str, user_msg: str, response: str) -> bool`, y la instancia global `memory = VikingMemory()`.
- Firma de `ask_nvidia_sync`/`ask_nvidia` gana el parámetro keyword-only `user_label: str = None` al final (compatible con todos los llamadores existentes).
- Constantes del módulo: `MEMORY_ROOT = "viking://memories/agents"`, `RETRIEVE_LIMIT = 3`, `MAX_CONTEXT_CHARS = 1600` (~400 tokens), `RETRIEVE_TIMEOUT_S = 1.5`, `SAVE_TIMEOUT_S = 2.0`.
- Prefijos de error que NO se guardan como memoria: `("Timeout", "Error curl", "respuesta vacia", "Error NVIDIA", "Error de red", "Error:", "Respuesta inesperada")`; respuestas ≤ 20 caracteres tampoco.

## Review Focus

1. **Servidor caído o colgado** — un usuario que chatea no debe notar nada: respuesta idéntica, sin espera extra. Test en Task 4: cliente que lanza y cliente que tarda >1,5 s → prompt original, tiempo acotado.
2. **Formato del resultado de `find` cambiado entre versiones del server** — parse tolerante a dict/lista con claves `content`/`text`/`abstract`/`uri`. Tests en Task 2 con los tres formatos.
3. **Contexto OpenViking contaminando la memoria SQLite a corto plazo** (el prompt enriquecido se guardaría como si fuera la pregunta del usuario) — `user_label`. Test en Task 4: `save_turn` recibe la pregunta original, no la enriquecida.
4. **`create_session` repetido cada turno** (error o duplicado) — sesión idempotente: si ya existe, se reutiliza sin romper. Tests en Task 3: segundo `save` no vuelve a requerir creación y una creación fallida no impide `add_message`.
5. **Mensajes de error del LLM archivados como memoria** (ruido que contamina el retrieval futuro) — filtro de prefijos y longitud. Tests en Task 3: cada prefijo → `False` sin llamadas al servidor.

---

### Task 1: Módulo `viking_memory` — conexión y degradación

**Files:**
- Create: `AgentBiz/backend/agents/viking_memory.py`
- Test: `AgentBiz/tests/test_viking_memory.py`

**Interfaces:**
- Consumes: `openviking_sdk.SyncHTTPClient` (se importa dentro de `connect()` para que la suite no requiera el paquete instalado cuando el cliente viene inyectado).
- Produces: `VikingMemory(client: object | None = None)`, `.connect() -> bool`, `.enabled: bool`, `.reason: str`, instancia global `memory`. Los tests de Task 2+ importan `memory` y `VikingMemory` de `agents.viking_memory`.

- [ ] **Step 1: Escribir el test fallido de conexión**

```python
# AgentBiz/tests/test_viking_memory.py
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


def test_sin_servidor_local_no_explota():
    # sin OPENVIKING_URL real y sin cliente: connect() no debe lanzar
    from agents.viking_memory import VikingMemory
    m = VikingMemory()
    ok = m.connect()  # intenta servidor local inexistente en tests
    assert ok is False
    assert m.enabled is False
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_viking_memory.py -q`
Expected: FAIL (ModuleNotFoundError: No module named 'agents.viking_memory')

- [ ] **Step 3: Escribir la implementación mínima**

```python
# AgentBiz/backend/agents/viking_memory.py
# -*- coding: utf-8 -*-
"""Memoria de largo plazo de la oficina en OpenViking (servidor local).

Regla de la casa: el chat nunca falla por OpenViking. Cada operacion esta
envuelta en try/except; cualquier problema deja el modulo en `enabled=False`
y el flujo actual (SQLite) sigue igual.
"""
import logging
import os

log = logging.getLogger("viking_memory")

MEMORY_ROOT = "viking://memories/agents"
RETRIEVE_LIMIT = 3
MAX_CONTEXT_CHARS = 1600          # ~400 tokens
RETRIEVE_TIMEOUT_S = 1.5
SAVE_TIMEOUT_S = 2.0
ERROR_PREFIXES = (
    "Timeout", "Error curl", "respuesta vacia", "Error NVIDIA",
    "Error de red", "Error:", "Respuesta inesperada",
)


class VikingMemory:
    def __init__(self, client=None):
        self._client = client
        self._sessions_ready = set()
        self.enabled = False
        self.reason = "no conectado"

    def connect(self) -> bool:
        try:
            if self._client is None:
                from openviking_sdk import SyncHTTPClient
                url = os.environ.get("OPENVIKING_URL", "http://127.0.0.1:1933")
                key = os.environ.get("OPENVIKING_API_KEY", "")
                self._client = SyncHTTPClient(url=url, api_key=key)
            self._client.initialize()
            health = self._client.health()
            if not health:
                raise RuntimeError("health sin respuesta")
            self.enabled = True
            self.reason = ""
        except Exception as e:
            self.enabled = False
            self.reason = str(e)
            log.warning("openviking no disponible: %s", e)
        return self.enabled


memory = VikingMemory()
```

- [ ] **Step 4: Correr para verificar que pasa**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_viking_memory.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add AgentBiz/backend/agents/viking_memory.py AgentBiz/tests/test_viking_memory.py
git commit -m "feat(viking): modulo de memoria con connect/health y degradacion segura"
```

---

### Task 2: `retrieve` con límites (3 nodos, 1600 chars)

**Files:**
- Modify: `AgentBiz/backend/agents/viking_memory.py` (añadir `retrieve`)
- Test: `AgentBiz/tests/test_viking_memory.py` (añadir tests)

**Interfaces:**
- Consumes: `MEMORY_ROOT`, `RETRIEVE_LIMIT`, `MAX_CONTEXT_CHARS` (ya definidos), `.enabled`.
- Produces: `retrieve(self, agent_id: str, query: str) -> str` — contexto concatenado (≤1600 chars) o `""`.

- [ ] **Step 1: Escribir los tests fallidos de retrieve**

```python
# añadir a AgentBiz/tests/test_viking_memory.py


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
```

- [ ] **Step 2: Correr para verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_viking_memory.py -q`
Expected: FAIL con `AttributeError: 'VikingMemory' object has no attribute 'retrieve'`

- [ ] **Step 3: Implementar `retrieve`**

```python
# añadir a VikingMemory en viking_memory.py

    def _node_text(self, node) -> str:
        if isinstance(node, str):
            return node.strip()
        if not isinstance(node, dict):
            return ""
        for key in ("content", "text", "abstract", "overview"):
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                uri = node.get("uri")
                return (f"[{uri}] {val.strip()}" if uri else val.strip())
        return ""

    def retrieve(self, agent_id: str, query: str) -> str:
        if not self.enabled:
            return ""
        try:
            result = self._client.find(
                query=query,
                limit=RETRIEVE_LIMIT,
                target_uri=f"{MEMORY_ROOT}/{agent_id}",
            )
            items = result if isinstance(result, list) else (
                result.get("nodes") or result.get("results") or []
                if isinstance(result, dict) else []
            )
            texts = [t for t in (self._node_text(n) for n in items) if t]
            return "\n".join(texts)[:MAX_CONTEXT_CHARS]
        except Exception as e:
            log.warning("viking retrieve fallo: %s", e)
            return ""
```

- [ ] **Step 4: Correr para verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_viking_memory.py -q`
Expected: 8 passed (3 del Task 1 + 5 nuevos)

- [ ] **Step 5: Commit**

```bash
git add AgentBiz/backend/agents/viking_memory.py AgentBiz/tests/test_viking_memory.py
git commit -m "feat(viking): retrieve acotado por subtree con parse tolerante y degradacion"
```

---

### Task 3: `save` con filtro de errores y sesión idempotente

**Files:**
- Modify: `AgentBiz/backend/agents/viking_memory.py` (añadir `save`)
- Test: `AgentBiz/tests/test_viking_memory.py` (añadir tests)

**Interfaces:**
- Consumes: `ERROR_PREFIXES`, `MEMORY_ROOT` no necesario aquí; usa `create_session`/`session().add_message`/`session().commit` del SDK.
- Produces: `save(self, agent_id: str, user_msg: str, response: str) -> bool` — `True` si el turno llegó a `commit`; `False` en cualquier otro caso (deshabilitado, mensaje de error, respuesta corta, excepción).

- [ ] **Step 1: Escribir los tests fallidos de save**

```python
# añadir a AgentBiz/tests/test_viking_memory.py


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
    # el mensaje del asistente lleva peer_id = agente (autoría)
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
```

- [ ] **Step 2: Correr para verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_viking_memory.py -q`
Expected: FAIL con `AttributeError: ... no attribute 'save'`

- [ ] **Step 3: Implementar `save`**

```python
# añadir a VikingMemory en viking_memory.py

    def save(self, agent_id: str, user_msg: str, response: str) -> bool:
        if not self.enabled:
            return False
        if any(response.startswith(p) for p in ERROR_PREFIXES):
            return False
        if len(response.strip()) <= 20:
            return False
        try:
            sid = f"agentbiz-{agent_id}"
            if sid not in self._sessions_ready:
                try:
                    self._client.create_session(session_id=sid, options={
                        "memory_extraction_config": {
                            "events": {"tags": [f"agent={agent_id}"]},
                        },
                    })
                except Exception:
                    # la sesion ya existe en el server: se reutiliza
                    pass
                self._sessions_ready.add(sid)
            session = self._client.session(session_id=sid)
            session.add_message(role="user", content=user_msg[:2000])
            session.add_message(role="assistant",
                                content=response[:2000], peer_id=agent_id)
            session.commit(options={"event_tags": [f"agent={agent_id}"]})
            return True
        except Exception as e:
            log.warning("viking save fallo: %s", e)
            return False
```

- [ ] **Step 4: Correr para verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_viking_memory.py -q`
Expected: 14 passed (8 previos + 6 nuevos)

- [ ] **Step 5: Commit**

```bash
git add AgentBiz/backend/agents/viking_memory.py AgentBiz/tests/test_viking_memory.py
git commit -m "feat(viking): save de turnos con filtro de errores y sesion idempotente"
```

---

### Task 4: Integración en `chat_with_agent` + `user_label`

**Files:**
- Modify: `AgentBiz/backend/agents/ai_brain.py` — `ask_nvidia_sync` (nueva kwarg `user_label`), `ask_nvidia` (pasa la kwarg), `chat_with_agent` (retrieve → inyectar → responder → guardar en background)
- Test: `AgentBiz/tests/test_viking_memory.py` (tests del flujo de chat)

**Interfaces:**
- Consumes: `memory` (global de `agents.viking_memory`), `RETRIEVE_TIMEOUT_S`, `SAVE_TIMEOUT_S`, `viking_memory.memory.connect()`.
- Produces: `chat_with_agent(agent_id: str, message: str) -> str` (misma firma pública); `ask_nvidia(..., user_label: str = None)`; `asyncio` task pendiente en `chat_with_agent` accesible para tests vía la lista `chat_with_agent._pending`.

- [ ] **Step 1: Escribir los tests fallidos del flujo**

```python
# añadir a AgentBiz/tests/test_viking_memory.py
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
        return out, M.__dict__.get("called")
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
```

- [ ] **Step 2: Correr para verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_viking_memory.py -q`
Expected: FAIL — `chat_with_agent` actual no acepta `memory_viking` ni `user_label`

- [ ] **Step 3: Modificar `ai_brain.py`**

3a. En `ask_nvidia_sync`, añadir kwarg `user_label` y usarlo en el guardado:

```python
def ask_nvidia_sync(prompt: str, system: str = "", model: str = None,
                    max_tokens: int = 1000, temperature: float = 0.7,
                    agent_id: str = None, user_label: str = None) -> str:
```

y dentro, donde hoy hace `memory.save_turn(agent_id, prompt, response)`:

```python
                if response:
                    if agent_id:
                        memory.save_turn(agent_id, user_label or prompt, response)
                    return response
```

3b. En `ask_nvidia`, pasar la kwarg:

```python
async def ask_nvidia(prompt: str, system: str = "", model: str = None,
                     max_tokens: int = 1000, temperature: float = 0.7,
                     agent_id: str = None, user_label: str = None) -> str:
    return await asyncio.to_thread(
        ask_nvidia_sync, prompt, system, model, max_tokens, temperature,
        agent_id, user_label)
```

3c. Reemplazar `chat_with_agent` completo:

```python
from agents import viking_memory as _vm   # arriba del archivo, con los demas imports

async def chat_with_agent(agent_id: str, message: str) -> str:
    system = AGENT_SYSTEM_PROMPTS.get(agent_id, AGENT_SYSTEM_PROMPTS["scout"])

    context = ""
    try:
        context = await asyncio.wait_for(
            asyncio.to_thread(memory_viking.retrieve, agent_id, message),
            timeout=_vm.RETRIEVE_TIMEOUT_S + 0.5,
        )
    except Exception as e:
        log.debug("viking retrieve omitido: %s", e)

    prompt = message
    if context:
        prompt = ("Contexto de tu memoria (usa solo si ayuda):\n"
                  f"{context}\n\nPregunta actual:\n{message}")

    response = await ask_nvidia(prompt, system=system, agent_id=agent_id,
                                max_tokens=4000, user_label=message)

    task = asyncio.get_running_loop().create_task(
        asyncio.wait_for(
            asyncio.to_thread(memory_viking.save, agent_id, message, response),
            timeout=_vm.SAVE_TIMEOUT_S + 0.5,
        )
    )
    chat_with_agent._pending.add(task)
    task.add_done_callback(chat_with_agent._pending.discard)
    return response

chat_with_agent._pending = set()
memory_viking = _vm.memory
log = logging.getLogger("agentbiz.ai_brain")
```

(Nota: `log`/`logging` se declaran junto a los imports; si ya existe `log` en el archivo, reutilizarla. `memory_viking` es el nombre que los tests parchean.)

- [ ] **Step 4: Correr todos los tests de viking + los existentes de ai_brain**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_viking_memory.py AgentBiz/tests/test_ai_brain_chat.py -q`
Expected: 20 passed

- [ ] **Step 5: Correr la suite completa**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: ~166 passed, 5 deselected

- [ ] **Step 6: Commit**

```bash
git add AgentBiz/backend/agents/ai_brain.py AgentBiz/tests/test_viking_memory.py
git commit -m "feat(viking): chat con contexto de memoria, save en background y user_label para SQLite"
```

---

### Task 5: Scripts de instalación y arranque + verificación real (network)

**Files:**
- Create: `AgentBiz/scripts/setup-openviking.ps1`
- Create: `AgentBiz/scripts/start-openviking.ps1`
- Modify: `AgentBiz/backend/requirements.txt` (añadir `openviking-sdk`)

**Interfaces:**
- Consumes: NVIDIA key ya presente en `.env` (nunca se imprime), `uv` en PATH (se instala si falta).
- Produces: servidor OpenViking en `http://127.0.0.1:1933` con `auth_mode api_key`, `OPENVIKING_URL`/`OPENVIKING_API_KEY` en `.env` de AgentBiz, y el paquete `openviking-sdk` instalado en el Python de la suite.

- [ ] **Step 1: Añadir la dependencia al requirements**

```txt
# añadir la última línea a AgentBiz/backend/requirements.txt
openviking-sdk
```

Run: `C:/Python313/python.exe -m pip install openviking-sdk`
Expected: instalación correcta

- [ ] **Step 2: Escribir el script de setup**

```powershell
# AgentBiz/scripts/setup-openviking.ps1
# Instala OpenViking server (uv) y genera ~/.openviking/ov.conf con NVIDIA NIM.
# No imprime claves. Requiere NVIDIA_API_KEY en el .env de AgentBiz.
$ErrorActionPreference = "Stop"

$envFile = Join-Path $PSScriptRoot "..\.env"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$confDir = Join-Path $env:USERPROFILE ".openviking"
$conf = Join-Path $confDir "ov.conf"

function Get-EnvValue([string]$name) {
    if (-not (Test-Path $envFile)) { return $null }
    foreach ($line in Get-Content $envFile) {
        if ($line -match "^$name=(.+)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}

# 1. uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Instalando uv..."
    irm https://astral.sh/uv/install.ps1 | iex
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# 2. paquete openviking
Write-Host "Instalando openviking..."
uv tool install openviking --upgrade

# 3. clave NIM (sin imprimirla)
$nvidiaKey = Get-EnvValue "NVIDIA_API_KEY"
if (-not $nvidiaKey) { throw "Falta NVIDIA_API_KEY en $envFile" }
$ovKey = Get-EnvValue "OPENVIKING_API_KEY"
if (-not $ovKey) {
    $ovKey = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    Add-Content -Path $envFile -Value "OPENVIKING_API_KEY=$ovKey" -Encoding utf8
    Write-Host "OPENVIKING_API_KEY generada en .env (no se muestra)."
}
Add-Content -Path $envFile -Value "OPENVIKING_URL=http://127.0.0.1:1933" -Encoding utf8

# 4. ov.conf
New-Item -ItemType Directory -Force -Path $confDir | Out-Null
$confJson = @{
    storage = @{
        workspace = (Join-Path $confDir "data")
        vectordb  = @{ name = "context"; backend = "local" }
        agfs      = @{ backend = "local" }
    }
    embedding = @{
        dense = @{
            api_base  = "https://integrate.api.nvidia.com/v1"
            api_key   = $nvidiaKey
            provider  = "openai"
            model     = "nvidia/nv-embedqa-e5-v5"
            dimension = 1024
        }
    }
    vlm = @{
        api_base = "https://integrate.api.nvidia.com/v1"
        api_key  = $nvidiaKey
        provider = "openai"
        model    = "qwen/qwen2-vl-7b-instruct"
    }
    server = @{
        host         = "127.0.0.1"
        port         = 1933
        auth_mode    = "api_key"
        root_api_key = $ovKey
    }
} | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($conf, $confJson, (New-Object System.Text.UTF8Encoding $false))
Write-Host "ov.conf escrito en $conf (claves no mostradas)."

# 5. verificacion del provider (embedding responde en NIM)
Write-Host "Verificando embedding en NIM..."
$probe = @{ model = "nvidia/nv-embedqa-e5-v5"; input = "prueba" } | ConvertTo-Json
try {
    $r = Invoke-RestMethod -Uri "https://integrate.api.nvidia.com/v1/embeddings" `
        -Method Post -Headers @{ Authorization = "Bearer $nvidiaKey"; "Content-Type" = "application/json" } `
        -Body $probe -TimeoutSec 30
    Write-Host "Embedding OK (dimension: $($r.data[0].embedding.Count))."
} catch {
    Write-Warning "El embedding no respondio con el modelo elegido ($($_.Exception.Message)). Ajusta 'model' en $conf y vuelve a correr."
}

# 6. doctor (PowerShell 5.1 no tiene ||)
Write-Host "Ejecutando doctor..."
& uv tool run openviking-server doctor
if ($LASTEXITCODE -ne 0) { Write-Warning "doctor reporto problemas (revisa arriba)." }
Write-Host "Setup listo. Arranca con: .\scripts\start-openviking.ps1"
```

- [ ] **Step 3: Escribir el script de arranque**

```powershell
# AgentBiz/scripts/start-openviking.ps1
# Arranca OpenViking server en segundo plano y espera health.
$ErrorActionPreference = "Stop"
$port = 1933

# uv puede haberse instalado en ~/.local/bin sin estar en PATH de esta sesion
$uvLocal = Join-Path $env:USERPROFILE ".local\bin"
if ((Test-Path (Join-Path $uvLocal "uv.exe")) -and (-not (Get-Command uv -ErrorAction SilentlyContinue))) {
    $env:Path = "$uvLocal;$env:Path"
}

$alive = $false
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
    $alive = $true
} catch { }

if ($alive) { Write-Host "OpenViking ya corre en :$port"; exit 0 }

Start-Process -FilePath "uv" -ArgumentList "tool","run","openviking-server","start" `
    -WindowStyle Hidden -RedirectStandardOutput "$PSScriptRoot\..\ov_out.log" `
    -RedirectStandardError "$PSScriptRoot\..\ov_err.log"

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
        Write-Host "OpenViking OK en :$port"
        exit 0
    } catch { }
}
Write-Warning "OpenViking no respondio en 60s. Revisa ov_err.log."
exit 1
```

- [ ] **Step 4: Ejecutar setup y arranque contra el servidor real**

Run: `powershell -ExecutionPolicy Bypass -File AgentBiz/scripts/setup-openviking.ps1` y luego `powershell -ExecutionPolicy Bypass -File AgentBiz/scripts/start-openviking.ps1`
Expected: `ov.conf` creado, "Embedding OK", servidor responde `/health` (si el modelo VLM/embedding no existe en NIM, ajustar `model` en `ov.conf` y reintentar — paso explícito del script)

- [ ] **Step 5: Verificar con el SDK real (network, fuera de la suite)**

```python
# prueba manual (no es test de suite)
import os
from openviking_sdk import SyncHTTPClient
c = SyncHTTPClient(url=os.environ["OPENVIKING_URL"], api_key=os.environ["OPENVIKING_API_KEY"])
c.initialize()
print("health:", c.health())
```

Expected: `health` positivo

- [ ] **Step 6: Commit**

```bash
git add AgentBiz/scripts/setup-openviking.ps1 AgentBiz/scripts/start-openviking.ps1 AgentBiz/backend/requirements.txt
git commit -m "feat(viking): scripts de setup/arranque local con NIM y dependencia openviking-sdk"
```

---

### Task 6: Puesta en marcha integral y criterios de aceptación

**Files:**
- Modify: `AgentBiz/backend/agents/viking_memory.py` (solo si la verificación real descubre ajuste menor de rutas)
- No nuevos archivos: este task enlaza todo y verifica el spec.

**Interfaces:**
- Consumes: todo lo anterior — servidor vivo, `.env` con `OPENVIKING_URL/OPENVIKING_API_KEY`, `memory.connect()` en el arranque de AgentBiz.

- [ ] **Step 1: Conectar la memoria al arranque de AgentBiz**

En `AgentBiz/backend/api/main.py`, dentro del `@app.on_event("startup")` existente (tras los init actuales), añadir:

```python
    from agents.viking_memory import memory as viking_memory
    import threading
    def _viking_loop():
        # reintento cada 10 min hasta conectar; nunca bloquea el startup
        import time
        while True:
            if viking_memory.enabled:
                return
            if viking_memory.connect():
                log.info("openviking conectado")
                return
            log.warning("openviking deshabilitado: %s", viking_memory.reason)
            time.sleep(600)
    threading.Thread(target=_viking_loop, daemon=True).start()
```

- [ ] **Step 2: Suite completa**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: todos en verde (160 base + ~6 nuevos = ~166+)

- [ ] **Step 3: Verificación en vivo (criterios de aceptación del spec)**

1. Servidor vivo: `Invoke-RestMethod http://127.0.0.1:1933/health` → OK.
2. Reiniciar uvicorn (matar proceso `*uvicorn*`, relanzar con Start-Process como en la rutina) → log sin `openviking deshabilitado` (o con él si el server está apagado — degradación correcta).
3. Chat en vivo contra la oficina:

```python
# C:/Python313/python.exe -c con PYTHONUTF8, POST /api/chat/scout con pregunta real
```
Expected: respuesta del agente, sin errores en el feed.
4. Con OpenViking **apagado**: repetir el chat → respuesta igual (degradación).

- [ ] **Step 4: Documentar la rutina de servicios**

Comprobar si existe `AgentBiz/README.md` (o crear `AgentBiz/SERVICES.md` si no hay
ningún README) y añadir la tabla de servicios con esta fila junto a las existentes:

```markdown
| Servicio | URL | Puerto | Arranque |
|----------|-----|--------|----------|
| OpenViking (memoria oficina) | http://127.0.0.1:1933 | 1933 | scripts/start-openviking.ps1 |
```

- [ ] **Step 5: Commit final**

```bash
git add -A AgentBiz/backend/api/main.py AgentBiz/backend/agents/viking_memory.py
git commit -m "feat(viking): conecta memoria en startup con degradacion y verifica criterios de aceptacion"
```

- [ ] **Step 6: Push al fork (actualiza el PR #1)**

```bash
git push fork main
```
