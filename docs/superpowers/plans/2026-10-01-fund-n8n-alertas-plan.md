# Segundo Cerebro Capital — Fase 5: n8n v2 + Alerta Diaria — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** API de marcado a mercado (`POST /api/fund/mark`), reemplazo del workflow n8n unificado por v2 con intenciones de fondo, y workflow de reporte diario 8:00 AM + scan corto cada 4h con alertas a Telegram.

**Architecture:** Backend FastAPI añade un endpoint síncrono-en-hilo que obtiene precios reales (yfinance/ccxt) y ejecuta `Portfolio.mark_to_market()` + `record_equity()`. Sobre n8n se crean 2 workflows versionados: el v2 del webhook unificado (detección de intención por código + IF-chain a `/api/fund/*`, trading y chat, con rama research que responde antes de lanzar el ciclo) y el reporte diario (cron 4h + webhook manual, que marca a mercado, arma contexto, formatea con `social` y envía por Telegram).

**Tech Stack:** FastAPI + SQLite (`fund.db`), `paper_portfolio.py`, `market_data.py` (yfinance/ccxt), n8n public API (workflows vía JSON), nodos `httpRequest` 4.2 / `if` 2.2 / `code` 2 / `scheduleTrigger` 1.2 / `webhook` 2, Telegram Bot HTTP API, NVIDIA NIM.

**Spec:** `docs/superpowers/specs/2026-09-30-segundo-cerebro-capital-design.md` (§7 Integración n8n, §9 fila 5 "n8n v2 + alerta diaria", §4 SL/TP con marcado a mercado) + ruling I6 del ledger del Plan 2 (llamada de `mark_to_market` en producción → cron n8n).

## Global Constraints

- Local Windows: n8n :5678, AgentBiz :8000 (corriendo desde `AgentBiz\backend`), Trader API :5001.
- Regresión permanente (spec §9): webhook unificado (ramas trading + negocio) y chat con agentes deben seguir OK tras cada fase.
- Modelos NVIDIA NIM con fallback (nemotron default); `NVIDIA_API_KEY` vive en `.env` (gitignored).
- PowerShell: sin `&&`; JSON siempre `[IO.File]::WriteAllText` (SIN BOM) + `--data-binary @archivo`; `PYTHONUTF8=1`; curl = `C:\Windows\System32\curl.exe`.
- n8n public API: header `X-N8N-API-KEY` = valor de `N8N_JWT` en `.env` (la env var `N8N_API_KEY` de n8n NO funciona).
- **Todo nodo webhook DEBE llevar `webhookId` único**; sin él, `/webhook/<path>` devuelve 404 aunque el workflow esté activo (verificado empíricamente 2026-10-01; v1 usa `segundo-cerebro-unified`).
- Executions API: `GET /api/v1/executions?workflowId=<id>&limit=N` (parámetro `filter` NO existe) y `GET /api/v1/executions/<id>?includeData=true` → `data.resultData.runData` = nombres de nodos ejecutados (verificado).
- Credenciales de n8n vía API restringidas (400 `req.body.type is not a known type`) → Telegram se integra con nodo HTTP y token en la URL.
- Secretos NUNCA en git: el plan usa el marcador `__TELEGRAM_TOKEN__` sustituido desde `.env` antes de crear workflows; exports a `.superpowers/n8n-exports/` (gitignored). El JWT de n8n no aparece en este documento.
- Ejecución nativa en main (ruling heredado de Plan 1/2), método aprobado por Carlos.
- Payloads de prueba con `--data-binary @archivo` (nunca `-d` con acentos).

## Review Focus

1. **Precio no disponible para un símbolo en `/mark`** → el endpoint marca las posiciones que sí tienen precio, responde 200 y las demás quedan intactas — test `test_mark_tolerates_price_failure` (Task 1).
2. **El marcado toca el SL** → cierre automático con trade registrado `reason="sl"` y `exit` al precio del SL — test `test_mark_closes_position_at_sl` (Task 1).
3. **"investiga estrategias"** → el webhook responde en <10s con `status:lanzado` y el ciclo corre después (patrón W→R→HTTP verificado empíricamente) — cronómetro + `status=running` en executions (Task 2).
4. **Matriz de intenciones**: `señales del fondo`→`/api/fund/status` (nuevo, manda spec), `analiza bitcoin`→trading, `háblame de scout`→chat — 7 payloads con esperado (Task 2).
5. **Doble mensaje a las 8:00 y scan en moderada** → `force:mañana` ejercita la rama completa; en fase `moderate` la ejecución termina sin nodo de Telegram — `runData` sin `Enviar Telegram (scan)` (Task 3).

---

### Task 1: Endpoint `POST /api/fund/mark`

**Files:**
- Modify: `AgentBiz/backend/api/fund.py` (import + endpoint nuevo)
- Test: `AgentBiz/tests/test_fund_api.py` (4 tests nuevos)

