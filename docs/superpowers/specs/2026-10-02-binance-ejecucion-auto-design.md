# Spec — Plan 4: Integración Binance (demo testnet) + Auto-trader loop

Fecha: 2026-10-02 · Estado: **borrador para revisión de Carlos** · Método: superpowers (brainstorming completado, approach A aprobada)

## 1. Objetivo

Pasar el fondo de operar solo en papel a **operar contra Binance en DEMO (testnet)** con un **auto-trader loop que corre días sin intervención**, manteniendo intacta la contabilidad actual (equity, fases, risk gate, performance). Cuando Carlos consiga el dinero real, el switch a producción = cambiar variables de entorno (keys + modo).

## 2. Alcance

**Incluido:**
1. `broker_binance.py` — cliente REST de Binance (firma HMAC-SHA256) con soporte **Spot y Futuros (USDT-M)**.
2. Modo de ejecución conmutable `paper | testnet | real` por variable de entorno.
3. Integración en `POST /api/fund/orders` (apertura y cierre) — misma validación, mismo risk gate, misma contabilidad.
4. **Auto-trader loop**: tarea asyncio dentro del servidor AgentBiz; cada N minutos:
   `mark (SL/TP) → señales cripto elegibles → Trader API (entrada/SL/TP) → Director de Riesgo → orden → Telegram`.
5. Notificaciones Telegram por cada orden automática (aprobada/rechazada/fallida).
6. Suite TDD: unit (sin red) + tests de red `network` contra testnet (skip sin keys).

**NO incluido (explícito):**
- Dinero real operativo (queda listo el switch; no se prueba con dinero real).
- Auto-trading de ETF/acciones/forex/futuros tradicionales (solo cripto en Binance; los otros 4 mercados siguen en paper hasta MT5/broker).
- Semiauto con botones de aprobación en Telegram (diseñar cuando haya dinero real — ver §10).
- Cambios en paper_portfolio, risk gate, fases, research, performance, n8n (salve lo mínimo indicado en §5).
- Docker/VPS (sigue pendiente de Carlos).

## 3. Arquitectura (approach A aprobada)

```
                 ┌───────────────────── AgentBiz (uvicorn) ─────────────────────┐
                 │                                                              │
 auto-trader ───►│  auto_trader.py (asyncio task, AUTO_TRADER=1)                │
   tick cada N   │    1. POST internamente mark (cierra SL/TP tocados)          │
   minutos       │    2. strategy_results cripto elegibles (research.latest_*)  │
                 │    3. Trader API (:5001) → operation {entry, sl, tp, señal}  │
                 │    4. risk_review (Director, LLM) → aprueba/rechaza          │
                 │    5. fund_orders lógica → risk limits (PHASES)               │
                 │    6. EXECUTION_MODE:                                        │
                 │         paper   → solo contabilidad (hoy)                    │
                 │         testnet → broker_binance (USDT falso) + contabilidad │
                 │         real    → broker_binance (producción) + contabilidad │
                 │    7. Telegram notify                                        │
                 └──────────────────────────────────────────────────────────────┘
```

**Principio rector: la contabilidad no cambia.** `paper_portfolio` sigue siendo la única fuente de verdad de equity/posiciones/fases. El broker solo ejecuta la orden en el exchange; el fill se registra con el precio de ejecución real. Un solo punto de conmutación: `EXECUTION_MODE`.

## 4. Configuración (`.env` raíz, gitignored — precedente purga de claves)

| Variable | Default | Descripción |
|---|---|---|
| `EXECUTION_MODE` | `paper` | `paper` \| `testnet` \| `real` |
| `BINANCE_TESTNET_KEY` / `BINANCE_TESTNET_SECRET` | vacío | Keys de testnet (las crea Carlos, §9) |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | vacío | Keys reales (se llenan al llegar el dinero) |
| `AUTO_TRADER` | `0` | `1` activa el loop |
| `AUTO_TRADER_INTERVAL_MIN` | `15` | Cadencia del tick |

Endpoints por modo:
- spot: testnet `https://testnet.binance.vision`, prod `https://api.binance.com`
- futuros: testnet `https://testnet.binancefuture.com`, prod `https://fapi.binance.com`

`real` **exige** keys presentes, si no → error al iniciar (fail-fast). `testnet` idem con keys de testnet.

## 5. Módulos nuevos y cambios

