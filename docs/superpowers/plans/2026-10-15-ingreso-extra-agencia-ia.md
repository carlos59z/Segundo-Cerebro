# Plan: Ingreso Extra — Agencia de Automatización IA + Marca Segundo Cerebro

> **Para ejecutores:** usar `superpowers:executing-plans`. Steps con checkbox (`- [ ]`).
> Decisión de negocio grande (gastos, cobrar, contratar) → aprobación de Carlos primero.

**Goal:** Generar ingreso extra en 90 días con servicios de automatización IA para PYMEs LatAm, alimentados por la marca "Segundo Cerebro", sin promesas de rendimiento ni atajos.

**Approach:** Marca primero (contenido honesto), evidencia antes de cobrar (pilotos gratis medibles), luego paquete fijo + retainer. El portal-reembolsos se convierte en producto vertical en fase 4. El fondo de trading sigue SOLO en paper y no se mezcla con este plan.

**Stack:** AgentBiz (agentes), n8n (workflows), Next.js/WhatsApp (portales), Python. ES/EN.

**Spec/Reglas:** `AGENTS.md` — reglas Squibb (5 reglas madre + accionables) y reglas de honestidad. Este plan argumenta desde ahí.

## Global Constraints
- Sin promesas de rendimiento ni resultados garantizados (honestidad).
- Delayed gratification: NO se cobra hasta tener evidencia medible del piloto.
- Gasto comprometido > $100 o precio público → aprobación previa de Carlos.
- Cliente malo (spider-sense rojo) → se dice que no, aunque pague.
- Marca > negocio: el contenido continúa aunque no haya ventas esa semana.
- Trading/fondo: territorio separado, gate OOS, sin mezclar con clientes.
- Ritmo: maratón, no sprint — hitos no se apuran por ansiedad.

## Review Focus (riesgos más probables)
1. **Agencia genérica "AI agency" en mercado saturado** → diferenciar por vertical (agencias/expedientes) y casos con números; el plan exige caso de estudio antes de cobrar.
2. **Piloto gratis que nunca se convierte** → fecha límite de conversión por piloto (Task 3), máximo 6 semanas.
3. **Carlos como cuello de botella en ventas** → cada paso deja artefacto reutilizable (landing, pitch, checklist de llamada).
4. **Scope/servicio que se sale de lo que sabemos construir** → solo vender lo ya probado internamente (agentes, WhatsApp, workflows).
5. **Cambios de WhatsApp API (billing ene-2026, ban de chatbots genéricos)** → usar solo BSP oficial Meta y agentes especializados por tarea.

---

### Task 0: Canal tiempo-sensible — Startup Venezuela Summit (21-23 oct 2026, Caracas)

**Decision de Carlos (antes del 20-oct):** ¿asistir? Si NO → cerrar task, seguir con Fase 1.

**Steps:**
- [ ] Confirmar asistencia + cupo/registro.
- [ ] Preparar pitch de 1 página (quién soy / qué construyo / qué ofrezco / qué busco) — 60 min.
- [ ] Lista de 10 contactos objetivo (fundadores, dueños de PYMEs, mentores).
- [ ] Meta: 3 conversaciones reales sobre problemas automatizables (escuchar, no vender — ventas en 3 pasos: ¿te necesito? primero).
- [ ] De vuelta: notas en `03-Trabajo/summit_2026_notas.md`.

**Hecho cuando:** notas con ≥3 leads/calificados anotados (o task cancelado con decisión registrada).

---

### Task 1: Oferta + landing (semanas 1-2)

**Files:**
- Create: `AgentBiz/docs/oferta-agencia.md` (paquete y precios de referencia)
- Create: landing estática en el stack Next existente (repo nuevo o rama; 1 página)

**Contenido concreto de la oferta (precios referenciales del mercado 2026):**
- **Diagnóstico gratis:** auditoría de 30 min + plan escrito con precio fijo (give without take).
- **Build:** $500–1,500 según alcance (workflows + agente WhatsApp especializado).
- **Retainer:** $150–500/mes (mantenimiento, mejoras, métricas).
- Lenguaje de venta: resultado del cliente, no feature list (vender el sizzle).

**Steps:**
- [ ] Escribir `oferta-agencia.md` con los 3 tiers y 3 casos de uso (retail, servicios, agencias).
- [ ] Landing de 1 página: problema → solución → proceso (diagnóstico→build→retainer) → contacto WhatsApp.
- [ ] Publicar landing + probar en móvil.
- [ ] Commit + push.

