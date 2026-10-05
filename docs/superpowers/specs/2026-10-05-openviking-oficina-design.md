# Spec: OpenViking como memoria de largo plazo de la oficina (Segundo-Cerebro)

Fecha: 2026-10-05
Estado: aprobado en diseño, pendiente de revisión de spec
Decisión del usuario: oficina (AgentBiz) + despliegue local + memoria largo plazo + provider NVIDIA NIM

## Contexto

AgentBiz tiene 8 agentes (Scout, Trading, Analytics, Content, Social, Freelancer, Affiliate,
CEC) con `ConversationMemory` en SQLite (`ai_brain.py`): guarda los últimos turnos de chat
(límite 4 por petición) pero no ofrece memoria persistente ni recuperación semántica. Los
agentes no retienen aprendizajes entre sesiones.

OpenViking (volcengine/OpenViking, AGPLv3) es una base de contexto para agentes: un sistema
de archivos virtual `viking://` con memoria, recursos y skills, recuperación semántica
acotada por directorio y resúmenes jerárquicos L0/L1/L2. Se despliega localmente con `uv`
(Python 3.10+) y un provider de modelos (embeddings + VLM) OpenAI-compatible o local.

Ya existen en el entorno: `NVIDIA_API_KEY` (NIM, `integrate.api.nvidia.com`), skills
`openviking-*` instaladas en `~/.agents/skills/`, oficina 3D en `/office` y suite de 160
tests.

## Alcance

- Servidor OpenViking local (127.0.0.1:1933) con embeddings + VLM vía NVIDIA NIM.
- Módulo `AgentBiz/backend/agents/viking_memory.py`: retrieve antes de responder y guardado
  de resúmenes al final del turno de chat.
- Inyección de contexto de memoria en `chat_with_agent` con presupuesto fijo.
- Degradación transparente: si OpenViking está caído o lento, el chat se comporta exactamente
  como hoy.
- Tests con doble falso del cliente ov (sin red en la suite).

### Fuera de alcance

- Migrar el feed, tareas o estado de agentes fuera de SQLite (queda intacto).
- Memoria de opencode / plugin de memoria del agente de desarrollo.
- Ingesta del vault personal de notas/tesis (fase futura).
- MCP: la integración es SDK Python directo desde AgentBiz.
- Web Studio ni escritorio OpenViking.

## Sección 1 — Arquitectura

```
┌─ Tu PC ─────────────────────────────────────────────┐
│  OpenViking server (uv, puerto 1933, auth local)    │
│    ├─ embedding: NVIDIA NIM (integrate.api.nvidia)  │
│    └─ VLM:      NVIDIA NIM                          │
│           ▲ HTTP (openviking-sdk)                   │
│  AgentBiz (FastAPI 8000)                            │
│    └─ agents/viking_memory.py  ← módulo nuevo       │
│         retrieve antes de responder / guardar al fin│
│  SQLite: queda intacto (tareas, feed, estado)       │
└─────────────────────────────────────────────────────┘
```

- Servidor: `uv tool install openviking --upgrade` + `openviking-server init`/`ov.conf`
  con `embedding.dense` y `vlm` apuntando a NIM (`api_base` OpenAI-compatible, dimensión
  del embedding elegida al configurar) y sección `server` (`host 127.0.0.1`, `port 1933`,
  `auth_mode api_key` con `root_api_key` local).
- Arranque en Windows en segundo plano (`Start-Process`) con health check, como uvicorn.
- Cliente: paquete PyPI `openviking-sdk` (import `openviking_sdk`), `SyncHTTPClient`
  (`url`, `api_key`), configurable por `OPENVIKING_URL`/`OPENVIKING_API_KEY`.

## Sección 2 — Esquema de memoria

- Subtree por agente: `viking://memories/agents/{agent_id}/` para los 8 agentes.
- Se guarda: hallazgos resumidos y útiles (señales detectadas, decisiones, aprendizajes
  sobre el usuario o el mercado). NO se guarda cada turno de chat.
