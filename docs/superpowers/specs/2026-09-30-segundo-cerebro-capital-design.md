# Spec: Segundo Cerebro Capital — Fondo de Inversión con Agentes

**Fecha:** 2026-09-30
**Estado:** Aprobado por el CEO (Carlos Zambrano)
**Enfoque:** A — Reconversión sobre AgentBiz (aprobado)
**Spec → Plan:** pasa a `writing-plans` tras aprobación de este documento

## 1. Contexto y objetivo

Reconversión total del sistema AgentBiz (7 agentes de negocio) en una **empresa de gestión de fondos e inversiones**, donde los agentes actuales pasan a ser **empleados con nuevos cargos**. Los agentes NO se descartan: se reestructuran.

- **Capital:** $2,500 USD **simulados (paper trading)**
- **Período de prueba:** 2 semanas, luego decisión de pasar a real
- **Objetivo:** multiplicar el capital lo que quede del año (Q4 2026)
- **Fases de riesgo:** Fase 1 **Agresiva** (ahora) → Fase 2 **Moderada** (post-prueba o por decisión del CEO)
- **Mercados:** crypto + ETF + acciones + forex + **futuros**
- **Sin dinero real ni API keys** hasta que el CEO lo decida (paso a real = fase posterior)

### Restricciones
- Datos de mercado **gratuitos y sin API keys** (ccxt + yfinance)
- Todo correrá en local (Windows, servicios existentes: n8n :5678, AgentBiz :8000, Trader API :5001)
- Los flujos ya probados (webhook unificado, chat con agentes, trading AI) deben seguir funcionando
- Modelos NVIDIA NIM con fallback (deepseek y kimi-k3 caídos hoy; nemotron funciona 1-2s)

## 2. Organigrama (reconversión de agentes)

CEO: **Carlos** (aprueba estrategia ganadora y cambios de fase).

| Agente actual | Nuevo cargo | Departamento | Trabajo |
|---|---|---|---|
| `scout` | Analista de Mercados | Investigación | Vigila crypto/ETF/acciones/forex/futuros; detecta oportunidades y tendencias |
| `trading` | Mesa de Operaciones | Trading | Señales BUY/SELL con SL/TP en los 4 mercados; ejecuta paper trades |
| `analytics` | Director de Estrategias | **Estrategias** | Backtesting, ranking, ciclo de investigación; dice cuál es la más rentable |
| `content` | Director de Riesgo | Riesgo | Aprueba/rechaza operaciones; vigila drawdown, exposición y límites por fase |
| `social` | Comunicaciones | Reportes | Reporte diario a Telegram (PnL, operaciones, señales, ganadora) |
| `freelancer` | Desarrollo | Tech | Escribe/mantiene estrategias nuevas (implementa SPECs ganadoras) |
| `affiliate` | Conexiones | Ejecución | Puesto para fase real (API keys de exchange/broker) |

**Flujo:** Investigación detecta → Estrategias valida con backtest → Riesgo aprueba → Mesa opera en paper → Comunicaciones reporta.

## 3. Capa de datos de mercado

Módulo único `AgentBiz/backend/market_data.py`:

| Mercado | Fuente | Universo inicial | Notas |
|---|---|---|---|
| Crypto | ccxt (Binance público) | BTC, ETH + top 15 | 24/7 |
| ETF | yfinance | SPY, QQQ, DIA, GLD, TLT, VTI | Horario NY |
| Acciones | yfinance | AAPL, NVDA, MSFT, TSLA, AMZN | Horario NY |
| Forex | yfinance (`EURUSD=X`) | EURUSD, GBPUSD, USDJPY, AUDUSD | 24/5 |
| Futuros | yfinance (`ES=F`, `NQ=F`, `GC=F`, `CL=F`) + perpetuos ccxt `binanceusdm` | S&P, Nasdaq, Oro, Petróleo, BTC/ETH perp | 24/5 con mantenimiento |

**API:** `get_price(symbol)`, `get_ohlc(symbol, period, interval)`, `list_universe()`, `resolve(symbol)` (mapea ticker normalizado a fuente).
- Historial para backtest: 1 año de velas diarias + intradía (1h)
- Caché local en SQLite para respetar rate limits de yfinance
- Timestamps con zona horaria; fuera de horario se usa el último cierre
- Instalar: `pip install yfinance`

## 4. Portafolio paper (Sección 4)

Módulo `AgentBiz/backend/paper_portfolio.py` + tablas SQLite (`positions`, `trades`, `equity_curve`, `phases`).

Capital inicial: **$2,500**.

| Regla | Fase 1 Agresiva (actual) | Fase 2 Moderada |
|---|---|---|
| Riesgo/operación | 5–10% ($125–250) | 2–3% |
| Apalancamiento máx. | 5x | 2x |
| Posiciones abiertas máx. | 5 | 4 |
| Pérdida diaria tope | -10% → stop del día | -5% |
| Drawdown de alerta | -20% | -10% |

- Toda posición lleva SL/TP obligatorios; cierre automático al tocarlos (marcado a mercado según horario del activo)
- Cambio de fase: por decisión del CEO (`POST /api/fund/phase`) — ajusta límites al instante; el portafolio NO se resetea
- Métricas: PnL total, PnL día, trades, win rate, drawdown actual, curva de equity vs meta

## 5. Departamento de Estrategias (Sección 3 ampliada)

### 5.1 Estrategias iniciales (`strategies.py`, sobre OHLCV)
1. Cruce SMA 20/50 (tendencia)
2. RSI mean-reversion (14, compra <30, venta >70)
3. Momentum 30d
4. Breakout Donchian + filtro ATR
5. MACD trend
6. Bollinger reversion (20, 2σ)