**Hecho cuando:** URL pública responde 200 y el mensaje pasa el test de honestidad (sin palabras tipo "garantizado/gana").

---

### Task 2: Marca en contenido (semanal, continuo desde semana 1)

**Steps:**
- [ ] Elegir canal principal (recomendado: LinkedIn; opcional YouTube después).
- [ ] Calendario de 4 semanas de temas (2 agringados/2 en ES): casos reales de automatización, detrás de cámaras del piloto, mitos de IA sin exagerar.
- [ ] Publicar 1 post/semana durante 4 semanas mínimo.
- [ ] Cada post = dar valor primero; CTA suave al diagnóstico gratis.
- [ ] Registrar métricas (views, DMs, clics) en `AgentBiz/docs/marca-metricas.md`.

**Hecho cuando:** 4 posts publicados + ≥1 conversación entrante de un potencial cliente.

---

### Task 3: 2 pilotos GRATIS con evidencia medible (semanas 3-6)

**Reglas del piloto:** gratis, 2–4 semanas, con baseline antes/después, fecha límite de conversión a pago (máx. semana 6). Elegir cliente cuyo spider-sense diga que sí.

**Steps:**
- [ ] Seleccionar 2 negocios reales de la red de Carlos (perfil: ≥1 persona atendiendo WhatsApp/correo manualmente).
- [ ] Baseline: medir horas/semana en la tarea antes de tocar nada.
- [ ] Construir: agente/workflow especializado (una tarea acotada, no "automatizar todo").
- [ ] Medir después: horas ahorradas, tiempo de respuesta, errores.
- [ ] Caso de estudio de 1 página con números + permiso de cita del cliente.
- [ ] Ofrecer plan de pago (paquete Task 1) antes de la fecha límite; si dice no → agradecer y pedir testimonio/referral.

**Hecho cuando:** ≥1 caso de estudio publicado con números reales y ≥1 decisión de pago (sí/no) antes de la semana 6.

---

### Task 4: Primeros clientes pagos + MRR (meses 2-3)

**Meta honesta:** $500–1,000 MRR con 3–5 clientes (no proyectar más sin evidencia).

**Steps:**
- [ ] Pipeline: leads de Task 0 + Task 2 + referidos de pilotos → checklist de llamada (problema actual, costo actual, ¿me necesito?).
- [ ] Cerrar 2–3 clientes en build + retainer.
- [ ] Contrato simple de 1 página (alcance, precio, mes a mes, salida limpia).
- [ ] Onboarding automatizado con plantillas (reutilizar del piloto).
- [ ] Revisión semanal de pipeline (15 min) + log en `AgentBiz/docs/pipeline.md`.

**Hecho cuando:** ≥2 clientes pagando y MRR registrado 2 meses seguidos.

---

### Task 5: Vertical portal-reembolsos como SaaS (mes 3+)

**Prerequisito:** Task 4 con ≥2 clientes pagando (no antes).

**Steps:**
- [ ] Lista de 20 agencias/asesorías con expedientes (contactos de Carlos).
- [ ] Demo con el portal real (flujo cliente → expediente → WhatsApp → backoffice).
- [ ] Precio SaaS: $30–150/mes + setup.
- [ ] 1 cliente vertical cerrado → decide si se abre como producto independiente.

**Hecho cuando:** 1 agencia pagando o decisión documentada de pausar.

---

### Task 6: Vigilancia SENIAT facturación electrónica (continuo, coste cero)

- [ ] Chequeo mensual de noticias del anuncio de la app del SENIAT para pymes.
- [ ] Si hay fecha: preparar plantilla de automatización de facturación (Task del plan Fase 5) y avisar a Carlos con números.

---

## Criterios globales de éxito (90 días)
| Métrica | Meta |
|---|---|
| Posts publicados | ≥12 |
| Casos de estudio con números | ≥1 |
| Clientes pagando | ≥2 |
| MRR | $500–1,000 |
| Pilotos convertidos | ≥50% o lección documentada |

## Fuera de alcance (hasta nuevo aviso)
- Capital real en trading (queda en paper hasta gate OOS).
- Contratar equipo / socios (regla equity 50/50 cuando aplique).
- Gastos de anuncios pagados (orgánico primero).
