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


memory = VikingMemory()