**Interfaces:**
- Consumes: `paper_portfolio.Portfolio.get_positions(status="open") -> list[dict]` (cols incl. `symbol`), `Portfolio.mark_to_market(prices: dict, bars=None) -> list[dict]` (cierra SL/TP y actualiza `unrealized`; `prices` es `{symbol: float}`), `Portfolio.record_equity() -> float`, `Portfolio.get_status() -> dict`, `market_data.get_price(symbol) -> float`.
- Produces: `POST /api/fund/mark` → `{"marked": int, "open": int, "closed": list[dict], "failed": list[str], "status": dict}` — lo consume el nodo "Marcar a Mercado" del Task 3. (`failed` = símbolos sin precio; `RiskError` concurrente → 409.)

- [ ] **Step 1: Escribir los tests fallando**

Añadir a `AgentBiz/tests/test_fund_api.py`:

```python
def test_mark_updates_unrealized_and_curve(client, monkeypatch):
    import api.fund as fmod
    r0 = client.post("/api/fund/orders", json=_open_order())
    assert r0.status_code == 200
    before = client.get("/api/fund/performance").json()
    monkeypatch.setattr(fmod, "get_price", lambda sym: 105.0)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    d = r.json()
    assert d["marked"] == 1 and d["open"] == 1 and d["closed"] == []
    pf = client.get("/api/fund/portfolio").json()
    assert abs(pf["positions"][0]["unrealized"] - 30.0) < 0.01
    after = client.get("/api/fund/performance").json()
    assert len(after["curve"]) == len(before["curve"]) + 1
    assert after["equity"] == 2530.0


def test_mark_closes_position_at_sl(client, monkeypatch):
    import api.fund as fmod
    client.post("/api/fund/orders", json=_open_order())  # entry 100, sl 95, tp 110
    monkeypatch.setattr(fmod, "get_price", lambda sym: 90.0)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    d = r.json()
    assert d["open"] == 0 and len(d["closed"]) == 1
    pf = client.get("/api/fund/portfolio").json()
    assert pf["status"]["open_positions"] == 0
    tr = pf["trades"][0]
    assert tr["reason"] == "sl" and tr["exit"] == 95.0


def test_mark_without_positions_records_curve(client):
    before = client.get("/api/fund/performance").json()
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    d = r.json()
    assert d["marked"] == 0 and d["closed"] == []
    after = client.get("/api/fund/performance").json()
    assert len(after["curve"]) == len(before["curve"]) + 1


def test_mark_tolerates_price_failure(client, monkeypatch):
    import api.fund as fmod
    client.post("/api/fund/orders", json=_open_order())

    def boom(sym):
        raise RuntimeError("sin red")

    monkeypatch.setattr(fmod, "get_price", boom)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    assert r.json()["marked"] == 0
    pf = client.get("/api/fund/portfolio").json()
    assert pf["status"]["open_positions"] == 1
```

- [ ] **Step 2: Correr los tests y verlos fallar**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest AgentBiz/tests/test_fund_api.py -k mark -q` (desde la raíz)
Expected: **4 failed** con `404 Not Found` (el endpoint no existe).

- [ ] **Step 3: Implementar el endpoint**

En `AgentBiz/backend/api/fund.py`: añadir import `from market_data import get_price` (junto a los imports existentes) y este endpoint (usar `asyncio.to_thread` en TODO — regla I1; los precios se obtienen por posición tolerando fallos individuales). Ruling ejecución: siembra de línea base en la curva (el test 4 no podía pasar sin ella) + `failed` + 409 en `RiskError` + sin punto de curva si todas las cotizaciones fallan:

```python
@router.post("/mark")
async def fund_mark():
    def work():
        p = _pf()
        if not p.get_equity_curve():
            p.record_equity()  # linea base: capital inicial antes del 1er marcado
        positions = p.get_positions("open")
        prices = {}
        failed = []
        marked = 0
        for pos in positions:
            sym = pos["symbol"]
            try:
                prices[sym] = get_price(sym)
                marked += 1
            except Exception:
                if sym not in failed:
                    failed.append(sym)
        try:
            closed = p.mark_to_market(prices)
        except RiskError as e:
            raise HTTPException(status_code=409, detail=str(e))
        if prices or not positions:
            p.record_equity()
        st = p.get_status()
        return {"marked": marked, "open": st["open_positions"],
                "closed": closed, "failed": failed, "status": st}
    return await asyncio.to_thread(work)
```

- [ ] **Step 4: Correr los tests y verlos pasar**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest AgentBiz/tests/test_fund_api.py -q`
Expected: **todos pass** (los existentes + 4 nuevos).

- [ ] **Step 5: Suite completa + commit**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: **80 passed** (76 + 4), 3 deselected.

```bash
git add AgentBiz/backend/api/fund.py AgentBiz/tests/test_fund_api.py
git commit -m "feat: POST /api/fund/mark — marcado a mercado con precios reales y curva de equity"
```

---

### Task 2: Workflow "Sistema Unificado v2" (reemplaza al v1 `rd6Io093fYW0yLgA`)

**Files:**
- Create (runtime): workflow n8n "Sistema Unificado v2"
- Create (local, gitignored): `.superpowers/n8n-exports/sistema-unificado-v1.json` (backup) y `sistema-unificado-v2.json`
- No cambios en el repo → sin commit en este task.

