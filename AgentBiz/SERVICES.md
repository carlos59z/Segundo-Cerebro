# Servicios de AgentBiz

| Servicio | URL | Puerto | Arranque |
|----------|-----|--------|----------|
| AgentBiz backend (uvicorn) | http://127.0.0.1:8000 | 8000 | `python -m uvicorn api.main:app --host 127.0.0.1 --port 8000` (desde `backend/`) |
| OpenViking (memoria oficina) | http://127.0.0.1:1933 | 1933 | `scripts/start-openviking.ps1` |

## Notas

- OpenViking requiere setup previo: `scripts/setup-openviking.ps1` (genera `~/.openviking/ov.conf` con NVIDIA NIM y las claves `OPENVIKING_URL`/`OPENVIKING_API_KEY` en el `.env`).
- Si OpenViking está apagado, AgentBiz degrada sin errores: el chat funciona igual y la memoria se omite.
- Health checks: `GET /api/health` (backend) · `GET /health` (OpenViking).
