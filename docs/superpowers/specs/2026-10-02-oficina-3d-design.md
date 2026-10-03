# Oficina 3D — Segundo Cerebro Capital

Fecha: 2026-10-02
Estado: borrador para revisión
Spec maestro relacionado: `2026-09-30-segundo-cerebro-capital-design.md` §8 (definición original; este spec lo detalla)

## 1. Contexto y objetivo

El diseño maestro (§8) define una página local `http://127.0.0.1:8000/office` que
muestra el fondo como una oficina 3D viva: 7 escritorios (un cargo por agente),
mesa CEO, pizarrón con la meta, estados animados y HUD de mercado. Nunca se
construyó (la fase quedó fuera de los planes ejecutados; `GET /office` → 404).

Objetivo: construirla completa según §8, más interacción añadida aprobada por el
CEO: **clic en un escritor abre un panel de chat con ese agente**
(`POST /api/chat/{id}`, endpoint ya existente).

Éxito: la página abre, se anima con datos reales cada 3s, el chat por clic
funciona de extremo a extremo, y las suites existentes siguen verdes.

## 2. Alcance

- `GET /api/fund/office` — agregador JSON (agents + messages + fund + tickers).
- `GET /office` — página estática servida por AgentBiz.
- Escena Three.js (r128 local, sin CDN): planta, 7 escritorios, mesa CEO, pizarrón.
- Estados `idle`/`working` con luces; burbujas de habla; líneas animadas
  inter-departamento; HUD (ticker, PnL, drawdown, trades/winrate, reloj NY);
  feed lateral de mensajes.
- Panel de chat por clic: historial + input + `POST /api/chat/{id}`.
- Cambio mínimo en `/api/chat/{id}`: además de responder, insertar la respuesta
  en `messages` para que feed/burbujas la muestren (hoy solo inserta en `tasks`).

Fuera de alcance: click-through a otros endpoints, sonido, móvil, multi-escena,
configuración de layout, autenticación (todo local).

## 3. API: `GET /api/fund/office`

Implementación en `AgentBiz/backend/api/fund.py` (router existente). Fuentes:
`memory/database.py` (agents/tasks/messages), helpers de fondo ya usados por
`/api/fund/status`, `market_data.get_price`.

```jsonc
{
  "agents": [
    {
      "id": "scout",
      "name": "Scout",
      "role": "Analista de Mercados",
      "avatar": "🔍",
      "status": "idle",              // agents.status: idle | working
      "last_active": "…ISO…",         // o null
      "tasks_completed": 3,
      "task": {                       // última tarea por created_at DESC, o null
        "title": "consulta del usuario…",
        "status": "completed"
      }
    }
    // …los 7 agentes de default_agents (scout, content, affiliate, trading,
    // freelancer, social, analytics)
  ],
  "messages": [                       // últimos 20 por created_at DESC (id desc)
    {"id": 42, "from_agent": "scout", "to_agent": "analytics",
     "content": "…", "message_type": "info", "created_at": "…ISO…"}
  ],
  "fund": {
    "capital": 2500.0,
    "equity": 2563.05,
    "daily_pnl": 0.0,
    "drawdown": -0.0199,
    "trades": 2,
    "win_rate": 0.5,
    "open_positions": 2,
    "daily_stop_hit": false,
    "phase": "aggressive",            // aggressive | moderate
    "target": 5000.0,
    "strategy": "SMA Crossover Agresivo {…}"   // ganadora (status.standard.nombre), o null
  },
  "tickers": {
    "BTC": 84000.12,                  // market_data.get_price; símbolo fallido → null
    "ETH": 3100.5,
    "DIA": 431.2,
    "TSLA": 265.4,
    "USDJPY": 151.3
  },
  "server_time": "…ISO…"
}
```

Reglas:
- Modo paper y testnet/real funcionan igual (nada de broker aquí).
- Un precio fallido → `null` en ese símbolo; el resto del payload se entrega
  igual (nunca 500 por ticker caído).
- Si la BD de agentes está vacía → `agents: []` (la página muestra estado vacío).
- Consulta por agente para `task`: una sola query con `GROUP BY agent_id` +
  `MAX(created_at)` (evitar N+1).

## 4. Serving estático

- Archivos: `AgentBiz/backend/static/office/` → `index.html`, `office.js`,
  `office.css`; `AgentBiz/backend/static/lib/three.min.js` (r128 UMD, descarga
  única del artefacto oficial — misma versión que `SuperAgenteTrader/dashboard.html`).
- `api/main.py`: `app.mount("/static", StaticFiles(directory=…))` +
  `@app.get("/office")` → `FileResponse("…/static/office/index.html")`.
- HTML referencia scripts en `/static/lib/three.min.js` y
  `/static/office/office.js` (sin CDN, sin build).