### 5.1 `backend/broker_binance.py` (nuevo)
- `sign_request(secret, params)` → HMAC-SHA256 hex; `place_order(...)`; `cancel_order`; `get_position_info`/`get_account`; `ping()`.
- Routear Spot vs Futuros por `market_type`:
  - **Spot**: `POST /api/v3/order` — comprar con `quoteOrderQty` (USDT), vender con `quantity` (base). Solo LONG, `leverage` debe ser 1 → si la orden trae `side=short` o `leverage>1` → error 422 claro.
  - **Futuros**: `POST /fapi/v1/order` — MARKET de entrada + **órdenes de protección en el exchange**: `STOP_MARKET` + `TAKE_PROFIT_MARKET` (reduceOnly) para que SL/TP existan aunque el portátil se duerma.
- Mapeo de símbolos (universo `market_data.UNIVERSE["crypto"]` + PERP):
  - `BTC` → spot `BTCUSDT`; `BTCUSDT-PERP` → futuros `BTCUSDT`.
- Errores Binance (`code`, `msg`) → excepción `BrokerError` con contexto.
- `close(symbol, market_type, side, ...)` idempotente: futuros = cancelar órdenes de protección pendientes del símbolo + cerrar reduceOnly (si ya flat → no-op sin error); spot = venta de la base (si no hay base → no-op).
- Sin claves → `BrokerError` (nunca falla silencioso).

### 5.1b Sincronización de cierres (gap detectado en self-review)
Los cierres de SL/TP los hace `fund_mark`→`mark_to_market` (contabilidad), **no** pasa por `fund_orders`. Reglas por instrumento cuando `EXECUTION_MODE≠paper`:
- **Futuros**: la protección vive en el exchange (STOP/TP MARKET se ejecutan solas) → `mark` cierra solo la contabilidad; sin acción de broker. Si el cierre fuera por precio manual/otro motivo → sí cerrar en broker (5.2).
- **Spot**: `fund_mark`, después de cerrar posiciones en la lista `closed`, llama `broker.close(...)` por cada una (**best-effort**): si falla → alerta Telegram + campo `broker_sync_failed[]` en la respuesta de `mark` (la contabilidad NO se revierte; queda visible para reconciliación).
- Limitación documentada (§10): en spot la protección SL/TP real depende de que `mark` corra (auto-trader lo hace en cada tick; en modo `real` spot revisar antes de operar dinero).

### 5.2 `backend/api/fund.py` — `POST /api/fund/orders` (modificación mínima)
Flujo actual intacto (validación → risk_review opcional → open/close → record_equity → audit). Se inserta **entre el risk gate y `open_position`/`close_position`**:
- `EXECUTION_MODE=paper`: comportamiento idéntico al hoy (suite existente sin cambios).
- `testnet`/`real`: ejecutar en broker **primero**; si el broker falla → 502 `BrokerError` (no se registra posición). Fill del broker → `entry` real (reemplaza `req.entry`); luego `open_position` como hoy.
- Cierre (`action=close`): ejecutar en broker (futuros: reduceOnly, spot: venta de la base) y registrar con precio real.
- El campo de respuesta añade `"execution": {"mode": "...", "broker": "binance-testnet"|null, "order_id": ...}`.

### 5.3 `backend/auto_trader.py` (nuevo) + hook en `api/main.py`
- Arranque: en `@app.on_event("startup")`, si `AUTO_TRADER=1` → `asyncio.create_task(loop)` (log de arranque con modo y cadencia).
- Tick:
  1. `mark` (cierra posiciones cuyo SL/TP tocó — ya existente).
  2. `research.latest_results(FUND_DB, N)` → filtrar `market=="crypto"` y `eligible==True`; excluir símbolos con posición abierta y con orden en los últimos K ticks (cooldown, default 24 ticks ≈ 6 h).
  3. Límites duros **antes** de llamar al Trader: `open_positions < max_positions`, stop diario no tocado (`can_open` + `daily_loss_stop`), si toca → log + skip total.
  4. Por cada candidato (máx `1` orden nueva por tick): Trader API `GET /api/operation/{SYMBOL}?interval=1h&risk=...` → `operation.signal` distinto de HOLD → construir orden.
  5. **Sizing**: `dollar_risk = equity × banda central de risk_pct de fase` (aggressive ≈ 7.5%, moderate ≈ 2.5%); `qty_usd = dollar_risk / (|entry−sl|/entry × leverage)`; tope `qty_usd ≤ equity × 0.5`.
  6. `risk_review` (Director) → si `rechaza` → Telegram (rechazo) + skip.
  7. Ejecutar vía la misma lógica que `fund_orders` (extraída a función compartida `_execute_order(...)`) → broker si `EXECUTION_MODE≠paper`.
  8. Telegram: orden abierta (símbolo, lado, entry, SL/TP, qty, modo) o fallo/rechazo.