**Interfaces:**
- Consumes: `GET /api/fund/{status,portfolio,performance,strategies}` (query param `endpoint` detectado), `POST /api/trading/ai`, `POST /api/chat/{agent}` (body `{"query": ...}`), `POST /api/fund/research` (body `{"period":"1y"}`).
- Produces: webhook `POST http://localhost:5678/webhook/unified` con respuestas JSON de cada rama; rama research responde `{"status":"lanzado",...}` y dispara `Lanzar Research` en segundo plano.

**Rulings:**
- `señal/señales` migra de la rama trading a `/api/fund/*` (manda spec §7); `btc/precio/analiza/...` sigue en trading (regresión intacta).
- Borrado de v1 SOLO después de pasar la matriz (antes solo desactivado → rollback = reactivarlo).

- [ ] **Step 1: Backup del v1 y JWT listo**

```powershell
New-Item -ItemType Directory -Force -Path ".superpowers\n8n-exports" | Out-Null
$jwt = ((Get-Content .env | Where-Object { $_ -like 'N8N_JWT=*' }) -replace '^N8N_JWT=', '')
C:\Windows\System32\curl.exe -s -m 15 -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/workflows/rd6Io093fYW0yLgA" -o ".superpowers\n8n-exports\sistema-unificado-v1.json"
```
Expected: archivo creado, contiene `"name": "Sistema Unificado v1"`.

- [ ] **Step 2: Escribir el JSON del v2 (temp, sin BOM) y validar**

Guardar el bloque JSON de abajo ("Workflow JSON — Sistema Unificado v2") en `$env:TEMP\opencode\wf_v2.json` usando `[IO.File]::WriteAllText`, luego validar:

```powershell
$wf = Get-Content "$env:TEMP\opencode\wf_v2.json" -Raw | ConvertFrom-Json
"nodos: $($wf.nodes.Count)"   # esperado: 11
```
Expected: `nodos: 11` (error de parseo = JSON mal copiado; corregir antes de seguir).

- [ ] **Step 3: Crear v2, desactivar v1, activar v2**

```powershell
$r = C:\Windows\System32\curl.exe -s -m 15 -X POST -H "X-N8N-API-KEY: $jwt" -H "Content-Type: application/json" --data-binary "@$env:TEMP\opencode\wf_v2.json" "http://localhost:5678/api/v1/workflows"
$v2id = ($r | ConvertFrom-Json).id
C:\Windows\System32\curl.exe -s -m 15 -X POST -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/workflows/rd6Io093fYW0yLgA/deactivate" -o $null -w "v1 deactivate %{http_code}`n"
C:\Windows\System32\curl.exe -s -m 15 -X POST -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/workflows/$v2id/activate" -o $null -w "v2 activate %{http_code}`n"
```
Expected: `v1 deactivate 200`, `v2 activate 200`, `$v2id` con valor.

- [ ] **Step 4: Matriz de intenciones (7 payloads)**

Escribir cada mensaje a su archivo con `[IO.File]::WriteAllText("$env:TEMP\opencode\m.json", '{"message":"..."}')` y llamar `C:\Windows\System32\curl.exe -s -m 60 -X POST -H "Content-Type: application/json" --data-binary "@$env:TEMP\opencode\m.json" http://localhost:5678/webhook/unified`:

| # | message (payload) | Esperado en respuesta |
|---|---|---|
| 1 | `estado del fondo` | JSON con `"portfolio"` y `"equity"` |
| 2 | `señales del fondo` | JSON con `"signals"` |
| 3 | `portafolio` | JSON con `"positions"` |
| 4 | `ganadora` | JSON con `"standard"` |
| 5 | `analiza bitcoin` | `"response"` con análisis de la rama **trading** (regresión) |
| 6 | `háblame de scout` | `"response"` del agente **scout** (regresión negocio) |
| 7 | `investiga estrategias` | `"status":"lanzado"` y `time_total` **< 10s** (`-w "\|%{time_total\}"`) |

Cualquier 404 → revisar `webhookId` y activación. Cualquier fallo en 5/6 → rollback (Step 7).

- [ ] **Step 5: Verificar que research corre DESPUÉS de la respuesta**

(~15s tras el payload 7):

```powershell
$ex = C:\Windows\System32\curl.exe -s -m 15 -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/executions?limit=1&workflowId=$v2id" | ConvertFrom-Json
$ex.data[0].status   # esperado: "running" (el ciclo dura ~9 min)
```
Expected: `running` (si fuera `success` de inmediato, research no corrió → investigar nodo `Lanzar Research`).

- [ ] **Step 6: Export del v2 + borrar v1**

