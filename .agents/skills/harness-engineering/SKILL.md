---
name: harness-engineering
description: Checklist de arquitectura para sistemas con LLM/agentes - los 6 componentes (loop, tools, context, environment, memory, observability) con las preguntas de diseño de cada uno, hard vs soft constraints, step budget y barra mínima de evals. Usar ANTES de diseñar, revisar o entregar un agente, workflow n8n o sistema "con IA" para cliente o para nosotros; cuando se pida revisar la arquitectura de un agente; o cuando un agente falle y haya que responder qué pasó. Fuente: playlist "10 Days of Harness Engineering".
---

# Harness engineering — checklist de arquitectura de agentes

**Idea central:** el modelo crudo es un text transformer — *"los modelos no hacen cosas; describen la realización de cosas"*. Todo agente = modelo + **harness**: el sistema ingenierizado alrededor que convierte el texto en **acción, persistencia y comportamiento medible**. Los 5 gaps que el harness cierra: no execution → tools; no durable state → memory; no fresh knowledge → context; no verification → observability; no environment → environment.

**Regla:** todo diseño o entrega de agente pasa por los 6 componentes. Si alguno no tiene respuesta explícita, **no está listo para producción**.

## Los 6 componentes (preguntas que hay que responder)

### 1. The loop
- ¿Cuál es la **termination condition**? Obligatoria una de: **step budget (5-20)**, palabra clave/stop sequence, o umbral de errores (~3 fallos seguidos → parar y reportar).
- El error **no rompe el loop**: vuelve al historial como *observation* para que el modelo lo reporte/reintente.
- Patrones conocidos: ReAct, plan-then-act, orchestrator-worker. Si el loop no termina, no se entrega (coste acotado = contrato).

### 2. The tools
- **"Composability over monoliths"**: pocas tools afiladas y compuestas (`read/write/bash/fetch` + skills) > 50 tools bespoke. Ni micro-tools (`get_file_name`) ni monolitos opacos (`analyze_web_page`).
- Cada tool devuelve **éxito/fracaso estructurado**, diciendo *qué* falló — un fallo mudo envenena el loop.
- La superficie de tools del cliente (whitelist) **es** su contrato de seguridad: sin tools de SQL libre, sin destructivas.

### 3. The context
- System prompt = **control plane**: quién eres, qué tools existes, qué es buen comportamiento. Incluir el `AGENTS.md` del consumidor.
- Decidir estrategia de historial: full replay / compaction / truncation — **el contexto es un moving target que se decide cada turno** (context engineering ≠ prompt engineering).
- RAG: solo lo necesario ("no metas un libro de Python para un patrón Observer").

### 4. The environment
- **Soft constraints** ("no borres mi archivo" en el prompt) **el modelo puede ignorar** → no valen como garantía. **Hard constraints las aplica el harness**: workspace acotado, whitelist de red, credenciales de mínimo permiso, DB sin DELETE, container desechable por tarea.
- Reproducible = entorno limpio por tarea: si falla 2 veces igual, es del agente, no del entorno.
- Regla de entrega: **si una garantía importa, es hard, nunca solo prompt.**

### 5. The memory
- La memoria es **responsabilidad del harness, no del modelo**: "si le dejas al modelo decidir qué recordar, guardas cosas distintas en cada run e imposible de depurar."
- Escritura con **triggers definidos por código**; long-term guarda perfil/preferencias — NO tool results arbitrarios.
- Lectura también acotada: presupuesto + retrieval (¿qué entra y qué no?).

### 6. The observability
- Tres niveles: **logs por llamada** (contexto, respuesta, latencia, tokens) → **traces por sesión** (trace ID → replay: *¿qué hizo el modelo, en qué orden, con qué entradas?*) → **evals** (tarea fija + salida esperada + score).
- *"No puedes mejorar el harness si no mides si tus cambios lo empeoraron o mejoraron."* Los harnesses suben ~30% en benchmarks solo mejorando el harness, sin tocar el modelo.
- **La ausencia de errores NO es señal de salud**: heartbeat por ausencia de actividad (si no corre cuando debería, alerta).

## Barra mínima de entrega (antes de decir "listo" a un cliente)

1. Step budget + termination explícitos en todo loop.
2. Al menos **1 hard constraint real** (no solo prompt) protegiendo datos/acciones del cliente.
3. **3-5 evals fijas** con salida esperada: score antes/después de cada cambio de modelo/prompt → detectar degradación.
4. Error workflow + heartbeat (logs que permitan responder "qué pasó" el día que falle).
5. Honesty gate: sin environment+verification, el agente **solo recomienda** — decirlo claro; cero promesas de autonomía ni de rendimiento.

## Aplicación en este repo
- Metodología de piloto y checklist de entrega: `AgentBiz/docs/notas-videos-2026-10-17.md` §4A-4B.
- El fondo ya cumple observability/evals (suite 236 + gate OOS/Monte Carlo): no cambiar modelo/estrategia sin número.