- Todo el loop envuelto en try/except por tick: un tick que revienta **no** mata la tarea (log + notificación de error).
- Mercado de ejecución: solo símbolos del universo cripto; **spot** por defecto (`BINANCE_MARKET_TYPE=spot` default; `futures` opt-in — decisión de detalle abierta §10).

### 5.4 Telegram
- Helper `_send_telegram(text)` en `auto_trader.py` usando `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` ya presentes en `.env` (mismo patrón que n8n, vía `requests` directo). Silencioso si no hay token (modo dev).

## 6. Contratos de error

| Escenario | Comportamiento |
|---|---|
| `EXECUTION_MODE=testnet` sin keys | fall-fast al iniciar broker; endpoint → 502 con mensaje claro |
| Orden spot con short/leverage>1 | 422 (validación antes de llamar al broker) |
| Broker rechaza/timeout | 502 `BrokerError`, **no** se registra posición en paper |
| Risk gate rechaza | 403 (igual que hoy) — nunca se toca el broker |
| Límites de fase | 409 RiskError (igual que hoy) |
| Tick del loop revienta | log + Telegram de error, tarea sigue viva |
| `AUTO_TRADER=0` | cero comportamiento nuevo (default) |

## 7. Pruebas (TDD, suite actual 86 offline)

**Unit (sin red) — nuevas:**
1. Firma HMAC: vector conocido (params fijos → hash esperado).
2. Mapeo símbolo: `BTC`→`BTCUSDT` spot; `BTCUSDT-PERP`→futuros.
3. Constraint spot: short/leverage>1 → error 422.
4. `EXECUTION_MODE=paper` → el broker **no** se invoca (mock con assert).
5. `EXECUTION_MODE=testnet` → broker invocado con URL de testnet, fill manda a `open_position`.
6. Broker falla → 502 y **sin** posición registrada.
7. Sizing: dollar_risk/qty_usd según banda de fase + tope 0.5×equity.
8. Auto-tick con mocks: señal cripto elegible → aprueba → orden; señal HOLD → skip; símbolo con posición abierta → skip; risk rechaza → skip; límites tocados → skip total; tick con excepción → no mata la tarea.
9. Filtro de mercado: señales etf/forex/acciones ignoradas.

**Red (marker `network`, skip si no hay keys):** ping testnet + orden market testnet mínima + cancelación.

**Regresión:** los 86 tests existentes deben pasar sin modificación (modo paper es el default exacto de hoy).

## 8. Flujo de la sesión de pruebas en vivo (smoke test)

1. Carlos crea keys de testnet (§9) → las pego en `.env`.
2. `EXECUTION_MODE=testnet AUTO_TRADER=0` → `POST /api/fund/orders` a mano (orden pequeña) → verifica en testnet.binance.vision que la orden aparece + posición en `/api/fund/portfolio`.
3. `AUTO_TRADER=1` → dejar correr ≥1 tick → verificar Telegram + trades.
4. Volver a `paper` (default) cuando no se quiera operar.

## 9. Acciones de Carlos (bloquean smoke, no el desarrollo)

1. Crear keys de testnet: `https://testnet.binance.vision` → login (GitHub) → API Key/Secret → pasármelas (las pongo en `.env`, gitignored).
2. Decidir: ¿spot por defecto o futuros por defecto? (recomendación: **spot** para el primer demo; futuros queda como opt-in).
3. Definir cuándo retomar el tema del dinero real (semiauto vs auto — §10).

## 10. Abiertos (resueltos antes o durante el plan)

- **Autonomía con dinero real**: sin resolver (no hay dinero aún). Diseño deja `EXECUTION_MODE=real` operativo pero **recomendación**: al llegar dinero, empezar semiauto (aprobación por Telegram) — se decide entonces.
- **Intervalo y timeframe**: default 15 min / Trader en `1h` — ajustable por env, confirmar con Carlos si quiere otra cadencia.
- **Futuros como opt-in**: mantener cerrado hasta que spot demo corra días.
- **Spot sin protección en exchange** (solo §10): SL/TP de spot viven en la contabilidad + `mark` — aceptable en testnet; al pasar a `real` con spot, evaluar OCO o migrar a futuros para protección nativa.
- **Dónde corre días sin dormirse**: portátil despierto hoy; Docker/VPS pendiente de Carlos (ya anotado en Plan 3).