## 5. Frontend

**Cámara/escena:** isométrica fija (vista 3/4 de la planta), rotación ligera al
arrastrar (limitada), zoom rueda. Planta: suelo, 7 escritorios en 2 filas
agrupados por zona de departamento, mesa CEO al frente, pizarrón detrás.

**Escritorio:** mesa (caja) + monitor (plano con `CanvasTexture` = título de la
tarea actual) + avatar (esfera/cápsula, color fijo por id de agente) +
etiqueta `Sprite` con `name` + `role`.

**Estados:**
- `idle` → luz azul tenue junto al escritorio, avatar quieto.
- `working` → luz ámbar, avatar con bobbing (±y sinusoidal), monitor muestra la
  tarea actual en ámbar.

**Hablando:** para cada agente, último mensaje con `from_agent == id` → burbuja
(`Sprite` con `CanvasTexture`, texto truncado a ~90 chars, visible 6s desde que
se detecta en el poll o hasta cambiar).

**Línea inter-departamento:** último mensaje con `from_agent` y `to_agent` ambos
en la lista de agentes y distintos → línea animada (`THREE.Line` + esfera
viajera) entre los dos escritorios, visible mientras ese mensaje siga siendo
el inter-dept más reciente.

**Pizarrón:** plano con `CanvasTexture` redibujado cuando cambia:
estrategia ganadora, fase (AGRESIVA/MODERADA), meta $5,000 y drawdown actual.

**HUD (overlay HTML, fuera de WebGL):** cinta ticker (5 símbolos, precio y %
vs. primer valor de la sesión de página), equity/PnL del día, drawdown,
trades/winrate, reloj `America/New_York` (actualiza 1s).

**Feed lateral:** panel HTML con los últimos 20 mensajes
(`from → to`, texto, hora HH:MM).

**Panel de chat (clic en escritor):** raycaster sobre los escritorios → abre
panel lateral con: nombre/cargo, últimas ~10 conversaciones (derivadas de
`messages` donde `to_agent == "user"` o `from_agent == id`), input + botón.
Envía `POST /api/chat/{agent_id}` con `{"query": "…"}`; mientras carga,
spinner y avatar del escritorio pasa a `working` localmente; al responder,
muestra `response` (tarda ~2-15 s con el LLM) y el próximo poll lo refleja en
burbuja/feed. Cierre del panel con X.

**Polling:** `fetch("/api/fund/office")` cada 3000 ms; errores de red → reintentar
en el ciclo siguiente sin romper la escena (mostrar indicador "sin conexión"
tenue en el HUD).

**Idioma:** todo el texto de la UI en español.

## 6. Cambio backend mínimo en chat

`api/main.py::chat` — tras obtener `result`, insertar:
`INSERT INTO messages (from_agent, to_agent, content, message_type) VALUES (?, 'user', ?, 'chat')`
con `from_agent = agent_id`, `content = result`. Sin cambiar la respuesta HTTP.
(Existe riesgo de doble escritura solo si chat_with_agent también inserta — hoy
no lo hace; el test lo fija.)

## 7. Testing

- **Endpoint** (`AgentBiz/tests/test_fund_office.py`, nuevos):
  1. Shape: 200, claves `agents/messages/fund/tickers/server_time`, 7 agentes
     con sus campos, `task` null o con `title`.
  2. Tolerancia: `get_price` lanza → ese símbolo `null`, payload completo (200).
  3. Mensajes: inserto 2 en BD de test → aparecen en `messages` (orden DESC) y
     su inter-dept más reciente queda reflejado en el payload.
  4. `GET /office` → 200 + `text/html`.
  5. Chat: `POST /api/chat/{id}` con `chat_with_agent` mockeado → 200 y la
     respuesta queda insertada en `messages` (contract del §6).
- **QA visual** con la skill `design-review` (spec §8 nombraba `design-html`,
  no instalada): página abierta en el navegador, capturas, correcciones.
- **Regresión:** suite offline completa (`-m "not network"`) verde antes y después.

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Precios yfinance caídos/rate limit | tickers → null + caché existente de market_data; HUD muestra "—" |
| LLM NVIDIA lento en chat | spinner + estado working local; timeouts del cliente a 60 s |
| Three.js local desactualizado | r128 UMD probado ya en SuperAgenteTrader; sin módulos ES |
| Escena pesada en PC modesta | geometrías simples, sin sombras, texto en CanvasTexture |
| `GET /office` choca con montaje estático | ruta explícita antes del mount; test de 200 |

## 9. Fuera de alcance

- Dinero real / broker (la oficina solo lee).
- Trabajo remoto o móvil (página local).
- Persistencia de configuración de la escena.