```powershell
C:\Windows\System32\curl.exe -s -m 15 -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/workflows/$v2id" -o ".superpowers\n8n-exports\sistema-unificado-v2.json"
C:\Windows\System32\curl.exe -s -m 15 -X DELETE -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/workflows/rd6Io093fYW0yLgA" -o $null -w "v1 delete %{http_code}`n"
```
Expected: `v1 delete 200` y los 2 exports en `.superpowers\n8n-exports\`.

- [ ] **Step 7: Rollback (SOLO si falla Step 4/5)**

```powershell
C:\Windows\System32\curl.exe -s -m 15 -X DELETE -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/workflows/$v2id" -o $null
$body = Get-Content ".superpowers\n8n-exports\sistema-unificado-v1.json" -Raw
[IO.File]::WriteAllText("$env:TEMP\opencode\wf_v1_restore.json", $body)
$r1 = C:\Windows\System32\curl.exe -s -m 15 -X POST -H "X-N8N-API-KEY: $jwt" -H "Content-Type: application/json" --data-binary "@$env:TEMP\opencode\wf_v1_restore.json" "http://localhost:5678/api/v1/workflows"
$old = ($r1 | ConvertFrom-Json).id
C:\Windows\System32\curl.exe -s -m 15 -X POST -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/workflows/$old/activate" -o $null
```
(Nota: al importar de export, el `id` es nuevo; usar el retornado.)

- [ ] **Step 8: Ledger — ruling n8n v2**

Añadir a `.superpowers/sdd/2026-10-01-fund-n8n-alertas-plan/progress.md`:
`Task 2: complete (workflow id <v2id>; rulings: señales→fondo per spec §7; v1 borrado tras matriz OK; exports en .superpowers/n8n-exports/; research respondió <10s y corrió en background).`

---

### Task 3: Workflow "Reporte Diario Fondo" (cron 4h + manual)

**Files:**
- Create (runtime): workflow n8n "Reporte Diario Fondo"
- Create (local, gitignored): `.superpowers/n8n-exports/reporte-diario.json`
- No cambios en el repo → sin commit en este task.

**Interfaces:**
- Consumes: `POST /api/fund/mark` (Task 1), `GET /api/fund/status`, `POST /api/chat/scout`, `POST /api/chat/social`, Telegram `POST https://api.telegram.org/bot<token>/sendMessage` (`chat_id: 671160911`).
- Produces: cron `0 0,4,8,12,16,20 * * *` (America/Caracas) y webhook manual `POST http://localhost:5678/webhook/reporte-manual` (body opcional `{"force":"mañana"}`).

**Rulings:**
- I6 (Plan 2) cumplido: `Marcar a Mercado` corre en CADA disparo (cron y manual) antes del reporte.
- A las 8:00 se envía SOLO el reporte completo (el IF evita doble mensaje); el scan de 4h solo existe en fase `aggressive` (spec §7).
- `settings.timezone = America/Caracas` obligatorio ( `$now.hour` y el cron dependen de él).

- [ ] **Step 1: Escribir el JSON con el token sustituido (temp, sin BOM)**

```powershell
$token = ((Get-Content .env | Where-Object { $_ -like 'TELEGRAM_TOKEN=*' }) -replace '^TELEGRAM_TOKEN=', '')
$raw = Get-Content "docs\superpowers\plans\2026-10-01-fund-n8n-alertas-plan.md" -Raw
# extraer el bloque ```json bajo "Workflow JSON — Reporte Diario Fondo" entre los marcadores
$m = [regex]::Match($raw, '(?s)Workflow JSON — Reporte Diario Fondo ```json\r?\n(.*?)\r?\n```')
$json = $m.Groups[1].Value.Replace('__TELEGRAM_TOKEN__', $token)
[IO.File]::WriteAllText("$env:TEMP\opencode\wf_diario.json", $json)
$wf = Get-Content "$env:TEMP\opencode\wf_diario.json" -Raw | ConvertFrom-Json
"nodos: $($wf.nodes.Count)"   # esperado: 13
```
Expected: `nodos: 13`; falla = bloque mal extraído o JSON inválido.

- [ ] **Step 2: Crear y activar**

```powershell
$jwt = ((Get-Content .env | Where-Object { $_ -like 'N8N_JWT=*' }) -replace '^N8N_JWT=', '')
$r = C:\Windows\System32\curl.exe -s -m 15 -X POST -H "X-N8N-API-KEY: $jwt" -H "Content-Type: application/json" --data-binary "@$env:TEMP\opencode\wf_diario.json" "http://localhost:5678/api/v1/workflows"
$repId = ($r | ConvertFrom-Json).id
C:\Windows\System32\curl.exe -s -m 15 -X POST -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/workflows/$repId/activate" -o $null -w "activate %{http_code}`n"
```
Expected: `activate 200`.

- [ ] **Step 3: Test A — ejecución manual (scan corto) + marcado**

