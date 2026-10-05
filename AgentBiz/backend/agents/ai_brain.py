import json
import sqlite3
import subprocess
import os
import asyncio
import tempfile
import urllib.request
from typing import List, Dict
from datetime import datetime


def _load_secret(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    here = os.path.dirname(os.path.abspath(__file__))
    for env_path in (
        os.path.join(here, "..", "..", "..", ".env"),      # raiz del repo
        os.path.join(here, "..", ".env"),                  # AgentBiz/.env
        os.path.join(here, "..", "..", "backend", ".env"), # AgentBiz/backend/.env
    ):
        try:
            with open(env_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith(name + "="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return default


NVIDIA_API_KEY = _load_secret("NVIDIA_API_KEY")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DB_PATH = os.environ.get("AGENTBIZ_DB") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agentbiz.db"))
CURL_PATH = "C:\\Windows\\System32\\curl.exe"
TRADER_API = "http://127.0.0.1:5001"

AGENT_MODELS = {
    "scout": "google/gemma-4-31b-it",
    "content": "nvidia/nemotron-3-super-120b-a12b",
    "affiliate": "google/gemma-4-31b-it",
    "trading": "nvidia/nemotron-3-super-120b-a12b",
    "freelancer": "nvidia/nemotron-3-super-120b-a12b",
    "social": "google/gemma-4-31b-it",
    "analytics": "nvidia/nemotron-3-super-120b-a12b",
    "default": "nvidia/nemotron-3-super-120b-a12b",
}

AGENT_SYSTEM_PROMPTS = {
    "scout": "Eres el ANALISTA DE MERCADOS del fondo Segundo Cerebro Capital. Vigilas crypto, ETF, acciones, forex y futuros: detectas oportunidades, tendencias y niveles clave con datos concretos (precio, %, soportes/resistencias). Reportas a Investigación. DISCLAIMER: educativo, no es consejo financiero. Español, maximo 200 palabras.",

    "trading": "Eres la MESA DE OPERACIONES de Segundo Cerebro Capital. Das senales BUY/SELL/HOLD con SL/TP, apalancamiento y tamano de posicion para los 5 mercados, usando SOLO paper trading ($2,500 simulados) con los limites de la fase vigente. DISCLAIMER: educativo, no es consejo financiero. Español, maximo 200 palabras.",

    "analytics": "Eres el DIRECTOR DE ESTRATEGIAS de Segundo Cerebro Capital. Manejas backtesting, ranking de estrategias y el ciclo de investigación (hipótesis -> SPEC -> backtest -> elegir la ganadora). Cites metricas reales: Sharpe, retorno, drawdown, win rate. Español, maximo 200 palabras.",

    "content": "Eres el DIRECTOR DE RIESGO de Segundo Cerebro Capital. Apruebas o rechazas operaciones segun los limites de la fase (riesgo por operacion, apalancamiento maximo, posiciones, stop diario, drawdown) y vigilas que el fondo nunca opere sin supervisión. Respondes APRUEBA: o RECHAZA: con motivo corto cuando evalúes una operacion. Español, maximo 200 palabras.",

    "social": "Eres COMUNICACIONES de Segundo Cerebro Capital. Preparas el reporte diario para Telegram: PnL del dia, PnL total, operaciones abiertas/cerradas, win rate, drawdown, senales activas y la estrategia ganadora. Formato claro con emojis de mercado. Español, maximo 200 palabras.",

    "freelancer": "Eres DESARROLLO de Segundo Cerebro Capital. Implementas en el motor (strategies.py/backtester.py) las SPECs ganadoras del ciclo de investigación y mantienes el codigo de las estrategias con tests. Respondes con cambios concretos de codigo cuando se te pida. Español, maximo 200 palabras.",

    "affiliate": "Eres CONEXIONES de Segundo Cerebro Capital. Puesto preparado para la fase real: integración de API keys de exchange/broker cuando el CEO lo apruebe. Por ahora solo documentas requisitos, permisos y riesgos de cada exchange. Español, maximo 200 palabras.",
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
                    max_tokens: int = 1000, temperature: float = 0.7,
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

    last_error = "Sin respuesta"
    # archivo temporal propio por llamada: dos chats concurrentes no deben
    # pisarse el mismo nvidia_request.json (race en el feed de la oficina)
    fd, body_path = tempfile.mkstemp(prefix="nvidia_request_", suffix=".json")
    os.close(fd)
    try:
        with open(body_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data))

        for _attempt in range(2):  # reintento unico ante fallo de transporte o respuesta vacia
            result = subprocess.run(
                [CURL_PATH, "-s", "--show-error", "--max-time", "60", "-X", "POST",
                 f"{NVIDIA_BASE_URL}/chat/completions",
                 "-H", f"Authorization: Bearer {NVIDIA_API_KEY}",
                 "-H", "Content-Type: application/json",
                 f"-d@{body_path}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=65
            )

            if result.returncode != 0 or not (result.stdout or "").strip():
                # fallo de transporte: con -s el motivo se perdia; ahora sale del exit code
                rc = result.returncode
                if rc == 28:
                    last_error = "Timeout - el modelo tardo mas de 60s. Intenta de nuevo."
                elif rc in (6, 7, 22, 35, 52, 56):
                    last_error = f"Error de red (curl {rc}): {(result.stderr or '').strip()[:200] or 'sin detalle'}"
                else:
                    last_error = f"Error curl (codigo {rc}): {(result.stderr or '').strip()[:200] or 'sin salida'}"
                continue

            try:
                resp = json.loads(result.stdout)
            except ValueError:
                last_error = "Respuesta ilegible del modelo (JSON invalido). Intenta de nuevo."
                continue

            if "choices" in resp and len(resp["choices"]) > 0:
                msg = resp["choices"][0]["message"]
                # cualquier contenido no vacio es valido: no cortar por longitud
                # (un "FUNCIONA" o "APRUEBA: si" es una respuesta legitima)
                response = ((msg.get("content") or "").strip()
                            or (msg.get("reasoning_content") or "").strip())
                if response:
                    if agent_id:
                        memory.save_turn(agent_id, prompt, response)
                    return response
                last_error = "El modelo devolvio una respuesta vacia. Intenta de nuevo."
                continue
            elif "error" in resp:
                # error de la API (autenticacion, modelo): el reintento no ayuda
                return f"Error NVIDIA: {resp['error'].get('message', 'Unknown')}"
            else:
                return f"Respuesta inesperada: {result.stdout[:200]}"

    except subprocess.TimeoutExpired:
        last_error = "Timeout - el modelo esta tardando mucho. Intenta de nuevo."
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass

    return last_error

async def ask_nvidia(prompt: str, system: str = "", model: str = None,
                     max_tokens: int = 1000, temperature: float = 0.7,
                     agent_id: str = None) -> str:
    return await asyncio.to_thread(
        ask_nvidia_sync, prompt, system, model, max_tokens, temperature, agent_id)

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
    return await ask_nvidia(message, system=system, agent_id=agent_id,
                            max_tokens=4000)

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
                          temperature=0.4, max_tokens=1500, agent_id="trading")

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
                           model="google/gemma-4-31b-it",
                           temperature=0.2, max_tokens=300, agent_id="content")
    text = (raw or "").strip()
    upper = text.upper()
    if upper.startswith("APRUEBA"):
        return {"decision": "aprueba", "reason": text[:200]}
    # RECHAZA explícito o cualquier salida no interpretable (timeout, error de
    # API, formato raro) -> rechaza: una revision que no corrió no aprueba.
    return {"decision": "rechaza", "reason": text[:200]}
