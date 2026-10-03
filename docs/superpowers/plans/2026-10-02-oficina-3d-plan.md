# Oficina 3D — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir la página `/office` (oficina 3D viva de Segundo Cerebro Capital) con endpoint agregador, Three.js local y chat por clic en escritorios.

**Architecture:** Endpoint `GET /api/fund/office` en `api/fund.py` agrega agents/tasks/messages (BD de agentes), resumen de fondo (helpers existentes) y 5 tickers con tolerancia a fallos. FastAPI sirve estáticos desde `backend/static/` (`GET /office` + mount `/static`). Frontend vanilla JS + Three.js r128 (UMD local, sin CDN, sin build) con polling cada 3s, raycaster para clics y panel de chat que consume `POST /api/chat/{id}` ya existente (más un insert en `messages` para que feed/burbujas muestren las respuestas).

**Tech Stack:** Python 3.13 / FastAPI / pytest; SQLite (`memory.database`, `fund.db`); Three.js r128 UMD; HTML/CSS/JS vanilla.

**Spec:** `docs/superpowers/specs/2026-10-02-oficina-3d-design.md`

## Global Constraints

- UI 100% en español (etiquetas, feed, chat, HUD, pizarrón).
- Three.js **r128 UMD local** en `/static/lib/three.min.js`; **sin CDN en runtime**; sin build/npm.
- Geometrías válidas en r128: `BoxGeometry`, `SphereGeometry`, `CylinderGeometry`, `PlaneGeometry`, `Sprite`, `CanvasTexture`, `Raycaster`, `PointLight`. **Prohibido `CapsuleGeometry`** (existe desde r141).
- Polling exacto: `setInterval(poll, 3000)`.
- Ticker caído → ese símbolo `null` en JSON y "—" en HUD; **nunca** 500 por precio.
- `GET /api/fund/office` no toca broker ni `paper_portfolio` (solo lectura).
- Tests: `PYTHONUTF8=1`, rutas con `/`, PowerShell sin `&&` (usa `;`).
- Suite offline siempre verde: `C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`.
- Archivos estáticos solo bajo `AgentBiz/backend/static/`.
- Tras cada cambio de backend: reiniciar uvicorn (comando en Task 2 Paso 5).

## Review Focus

1. **Ticker yfinance caído/rate-limit** → solo ese símbolo null, resto del payload intacto. Test dueño: Task 1 `test_office_ticker_failure_is_isolated`.
2. **Mensajes `to_agent='user'` (respuestas de chat)** → el feed los muestra, pero burbuja/línea NO deben dibujar un escritorio fantasma "user". Test dueño: Task 7 paso visual + filtro `AGENT_IDS` en el código.
3. **Chat LLM caído o backend apagado al enviar** → el panel muestra error legible y se reactiva el botón; el polling no se rompe. Paso dueño: Task 8 verificación de error.
4. **Servidor apagado durante el polling** → indicador "sin conexión", la escena sigue renderizando y se recupera sola. Paso dueño: Task 5 verificación offline.
5. **Mount `/static` no sombrea `/api/*` y la app arranca con los directorios creados** → `/api/fund/status` sigue 200 tras el mount. Test dueño: Task 2 `test_static_and_office_page`.

## File Structure

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Crear | `AgentBiz/tests/test_fund_office.py` | Tests del endpoint/página/chat-insert |
| Modificar | `AgentBiz/backend/api/fund.py` | `GET /api/fund/office` (solo lectura) |
| Modificar | `AgentBiz/backend/api/main.py` | mount estático + `GET /office` + insert en messages |
| Crear | `AgentBiz/backend/static/lib/three.min.js` | Three.js r128 (descarga única) |
| Crear | `AgentBiz/backend/static/office/index.html` | Esqueleto HTML (HUD, feed, panel chat) |
| Crear | `AgentBiz/backend/static/office/office.css` | Estilos overlay/paneles |
| Crear | `AgentBiz/backend/static/office/office.js` | Toda la escena y lógica de cliente |

---

### Task 1: Endpoint `GET /api/fund/office`

**Files:**
- Modify: `AgentBiz/backend/api/fund.py` (agregar imports + endpoint al final del router)
- Test: `AgentBiz/tests/test_fund_office.py` (crear)

**Interfaces:**
- Consumes: `_pf().get_status()` (claves: capital, equity, daily_pnl, drawdown, trades, win_rate, open_positions, daily_stop_hit, phase), `research.get_standard(FUND_DB)`, `research.get_meta(FUND_DB, key, default)`, `market_data.get_price(sym)` (ya importado como `get_price`), `memory.database.get_db()`.
- Produces (lo consumen Tasks 4-8): JSON `{"agents": [{id,name,role,avatar,status,last_active,tasks_completed,task:{title,status}|null}], "messages": [{id,from_agent,to_agent,content,message_type,created_at}] (máx 20, más reciente primero), "fund": {capital,equity,daily_pnl,drawdown,trades,win_rate,open_positions,daily_stop_hit,phase,target,strategy|null}, "tickers": {BTC,ETH,DIA,TSLA,USDJPY} (float|null), "server_time": ISO}`.

- [ ] **Step 1: Escribir el test fallido**

Crear `AgentBiz/tests/test_fund_office.py`:

```python
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
```

- [ ] **Step 2: Correr para verificar falla**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_fund_office.py -q`
Expected: 4 failed (404 en `/api/fund/office`).

- [ ] **Step 3: Implementar el endpoint**

En `AgentBiz/backend/api/fund.py`:
1. Agregar a los imports superiores: `from datetime import datetime, timezone` y `from memory.database import get_db`.
2. Al final del archivo (después del último endpoint del router) agregar:

```python
_OFFICE_TICKERS = ("BTC", "ETH", "DIA", "TSLA", "USDJPY")


