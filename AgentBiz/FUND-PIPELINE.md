# Segundo Cerebro Capital — Pipeline vivo (ledger 2026-10-14)

Registro de la construcción y primeras pruebas reales del pipeline de estrategias
del fondo paper ($2,500), replicando el sistema del video de Vicente Conesa Santos.

## Componentes (todos con tests, suite 220/220)

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
