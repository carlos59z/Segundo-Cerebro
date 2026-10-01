import json
import sqlite3
import subprocess
import os
import tempfile
import urllib.request
from typing import List, Dict
from datetime import datetime

NVIDIA_API_KEY = "NVIDIA_KEY_REDACTED_BY_FILTER_REPO"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DB_PATH = "C:\\Users\\USUARIO\\OneDrive\\Desktop\\Segundo-Cerebro\\AgentBiz\\backend\\agentbiz.db"
CURL_PATH = "C:\\Windows\\System32\\curl.exe"
TRADER_API = "http://127.0.0.1:5001"

AGENT_MODELS = {
    "scout": "nvidia/nemotron-3-super-120b-a12b",
    "content": "nvidia/nemotron-3-super-120b-a12b",
    "affiliate": "google/gemma-4-31b-it",
    "trading": "nvidia/nemotron-3-super-120b-a12b",
    "freelancer": "nvidia/nemotron-3-super-120b-a12b",
    "social": "z-ai/glm-5.3",
    "analytics": "nvidia/nemotron-3-super-120b-a12b",
    "default": "nvidia/nemotron-3-super-120b-a12b",
}

AGENT_SYSTEM_PROMPTS = {
    "scout": "Eres SCOUT, investigador de oportunidades de negocio. Encuentra formas de ganar dinero online sin inversion. Responde en español, se especifico con plataformas y montos. Maximo 200 palabras.",

    "content": "Eres CONTENT, creador de contenido digital. Genera contenido atractivo y optimizado para SEO. Usa formato markdown con titulos y listas. Responde en español. Maximo 200 palabras.",

    "affiliate": "Eres AFFILIATE, experto en marketing de afiliados. Analiza productos y estrategias de promocion. Incluye comisiones estimadas y pasos concretos. Responde en español. Maximo 200 palabras.",

    "trading": "Eres TRADING, analista crypto. Analisis tecnico con niveles clave. DISCLAIMER: No es consejo financiero, solo educativo. Responde en español. Maximo 200 palabras.",

    "freelancer": "Eres FREELANCER, experto en generar ingresos independientes. Crea estrategias para conseguir clientes en Fiverr, Upwork, Workana. Responde en español. Maximo 200 palabras.",

    "social": "Eres SOCIAL, gestor de redes sociales. Crea estrategias de contenido para Instagram, TikTok, Twitter. Incluye hashtags y horarios. Responde en español. Maximo 200 palabras.",

    "analytics": "Eres ANALYTICS, director de datos. Analiza KPIs y metricas de negocio. Genera reportes ejecutivos con recomendaciones. Responde en español. Maximo 200 palabras.",
}

_FINAL_ONLY = (" Responde SOLO con la respuesta final en español. "
               "NO incluyas tu razonamiento, cadenas de pensamiento ni notas internas "
               "(nada de 'Okay, the user is asking...', 'Let me...', 'Wait...', 'Hmm...'). "
               "Empieza directamente con la respuesta.")
AGENT_SYSTEM_PROMPTS = {k: v + _FINAL_ONLY for k, v in AGENT_SYSTEM_PROMPTS.items()}