@router.get("/office")
async def fund_office():
    def work():
        st = _pf().get_status()
        standard = research.get_standard(FUND_DB)
        target = research.get_meta(FUND_DB, "target", st["capital"] * 2)
        db = get_db()
        try:
            agents = [dict(r) for r in
                      db.execute("SELECT * FROM agents ORDER BY rowid")]
            latest_task = {
                r["agent_id"]: {"title": r["title"], "status": r["status"]}
                for r in db.execute(
                    "SELECT agent_id, title, status FROM tasks t1 "
                    "WHERE id = (SELECT MAX(id) FROM tasks t2 "
                    "WHERE t2.agent_id = t1.agent_id)")}
            messages = [dict(r) for r in db.execute(
                "SELECT * FROM messages "
                "ORDER BY created_at DESC, id DESC LIMIT 20")]
        except Exception:
            agents, latest_task, messages = [], {}, []
        finally:
            db.close()
        for a in agents:
            a["task"] = latest_task.get(a["id"])
        tickers = {}
        for sym in _OFFICE_TICKERS:
            try:
                tickers[sym] = get_price(sym)
            except Exception:
                tickers[sym] = None
        return {
            "agents": agents,
            "messages": messages,
            "fund": {
                "capital": st["capital"], "equity": st["equity"],
                "daily_pnl": st["daily_pnl"], "drawdown": st["drawdown"],
                "trades": st["trades"], "win_rate": st["win_rate"],
                "open_positions": st["open_positions"],
                "daily_stop_hit": st["daily_stop_hit"],
                "phase": st["phase"], "target": target,
                "strategy": (standard or {}).get("nombre"),
            },
            "tickers": tickers,
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
    return await asyncio.to_thread(work)
```

- [ ] **Step 4: Correr para verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_fund_office.py -q`
Expected: 4 passed.

- [ ] **Step 5: Regresión offline**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: 144 passed (140 previos + 4 nuevos), 5 deselected.

- [ ] **Step 6: Commit**

```powershell
git add AgentBiz/backend/api/fund.py AgentBiz/tests/test_fund_office.py
git commit -m "feat(office): endpoint GET /api/fund/office (agents+messages+fund+tickers)"
```

---

### Task 2: Serving estático (`/office`, `/static`) + Three.js local

**Files:**
- Modify: `AgentBiz/backend/api/main.py` (imports + rutas al final del archivo)
- Create: `AgentBiz/backend/static/lib/three.min.js` (descarga)
- Create: `AgentBiz/backend/static/office/index.html` (placeholder mínimo)
- Test: `AgentBiz/tests/test_fund_office.py` (agregar test)

**Interfaces:**
- Consumes: FastAPI `app` existente en `api/main.py`; `STATIC_DIR` = `AgentBiz/backend/static/`.
- Produces: `GET /office` → HTML; `GET /static/**` → archivos; global `THREE` (r128 UMD) disponible vía `<script src="/static/lib/three.min.js">` para Tasks 4-8.

- [ ] **Step 1: Test fallido**

Agregar al final de `AgentBiz/tests/test_fund_office.py`:

```python
def test_static_and_office_page(client):
    r = client.get("/office")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    r2 = client.get("/static/lib/three.min.js")
    assert r2.status_code == 200
    r3 = client.get("/api/fund/status")
    assert r3.status_code == 200
```

- [ ] **Step 2: Verificar falla**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_fund_office.py::test_static_and_office_page -q`
Expected: FAIL (404 en `/office`).

- [ ] **Step 3: Crear directorios + descargar Three.js + placeholder**

```powershell
New-Item -ItemType Directory -Force -Path "AgentBiz\backend\static\lib" | Out-Null
New-Item -ItemType Directory -Force -Path "AgentBiz\backend\static\office" | Out-Null
& C:\Windows\System32\curl.exe -L -o "AgentBiz\backend\static\lib\three.min.js" "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
(Get-Item "AgentBiz\backend\static\lib\three.min.js").Length
```
Expected: archivo > 500000 bytes.

Crear `AgentBiz/backend/static/office/index.html` (placeholder — Task 4 lo reemplaza):

```html
<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><title>Oficina 3D</title></head>
<body><h1>Oficina 3D — cargando…</h1></body>
</html>
```

- [ ] **Step 4: Montar estáticos en main.py**

En `AgentBiz/backend/api/main.py`:
1. Agregar import: `from fastapi.responses import FileResponse` y `from fastapi.staticfiles import StaticFiles`.
2. **Al final del archivo** (últimas líneas, después de todas las rutas) agregar:

```python
STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))