- Escritura con `use_actor_peer(agent_id)` para trazabilidad de autoría.
- Los resúmenes L0/L1 los genera OpenViking; los agentes los usan antes de leer contenido
  completo.

## Sección 3 — Flujo de chat

Integración en `chat_with_agent` (ai_brain.py), en este orden:

1. **Retrieve**: `client.find` acotado al subtree del agente, timeout 1,5 s. Si hay
   resultados, inyectar un máximo de ~400 tokens de contexto al prompt (resúmenes L0/L1,
   nunca el árbol completo).
2. **Responder**: llamada LLM actual intacta (curl → NIM).
3. **Guardar**: si la respuesta del LLM no es un mensaje de error de los reconocidos
   (`Timeout`, `Error curl`, `respuesta vacia`, `Error NVIDIA`, `Error de red`) y tiene
   más de 20 caracteres, escribir un resumen del turno (timeout 2 s, fire-and-forget:
   la respuesta del chat no espera este paso).
4. Presupuesto y límites: 3 nodos máx. por retrieve, 400 tokens de contexto inyectado,
   sin errores visibles al usuario por problemas de OpenViking.

## Sección 4 — Fallos y degradación

- Principio: el chat de la oficina nunca falla por OpenViking.
- `viking_memory.py` envuelve cada operación en try/except con timeout duro; fallo → log
  silencioso + flujo actual (solo SQLite).
- Al arrancar AgentBiz: health check; si el servidor no responde, el módulo queda
  `disabled` y reintenta cada 10 minutos en background sin bloquear el evento startup.
- Fallos de API key/permisos de NIM u ov: visibles en logs del servidor/módulo, nunca en
  el feed de la oficina.

## Sección 5 — Testing

- Cliente ov inyectable (inyección de dependencia o monkeypatch), mismo estilo que los
  tests existentes de `ask_nvidia` (`test_ai_brain_chat.py`).
- Tests nuevos (~10, sin red):
  - retrieve inyecta contexto al prompt cuando hay nodos; no lo inyecta cuando no hay.
  - el guardado ocurre tras la respuesta del LLM.
  - servidor caído o timeout → respuesta idéntica al comportamiento actual (sin cambios
    visibles).
  - presupuesto: contexto inyectado ≤ 400 tokens y ≤ 3 nodos.
  - `use_actor_peer` aísla el subtree por agente.
  - módulo `disabled` no intenta llamadas y se marca correctamente.
- Suite objetivo: 160 → ~170 con `-m "not network"` intacto.

## Sección 6 — Operación

- `AgentBiz/scripts/setup-openviking.ps1`: instala uv + openviking, genera `ov.conf`
  (NIM, auth local), no imprime claves.
- `AgentBiz/scripts/start-openviking.ps1`: arranque en segundo plano + health check.
- Rutina de servicios documentada junto a n8n (5678), AgentBiz (8000) y Trader (5001).
- Verificación: `ov status`, `ov find "prueba"`, suite completa en verde.

## Criterios de aceptación

1. Servidor OpenViking local responde `health` desde `SyncHTTPClient`.
2. Un turno de chat con memoria inyecta contexto recuperado (verificable con doble falso
   y manualmente contra el servidor real).
3. Con OpenViking apagado, el chat responde igual que hoy (160 tests existentes en verde).
4. Suite completa `-m "not network"` en verde con los tests nuevos incluidos.
5. La oficina muestra mensajes de chat sin errores nuevos en el feed.

## Riesgos

- El wizard `openviking-server init` puede pedir interacción manual en la consola; el
  setup script debe generar `ov.conf` directamente cuando el wizard no sea automatizable.
- NIM: verificar que el embedding modelo elegido exista en la key actual (si no, cambiar
  modelo o caer a Ollama como se acordó como fallback).
- AGPLv3: solo se usa como servicio HTTP por SDK — no se incorpora código al repo.