class ConversationMemory:
    def __init__(self):
        self.db_path = DB_PATH
        self._init_memory_table()

    def _init_memory_table(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()
            conn.close()
        except Exception:
            pass

    def get_history(self, agent_id: str, limit: int = 6) -> List[Dict]:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(
                "SELECT role, content FROM agent_memory WHERE agent_id = ? ORDER BY timestamp DESC LIMIT ?",
                (agent_id, limit)
            )
            rows = cursor.fetchall()
            conn.close()
            return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
        except Exception:
            return []

    def save_turn(self, agent_id: str, user_msg: str, ai_response: str):
        try:
            conn = sqlite3.connect(self.db_path)
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO agent_memory (agent_id, role, content, timestamp) VALUES (?, 'user', ?, ?)",
                (agent_id, user_msg, now)
            )
            conn.execute(
                "INSERT INTO agent_memory (agent_id, role, content, timestamp) VALUES (?, 'assistant', ?, ?)",
                (agent_id, ai_response, now)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

memory = ConversationMemory()

def ask_nvidia_sync(prompt: str, system: str = "", model: str = None,
                    max_tokens: int = 500, temperature: float = 0.7,
                    agent_id: str = None) -> str:
    if model is None:
        model = AGENT_MODELS.get(agent_id, AGENT_MODELS["default"])

    messages = []
    if system:
        messages.append({"role": "system", "content": system})

    if agent_id:
        history = memory.get_history(agent_id, limit=4)
        messages.extend(history)

    messages.append({"role": "user", "content": prompt})

    data = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    try:
        body = json.dumps(data)
        path = os.path.join(tempfile.gettempdir(), "nvidia_request.json")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(body)

        result = subprocess.run(
            [CURL_PATH, "-s", "--max-time", "60", "-X", "POST",
             f"{NVIDIA_BASE_URL}/chat/completions",
             "-H", f"Authorization: Bearer {NVIDIA_API_KEY}",
             "-H", "Content-Type: application/json",
             f"-d@{path}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=65
        )

        if result.stdout:
            resp = json.loads(result.stdout)
            if "choices" in resp and len(resp["choices"]) > 0:
                msg = resp["choices"][0]["message"]
                response = msg.get("content") or msg.get("reasoning_content") or "Sin respuesta del modelo"
                if response and len(response) > 10:
                    if agent_id:
                        memory.save_turn(agent_id, prompt, response)
                    return response
                else:
                    return "El modelo devolvio una respuesta muy corta. Intenta de nuevo."
            elif "error" in resp:
                return f"Error NVIDIA: {resp['error'].get('message', 'Unknown')}"
            else:
                return f"Respuesta inesperada: {result.stdout[:200]}"
        else:
            return f"Error: {result.stderr[:200] if result.stderr else 'Sin respuesta'}"

    except subprocess.TimeoutExpired:
        return "Timeout - el modelo esta tardando mucho. Intenta de nuevo."
    except Exception as e:
        return f"Error: {str(e)}"

async def ask_nvidia(prompt: str, system: str = "", model: str = None,
                     max_tokens: int = 500, temperature: float = 0.7,
                     agent_id: str = None) -> str:
    return ask_nvidia_sync(prompt, system, model, max_tokens, temperature, agent_id)

async def scout_research(topic: str) -> str:
    return await ask_nvidia(
        f" investiga y analiza oportunidades de negocio sobre: {topic}",
        system=AGENT_SYSTEM_PROMPTS["scout"],
        agent_id="scout"
    )

async def content_create(topic: str, content_type: str = "blog") -> str:
    return await ask_nvidia(
        f"Crea un {content_type} profesional sobre: {topic}",
        system=AGENT_SYSTEM_PROMPTS["content"],
        agent_id="content"
    )

async def affiliate_analyze(product: str) -> str:
    return await ask_nvidia(
        f"Analiza este producto/servicio para marketing de afiliados: {product}",
        system=AGENT_SYSTEM_PROMPTS["affiliate"],
        agent_id="affiliate"
    )

async def trading_analyze(crypto: str) -> str:
    return await ask_nvidia(
        f"Haz un analisis tecnico y fundamental de: {crypto}",
        system=AGENT_SYSTEM_PROMPTS["trading"],
        temperature=0.5,
        agent_id="trading"
    )

async def freelancer_strategy(service: str) -> str:
    return await ask_nvidia(
        f"Crea una estrategia completa para vender este servicio como freelancer: {service}",
        system=AGENT_SYSTEM_PROMPTS["freelancer"],
        agent_id="freelancer"
    )

async def social_strategy(brand: str) -> str:
    return await ask_nvidia(
        f"Crea una estrategia de redes sociales completa para: {brand}",
        system=AGENT_SYSTEM_PROMPTS["social"],
        agent_id="social"
    )

async def analytics_report(data: dict) -> str:
    return await ask_nvidia(
        f"Analiza estos datos y genera un reporte ejecutivo: {json.dumps(data, ensure_ascii=False)}",
        system=AGENT_SYSTEM_PROMPTS["analytics"],
        agent_id="analytics"
    )

async def chat_with_agent(agent_id: str, message: str) -> str:
    system = AGENT_SYSTEM_PROMPTS.get(agent_id, AGENT_SYSTEM_PROMPTS["scout"])
    return await ask_nvidia(message, system=system, agent_id=agent_id)

def _fetch_trader(symbol: str, interval: str, risk: str) -> dict:
    url = f"{TRADER_API}/api/operation/{symbol}?interval={interval}&risk={risk}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

async def trading_ai_analysis(symbol: str = "BTCUSDT", interval: str = "1h",
                              risk: str = "medium") -> dict:
    symbol = symbol.upper().replace("/", "").replace(":", "")
    try:
        data = _fetch_trader(symbol, interval, risk)
    except Exception as e:
        return {
            "error": True,
            "symbol": symbol,
            "response": f"Trader API no disponible (puerto 5001): {e}",
            "timestamp": datetime.now().isoformat()
        }

    analysis = data.get("analysis", {})
    operation = data.get("operation")
    prompt = (
        f"Analisis tecnico de {symbol} ({interval}):\n"
        f"{json.dumps(analysis, ensure_ascii=False)}\n\n"
        + (f"Parametros de operacion calculados:\n{json.dumps(operation, ensure_ascii=False)}\n\n"
           if operation else "Senal actual: HOLD (sin operacion sugerida).\n\n")
        + "Interpreta esto para el trader: fortaleza de la senal, niveles clave, "
          "que vigilar antes de operar y gestor de riesgo. Maximo 150 palabras, en espanol."
    )
    ai = await ask_nvidia(prompt, system=AGENT_SYSTEM_PROMPTS["trading"],
                          temperature=0.4, max_tokens=600, agent_id="trading")

    return {
        "error": False,
        "symbol": symbol,
        "interval": interval,
        "analysis": analysis,
        "operation": operation,
        "ai_interpretation": ai,
        "model": AGENT_MODELS.get("trading"),
        "timestamp": datetime.now().isoformat()
    }


async def risk_review(order: dict) -> dict:
    prompt = (
        "Evalua esta operacion paper del fondo Segundo Cerebro Capital segun los limites de fase "
        f"y aprueba o rechaza.\nOperacion: {json.dumps(order, ensure_ascii=False)}\n"
        "Responde en UNA linea exactamente con el formato: "
        "APRUEBA: <motivo corto>  o  RECHAZA: <motivo corto>."
    )
    raw = await ask_nvidia(prompt, system=AGENT_SYSTEM_PROMPTS["content"],
                           temperature=0.2, max_tokens=120, agent_id="content")
    text = (raw or "").strip()
    if "RECHAZA" in text.upper():
        return {"decision": "rechaza", "reason": text[:200]}
    return {"decision": "aprueba", "reason": text[:200]}
