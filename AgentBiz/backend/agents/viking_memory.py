# -*- coding: utf-8 -*-
"""Memoria de largo plazo de la oficina en OpenViking (servidor local).

Regla de la casa: el chat nunca falla por OpenViking. Cada operacion esta
envuelta en try/except; cualquier problema deja el modulo en `enabled=False`
y el flujo actual (SQLite) sigue igual.
"""
import logging
import os

log = logging.getLogger("viking_memory")

MEMORY_ROOT = "viking://memories/agents"
RETRIEVE_LIMIT = 3
MAX_CONTEXT_CHARS = 1600          # ~400 tokens
RETRIEVE_TIMEOUT_S = 1.5
SAVE_TIMEOUT_S = 2.0
ERROR_PREFIXES = (
    "Timeout", "Error curl", "respuesta vacia", "Error NVIDIA",
    "Error de red", "Error:", "Respuesta inesperada",
)


class VikingMemory:
    def __init__(self, client=None):
        self._client = client
        self._sessions_ready = set()
        self.enabled = False
        self.reason = "no conectado"

    def connect(self) -> bool:
        try:
            if self._client is None:
                from openviking_sdk import SyncHTTPClient
                url = os.environ.get("OPENVIKING_URL", "http://127.0.0.1:1933")
                key = os.environ.get("OPENVIKING_API_KEY", "")
                self._client = SyncHTTPClient(url=url, api_key=key)
            self._client.initialize()
            health = self._client.health()
            if not health:
                raise RuntimeError("health sin respuesta")
            self.enabled = True
            self.reason = ""
        except Exception as e:
            self.enabled = False
            self.reason = str(e)
            log.warning("openviking no disponible: %s", e)
        return self.enabled

    def _node_text(self, node) -> str:
        if isinstance(node, str):
            return node.strip()
        if not isinstance(node, dict):
            return ""
        parts = []
        for key in ("content", "text", "abstract", "overview"):
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
        if not parts:
            return ""
        uri = node.get("uri")
        joined = " — ".join(parts)
        return f"[{uri}] {joined}" if uri else joined

    def retrieve(self, agent_id: str, query: str) -> str:
        if not self.enabled:
            return ""
        try:
            result = self._client.find(
                query=query,
                limit=RETRIEVE_LIMIT,
                target_uri=f"{MEMORY_ROOT}/{agent_id}",
            )
            items = result if isinstance(result, list) else (
                result.get("nodes") or result.get("results") or []
                if isinstance(result, dict) else []
            )
            texts = [t for t in (self._node_text(n) for n in items) if t]
            return "\n".join(texts)[:MAX_CONTEXT_CHARS]
        except Exception as e:
            log.warning("viking retrieve fallo: %s", e)
            return ""


memory = VikingMemory()
