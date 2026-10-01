import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'agentbiz.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT DEFAULT 'idle',
        avatar TEXT,
        description TEXT,
        tasks_completed INTEGER DEFAULT 0,
        earnings REAL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_active TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'pending',
        priority TEXT DEFAULT 'medium',
        result TEXT,
        earnings REAL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        FOREIGN KEY (agent_id) REFERENCES agents(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT,
        key TEXT NOT NULL,
        value TEXT,
        category TEXT DEFAULT 'general',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (agent_id) REFERENCES agents(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS earnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT,
        source TEXT,
        amount REAL,
        currency TEXT DEFAULT 'USD',
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (agent_id) REFERENCES agents(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_agent TEXT,
        to_agent TEXT,
        content TEXT,
        message_type TEXT DEFAULT 'info',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        source TEXT,
        potential_earnings REAL,
        status TEXT DEFAULT 'new',
        assigned_agent TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    default_agents = [
        ('scout', 'Scout', 'Analista de Mercados', '🔍', 'Vigila crypto/ETF/acciones/forex/futuros; detecta oportunidades y tendencias'),
        ('content', 'Content', 'Director de Riesgo', '⚖️', 'Aprueba/rechaza operaciones; vigila drawdown, exposicion y limites por fase'),
        ('affiliate', 'Affiliate', 'Conexiones', '🔗', 'Puesto para fase real: API keys de exchange/broker'),
        ('trading', 'Trading', 'Mesa de Operaciones', '📈', 'Senales BUY/SELL con SL/TP; ejecuta paper trades'),
        ('freelancer', 'Freelancer', 'Desarrollo', '💼', 'Implementa SPECs ganadoras en el motor de trading'),
        ('social', 'Social', 'Comunicaciones', '📱', 'Reporte diario a Telegram: PnL, operaciones, senales, ganadora'),
        ('analytics', 'Analytics', 'Director de Estrategias', '📊', 'Backtesting, ranking y ciclo de investigación'),
    ]
    
    for agent in default_agents:
        c.execute('''INSERT OR IGNORE INTO agents (id, name, role, avatar, description) 
                     VALUES (?, ?, ?, ?, ?)''', agent)

    for aid, name, role, avatar, desc in default_agents:
        c.execute('''UPDATE agents SET name=?, role=?, avatar=?, description=? WHERE id=?''',
                  (name, role, avatar, desc, aid))
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Base de datos inicializada.")