```powershell
[IO.File]::WriteAllText("$env:TEMP\opencode\manual.json", '{}')
C:\Windows\System32\curl.exe -s -m 60 -X POST -H "Content-Type: application/json" --data-binary "@$env:TEMP\opencode\manual.json" "http://localhost:5678/webhook/reporte-manual" -w "|HTTP %{http_code}"
Start-Sleep -Seconds 45
$ex = C:\Windows\System32\curl.exe -s -m 15 -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/executions?limit=1&workflowId=$repId" | ConvertFrom-Json
$eid = $ex.data[0].id; $ex.data[0].status
$det = C:\Windows\System32\curl.exe -s -m 15 -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/executions/$eid?includeData=true" | ConvertFrom-Json
$runNodes = $det.data.resultData.runData.PSObject.Properties.Name
$runNodes -join ' -> '
```
Expected: webhook `HTTP 200` (respuesta onReceived), status `success`, y en `runNodes` aparecen: `Origen`, `Marcar a Mercado`, `Obtener Estado`, `Armar Contexto`, `¿Mañana?`, `¿Agresiva?`, `Escaneo Corto`, `Enviar Telegram (scan)`. Además `GET /api/fund/performance` debe mostrar la curva +1 punto (marcado ejecutado) y **llega mensaje de scan al Telegram** (Carlos lo confirma).

- [ ] **Step 4: Test B — rama de 8:00 con `force:mañana`**

```powershell
[IO.File]::WriteAllText("$env:TEMP\opencode\manual2.json", '{"force":"mañana"}')
C:\Windows\System32\curl.exe -s -m 60 -X POST -H "Content-Type: application/json" --data-binary "@$env:TEMP\opencode\manual2.json" "http://localhost:5678/webhook/reporte-manual" -w "|HTTP %{http_code}"
Start-Sleep -Seconds 60
# misma consulta de executions que Step 3
```
Expected: status `success` y `runNodes` incluye `Escaneo Scout`, `Formatear Social`, `Enviar Telegram (reporte)` (y NO `Escaneo Corto`); **llega el reporte completo** con la línea `Fase: aggressive` (Carlos confirma).

- [ ] **Step 5: Test C — en fase moderate NO hay scan**

```powershell
C:\Windows\System32\curl.exe -s -m 30 -X POST -H "Content-Type: application/json" -d '{"phase":"moderate"}' "http://127.0.0.1:8000/api/fund/phase"
C:\Windows\System32\curl.exe -s -m 60 -X POST -H "Content-Type: application/json" --data-binary "@$env:TEMP\opencode\manual.json" "http://localhost:5678/webhook/reporte-manual" -w "|HTTP %{http_code}"
Start-Sleep -Seconds 30
# consulta de executions: runNodes esperado termina en ¿Agresiva? SIN ningún nodo "Enviar Telegram"
C:\Windows\System32\curl.exe -s -m 30 -X POST -H "Content-Type: application/json" -d '{"phase":"aggressive"}' "http://127.0.0.1:8000/api/fund/phase"
```
Expected: status `success`, `runNodes` contiene `¿Agresiva?` y NO contiene `Enviar Telegram (scan)`; phase restaurada a `aggressive` (GET /api/fund/status lo confirma). **No llega mensaje** en este test (Carlos confirma).

- [ ] **Step 6: Verificar cron + timezone en el export**

```powershell
C:\Windows\System32\curl.exe -s -m 15 -H "X-N8N-API-KEY: $jwt" "http://localhost:5678/api/v1/workflows/$repId" -o ".superpowers\n8n-exports\reporte-diario.json"
$exp = Get-Content ".superpowers\n8n-exports\reporte-diario.json" -Raw | ConvertFrom-Json
$exp.settings.timezone
($exp.nodes | Where-Object { $_.name -eq 'Cada 4 horas' }).parameters.rule.interval[0].expression
```
Expected: `America/Caracas` y `0 0,4,8,12,16,20 * * *`.

- [ ] **Step 7: Ledger — ruling reporte diario**

Añadir al ledger:
`Task 3: complete (workflow id <repId>; I6 cerrado: Marcar a Mercado en cada disparo; tests A/B/C OK — scan corto aggressive, reporte completo con force=mañana, sin Telegram en moderate; exports en .superpowers/n8n-exports/).`

---

### Task 4: Regresión final + cierre

**Files:**
- Modify: `.superpowers/sdd/2026-10-01-fund-n8n-alertas-plan/progress.md` (ledger local)
- Sin cambios en repo → sin commit (los exports y el ledger son gitignored).

**Interfaces:**
- Consumes: todo lo producido por Tasks 1–3.

- [ ] **Step 1: Suite completa**

Run: `$env:PYTHONUTF8="1"; C:\Python313\python.exe -m pytest AgentBiz/tests/ -q`
Expected: **84 passed** (81 offline + 3 network; el 81 incluye `test_chat_with_agent_hardens_system_prompt` agregado en el ruling de contenido del Task 3).

- [ ] **Step 2: Regresión webhook unificado + chat + fondo**

```powershell
# (payloads con [IO.File]::WriteAllText + --data-binary)
# rama trading:  {"message":"analiza bitcoin"}   → 200, "ai_interpretation" (clave según ruling matriz; "response" solo en fallback)
# rama negocio:  {"message":"háblame de scout"}  → 200, "response"
# chat directo:  POST http://127.0.0.1:8000/api/chat/scout {"query":"hola"} → 200, "response"
# fondo:         GET  http://127.0.0.1:8000/api/fund/status → 200, "portfolio"
# mark vivo:     POST http://127.0.0.1:8000/api/fund/mark → 200, "status"
```
Expected: todos 200. (Research: verificar vía `GET /api/fund/strategies` → `standard.tested_at` presente — ruling Task 2; la exec 26 queda `error` histórico por ECONNABORTED aunque el ciclo terminó server-side.)

