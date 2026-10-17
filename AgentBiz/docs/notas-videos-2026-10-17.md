# Notas de videos — 2026-10-17

Tres recursos pedidos por Carlos antes de publicar el post 1 de LinkedIn:

1. **"Cómo vivir de la IA: Tu plan de acción de 30 días"** — Agustín Medina (22 min, ES)
   https://youtu.be/RIOjZevA0NE → *ideas de ganar dinero con IA*
2. **"¿Este es el MEJOR stack para proyectos grandes?"** — Fazt Code (29 min, ES)
   https://youtu.be/tZvYZ5a5yfE → *aplicar en nuestros sistemas*
3. **Playlist "10 Days of Harness Engineering"** (10 días + masterclass 2 h, EN)
   https://youtube.com/playlist?list=PLDCqy1KBwS34 → *aprender todo y aplicar*

Transcripciones limpias: `%TEMP%\opencode\videos\txt\`.

---

# 1. Video 1 — Plan de 30 días (Agustín Medina)

Agencia propia de IA (Lambda) + comunidad (Eilin). Mensaje central: **no se trata de qué aprender, sino de qué NO aprender**; lo que caduca son los botones, no el criterio.

## Las 3 preguntas (filtro de 10 segundos antes de aprender cualquier novedad)

1. **¿Valdrá más o menos cuando salga el próximo modelo?** — Si la skill te la trae de serie el próximo modelo, caducó. Si sabes dónde el negocio pierde dinero, cada modelo nuevo te hace *más* valioso, no menos.
2. **¿Lo necesito para un problema que tengo QUE resolver este mes?** — "Lo que aprendes por si acaso se olvida antes de utilizarlo."
3. **¿Mueve el número de alguien?** (ahorra horas, gana dinero, trae clientes) — Si no se conecta a un número, es entretenimiento: honeo, no "aprender para emprender".

Lo que no pasa el filtro **no se tira: se apunta a una lista de espera** y se revisa 30 min/semana, pasándolo por las mismas 3 preguntas.

## Las 5 habilidades (en orden — si saltas una, cae la siguiente)

| # | Habilidad | Quién la tiene | Esencia |
|---|-----------|----------------|---------|
| 1 | **Soft skills** | Oficinistas con años de hablar con jefes (media habilidad ya hecha) | Escuchar lo que duele, preguntar de verdad, explicar **en euros, no en nodos**. "Lo que el dueño no entiende, no lo compra." |
| 2 | **Entender el negocio** | Se aprende antes que tecnología | Saber cómo *entra* el dinero y por dónde *se escapa*. Si no sabes dónde pierde dinero, no sabes cómo arreglarlo. |
| 3 | **Dibujar procesos** | Cualquiera con papel | "Lo que no sabes dibujar no lo puedes automatizar." Pasos, quién, cuánto tarda, dónde se atasca. Caso Sara: 7 pasos, 2 se comen el 70% del tiempo (limpiar y cruzar). |
| 4 | **Medir** | "La que más dinero me ha hecho ganar" | **Lo que no mides no lo puedes cobrar.** Línea base antes de tocar nada → costo después → la diferencia es la prueba que justifica el cobro recurrente. |
| 5 | **Dominar la IA** | Fundamentos > trucos | Trucos = buen usuario (caducan). Fundamentos = buen director. |

Caso Sara: 6 h/semana en el informe = ~300 h/año (casi 2 meses) y llega 7 días tarde. Esos 2 números (horas y retraso) son lo que habla con el jefe. **Primero medir, luego pedir permiso — nadie dice que no a "300 horas al año".**

## El bucle (protocolo que nunca caduca)

1. **Contexto** — negocio, proceso dibujado, número objetivo (esa es tu línea base).
2. **Plan antes de ejecutar** — pedir el plan y corregirlo tú. "Equivocarse en el plan es barato; en la ejecución, caro."
3. **Ejecutar en pequeño** — fragmentar; nunca "hazme todo el sistema".
4. **Verificar** — comparar contra tu número; pedir a la propia IA que busque los fallos y casos más caros.
5. **Reglas** — "lo que corriges dos veces, lo escribes una vez". Cuando cambie el modelo, se revisa la regla, no se reescribe todo.

## Plan de 30 días (adaptado al caso, 1 práctica por habilidad/semana)

- **Semana 1** (hab. 1-2): Claude hace de dueño escéptico → ensayar 3 llamadas; hoja de cómo entra/sale el dinero.
- **Semana 2** (hab. 3): dibujar tu proceso en papel → foto → preguntarle al cuello de botella.
- **Semana 3** (hab. 4): cronometrar 5 días → tabla → línea base.
- **Semana 4** (hab. 5): bucle completo en cada uso → al día 30, 5 reglas escritas + antes/después.

**Por dónde empieza cada perfil:** no-técnico → habilidades 2 y 3 en su propio trabajo; **técnico → 1 y 4** (construir ya sabes; falta escuchar y demostrar con números); el que ya cobra por automatizar → 4 (su problema es cobrar una vez: llamar al último cliente y preguntar cuántas horas les ahorras → ese es tu precio recurrente).

## Errores propios de la agencia (advertencia)

Probaban cada herramienta el primer día → frustración, suelo subiendo. Cobraban 1.500 € por un flujo que hoy el cliente se monta en una tarde → "Esto lo hago yo con Claude". **Cambio: vender el número y el resultado, no la herramienta.** 3 reglas: (1) novedades pasan por las 3 preguntas; (2) ningún proyecto empieza sin un número antes; (3) lo corregido 2 veces se vuelve regla.

---

# 2. Video 2 — Stack para proyectos grandes (Fazt Code)

## El stack (tabla de decisiones)

| Capa | Elección | Alternativas / cuándo |
|------|----------|----------------------|
| **BD principal** | **Postgres** (80% de sus proyectos) | NoSQL (equivalente tipo Mongo) si el esquema es dinámico; **SQLite** para herramientas/CLI/sistemas propios (barato, backup = copiar archivo, corre en Raspberry); **Redis** = caché en RAM para respuestas frecuentes |
| **Backend** | **Go + Gin** (recomendación) | TS (Node/Bun/Deno) si compartes lógica con front; Python si hay libs de IA/data. Go: rápido, pocos recursos, bueno con IA para generarlo |
| **ORM/migraciones** | GORM (popular) | sqlx/sqlc, o migraciones SQL a mano |
| **Front (sin SEO)** | **React + Vite** (SPA) | Vue/Svelte equivalen |
| **Front (con SEO)** | **Next.js** (metaframework) | React+Vite = todo JS; Next renderiza HTML |
| **Monorepo** | **Solo si mismo lenguaje** (TS front+back) | Lenguajes distintos (Go+React) → repos separados; no hay lógica que compartir |
| **Móvil** | **React Native** (1 base, 2 plataformas) | Nativo (Swift/Kotlin) = mejor UX, más costo |
| **Escritorio** | **Tauri** (Rust por debajo, reusa el código web) | Nativo completo si máximo rendimiento |
| **IA: integración** | **CLI + skills** (agents locales) / **MCP** (chats remotos tipo ChatGPT) | El MCP = "una API encima de tu API": la IA no lee tu API, instala tu MCP con su doc |
| **Agentes/LLM** | Claude (contextos grandes) + ChatGPT; Claude Code como agente | Gemini para research. Editor: VS Code + plugin del agente; no pagar editor si ya pagas agente |
| **Deploy** | AWS / DigitalOcean / Railway / self-host | **GitHub Actions** (push → build → deploy), **GHCR** (containers), **Releases** (apps escritorio/CLI) |

Frases clave:
- El patrón **CLI + skills** es "la moda del día": si tu CLI está instalado, cualquier agente (Claude Code, Open Code, Trae…) puede operar tu backend; guardas la doc del CLI en un skill y la IA sabe usarlo.
- Los editores ya no importan: el trabajo lo hace el agente debajo.

## Aplicación a nuestros sistemas (honesto, con lo que existe hoy)

Nuestro stack real: **fondo** = Python (FastAPI + tests 236), **AgentBiz backend** = FastAPI + **aiosqlite** (SQLite ✓ — coincide con su recomendación para herramienta de un solo sistema), **AgentBiz frontend** = React + Vite (✓), **landing** = HTML estático en Pages (correcto: sin SEO complejo, rápido), **n8n** para automatización, portal con backoffice.

1. **SQLite está bien donde está** — él recomienda SQLite exactamente para "herramienta interna, pocos usuarios, backup fácil". No migrar a Postgres **hasta** que el portal/n8n necesite múltiples usuarios concurrentes o esquema que crezca con clientes reales. Entonces Postgres (y Redis solo si hay cuello de caché medido, no antes).
2. **CLI + skills para pilotear con IA**: exponer operaciones del fondo/portal/n8n como comandos CLI con doc = cualquier agente puede operarlos (nosotros y los clientes). El MCP es el siguiente paso cuando el cliente use ChatGPT/Desktop y no pueda instalar CLI.
3. **Deploy automático**: el portal cuando salga de fase local → GitHub Actions (push → tests → deploy). Releases para lo que sea CLI/escritorio.
4. **Go solo si aparece un cuello de botella medido** — hoy no lo hay; "mover a Go" falla el filtro #3 (no mueve número este mes).
5. **Monorepo**: sí si TS puro; nuestro caso Python+React → separado está bien.

---

# 3. Playlist — Harness Engineering (10 días + masterclass)

*Traducción de "harness" en las captions: honest/ANS/earnest; "Claude": cloud. Harness = el arnés: todo el sistema ingenierizado alrededor del modelo.*

## Mapa central (la idea que vale la serie)

**Raw model problem:** el LLM es un *text transformer* — tokens in, tokens out. **"Los modelos no hacen nada; describen la realización de las cosas"** (*Models don't do things. They describe the doing of things.*). Tool calling sigue siendo descripción: el modelo devuelve un *tool call*, nunca llama la función.

**Los 5 gaps** que todo modelo crudo tiene (y que el harness debe cerrar):

| Gap | Significado | Cierra con |
|-----|-------------|------------|
| No execution | no lee archivos, no corre scripts, no hace requests | tools |
| No durable state | cada llamada API es stateless; la "memoria de conversación" es una **ilusión** de reenviar el historial | memory |
| No fresh knowledge | no sabe nada post-training-cutoff; todo entra por prompt | context |
| No verification | puede *afirmar* pero no *verificar*; no corre el código | observability/evals |
| No environment | "un cerebro sin cuerpo"; sin filesystem/shell/red | environment |

**Definición de harness:** *"the engineered system surrounding a language model that turns its single output channel (text) into action, persistence and measurable behavior."* → **acción** (tools+environment), **persistencia** (memory), **comportamiento medible** (observability).

**Los 6 componentes** (el checklist de todo agente):
1. **The loop** — orquestador multi-turno: prompt → modelo → ¿tool call? → ejecuta → resultado al historial → siguiente turno, hasta *termination condition*.
2. **The tools** — superficie del modelo hacia el mundo.
3. **The context** — system prompt + historial + RAG + tool results (context engineering ≠ prompt engineering: el contexto es *moving target*, se decide **cada turno**).
4. **The environment** — runtime donde corren las tools: bounded, reproducible, inspectable.
5. **The memory** — short-term (sesión, full fidelity) + long-term (entre sesiones, comprimido, con presupuesto y **triggers definidos por código, no por el modelo**).
6. **The observability** — logs por llamada (contexto, respuesta, latencia, tokens), traces por sesión (trace ID → replay), evals (tarea fija + salida esperada + score → detecta degradación).

## Notas por día

- **Day 1 — Raw Model Program:** demo: se le pide a la API leer `article.txt` y escribir `summary.md` → el modelo admite que no puede y **no pasa nada en el mundo exterior**; a veces afirma que lo hizo y mintió. Lección: vender el harness, no al modelo. La memoria de conversación es reenviar todo el historial cada llamada.
- **Day 2 — The 6 Components:** el harness es "un stack de 6 preocupaciones", cada una puede estar bien o mal diseñada. Dominarlas = *literate about agents* (leer papers, depurar, comparar).
- **Day 3 — The Agent Loop:** forma del loop = capacidad del agente. Diseño: **termination condition** (palabra clave / stop sequence / **step budget** de 5-20 / umbral de 3 errores), **error handling que no rompe el loop** (el error vuelve al historial para que el modelo lo reporte como *observation*), y un patrón: **ReAct**, plan-then-act, multi-agent/orchestrator-worker, Ralph loop (deep recursion).
- **Day 4 — Tools:** *"Composability over monoliths"*; *"small sharp general-purpose tools beat specialized tools anytime"*. Caso Claude Code: `read, edit, bash, glob, grep` vs un agente de 50 tools bespoke. Ni micro-tools (`get_file_name` → `get_file_extension`…) ni monolitos (`analyze_web_page` que falla sin decir **qué** falló). Salidas estructuradas: éxito/fracaso distinguibles.
- **Day 5 — Context Layer:** system prompt = *control plane* (quién eres, qué tools, qué es buen comportamiento); `AGENTS.md` lo escribe el consumidor y también entra. Estrategias de historial: full replay / compaction / truncation. RAG: solo lo necesario ("no metas un libro de Python para un patrón Observer"). Caso **Cursor**: *"the context is the product"* — valorado ~$30B con los mismos modelos que todos.
- **Day 6 — Agent Environment:** **soft constraints** ("no borres mi archivo" en el prompt) *el modelo puede ignorar*; **hard constraints** las aplica el harness (workspace acotado, whitelist de red, DB sin DELETE). Reproducible = entorno limpio por task (si falla 2 veces igual, es del agente, no del entorno). Caso **Codex**: repo clonado en container desechable → cambios de vuelta como PR.
- **Day 7 — Memory:** la memoria es *responsabilidad del harness, no del modelo*. "Si le dejas al modelo decidir qué recordar, guardas cosas distintas en cada run e imposible de depurar." Long-term: perfil/preferencias sí; tool results arbitrarios no. Lectura también acotada (retrieval).
- **Day 8 — Observability:** sin medir, no puedes mejorar: *"You can't improve the harness if you can't measure whether your changes made things better or worse."* Nondeterminismo: cuando falle (y fallará) necesitas responder *¿qué hizo el modelo, en qué orden, con qué entradas y por qué?*. Harnesses han subido **~30% en benchmarks solo mejorando el harness**, sin tocar el modelo.
- **Day 9 — How It Connects:** *"An agent is basically a looped call wrapped around an LLM."* Flujo: prompt → modelo → tool → environment → observa → memory update → context assembly → siguiente turno. Observability envuelve todo (dashboards: Langfuse/LangSmith).
- **Day 10 — Case Study Claude Code:** loop ReAct + **step budget 15-20** (si no termina, empaqueta lo hecho y devuelve); tools mínimas componibles + MCP; memoria = `AGENTS.md` (estándar que usan Open Code, Codex…) en capas (repo/usuario/sistema); environment = máquina local con protección contra destructivas; la UI muestra cada tool call en tiempo real.
- **Masterclass (2 h):** consolida todo y da la **ruta de construcción**: raw model problem → demo de gaps → definición (3 verbos) → 6 componentes → arquitectura canónica → descomponer Claude Code → **construir desde cero**: loop → filesystem → tool registry → bash/code-execution → context+AGENTS.md → sandbox Docker → memory → framework de observability.

---

# 4. Aplicaciones a nuestros sistemas (la sección que importa)

## A) Metodología de piloto gratis (Task 3) — la más concreta

Cada piloto con cliente se ejecuta así (es el video 1 + harness, en 6 pasos):

1. **Escuchar** — llamada: ¿dónde duele? ¿dónde se pierde dinero/horas? (hab. 1).
2. **Dibujar** — su proceso en 5-7 pasos; marcar el paso que se come el tiempo (hab. 3, Gemba).
3. **Línea base (ANTES)** — cronometrar la realidad actual: horas/semana, $/mes, errores, retraso. **Sin número, no arranca el piloto** (hab. 4; ninguna de las 3 preguntas de Medina pasa sin número).
4. **Construir con el bucle** — contexto (proceso+número) → plan corregido → pieza pequeña → verificar contra el número → reglas.
5. **DESPUÉS + 5 reglas** — medir de nuevo; el antes/después **en números** es la entrega que justifica el retainer (hab. 4 es la que separa cobrar una vez vs. recurrente).
6. **Oferta de continuación** — "te ahorro N horas/mes" → retainer mensual (ya alineado con `oferta-agencia.md`).

## B) Agentes que construyamos (n8n, AgentBiz, clientes)

- **Checklist de arquitectura antes de entregar:** ¿loop? ¿tools? ¿context? ¿environment? ¿memory? ¿observability? — el día que un cliente diga "falló", sin logs/traces no puedes responder *qué pasó*.
- **Hard constraints, no solo prompts:** credenciales con permisos mínimos, workspace acotado, sin herramientas destructivas "controladas" por instrucción en el system prompt.
- **Tools pocas y compuestas** (`read/write/bash/fetch` + skills) en vez de una tool por cada feature del cliente.
- **Step budget + termination** en todo workflow con agente: coste acotado, loop que no se dispara.
- **evals ligeras:** 3-5 tareas fijas con salida esperada por integración; score antes/después de cada cambio de modelo → detectar degradación. (Ya lo hacemos con la suite del fondo — 236 tests —; extender el hábito a los agentes de clientes.)

## C) Fondo (Segundo Cerebro Capital)

- El **gate de robustez OOS + Monte Carlo** ya *es* observability/evals del sistema: el cambio solo se aprueba si el score no cae. Nada nuevo que tocar aquí; el video solo refuerza la regla: **no cambiar el modelo/estrategia sin número** (fallback honesto: sin verificación, el modelo afirma y no comprueba).

## D) Aprendizaje continuo (para aprobar con Carlos)

- Adoptar las **3 preguntas de Medina** como filtro de todo lo que aprendamos/nuevas herramientas: (1) ¿caduca con el próximo modelo? (2) ¿lo necesito este mes? (3) ¿mueve un número? Si no: lista de espera + **30 min/semana** de revisión.
- Regla 3 de su agencia = nuestra regla de TDD: *lo que corregimos dos veces, se vuelve regla/test*.
- **"Vender el número, no la herramienta":** ya es literalmente cómo presentamos la oferta ("2 h diarias → horas reales ahorradas") — mantener en todo copy de marca.

## E) Qué NO hacer (honestidad)

- No migrar stack por moda (Go/Postgres/Redis sin cuello de botella medido = no pasa el filtro #3).
- No prometer "agentes autónomos": sin environment+verification, el agente solo *recomienda* — decirlo claro al cliente.
- No comprar cursos de trucos ni perseguir cada modelo (video 1 y playlist coinciden: el valor está en el harness y el criterio).
- Nada de esto contradice la regla de la casa: **cero promesas de rendimiento**; los números de pilotos son horas ahorradas del cliente, no rendimientos.

---

# Resumen ejecutivo (para Carlos, 30 segundos)

1. **Video 1** = nuestro método de venta: dibujar proceso → medir baseline → construir con bucle → entregar antes/después → cobrar retainer. Es exactamente el diseño del Task 3 (2 pilotos gratis).
2. **Video 2** = confirmación de stack: lo que tenemos está bien; SQLite hasta donde dé, CLI+skills para que las IA operen nuestros sistemas, Actions para deploy, nada de migraciones por moda.
3. **Playlist** = la ingeniería seria de agentes: 6 componentes (loop, tools, context, environment, memory, observability) como checklist de calidad, hard constraints en vez de prompts, evals+logs desde el día 1.
4. **Acción propuesta:** filtrar novedades con sus 3 preguntas (30 min/semana) y aplicar la metodología de 6 pasos al primer piloto esta semana.