### 5.2 Backtester (`backtester.py`)
- Corre estrategias × universo con 1 año de velas
- Métricas: retorno total, anualizado, Sharpe, max drawdown, win rate, profit factor, nº operaciones
- Costes realistas: crypto 0.06%, acciones 0.01%, forex 1.5 pips, futuros 1 tick
- Resultados → tabla `strategy_results` (SQLite)

### 5.3 Ciclo de investigación continua (lo pedido)
```
1. INVESTIGAR    analytics genera hipótesis con NVIDIA (variantes de
                 parámetros, reglas nuevas)
2. ESPECIFICAR   cada hipótesis → SPEC JSON {nombre, indicadores,
                 reglas entrada/salida, grid de parámetros}
3. BACKTESTEAR   backtester corre specs × universo con costes
4. RANKEAR       Sharpe/retorno/drawdown según la fase vigente
5. ELEGIR        la #1 global = ESTRATEGIA ESTÁNDAR del fondo,
                 con parámetros afinados por mercado
6. DESPLEGAR     freelancer la implementa permanente en paper trading
```
- Historial de investigación en SQLite (specs probadas, Sharpe, si ganó) — no repetir
- Specs nuevas **solo tocan backtest** hasta ganar el ranking
- Backtest completo semanal + bajo demanda (`POST /api/fund/research`)
- Fase agresiva: prioriza Sharpe alto aceptando drawdown ≤ -35%
- Fase moderada: penaliza drawdown > -15%

## 6. Endpoints nuevos (AgentBiz)

| Endpoint | Función |
|---|---|
| `GET /api/fund/status` | Estado general: PnL, fase, ganadora, señales |
| `GET /api/fund/portfolio` | Posiciones, equity, trades, win rate |
| `POST /api/fund/orders` | Abrir/cerrar posición paper |
| `GET /api/fund/performance` | Curva equity, drawdown, vs meta |
| `POST /api/fund/backtest` | Backtest completo bajo demanda |
| `POST /api/fund/research` | Lanza ciclo de investigación |
| `GET /api/fund/strategies` | Ranking vivo + ganadora + historial |
| `POST /api/fund/phase` | Cambia fase (CEO) |
| `GET /api/fund/office` | Empleados + mensajes + portfolio + tickers (**alimenta la oficina 3D**) |

## 7. Integración n8n (2 workflows)

1. **Sistema Unificado v2** (reemplaza al v1 activo `rd6Io093fYW0yLgA`):
   - Webhook POST `/api/unified` → Detectar Intención →
     - "fondo/status/señales/portafolio/estrategia" → `/api/fund/*`
     - "investiga estrategias" → `POST /api/fund/research`
     - "háblame de X" → `POST /api/chat/{empleado}` (cargos nuevos)
   - Respond to Webhook
2. **Alerta diaria cron 8:00 AM**: `GET /api/fund/status` + scan de mercados → `social` formatea → Telegram API (`8669076747:AAH…`, chat `671160911`)
   - Opcional fase agresiva: **SÍ aplica** — scan corto cada 4h en fase agresiva; se desactiva al pasar a moderada

## 8. Oficina 3D (Sección 6)

Página local **`http://127.0.0.1:8000/office`**, servida por AgentBiz (static files).

- **Stack:** Three.js copiado local (sin CDN) + polling cada 3s a `GET /api/fund/office`
- **Escena:** planta de oficina; 7 escritorios por departamento con avatar (color depto + etiqueta + monitor); mesa CEO; pizarrón con ganadora/fase/meta
- **Trabajando:** `idle` → quieto/luz azul; `working` → animación + luz ámbar + tarea actual en monitor (de `agents.status` + `tasks`)
- **Hablando:** burujas con última frase; línea animada entre escritorios cuando hay mensaje inter-departamento (`messages`); feed lateral tipo chat con el log
- **HUD:** ticker de mercados, PnL, drawdown, trades/win rate, reloj NY
- **Calidad visual:** construir con skill `design-html`, pulir con `design-review`

## 9. Orden de construcción y tests

| # | Fase | Tests |
|---|---|---|
| 1 | `market_data.py` + yfinance + caché | precio de 1 símbolo por mercado, OHLC 1 año, resolve() |
| 2 | `paper_portfolio.py` + fases | SL/TP, tope diario, cambio de fase, límites |
| 3 | `strategies.py` + `backtester.py` | Sharpe conocido, costes, ranking |
| 4 | Reconversión agentes + research | prompts nuevos, risk gate, SPEC cycle, regresión chat |
| 5 | n8n v2 + alerta diaria | payloads de prueba, ejecución manual → Telegram |
| 6 | Oficina 3D | página abre, polling, burbujas, ticker |
| 7 | Backtest completo + arranque paper + docs | end-to-end + `07-SEGUNDO-CEREBRO-PRODUCCION.md` |

**Regresión permanente:** webhook unificado (rama trading + negocio) y chat con agentes deben seguir OK tras cada fase.

## 10. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Rate limits yfinance | Caché SQLite de OHLCV |
| Modelos NVIDIA caídos (deepseek, kimi-k3 hoy) | Fallback nemotron (probado 1-2s); no reinstalar transformers/torch |
| Horarios de mercado | Timestamps tz; último cierre fuera de horario |
| PowerShell vs UTF-8 | `--data-binary @archivo`, `PYTHONUTF8=1`, `encoding=utf-8` en subprocess |
| El fondo opera sin supervisión | Riesgo (content) con límites duros + stop diario + alerta de drawdown |

## 11. Fuera de alcance (esta iteración)

- Trading real con dinero (fase posterior, requiere API keys del CEO)
- Móvil / hosting externo (todo local)
- Más de 2 semanas de horizonte de prueba
