# Segundo Cerebro Capital — Pipeline vivo (ledger 2026-10-14)

Registro de la construcción y primeras pruebas reales del pipeline de estrategias
del fondo paper ($2,500), replicando el sistema del video de Vicente Conesa Santos.

## Componentes (todos con tests, suite 231/231)

| Componente | Archivo | Commit | Qué hace |
|---|---|---|---|
| Gate de robustez | `backend/robustness.py` | `9d91b52` | Walk-forward OOS (ventanas sin solape) + Monte Carlo (500 sims, prob. pérdida ≤60%). Obligatorio antes de promover. |
| Incubadora | `backend/research.py` | `9d91b52` | Candidatos promovidos entran `incubating` 30 días; graduación automática en `/mark` si drawdown real ≥ -10%, si no `failed`. |
| Minería automática | `backend/research.py` (`mine_specs`) | `84dd0d6` | 73 variantes deterministas (6 grillas), dedupe por huella, re-test cada 14 días (`refresh_days`). Endpoint `POST /api/fund/research {"mode":"mineria"}`. |
| Comité de riesgo | `backend/risk_committee.py` | `47e70b7` | Modos mantener/reducir/defensivo según drawdown, daily-stop y racha. Defensivo bloquea aperturas; `/orders` respeta límites efectivos. Se evalúa en cada `/mark`. Sin LLM. |
| Calendario económico | `backend/econ_calendar.py` | `47e70b7` | Feed ForexFactory; eventos High ±90 min bloquean aperturas (USD/All para crypto-bolsa; divisas para forex). Fail-open. `GET /api/fund/calendar`. |
| Prompt LLM anti-repetición | `backend/research.py` (`known_params_summary`) | `4b413fa` | El prompt de hipótesis NVIDIA incluye lo ya explorado y pide valores nuevos. Parser `raw_decode` inmune a prosa/fences. |

## Pruebas reales (2026-10-14)

| Ciclo | Specs nuevas | Runs | Mejor in-sample | Gate OOS | Resultado |
|---|---|---|---|---|---|
| Minería determinista | 65 | 2,015 | Bollinger(15,2.0) sharpe +2.79 (SPY) | OOS -13.1% | `sin_candidato_robusto` |
| LLM (NVIDIA) | 27 | 837 | Bollinger(10) sharpe +2.11 (SPY) | — | `sin_candidato_robusto` |

**Conclusión**: el gate tumbó a todos los héroes del in-sample. El estándar
**Donchian Breakout canal 20** (único con OOS +15.9% en el walk-forward de
oct-13) sigue `incubando`; graduación esperada ~2026-11-12 si el drawdown
real se mantiene ≥ -10%.

Estado fund.db (cierre del día): ~187 specs / ~5.8k runs. Respaldo previo a
pruebas: `%TEMP%\fund_backup_premineria.db`.

## Aprendizajes operativos

- **El servidor uvicorn debe reiniciarse tras deploy** — un ciclo corrió contra
  código viejo antes de darse cuenta (404 en `/calendar` = versión vieja).
- **Los ciclos de research tardan 9–17 min** (fetch + cientos de backtests).
  Un POST HTTP no es el canal para producción: usar job en background o
  scheduler n8n que lance el script directo (mejora pendiente).
- **El LLM propone el espacio popular** — sin el resumen de lo explorado,
  repetía hipótesis ya cubiertas. Ahora el prompt lo evita.
- **El feed ForexFactory es estable y sin key**; caché 6h en memoria,
  fetcher inyectable para tests.
- **Warmup de indicadores (2026-10-14, lección curso QuantConnect)** —
  QC se niega a usar un indicador hasta que `isReady` (`setWarmUp`). Nuestro
  backtester incluía las primeras barras con rolling inmaduro y señal vacía
  en las métricas. Ahora `warmup_bars(base, params)` en `strategies.py`
  descarta el inicio en `run_backtest` (mine + `rank_universe`). El gate
  walk-forward **no** lo usa: cada ventana OOS ya es un backtest independiente
  con rolling local (conservador) y recortar reduciría ventanas en series
  cortas. Impacto: métricas in-sample más honestas; ranking de specs puede
  cambiar levemente en la próxima re-minería (refresh ~28-oct).

## Curso QuantConnect (19 videos, 2026-10-14) — mapeo a nuestro stack

Ya replicamos todo el pipeline del video de Conesa. El curso de QC confirma
patrones y aporta lecciones trasladables (somos Python/pandas/sqlite, no QC):

| Concepto QC | Equivalente nuestro | Acción |
|---|---|---|
| market/stop/limit orders, update/cancel (OCO) | órdenes Binance reduceOnly SL/TP | hecho; trailing/SL-breakeven = futuro |
| indicators + `isReady`/`setWarmUp` | rolling pandas sin corte | **aplicado** (warmup_bars) |
| scheduled events | n8n + auto_trader | hecho |
| universe por volumen (top N) | `list_universe()` estático 31 | idea: ranking por liquidez |
| filtros fundamentales (PER) | N/A (cripto-heavy) | descartado por ahora |
| custom data (AddData) | `market_cache.db` | idea: funding rate / OI Binance |
| redes neuronales (TF) entrenando en live | LLM solo propone specs | lección: el curso logró +0.6% con NN vs +476% buy&hold de TSLA — la NN de precios no es magia; nuestro uso (hipótesis LLM + gate) es más honesto |
| Twitter bot (VADER sentiment, +52% 5a vs TSLA +476%) | — | lección: sentimiento social solo no basta; no perseguir |

## Experimento régimen ER (2026-10-14, lección registrada)

Se probó un filtro de régimen (efficiency ratio Kaufman 20 > 0.3) sobre
Donchian(20) con walk-forward OOS en los 31 símbolos. La primera versión
mostraba +40.9% OOS medio (vs +15.6% base) — **era un artefacto de lookahead**:
el mask usaba el cierre del día t para decidir la posición que capturaba
el return de t. Con la corrección legal (mask shift(1), decisión en t-1):

| Versión | Total medio/símbolo | % positivos |
|---|---|---|
| Donchian(20) base | +15.6% | 52% |
| + ER shift(1) | +10.8% | 61% |

Conclusión: el filtro ER **no se integra**; el estándar sigue Donchian(20)
sin cambios. `backend/regime.py` queda disponible (testeado, sin leak) para
futuros experimentos. Lección: todo experimento de señales debe usar la misma
convención de ejecución (shift(1)) que el backtester de producción, o los
resultados mienten.

## Próximos pasos

1. Graduación de Donchian(20) el ~12-nov (revisar `/mark` → `incubation`).
2. Re-minería automática de las 65+27 specs el ~28-oct (refresh 14 días).
3. Mejora: research como job de fondo (no HTTP bloqueante) + trigger n8n.
4. Integrar comité/calendario en `auto_trader.py` (cripto automático).
5. Documentar en `SERVICES.md` los dos módulos nuevos si se despliega.

## Cómo correr un ciclo a mano

```bash
# minería (sin LLM, ~10-17 min)
python -c "import sys; sys.path.insert(0,'AgentBiz/backend'); import research; print(research.run_research(db_path='AgentBiz/fund.db', specs=research.mine_specs(), refresh_days=14)['status'])"

# LLM (requiere NVIDIA_API_KEY)
# → research.run_research(db_path='AgentBiz/fund.db')  # specs=None => hipótesis NVIDIA
```