- [ ] **Step 3: Ledger de cierre**

Añadir al ledger: `Task 4: complete (suite 84 passed; regresión OK; Plan 3/Fase 5 cerrado).`

---

## Workflow JSON — Sistema Unificado v2

```json
{
  "name": "Sistema Unificado v2",
  "nodes": [
    {"parameters":{"httpMethod":"POST","path":"unified","responseMode":"responseNode","options":{}},"id":"wh","name":"Webhook Unificado","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[-640,320],"webhookId":"segundo-cerebro-unified-v2"},
    {"parameters":{"mode":"runOnceForEachItem","jsCode":"const body = $json.body || $json;\nlet msg = String(body.message || body.text || '').trim();\nconst phone = body.phone || '';\nif (!msg) msg = 'Hola';\nconst m = msg.toLowerCase();\n\nconst researchWords = ['investiga', 'investigación', 'investigacion', 'nuevas estrategias', 'prueba estrategias', 'ciclo de investigación', 'ciclo de investigacion', 'research'];\nif (researchWords.some(w => m.includes(w))) {\n  return { json: { message: msg, phone, intent: 'research' } };\n}\n\nconst fundMap = {\n  status: ['fondo', 'estado', 'resumen', 'pnl', 'cómo va', 'como va', 'señales', 'senales', 'señal', 'senal'],\n  portfolio: ['portafolio', 'posiciones', 'trades', 'operaciones'],\n  performance: ['curva', 'rendimiento', 'meta', 'drawdown', 'performance'],\n  strategies: ['estrategia', 'estrategias', 'ganadora', 'ranking']\n};\nfor (const [endpoint, words] of Object.entries(fundMap)) {\n  if (words.some(w => m.includes(w))) {\n    return { json: { message: msg, phone, intent: 'fondo', endpoint } };\n  }\n}\n\nconst tradingWords = ['btc','eth','xrp','sol','bnb','doge','ada','avax','link','dot','precio','mercado','cripto','crypto','bitcoin','ethereum','analiza','analisis','análisis','trading','ticker','usdt','rsi','futuros','exchange','comprar','vender'];\nconst isTrading = tradingWords.some(w => m.includes(w));\nlet symbol = 'BTCUSDT';\nconst tickers = ['BTC','ETH','XRP','SOL','BNB','DOGE','ADA','AVAX','LINK','DOT'];\nconst up = msg.toUpperCase();\nfor (const t of tickers) { if (up.includes(t)) { symbol = t + 'USDT'; break; } }\n\nlet agent = 'scout';\nif (/blog|contenido|art[ií]culo|escribe|newsletter|copy/.test(m)) agent = 'content';\nelse if (/instagram|tiktok|twitter|redes|reels|publica/.test(m)) agent = 'social';\nelse if (/afiliad|comisi[oó]n/.test(m)) agent = 'affiliate';\nelse if (/freelanc|fiverr|upwork|cliente|propuesta/.test(m)) agent = 'freelancer';\n\nreturn { json: { message: msg, phone, intent: isTrading ? 'trading' : 'business', agent, symbol, interval: '1h' } };\n"},"id":"detect","name":"Detectar Intencion","type":"n8n-nodes-base.code","typeVersion":2,"position":[-420,320]},
    {"parameters":{"conditions":{"options":{"caseSensitive":true,"leftValue":"","typeValidation":"loose","version":2},"conditions":[{"id":"cond-research","leftValue":"={{ $json.intent }}","rightValue":"research","operator":{"type":"string","operation":"equals"}}],"combinator":"and"},"options":{}},"id":"ifres","name":"¿Investiga?","type":"n8n-nodes-base.if","typeVersion":2.2,"position":[-200,320]},
    {"parameters":{"respondWith":"json","responseBody":"={{ JSON.stringify({ status: 'lanzado', message: 'Ciclo de investigación lanzado (~9 min). Consulta GET /api/fund/strategies cuando termine.' }) }}"},"id":"respl","name":"Responder Lanzado","type":"n8n-nodes-base.respondToWebhook","typeVersion":1.1,"position":[20,200]},
    {"parameters":{"method":"POST","url":"http://127.0.0.1:8000/api/fund/research","sendBody":true,"specifyBody":"json","jsonBody":"={{ JSON.stringify({ period: '1y' }) }}","options":{"timeout":600000}},"id":"research","name":"Lanzar Research","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[240,200]},
    {"parameters":{"conditions":{"options":{"caseSensitive":true,"leftValue":"","typeValidation":"loose","version":2},"conditions":[{"id":"cond-fondo","leftValue":"={{ $json.intent }}","rightValue":"fondo","operator":{"type":"string","operation":"equals"}}],"combinator":"and"},"options":{}},"id":"iffondo","name":"¿Fondo?","type":"n8n-nodes-base.if","typeVersion":2.2,"position":[-200,440]},
    {"parameters":{"method":"GET","url":"={{ 'http://127.0.0.1:8000/api/fund/' + $json.endpoint }}","options":{"timeout":30000}},"id":"fondog","name":"Fondo GET","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[20,380]},
    {"parameters":{"conditions":{"options":{"caseSensitive":true,"leftValue":"","typeValidation":"loose","version":2},"conditions":[{"id":"cond-trading","leftValue":"={{ $json.intent }}","rightValue":"trading","operator":{"type":"string","operation":"equals"}}],"combinator":"and"},"options":{}},"id":"iftr","name":"¿Trading?","type":"n8n-nodes-base.if","typeVersion":2.2,"position":[-200,560]},
    {"parameters":{"method":"POST","url":"http://127.0.0.1:8000/api/trading/ai","sendBody":true,"specifyBody":"json","jsonBody":"={{ JSON.stringify({ symbol: $json.symbol, interval: $json.interval, risk: 'medium' }) }}","options":{"timeout":120000}},"id":"trader","name":"Trader AI","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[20,520]},
    {"parameters":{"method":"POST","url":"={{ 'http://127.0.0.1:8000/api/chat/' + $json.agent }}","sendBody":true,"specifyBody":"json","jsonBody":"={{ JSON.stringify({ query: $json.message }) }}","options":{"timeout":120000}},"id":"neg","name":"Agente Negocios","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[20,660]},
    {"parameters":{"respondWith":"json","responseBody":"={{ JSON.stringify($json) }}"},"id":"resp","name":"Responder","type":"n8n-nodes-base.respondToWebhook","typeVersion":1.1,"position":[460,440]}
  ],
  "connections": {
    "Webhook Unificado": {"main": [[{"node":"Detectar Intencion","type":"main","index":0}]]},
    "Detectar Intencion": {"main": [[{"node":"¿Investiga?","type":"main","index":0}]]},
    "¿Investiga?": {"main": [[{"node":"Responder Lanzado","type":"main","index":0}],[{"node":"¿Fondo?","type":"main","index":0}]]},
    "Responder Lanzado": {"main": [[{"node":"Lanzar Research","type":"main","index":0}]]},
    "¿Fondo?": {"main": [[{"node":"Fondo GET","type":"main","index":0}],[{"node":"¿Trading?","type":"main","index":0}]]},
    "Fondo GET": {"main": [[{"node":"Responder","type":"main","index":0}]]},
    "¿Trading?": {"main": [[{"node":"Trader AI","type":"main","index":0}],[{"node":"Agente Negocios","type":"main","index":0}]]},
    "Trader AI": {"main": [[{"node":"Responder","type":"main","index":0}]]},
    "Agente Negocios": {"main": [[{"node":"Responder","type":"main","index":0}]]}
  },
  "settings": {"executionOrder": "v1"}
}
```