@app.get("/office")
def office_page():
    return FileResponse(os.path.join(STATIC_DIR, "office", "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
```

- [ ] **Step 5: Reiniciar uvicorn (comando estándar de este plan)**

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*uvicorn*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
Start-Process -FilePath "C:\Python313\python.exe" -ArgumentList "-m","uvicorn","api.main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory "C:\Users\USUARIO\OneDrive\Desktop\Segundo-Cerebro\AgentBiz\backend" -RedirectStandardOutput "C:\Users\USUARIO\OneDrive\Desktop\Segundo-Cerebro\AgentBiz\uvicorn_out2.log" -RedirectStandardError "C:\Users\USUARIO\OneDrive\Desktop\Segundo-Cerebro\AgentBiz\uvicorn_err2.log" -WindowStyle Hidden
Start-Sleep -Seconds 6
& C:\Windows\System32\curl.exe -s -o NUL -w "office [HTTP %{http_code}]" http://127.0.0.1:8000/office
```
Expected: `office [HTTP 200]`.

- [ ] **Step 6: Verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_fund_office.py -q`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```powershell
git add AgentBiz/backend/api/main.py AgentBiz/tests/test_fund_office.py AgentBiz/backend/static/office/index.html
git commit -m "feat(office): sirve /office y /static con three.js r128 local"
```
(`static/lib/three.min.js` es binario descargado; agregarlo también: `git add AgentBiz/backend/static/lib/three.min.js` — sí va al repo, es el spec "sin CDN".)

---

### Task 3: Chat guarda respuesta en `messages`

**Files:**
- Modify: `AgentBiz/backend/api/main.py` (endpoint `chat`, línea del insert en tasks)
- Test: `AgentBiz/tests/test_fund_office.py` (agregar test)

**Interfaces:**
- Consumes: endpoint `chat` existente (`POST /api/chat/{agent_id}`, body `{"query": str}`, respuesta `{agent, response, model, timestamp}`), `chat_with_agent` (mockeable en `api.main`).
- Produces: filas en `messages` con `from_agent=<id>, to_agent='user', content=<response>, message_type='chat'` — lo consumen burbujas/feed/historial de chat (Tasks 7-8).

- [ ] **Step 1: Test fallido**

Agregar al final de `AgentBiz/tests/test_fund_office.py`:

```python
def test_chat_saves_response_into_messages(client, monkeypatch):
    import api.main as main_mod
    from memory.database import init_db, get_db
    init_db()

    async def fake_chat(agent_id, message):
        return "respuesta del agente"

    monkeypatch.setattr(main_mod, "chat_with_agent", fake_chat)
    r = client.post("/api/chat/trading", json={"query": "hola"})
    assert r.status_code == 200
    assert r.json()["response"] == "respuesta del agente"
    db = get_db()
    row = db.execute(
        "SELECT * FROM messages WHERE message_type='chat' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    db.close()
    assert row is not None
    assert row["from_agent"] == "trading"
    assert row["to_agent"] == "user"
    assert row["content"] == "respuesta del agente"
```

- [ ] **Step 2: Verificar falla**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_fund_office.py::test_chat_saves_response_into_messages -q`
Expected: FAIL (`row is None`).

- [ ] **Step 3: Implementar el insert**

En `AgentBiz/backend/api/main.py`, endpoint `chat` (~línea 321), **justo antes** del `db.execute("INSERT INTO tasks ...")` agregar:

```python
    db.execute("INSERT INTO messages (from_agent, to_agent, content, message_type) VALUES (?, 'user', ?, 'chat')",
               (agent_id, result))
```

- [ ] **Step 4: Verificar que pasa**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_fund_office.py -q`
Expected: 6 passed.

- [ ] **Step 5: Regresión offline + reiniciar uvicorn (comando Task 2 Paso 5)**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: 145 passed, 5 deselected.
Luego reiniciar uvicorn con el comando del Task 2 Paso 5.

- [ ] **Step 6: Commit**

```powershell
git add AgentBiz/backend/api/main.py AgentBiz/tests/test_fund_office.py
git commit -m "feat(office): chat guarda la respuesta en messages (feed/burbujas)"
```

---

### Task 4: Escena Three.js (planta, 7 escritorios, CEO, pizarrón, cámara)

**Files:**
- Create: `AgentBiz/backend/static/office/index.html` (reemplaza placeholder)
- Create: `AgentBiz/backend/static/office/office.css`
- Create: `AgentBiz/backend/static/office/office.js`

**Interfaces:**
- Consumes: `THREE` global (r128 UMD, Task 2); datos en Tasks 5-8 (`/api/fund/office`).
- Produces: estructura de módulos globales de `office.js`: `scene`, `camera`, `renderer`, `desks` (dict id → {group, light, avatar, monitor, monitorCanvas, monitorCtx, monitorTex, label}), `wrapText(ctx, text, x, y, maxW, lh, maxLines)` (la usan Tasks 5-7), y el loop `animate()`. HTML con contenedores `#scene`, `#hud`, `#feed`, `#chat-panel`, `#offline`.

- [ ] **Step 1: index.html completo**

Crear `AgentBiz/backend/static/office/index.html`:

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Segundo Cerebro Capital — Oficina 3D</title>
  <link rel="stylesheet" href="/static/office/office.css">
</head>
<body>
  <div id="scene"></div>

  <div id="hud" class="panel">
    <div id="hud-ticker" class="ticker">—</div>
    <div id="hud-equity">—</div>
    <div id="hud-dd">—</div>
    <div id="hud-trades">—</div>
    <div id="hud-phase">—</div>
    <div id="hud-clock">NY —:—:—</div>
  </div>

  <aside id="feed" class="panel">
    <h3>Mensajes de la oficina</h3>
    <ul id="feed-list"></ul>
  </aside>

  <div id="chat-panel" class="panel hidden">
    <button id="chat-close" title="Cerrar">✕</button>
    <h3 id="chat-title">Agente</h3>
    <div id="chat-log"></div>
    <form id="chat-form">
      <input id="chat-input" type="text" placeholder="Escribe al agente…" autocomplete="off">
      <button id="chat-send" type="submit">Enviar</button>
    </form>
    <div id="chat-status"></div>
  </div>

  <div id="offline" class="hidden">Sin conexión — reintentando…</div>

  <script src="/static/lib/three.min.js"></script>
  <script src="/static/office/office.js"></script>
</body>
</html>
```

- [ ] **Step 2: office.css**

Crear `AgentBiz/backend/static/office/office.css`:

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 100%; height: 100%; overflow: hidden;
  background: #0b1220; color: #e2e8f0;
  font-family: "Segoe UI", system-ui, sans-serif; }
#scene, #scene canvas { position: absolute; inset: 0; display: block; }

.panel { position: absolute; background: rgba(15, 23, 42, 0.88);
  border: 1px solid #334155; border-radius: 10px; padding: 12px;
  backdrop-filter: blur(4px); z-index: 10; }

#hud { top: 14px; left: 14px; min-width: 260px; font-size: 14px;
  display: flex; flex-direction: column; gap: 6px; }
#hud .ticker { color: #7dd3fc; font-weight: 600; }
#hud #hud-phase { color: #fbbf24; font-weight: 700; letter-spacing: 1px; }
#hud #hud-clock { color: #94a3b8; }

#feed { top: 14px; right: 14px; width: 320px; max-height: 46vh;
  overflow: hidden; display: flex; flex-direction: column; }
#feed h3 { font-size: 13px; text-transform: uppercase; color: #7dd3fc;
  margin-bottom: 8px; letter-spacing: 1px; }
#feed-list { list-style: none; overflow-y: auto; font-size: 13px;
  display: flex; flex-direction: column; gap: 6px; }
#feed-list li { padding: 6px 8px; background: #1e293b; border-radius: 6px;
  line-height: 1.35; word-break: break-word; }
#feed-list .who { color: #38bdf8; font-weight: 600; }
#feed-list .time { color: #64748b; font-size: 11px; float: right; }

#chat-panel { bottom: 14px; left: 14px; width: 380px;
  display: flex; flex-direction: column; gap: 8px; }
#chat-panel.hidden { display: none; }
#chat-close { position: absolute; top: 8px; right: 10px; background: none;
  border: none; color: #94a3b8; font-size: 16px; cursor: pointer; }
#chat-title { font-size: 15px; color: #38bdf8; }
#chat-log { height: 200px; overflow-y: auto; font-size: 13px;
  display: flex; flex-direction: column; gap: 6px; }
#chat-log .msg { padding: 6px 8px; border-radius: 6px; max-width: 92%; }
#chat-log .mine { background: #1d4ed8; align-self: flex-end; }
#chat-log .theirs { background: #1e293b; align-self: flex-start; }
#chat-form { display: flex; gap: 6px; }
#chat-input { flex: 1; background: #0f172a; border: 1px solid #334155;
  border-radius: 6px; color: #e2e8f0; padding: 8px; font-size: 13px; }
#chat-send { background: #2563eb; border: none; border-radius: 6px;
  color: #fff; padding: 8px 12px; cursor: pointer; }
#chat-send:disabled { opacity: 0.5; cursor: wait; }
#chat-status { font-size: 12px; color: #f87171; min-height: 14px; }

#offline { position: absolute; bottom: 14px; right: 14px; z-index: 20;
  background: #7f1d1d; color: #fecaca; padding: 8px 14px;
  border-radius: 8px; font-size: 13px; }
#offline.hidden { display: none; }
```

- [ ] **Step 3: office.js — escena base**

Crear `AgentBiz/backend/static/office/office.js` con este contenido inicial (Tasks 5-8 lo extienden):

```javascript
"use strict";

const AGENT_META = {
  scout:      { name: "Scout",      role: "Analista de Mercados", emoji: "🔍" },
  content:    { name: "Content",    role: "Director de Riesgo",   emoji: "⚖️" },
  affiliate:  { name: "Affiliate",  role: "Conexiones",           emoji: "🔗" },
  trading:    { name: "Trading",    role: "Mesa de Operaciones",  emoji: "📈" },
  freelancer: { name: "Freelancer", role: "Desarrollo",           emoji: "💼" },
  social:     { name: "Social",     role: "Comunicaciones",       emoji: "📱" },
  analytics:  { name: "Analytics",  role: "Director de Estrategias", emoji: "📊" },
};
const AGENT_IDS = Object.keys(AGENT_META);
const AGENT_COLORS = {
  scout: 0x38bdf8, content: 0xfbbf24, affiliate: 0xf87171, trading: 0x34d399,
  freelancer: 0xf472b6, social: 0x60a5fa, analytics: 0xa78bfa,
};
const DESK_POS = {
  scout: [-7.5, -3.2], analytics: [-2.5, -3.2], trading: [2.5, -3.2],
  content: [7.5, -3.2], freelancer: [-5, 2.6], social: [0, 2.6],
  affiliate: [5, 2.6],
};

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b1220);

const camera = new THREE.PerspectiveCamera(
  45, window.innerWidth / window.innerHeight, 0.1, 200);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
document.getElementById("scene").appendChild(renderer.domElement);

scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const dirLight = new THREE.DirectionalLight(0xffffff, 0.65);
dirLight.position.set(8, 14, 6);
scene.add(dirLight);

const floor = new THREE.Mesh(
  new THREE.BoxGeometry(22, 0.2, 14),
  new THREE.MeshPhongMaterial({ color: 0x1e293b }));
floor.position.y = -0.1;
scene.add(floor);

function makeLabel(lines) {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 140;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "rgba(2, 6, 23, 0.75)";
  ctx.beginPath();
  ctx.roundRect ? ctx.roundRect(0, 0, 512, 140, 18) : ctx.rect(0, 0, 512, 140);
  ctx.fill();
  ctx.textAlign = "center";
  ctx.fillStyle = "#e2e8f0";
  ctx.font = "bold 44px Segoe UI";
  ctx.fillText(lines[0], 256, 58);
  ctx.fillStyle = "#7dd3fc";
  ctx.font = "30px Segoe UI";
  ctx.fillText(lines[1], 256, 106);
  const tex = new THREE.CanvasTexture(c);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true }));
  sp.scale.set(3.4, 0.93, 1);
  return sp;
}

const desks = {};

function buildDesk(id) {
  const meta = AGENT_META[id];
  const [x, z] = DESK_POS[id];
  const g = new THREE.Group();

  const table = new THREE.Mesh(
    new THREE.BoxGeometry(2.6, 0.14, 1.3),
    new THREE.MeshPhongMaterial({ color: 0x334155 }));
  table.position.y = 1.0;
  g.add(table);

  const leg = new THREE.Mesh(
    new THREE.BoxGeometry(2.3, 0.95, 0.15),
    new THREE.MeshPhongMaterial({ color: 0x1f2937 }));
  leg.position.y = 0.5;
  g.add(leg);

  const monitorCanvas = document.createElement("canvas");
  monitorCanvas.width = 512; monitorCanvas.height = 256;
  const monitorCtx = monitorCanvas.getContext("2d");
  const monitorTex = new THREE.CanvasTexture(monitorCanvas);
  const monitor = new THREE.Mesh(
    new THREE.BoxGeometry(1.3, 0.75, 0.07),
    new THREE.MeshPhongMaterial({ color: 0x0f172a }));
  monitor.position.set(0, 1.6, -0.35);
  g.add(monitor);
  const screen = new THREE.Mesh(
    new THREE.PlaneGeometry(1.2, 0.65),
    new THREE.MeshBasicMaterial({ map: monitorTex }));
  screen.position.set(0, 1.6, -0.31);
  g.add(screen);

  const color = AGENT_COLORS[id];
  const avatar = new THREE.Mesh(
    new THREE.SphereGeometry(0.34, 20, 20),
    new THREE.MeshPhongMaterial({ color, emissive: color, emissiveIntensity: 0.3 }));
  avatar.position.set(0, 1.05, 0.85);
  g.add(avatar);

  const chair = new THREE.Mesh(
    new THREE.CylinderGeometry(0.32, 0.32, 0.12, 16),
    new THREE.MeshPhongMaterial({ color: 0x0f172a }));
  chair.position.set(0, 0.6, 0.85);
  g.add(chair);

  const label = makeLabel([meta.emoji + " " + meta.name, meta.role]);
  label.position.set(0, 2.6, 0);
  g.add(label);

  const light = new THREE.PointLight(0x38bdf8, 0.5, 7);
  light.position.set(0, 2.2, 0);
  g.add(light);

  g.position.set(x, 0.1, z);
  g.traverse(o => { o.userData.agentId = id; });
  scene.add(g);
  desks[id] = { group: g, light, avatar, monitor, monitorCanvas, monitorCtx,
                monitorTex, label, working: false };
}

AGENT_IDS.forEach(buildDesk);

const ceoTable = new THREE.Mesh(
  new THREE.BoxGeometry(4.4, 0.18, 1.7),
  new THREE.MeshPhongMaterial({ color: 0x7c2d12 }));
ceoTable.position.set(0, 1.0, -6);
scene.add(ceoTable);
const ceoLeg = new THREE.Mesh(
  new THREE.BoxGeometry(4.0, 0.95, 0.2),
  new THREE.MeshPhongMaterial({ color: 0x431407 }));
ceoLeg.position.set(0, 0.5, -6);
scene.add(ceoLeg);
const ceoLabel = makeLabel(["🧑‍💼 CEO", "Mesa de Carlos"]);
ceoLabel.position.set(0, 2.7, -6);
scene.add(ceoLabel);

const boardCanvas = document.createElement("canvas");
boardCanvas.width = 1024; boardCanvas.height = 512;
const boardCtx = boardCanvas.getContext("2d");
const boardTex = new THREE.CanvasTexture(boardCanvas);
const whiteboard = new THREE.Mesh(
  new THREE.PlaneGeometry(7.5, 3.4),
  new THREE.MeshBasicMaterial({ map: boardTex }));
whiteboard.position.set(0, 3.0, -6.85);
scene.add(whiteboard);

const CAM = { theta: Math.PI / 4, phi: 1.0, radius: 19 };
function updateCamera() {
  camera.position.set(
    CAM.radius * Math.sin(CAM.phi) * Math.cos(CAM.theta),
    CAM.radius * Math.cos(CAM.phi),
    CAM.radius * Math.sin(CAM.phi) * Math.sin(CAM.theta));
  camera.lookAt(0, 1.2, 0);
}
updateCamera();

let dragging = false, dragMoved = 0, lastX = 0, lastY = 0;
renderer.domElement.addEventListener("pointerdown", e => {
  dragging = true; dragMoved = 0; lastX = e.clientX; lastY = e.clientY;
});
window.addEventListener("pointerup", () => { dragging = false; });
window.addEventListener("pointermove", e => {
  if (!dragging) return;
  const dx = e.clientX - lastX, dy = e.clientY - lastY;
  dragMoved += Math.abs(dx) + Math.abs(dy);
  lastX = e.clientX; lastY = e.clientY;
  CAM.theta += dx * 0.005;
  CAM.phi = Math.min(1.35, Math.max(0.45, CAM.phi - dy * 0.005));
  updateCamera();
});
renderer.domElement.addEventListener("wheel", e => {
  CAM.radius = Math.min(30, Math.max(10, CAM.radius + e.deltaY * 0.02));
  updateCamera();
}, { passive: true });

function wrapText(ctx, text, x, y, maxW, lh, maxLines) {
  const words = String(text || "").split(/\s+/);
  let line = "", lines = 0;
  for (let i = 0; i < words.length; i++) {
    const test = line ? line + " " + words[i] : words[i];
    if (ctx.measureText(test).width > maxW && line) {
      ctx.fillText(line, x, y + lines * lh);
      lines++;
      if (lines >= maxLines - 1) {
        ctx.fillText(line + " …", x, y + lines * lh);
        return lines + 1;
      }
      line = words[i];
    } else {
      line = test;
    }
  }
  if (line) { ctx.fillText(line, x, y + lines * lh); lines++; }
  return lines;
}

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

function animate() {
  requestAnimationFrame(animate);
  renderer.render(scene, camera);
}
animate();
```

- [ ] **Step 4: Verificación visual de la escena**

Reiniciar uvicorn (comando Task 2 Paso 5) y abrir `http://127.0.0.1:8000/office` con la skill `browse` (gstack):
- Captura: 7 escritorios con etiquetas, mesa CEO, pizarrón verde, suelo, HUD/feed en esquinas.
- Consola del navegador: sin errores (`THREE` definido, sin 404 de assets).
- Arrastrar rota la vista; rueda hace zoom.
Si hay errores de consola → corregir antes de continuar.

- [ ] **Step 5: Suite offline verde**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: 145 passed, 5 deselected.

- [ ] **Step 6: Commit**

```powershell
git add AgentBiz/backend/static/office/
git commit -m "feat(office): escena base — planta, 7 escritorios, mesa CEO, pizarron, camara orbit"
```

---

### Task 5: Polling, estados idle/working, monitores y HUD básico

**Files:**
- Modify: `AgentBiz/backend/static/office/office.js` (agregar bloques + reemplazar `animate`)

**Interfaces:**
- Consumes: `GET /api/fund/office` (Task 1), `desks`, `wrapText` (Task 4).
- Produces: `state` (último payload), `poll()`, `applyState()`, `drawMonitor(id, text, working)`; estados visuales y texto de monitores que usan Tasks 6-8; indicador `#offline`.

- [ ] **Step 1: Agregar a office.js — polling + estados**

Al final de `office.js` agregar:

```javascript
let state = null;

function drawMonitor(id, text, working) {
  const d = desks[id];
  if (!d) return;
  const ctx = d.monitorCtx;
  ctx.fillStyle = working ? "#451a03" : "#082f49";
  ctx.fillRect(0, 0, 512, 256);
  ctx.fillStyle = working ? "#fbbf24" : "#7dd3fc";
  ctx.font = "bold 34px Segoe UI";
  ctx.textAlign = "center";
  wrapText(ctx, text || "—", 256, 70, 460, 44, 4);
  d.monitorTex.needsUpdate = true;
}

function applyState() {
  if (!state) return;
  for (const a of state.agents) {
    const d = desks[a.id];
    if (!d) continue;
    const working = a.status === "working";
    d.working = working;
    d.light.color.setHex(working ? 0xfbbf24 : 0x38bdf8);
    d.light.intensity = working ? 1.8 : 0.5;
    const taskText = a.task && a.task.title ? a.task.title : "en espera";
    drawMonitor(a.id, taskText, working);
  }
}

async function poll() {
  try {
    const r = await fetch("/api/fund/office");
    if (!r.ok) throw new Error("HTTP " + r.status);
    state = await r.json();
    document.getElementById("offline").classList.add("hidden");
    applyState();
  } catch (e) {
    document.getElementById("offline").classList.remove("hidden");
  }
}
setInterval(poll, 3000);
poll();
```

- [ ] **Step 2: Reemplazar la función `animate` (bobbing del avatar working)**

Reemplazar el bloque `function animate() { ... } animate();` de Task 4 por:

```javascript
const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime();
  let i = 0;
  for (const id of AGENT_IDS) {
    const d = desks[id];
    if (d.working) {
      d.avatar.position.y = 1.05 + Math.sin(t * 6 + i) * 0.13;
    } else {
      d.avatar.position.y = 1.05;
    }
    i++;
  }
  renderer.render(scene, camera);
}
animate();
```

- [ ] **Step 3: Verificación visual de estados**

Reiniciar uvicorn (comando Task 2 Paso 5). Abrir `/office` con la skill `browse`:
1. Captura inicial: monitores con "en espera" en azul, luces azules.
2. Marcar un agente working en la BD real (una sola vez):
   `C:/Python313/python.exe -c "import sqlite3; db=sqlite3.connect(r'AgentBiz\agentbiz.db'); db.execute(\"UPDATE agents SET status='working' WHERE id='trading'\"); db.commit(); db.close()"`
3. Esperar ≤3s → captura: escritorio Trading con luz ámbar, avatar animado, monitor ámbar con texto.
4. Revertir: mismo comando con `status='idle'`.

- [ ] **Step 4: Verificación offline (Review Focus 4)**

Con la página abierta: matar uvicorn (`Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*uvicorn*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`), esperar 5s → captura: indicador "Sin conexión" visible y escena intacta. Levantar uvicorn (comando Task 2 Paso 5), esperar ≤5s → indicador desaparece solo.

- [ ] **Step 5: Suite verde + Commit**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: 145 passed, 5 deselected.

```powershell
git add AgentBiz/backend/static/office/office.js
git commit -m "feat(office): polling 3s, estados idle/working, monitores y offline indicator"
```

---

### Task 6: HUD completo (ticker/PnL/clock) + feed + pizarrón

**Files:**
- Modify: `AgentBiz/backend/static/office/office.js`

**Interfaces:**
- Consumes: `state` (fund, tickers, messages), `boardCtx/boardTex`, `wrapText` (Task 4).
- Produces: `updateHUD()`, `renderFeed()`, `drawBoard()` llamados desde `applyState` v2 — los usan Tasks 7-8 (burbujas se añaden al mismo `applyState`).

- [ ] **Step 1: Agregar funciones HUD/feed/pizarrón**

Al final de `office.js` (antes de `setInterval` si se prefiere, o al final del todo — el orden no importa porque todo se llama desde applyState) agregar:

```javascript
const TICKER_SYMS = ["BTC", "ETH", "DIA", "TSLA", "USDJPY"];
const sessionBase = {};

function updateHUD() {
  if (!state) return;
  const f = state.fund;
  document.getElementById("hud-equity").textContent =
    "Equity $" + f.equity.toFixed(2) + " · PnL día $" + f.daily_pnl.toFixed(2);
  document.getElementById("hud-dd").textContent =
    "Drawdown " + (f.drawdown * 100).toFixed(1) + "%";
  document.getElementById("hud-trades").textContent =
    "Trades " + f.trades + " · Win " + Math.round(f.win_rate * 100) + "%";
  document.getElementById("hud-phase").textContent =
    f.phase === "aggressive" ? "FASE AGRESIVA" : "FASE MODERADA";

  const parts = [];
  for (const sym of TICKER_SYMS) {
    const p = state.tickers[sym];
    if (p == null) { parts.push(sym + " —"); continue; }
    if (sessionBase[sym] == null) sessionBase[sym] = p;
    const pct = ((p - sessionBase[sym]) / sessionBase[sym]) * 100;
    const sign = pct >= 0 ? "+" : "";
    parts.push(sym + " $" + p.toFixed(2) + " (" + sign + pct.toFixed(2) + "%)");
  }
  document.getElementById("hud-ticker").textContent = parts.join("   ");
}

function feedName(id) {
  if (id === "user") return "CEO";
  return (AGENT_META[id] && AGENT_META[id].name) || id;
}

function renderFeed() {
  if (!state) return;
  const ul = document.getElementById("feed-list");
  ul.innerHTML = "";
  for (const m of state.messages) {
    const li = document.createElement("li");
    const time = String(m.created_at || "").slice(11, 16);
    li.innerHTML = '<span class="time">' + time + "</span>" +
      '<span class="who">' + feedName(m.from_agent) + " → " +
      feedName(m.to_agent) + "</span><br>";
    li.appendChild(document.createTextNode(
      String(m.content || "").slice(0, 140)));
    ul.appendChild(li);
  }
}

function drawBoard() {
  if (!state) return;
  const f = state.fund;
  boardCtx.fillStyle = "#14532d";
  boardCtx.fillRect(0, 0, 1024, 512);
  boardCtx.strokeStyle = "#bbf7d0";
  boardCtx.lineWidth = 6;
  boardCtx.strokeRect(10, 10, 1004, 492);
  boardCtx.fillStyle = "#ecfdf5";
  boardCtx.textAlign = "left";
  boardCtx.font = "bold 58px Segoe UI";
  boardCtx.fillText("SEGUNDO CEREBRO CAPITAL", 50, 90);
  boardCtx.font = "46px Segoe UI";
  boardCtx.fillText("ESTRATEGIA: " + (f.strategy || "—"), 50, 180);
  boardCtx.fillText("FASE: " + (f.phase === "aggressive" ? "AGRESIVA" : "MODERADA"), 50, 260);
  boardCtx.fillText("META: $" + Number(f.target).toLocaleString("es-VE"), 50, 340);
  boardCtx.fillStyle = f.daily_stop_hit ? "#fca5a5" : "#bbf7d0";
  boardCtx.fillText("DRAWDOWN: " + (f.drawdown * 100).toFixed(1) + "%", 50, 430);
  boardTex.needsUpdate = true;
}

setInterval(() => {
  document.getElementById("hud-clock").textContent =
    "NY " + new Date().toLocaleTimeString("es-VE",
      { timeZone: "America/New_York", hour12: false });
}, 1000);
```

- [ ] **Step 2: Reemplazar `applyState` (v2: estados + HUD + feed + pizarrón)**

Reemplazar la función `applyState` completa por:

```javascript
function applyState() {
  if (!state) return;
  for (const a of state.agents) {
    const d = desks[a.id];
    if (!d) continue;
    const working = a.status === "working";
    d.working = working;
    d.light.color.setHex(working ? 0xfbbf24 : 0x38bdf8);
    d.light.intensity = working ? 1.8 : 0.5;
    const taskText = a.task && a.task.title ? a.task.title : "en espera";
    drawMonitor(a.id, taskText, working);
  }
  updateHUD();
  renderFeed();
  drawBoard();
}
```

- [ ] **Step 3: Verificación visual**

Reiniciar uvicorn (comando Task 2 Paso 5). Abrir `/office` con `browse`:
- HUD: ticker con 5 símbolos (o "—" si un precio falla), equity, drawdown, trades, fase, reloj NY avanzando.
- Feed: lista de mensajes (o vacío si la BD no tiene).
- Pizarrón: texto legible (Estrategia/Fase/Meta $5.000/Drawdown).
- Si `state.fund.strategy` es null debe mostrar "—", sin error de consola.

- [ ] **Step 4: Suite verde + Commit**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: 145 passed, 5 deselected.

```powershell
git add AgentBiz/backend/static/office/office.js
git commit -m "feat(office): HUD con ticker/PnL/reloj NY, feed lateral y pizarron dinamico"
```

---

### Task 7: Burbujas de habla + líneas inter-departamento

**Files:**
- Modify: `AgentBiz/backend/static/office/office.js`

**Interfaces:**
- Consumes: `state.messages`, `desks`, `AGENT_IDS`, `feedName`, `wrapText`; `makeLabel` de Task 4 (reutiliza el patrón CanvasTexture, pero con función propia `makeBubble`).
- Produces: `updateBubbles()` + `updateLine()` invocados desde `applyState` v3; sprite `bubble` global y grupo `lineGroup` (Task 8 no los toca).

- [ ] **Step 1: Agregar burbuja y línea**

Al final de `office.js` agregar:

```javascript
let bubble = null;
let bubbleMsgId = 0;
let bubbleUntil = 0;

function makeBubble(text) {
  const c = document.createElement("canvas");
  c.width = 640; c.height = 320;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "rgba(248, 250, 252, 0.95)";
  ctx.beginPath();
  ctx.roundRect ? ctx.roundRect(0, 0, 640, 320, 28) : ctx.rect(0, 0, 640, 320);
  ctx.fill();
  ctx.fillStyle = "#0f172a";
  ctx.font = "36px Segoe UI";
  ctx.textAlign = "center";
  const clipped = String(text || "").slice(0, 90);
  wrapText(ctx, clipped, 320, 80, 560, 46, 5);
  const tex = new THREE.CanvasTexture(c);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true }));
  sp.scale.set(4.4, 2.2, 1);
  return sp;
}

function updateBubbles(now) {
  if (!state) return;
  const newest = state.messages.find(m =>
    AGENT_IDS.includes(m.from_agent) && m.content);
  if (newest && newest.id !== bubbleMsgId) {
    bubbleMsgId = newest.id;
    if (bubble) { scene.remove(bubble); bubble = null; }
    bubble = makeBubble(newest.content);
    const d = desks[newest.from_agent];
    bubble.position.set(d.group.position.x, 3.9, d.group.position.z);
    scene.add(bubble);
    bubbleUntil = now + 6000;
  }
  if (bubble && now > bubbleUntil) {
    scene.remove(bubble);
    bubble = null;
  }
}

let lineMesh = null;
let lineTraveler = null;
let lineMsgId = 0;
const lineState = { from: null, to: null };

function updateLine(now) {
  if (!state) return;
  const m = state.messages.find(x =>
    AGENT_IDS.includes(x.from_agent) && AGENT_IDS.includes(x.to_agent) &&
    x.from_agent !== x.to_agent);
  if (!m) {
    if (lineMesh) { scene.remove(lineMesh); lineMesh = null; }
    if (lineTraveler) { scene.remove(lineTraveler); lineTraveler = null; }
    lineMsgId = 0;
    return;
  }
  if (m.id !== lineMsgId) {
    lineMsgId = m.id;
    if (lineMesh) { scene.remove(lineMesh); lineMesh = null; }
    if (lineTraveler) { scene.remove(lineTraveler); lineTraveler = null; }
    const a = desks[m.from_agent].group.position;
    const b = desks[m.to_agent].group.position;
    lineState.from = new THREE.Vector3(a.x, 2.2, a.z);
    lineState.to = new THREE.Vector3(b.x, 2.2, b.z);
    const geo = new THREE.BufferGeometry().setFromPoints(
      [lineState.from, lineState.to]);
    lineMesh = new THREE.Line(geo,
      new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.75 }));
    scene.add(lineMesh);
    lineTraveler = new THREE.Mesh(
      new THREE.SphereGeometry(0.14, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0x7dd3fc }));
    scene.add(lineTraveler);
  }
  if (lineMesh && lineTraveler && lineState.from) {
    const t = (now % 2000) / 2000;
    lineTraveler.position.lerpVectors(lineState.from, lineState.to, t);
  }
}
```

- [ ] **Step 2: Reemplazar `applyState` (v3: + burbujas + línea)**

Reemplazar la función `applyState` completa por:

```javascript
function applyState() {
  if (!state) return;
  for (const a of state.agents) {
    const d = desks[a.id];
    if (!d) continue;
    const working = a.status === "working";
    d.working = working;
    d.light.color.setHex(working ? 0xfbbf24 : 0x38bdf8);
    d.light.intensity = working ? 1.8 : 0.5;
    const taskText = a.task && a.task.title ? a.task.title : "en espera";
    drawMonitor(a.id, taskText, working);
  }
  updateHUD();
  renderFeed();
  drawBoard();
  updateBubbles(Date.now());
  updateLine(Date.now());
}
```

- [ ] **Step 3: Verificación visual (incluye Review Focus 2)**

Reiniciar uvicorn (comando Task 2 Paso 5). Abrir `/office` con `browse`:
1. Insertar mensaje inter-dept vía API real:
   `& C:\Windows\System32\curl.exe -s -X POST http://127.0.0.1:8000/api/messages -H "Content-Type: application/json" -d "{\"from_agent\":\"scout\",\"to_agent\":\"analytics\",\"content\":\"BTC rompe resistencia\"}"`
2. Esperar ≤3s → captura: línea cian animada entre escritorios de Scout y Analytics; burbuja sobre Scout con el texto; feed lo lista.
3. Insertar mensaje a `user` (como el chat): mismo curl con `"to_agent":"user"` → **no** debe aparecer línea (sin escritorio fantasma) pero sí en feed y burbuja si `from_agent` es agente.
4. Esperar 6s → burbuja desaparece; la línea permanece mientras ese sea el inter-dept más reciente.

- [ ] **Step 4: Suite verde + Commit**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: 145 passed, 5 deselected.

```powershell
git add AgentBiz/backend/static/office/office.js
git commit -m "feat(office): burujas de habla 6s y lineas animadas inter-departamento"
```

---

### Task 8: Panel de chat por clic en escritorios

**Files:**
- Modify: `AgentBiz/backend/static/office/office.js`

**Interfaces:**
- Consumes: raycaster sobre `desks[*].group` (userData.agentId de Task 4), `state.messages` (historial, Task 3 lo alimenta), `POST /api/chat/{id}` (`{"query": str}` → `{response}`), `AGENT_META`, `feedName`.
- Produces: `openChat(id)`, `sendChat(query)` — fin del flujo de usuario; sin dependencias posteriores.

- [ ] **Step 1: Agregar panel de chat + raycaster**

Al final de `office.js` agregar:

```javascript
const chatPanel = document.getElementById("chat-panel");
const chatLog = document.getElementById("chat-log");
const chatInput = document.getElementById("chat-input");
const chatSend = document.getElementById("chat-send");
const chatStatus = document.getElementById("chat-status");
let currentChat = null;

function chatBubbleRow(cls, text) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

function openChat(id) {
  currentChat = id;
  const meta = AGENT_META[id];
  document.getElementById("chat-title").textContent =
    meta.emoji + " " + meta.name + " — " + meta.role;
  chatLog.innerHTML = "";
  chatStatus.textContent = "";
  if (state) {
    const hist = state.messages
      .filter(m => m.from_agent === id || m.to_agent === id)
      .slice(0, 10)
      .reverse();
    for (const m of hist) {
      const mine = m.to_agent === id && m.from_agent === "user";
      chatBubbleRow(mine ? "mine" : "theirs",
        (mine ? "Tú: " : feedName(m.from_agent) + ": ") + m.content);
    }
  }
  chatPanel.classList.remove("hidden");
  chatInput.focus();
}

document.getElementById("chat-close").addEventListener("click", () => {
  chatPanel.classList.add("hidden");
  currentChat = null;
});

async function sendChat(query) {
  chatSend.disabled = true;
  chatStatus.style.color = "#7dd3fc";
  chatStatus.textContent = "Pensando… (hasta 60 s)";
  chatBubbleRow("mine", "Tú: " + query);
  try {
    const r = await fetch("/api/chat/" + currentChat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    chatBubbleRow("theirs", AGENT_META[currentChat].name + ": " + d.response);
    chatStatus.textContent = "";
  } catch (e) {
    chatStatus.style.color = "#f87171";
    chatStatus.textContent = "No se pudo enviar: " + e.message;
  } finally {
    chatSend.disabled = false;
    chatInput.value = "";
    chatInput.focus();
  }
}

document.getElementById("chat-form").addEventListener("submit", e => {
  e.preventDefault();
  const q = chatInput.value.trim();
  if (!q || chatSend.disabled || !currentChat) return;
  sendChat(q);
});

renderer.domElement.addEventListener("click", () => {
  if (dragMoved > 6) return;
  const ndc = new THREE.Vector2(
    (lastX / window.innerWidth) * 2 - 1,
    -(lastY / window.innerHeight) * 2 + 1);
  const ray = new THREE.Raycaster();
  ray.setFromCamera(ndc, camera);
  const hits = ray.intersectObjects(
    Object.values(desks).map(d => d.group), true);
  if (hits.length) {
    const id = hits[0].object.userData.agentId;
    if (id) openChat(id);
  }
});
```

- [ ] **Step 2: Verificación visual y funcional**

Reiniciar uvicorn (comando Task 2 Paso 5). Abrir `/office` con `browse`:
1. Clic en escritorio Trading → panel abre con título correcto, historial (o vacío).
2. Escribir "di hola" → Enviar → spinner "Pensando…" → respuesta del LLM en ≤60s en el panel (verificación real, costo mínimo).
3. Tras el próximo poll (≤3s): la respuesta aparece en feed y como burbuja sobre Trading (flujo Task 3→7).
4. Clic en la X → panel cierra.
5. **Review Focus 3 (error):** cerrar uvicorn, escribir mensaje → estado rojo "No se pudo enviar: HTTP…"-o-fetch-fail, botón se reactiva; el resto de la página sigue con "Sin conexión" sin romperse. Levantar uvicorn de nuevo.
6. Arrastrar sobre un escritor NO abre el panel (dragMoved > 6).

- [ ] **Step 3: Suite verde + Commit**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: 145 passed, 5 deselected.

```powershell
git add AgentBiz/backend/static/office/office.js
git commit -m "feat(office): panel de chat por clic (raycaster) con estados de carga/error"
```

---

### Task 9: QA visual (design-review), regresión total y cierre

**Files:**
- Modify: posibles arreglos de `office.css` / `office.js` / `index.html` según hallazgos
- Modify: `AgentBiz/backend/static/office/*` solo si design-review encuentra issues

**Interfaces:**
- Consumes: TODO de Tasks 1-8 funcionando en servidor reiniciado con código nuevo.
- Produces: página pulida, suite completa verde, trabajo terminado.

- [ ] **Step 1: Correr la skill `design-review` (gstack)**

Abrir `http://127.0.0.1:8000/office` con la skill `design-review`: QA de inconsistencia visual, jerarquía, espaciado, legibilidad del HUD/feed/panel, y sensación de interacción (colores de estado, contraste del pizarrón). Aplicar los arreglos que la skill recomiende directamente en `office.css`/`office.js`.

- [ ] **Step 2: Regresión total de backend**

Reiniciar uvicorn (comando Task 2 Paso 5) y verificar:
- `& C:\Windows\System32\curl.exe -s -o NUL -w "status [HTTP %{http_code}]" http://127.0.0.1:8000/api/fund/status` → 200
- `& C:\Windows\System32\curl.exe -s -o NUL -w "office [HTTP %{http_code}]" http://127.0.0.1:8000/office` → 200
- `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q` → 145 passed, 5 deselected
- Con keys: `$env:BINANCE_TESTNET_KEY=(Select-String -Path .env -Pattern "^BINANCE_TESTNET_KEY=").Line.Substring(20); $env:BINANCE_TESTNET_SECRET=(Select-String -Path .env -Pattern "^BINANCE_TESTNET_SECRET=").Line.Substring(23); C:/Python313/python.exe -m pytest AgentBiz/tests/test_binance_network.py -q` → 2 passed

- [ ] **Step 3: Commit final**

```powershell
git add AgentBiz/backend/static/office/
git commit -m "style(office): ajustes de QA visual (design-review)"
```
(Si no hay cambios, omitir este commit.)

- [ ] **Step 4: Ledger de sesión**

Agregar al final de `.superpowers/sdd/2026-10-02-binance-ejecucion-auto-plan/progress.md`:
`OFICINA 3D construida (spec 2026-10-02-oficina-3d-design.md): endpoint /api/fund/office, /office estatico con three.js r128 local, estados/burbujas/lineas/HUD/feed/chat por clic. Suite offline 145 + red 2.`

---

## Self-Review (del plan)

1. **Spec coverage:** §3 endpoint → Task 1 (incl. N+1 y tolerancias); §4 serving/three local → Task 2; §6 chat insert → Task 3; §5 escena → Task 4; estados+polling+offline → Task 5; HUD+feed+pizarrón → Task 6; burbujas+líneas → Task 7; panel chat → Task 8; §7 QA design-review + regresión → Task 9; §7 tests (5 casos) → Tests de Tasks 1-3. Sin gaps.
2. **Placeholder scan:** todo paso trae código o comando exacto; sin "TBD"/"similar to".
3. **Type consistency:** `applyState` se reemplaza en Tasks 5/6/7 con versiones completas (v1→v3); nombres (`desks[id].monitorTex`, `wrapText`, `state.messages`, `AGENT_IDS`, `feedName`, `chatBubbleRow`) definidos en el task que los introduce y usados igual después. `makeLabel` (Task 4) ≠ `makeBubble` (Task 7), intencional.
4. **Review Focus:** 5 líneas, cada una con test/paso dueño en su task (Tasks 1, 7, 8, 5, 2 respectivamente).
