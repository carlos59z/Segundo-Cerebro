import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()  # .env del raiz del repo; no pisa variables ya presentes

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import json
import asyncio
from datetime import datetime, timedelta

from memory.database import init_db, get_db
from agents.ai_brain import (
    scout_research, content_create, affiliate_analyze,
    trading_analyze, freelancer_strategy, social_strategy, analytics_report,
    chat_with_agent, trading_ai_analysis, AGENT_MODELS
)
from api.fund import router as fund_router

app = FastAPI(title="AgentBiz API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TaskRequest(BaseModel):
    agent_id: str
    title: str
    description: str
    priority: str = "medium"

class AgentQuery(BaseModel):
    query: str

class MessageRequest(BaseModel):
    from_agent: str
    to_agent: str
    content: str

class TradingAIRequest(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    risk: str = "medium"

class EarningRequest(BaseModel):
    agent_id: str
    source: str
    amount: float
    description: str = ""

from auto_trader import start_auto_trader
from broker_binance import execution_mode, load_keys


@app.on_event("startup")
async def startup():
    mode = execution_mode()  # EXECUTION_MODE invalido -> aborta arranque
    if mode != "paper":
        load_keys(mode)  # testnet/real sin keys -> fail-fast (spec §6)
    init_db()
    start_auto_trader()

AGENT_MAP = {
    'scout': scout_research,
    'content': content_create,
    'affiliate': affiliate_analyze,
    'trading': trading_analyze,
    'freelancer': freelancer_strategy,
    'social': social_strategy,
    'analytics': analytics_report,
}

@app.get("/api/agents")
async def get_agents():
    db = get_db()
    agents = db.execute("SELECT * FROM agents").fetchall()
    db.close()
    result = []
    for a in agents:
        d = dict(a)
        d['model'] = AGENT_MODELS.get(a['id'], AGENT_MODELS['default'])
        result.append(d)
    return result

@app.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str):
    db = get_db()
    agent = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    db.close()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    d = dict(agent)
    d['model'] = AGENT_MODELS.get(agent_id, AGENT_MODELS['default'])
    return d

@app.post("/api/agents/{agent_id}/query")
async def query_agent(agent_id: str, req: AgentQuery):
    db = get_db()
    agent = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not agent:
        db.close()
        raise HTTPException(status_code=404, detail="Agent not found")

    db.execute("UPDATE agents SET status = 'working', last_active = ? WHERE id = ?",
               (datetime.now().isoformat(), agent_id))
    db.commit()

    func = AGENT_MAP.get(agent_id)
    if not func:
        db.close()
        raise HTTPException(status_code=400, detail="Unknown agent")

    try:
        if agent_id == 'analytics':
            result = await func({"query": req.query})
        else:
            result = await func(req.query)
    except Exception as e:
        result = f"Error: {str(e)}"

    db.execute("UPDATE agents SET status = 'idle', tasks_completed = tasks_completed + 1 WHERE id = ?", (agent_id,))
    db.execute("INSERT INTO tasks (agent_id, title, description, status, result) VALUES (?, ?, ?, 'completed', ?)",
               (agent_id, req.query[:100], req.query, result))
    db.execute("INSERT INTO messages (from_agent, to_agent, content, message_type) VALUES (?, 'user', ?, 'query')",
               (agent_id, req.query[:200]))
    db.commit()
    db.close()

    return {"agent": agent_id, "response": result, "model": AGENT_MODELS.get(agent_id, 'unknown'), "timestamp": datetime.now().isoformat()}

@app.get("/api/tasks")
async def get_tasks(limit: int = 50, agent_id: str = None):
    db = get_db()
    if agent_id:
        tasks = db.execute("SELECT * FROM tasks WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?", (agent_id, limit)).fetchall()
    else:
        tasks = db.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    db.close()
    return [dict(t) for t in tasks]

@app.post("/api/tasks")
async def create_task(req: TaskRequest):
    db = get_db()
    db.execute("INSERT INTO tasks (agent_id, title, description, priority) VALUES (?, ?, ?, ?)",
               (req.agent_id, req.title, req.description, req.priority))
    db.commit()
    db.close()
    return {"status": "created"}

@app.post("/api/tasks/auto")
async def auto_create_tasks():
    db = get_db()
    auto_tasks = [
        ("scout", "Analizar tendencias del dia", "Investigar las trending topics en Twitter, Google Trends y Reddit para encontrar oportunidades de negocio.", "high"),
        ("content", "Crear post blog semanal", "Generar un articulo SEO sobre la oportunidad mas rentable encontrada por Scout.", "medium"),
        ("affiliate", "Revisar comisiones", "Analizar las mejores ofertas de afiliados en Amazon, ClickBank y ShareASale.", "medium"),
        ("trading", "Analisis BTC y ETH", "Hacer analisis tecnico completo de Bitcoin y Ethereum con niveles clave.", "high"),
        ("freelancer", "Buscar clientes Fiverr", "Identificar los 5 servicios mas demandados en Fiverr y crear propuestas.", "low"),
        ("social", "Calendario semanal", "Crear calendario de contenido para Instagram y TikTok de la semana.", "medium"),
        ("analytics", "Reporte diario", "Generar reporte de metricas del sistema: tareas, ingresos, agentes activos.", "high"),
    ]
    created = 0
    for agent_id, title, desc, priority in auto_tasks:
        existing = db.execute("SELECT id FROM tasks WHERE agent_id = ? AND title = ? AND status != 'completed'", (agent_id, title)).fetchone()
        if not existing:
            db.execute("INSERT INTO tasks (agent_id, title, description, priority, status) VALUES (?, ?, ?, ?, 'pending')",
                       (agent_id, title, desc, priority))
            created += 1
    db.commit()
    db.close()
    return {"created": created, "message": f"{created} tareas auto-creadas"}

@app.get("/api/earnings")
async def get_earnings():
    db = get_db()
    earnings = db.execute("SELECT * FROM earnings ORDER BY created_at DESC").fetchall()
    total = db.execute("SELECT SUM(amount) as total FROM earnings").fetchone()
    today = db.execute("SELECT SUM(amount) as total FROM earnings WHERE date(created_at) = date('now')").fetchone()
    month = db.execute("SELECT SUM(amount) as total FROM earnings WHERE created_at >= date('now', 'start of month')").fetchone()
    by_agent = db.execute("SELECT agent_id, SUM(amount) as total FROM earnings GROUP BY agent_id").fetchall()
    db.close()
    return {
        "total": total['total'] or 0,
        "today": today['total'] or 0,
        "month": month['total'] or 0,
        "by_agent": {r['agent_id']: r['total'] for r in by_agent},
        "records": [dict(e) for e in earnings]
    }

@app.post("/api/earnings")
async def add_earning(req: EarningRequest):
    db = get_db()
    db.execute("INSERT INTO earnings (agent_id, source, amount, description) VALUES (?, ?, ?, ?)",
               (req.agent_id, req.source, req.amount, req.description))
    db.execute("UPDATE agents SET earnings = earnings + ? WHERE id = ?", (req.amount, req.agent_id))
    db.commit()
    db.close()
    return {"status": "added"}

@app.get("/api/opportunities")
async def get_opportunities():
    db = get_db()
    opps = db.execute("SELECT * FROM opportunities ORDER BY created_at DESC").fetchall()
    db.close()
    return [dict(o) for o in opps]

@app.post("/api/opportunities")
async def add_opportunity(data: dict):
    db = get_db()
    db.execute("INSERT INTO opportunities (title, description, source, potential_earnings, assigned_agent) VALUES (?, ?, ?, ?, ?)",
               (data.get('title', ''), data.get('description', ''), data.get('source', ''), data.get('potential_earnings', 0), data.get('assigned_agent', '')))
    db.commit()
    db.close()
    return {"status": "created"}

@app.get("/api/messages")
async def get_messages(limit: int = 50):
    db = get_db()
    msgs = db.execute("SELECT * FROM messages ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    db.close()
    return [dict(m) for m in msgs]

@app.post("/api/messages")
async def send_message(req: MessageRequest):
    db = get_db()
    db.execute("INSERT INTO messages (from_agent, to_agent, content) VALUES (?, ?, ?)",
               (req.from_agent, req.to_agent, req.content))
    db.commit()
    db.close()
    return {"status": "sent"}

@app.get("/api/stats")
async def get_stats():
    db = get_db()
    agents = db.execute("SELECT COUNT(*) as count FROM agents").fetchone()
    tasks = db.execute("SELECT COUNT(*) as count FROM tasks").fetchone()
    completed = db.execute("SELECT COUNT(*) as count FROM tasks WHERE status='completed'").fetchone()
    pending = db.execute("SELECT COUNT(*) as count FROM tasks WHERE status='pending'").fetchone()
    total_earnings = db.execute("SELECT SUM(amount) as total FROM earnings").fetchone()
    active = db.execute("SELECT COUNT(*) as count FROM agents WHERE status='working'").fetchone()
    opps = db.execute("SELECT COUNT(*) as count FROM opportunities").fetchone()
    today_tasks = db.execute("SELECT COUNT(*) as count FROM tasks WHERE date(created_at) = date('now')").fetchone()
    today_earnings = db.execute("SELECT SUM(amount) as total FROM earnings WHERE date(created_at) = date('now')").fetchone()
    week_earnings = db.execute("SELECT SUM(amount) as total FROM earnings WHERE created_at >= date('now', '-7 days')").fetchone()

    agent_stats = db.execute("""
        SELECT a.id, a.name, a.avatar, a.tasks_completed, a.earnings, a.status,
               (SELECT COUNT(*) FROM tasks t WHERE t.agent_id = a.id AND t.status='pending') as pending_tasks
        FROM agents a
    """).fetchall()

    recent_tasks = db.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 10").fetchall()
    db.close()

    return {
        "total_agents": agents['count'],
        "total_tasks": tasks['count'],
        "completed_tasks": completed['count'],
        "pending_tasks": pending['count'],
        "active_agents": active['count'],
        "total_earnings": total_earnings['total'] or 0,
        "today_tasks": today_tasks['count'],
        "today_earnings": today_earnings['total'] or 0,
        "week_earnings": week_earnings['total'] or 0,
        "opportunities": opps['count'],
        "agent_stats": [dict(a) for a in agent_stats],
        "recent_tasks": [dict(t) for t in recent_tasks],
    }

@app.get("/api/activity")
async def get_activity(limit: int = 30):
    db = get_db()
    tasks = db.execute("SELECT t.*, a.name as agent_name, a.avatar FROM tasks t LEFT JOIN agents a ON t.agent_id = a.id ORDER BY t.created_at DESC LIMIT ?", (limit,)).fetchall()
    earnings = db.execute("SELECT e.*, a.name as agent_name FROM earnings e LEFT JOIN agents a ON e.agent_id = a.id ORDER BY e.created_at DESC LIMIT 10").fetchall()
    msgs = db.execute("SELECT * FROM messages ORDER BY created_at DESC LIMIT 10").fetchall()
    db.close()
    return {
        "tasks": [dict(t) for t in tasks],
        "earnings": [dict(e) for e in earnings],
        "messages": [dict(m) for m in msgs],
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            await websocket.send_json({"type": "ack", "data": msg})
    except WebSocketDisconnect:
        pass

@app.post("/api/chat/{agent_id}")
async def chat(agent_id: str, req: AgentQuery):
    """Chat directo con un agente"""
    db = get_db()
    agent = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not agent:
        db.close()
        raise HTTPException(status_code=404, detail="Agente no encontrado")

    db.execute("UPDATE agents SET status = 'working', last_active = ? WHERE id = ?",
               (datetime.now().isoformat(), agent_id))
    db.commit()

    try:
        result = await chat_with_agent(agent_id, req.query)
    except Exception as e:
        result = f"Error: {str(e)}"

    db.execute("UPDATE agents SET status = 'idle', tasks_completed = tasks_completed + 1 WHERE id = ?", (agent_id,))
    db.execute("INSERT INTO tasks (agent_id, title, description, status, result) VALUES (?, ?, ?, 'completed', ?)",
               (agent_id, req.query[:100], req.query, result))
    db.commit()
    db.close()

    return {
        "agent": agent_id,
        "response": result,
        "model": AGENT_MODELS.get(agent_id, 'unknown'),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/trading/ai")
async def trading_ai(req: TradingAIRequest):
    """Analisis tecnico + interpretacion IA (Trader API + NVIDIA NIM)"""
    db = get_db()
    db.execute("UPDATE agents SET status = 'working', last_active = ? WHERE id = 'trading'",
               (datetime.now().isoformat(),))
    db.commit()

    result = await trading_ai_analysis(req.symbol, req.interval, req.risk)

    db.execute("UPDATE agents SET status = 'idle', tasks_completed = tasks_completed + 1 WHERE id = 'trading'")
    db.execute("INSERT INTO tasks (agent_id, title, description, status, result) VALUES ('trading', ?, ?, 'completed', ?)",
               (f"Trading AI: {req.symbol} {req.interval}", f"{req.symbol} {req.interval} risk={req.risk}",
                result.get("ai_interpretation", str(result.get("response", "")))))
    db.commit()
    db.close()
    return result

app.include_router(fund_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "AgentBiz", "version": "2.0.0", "models": AGENT_MODELS}