## Workflow JSON — Reporte Diario Fondo

```json
{
  "name": "Reporte Diario Fondo",
  "nodes": [
    {"parameters":{"rule":{"interval":[{"field":"cronExpression","expression":"0 0,4,8,12,16,20 * * *"}]}},"id":"cron","name":"Cada 4 horas","type":"n8n-nodes-base.scheduleTrigger","typeVersion":1.2,"position":[-640,200]},
    {"parameters":{"httpMethod":"POST","path":"reporte-manual","options":{}},"id":"whm","name":"Trigger Manual","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[-640,400],"webhookId":"segundo-cerebro-reporte-manual"},
    {"parameters":{"jsCode":"const body = $json.body || {};\nconst force = String(body.force || '');\nreturn [{ json: { force } }];"},"id":"origen","name":"Origen","type":"n8n-nodes-base.code","typeVersion":2,"position":[-420,300]},
    {"parameters":{"method":"POST","url":"http://127.0.0.1:8000/api/fund/mark","options":{"timeout":60000}},"id":"mark","name":"Marcar a Mercado","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[-200,300]},
    {"parameters":{"method":"GET","url":"http://127.0.0.1:8000/api/fund/status","options":{"timeout":30000}},"id":"status","name":"Obtener Estado","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[20,300]},
    {"parameters":{"jsCode":"const d = $input.first().json;\nconst p = d.portfolio;\nconst force = $('Origen').first().json.force;\nconst isMorning = force === 'mañana' || $now.hour === 8;\nconst estandar = d.standard\n  ? `${d.standard.nombre} (${d.standard.base}, sharpe ${d.standard.score_sharpe})`\n  : 'aun sin estandar';\nconst senales = (d.signals || []).slice(0, 3)\n  .map(s => `${s.symbol} ${s.strategy} (sharpe ${s.sharpe})`).join(', ') || 'ninguna';\nconst contexto = [\n  `Equity: $${p.equity} | PnL dia: $${p.daily_pnl} | Drawdown: ${(p.drawdown * 100).toFixed(1)}%`,\n  `Fase: ${p.phase} | Posiciones abiertas: ${p.open_positions} | Operaciones: ${p.trades} | Win rate: ${(p.win_rate * 100).toFixed(0)}%`,\n  `Estrategia ganadora: ${estandar}`,\n  `Senales top: ${senales}`\n].join('\\n');\nlet paso = 'scan';\nif (isMorning) paso = 'mañana';\nelse if (p.phase !== 'aggressive') paso = 'nada';\nconst reportQuery = `Datos del fondo Segundo Cerebro Capital:\\n${contexto}\\nFormatea el reporte diario para Telegram: maximo 150 palabras, emojis de mercado, y termina con la linea \"Fase: ${p.phase}\".`;\nreturn [{ json: { paso, fase: p.phase, contexto, reportQuery } }];"},"id":"ctx","name":"Armar Contexto","type":"n8n-nodes-base.code","typeVersion":2,"position":[240,300]},
    {"parameters":{"conditions":{"options":{"caseSensitive":true,"leftValue":"","typeValidation":"loose","version":2},"conditions":[{"id":"cond-manana","leftValue":"={{ $json.paso }}","rightValue":"mañana","operator":{"type":"string","operation":"equals"}}],"combinator":"and"},"options":{}},"id":"if8","name":"¿Mañana?","type":"n8n-nodes-base.if","typeVersion":2.2,"position":[460,300]},
    {"parameters":{"method":"POST","url":"http://127.0.0.1:8000/api/chat/scout","sendBody":true,"specifyBody":"json","jsonBody":"={{ JSON.stringify({ query: 'Escaneo de mercados de hoy: crypto, ETF, acciones y forex. Maximo 60 palabras, una linea por mercado.' }) }}","options":{"timeout":120000}},"id":"scanam","name":"Escaneo Scout","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[680,180]},
    {"parameters":{"method":"POST","url":"http://127.0.0.1:8000/api/chat/social","sendBody":true,"specifyBody":"json","jsonBody":"={{ JSON.stringify({ query: $('Armar Contexto').first().json.reportQuery + '\\n\\nEscaneo del Analista:\\n' + $json.response }) }}","options":{"timeout":120000}},"id":"social","name":"Formatear Social","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[900,180]},
    {"parameters":{"method":"POST","url":"https://api.telegram.org/bot__TELEGRAM_TOKEN__/sendMessage","sendBody":true,"specifyBody":"json","jsonBody":"={{ JSON.stringify({ chat_id: 671160911, text: $json.response }) }}","options":{"timeout":30000}},"id":"tg1","name":"Enviar Telegram (reporte)","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[1120,180]},
    {"parameters":{"conditions":{"options":{"caseSensitive":true,"leftValue":"","typeValidation":"loose","version":2},"conditions":[{"id":"cond-agresiva","leftValue":"={{ $json.fase }}","rightValue":"aggressive","operator":{"type":"string","operation":"equals"}}],"combinator":"and"},"options":{}},"id":"ifag","name":"¿Agresiva?","type":"n8n-nodes-base.if","typeVersion":2.2,"position":[680,440]},
    {"parameters":{"method":"POST","url":"http://127.0.0.1:8000/api/chat/scout","sendBody":true,"specifyBody":"json","jsonBody":"={{ JSON.stringify({ query: 'Escaneo corto de mercado en 2 lineas (crypto y bolsa), maximo 40 palabras.' }) }}","options":{"timeout":120000}},"id":"scans","name":"Escaneo Corto","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[900,440]},
    {"parameters":{"method":"POST","url":"https://api.telegram.org/bot__TELEGRAM_TOKEN__/sendMessage","sendBody":true,"specifyBody":"json","jsonBody":"={{ JSON.stringify({ chat_id: 671160911, text: $json.response }) }}","options":{"timeout":30000}},"id":"tg2","name":"Enviar Telegram (scan)","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[1120,440]}
  ],
  "connections": {
    "Cada 4 horas": {"main": [[{"node":"Origen","type":"main","index":0}]]},
    "Trigger Manual": {"main": [[{"node":"Origen","type":"main","index":0}]]},
    "Origen": {"main": [[{"node":"Marcar a Mercado","type":"main","index":0}]]},
    "Marcar a Mercado": {"main": [[{"node":"Obtener Estado","type":"main","index":0}]]},
    "Obtener Estado": {"main": [[{"node":"Armar Contexto","type":"main","index":0}]]},
    "Armar Contexto": {"main": [[{"node":"¿Mañana?","type":"main","index":0}]]},
    "¿Mañana?": {"main": [[{"node":"Escaneo Scout","type":"main","index":0}],[{"node":"¿Agresiva?","type":"main","index":0}]]},
    "Escaneo Scout": {"main": [[{"node":"Formatear Social","type":"main","index":0}]]},
    "Formatear Social": {"main": [[{"node":"Enviar Telegram (reporte)","type":"main","index":0}]]},
    "¿Agresiva?": {"main": [[{"node":"Escaneo Corto","type":"main","index":0}],[]]},
    "Escaneo Corto": {"main": [[{"node":"Enviar Telegram (scan)","type":"main","index":0}]]}
  },
  "settings": {"timezone": "America/Caracas", "executionOrder": "v1"}
}
```
