"""Calendario economico (ForexFactory) como filtro de aperturas del fondo.

Feed publico semanal sin API key. Eventos de impacto "High" bloquean
aperturas en una ventana corta alrededor del evento (crypto/bolsa por
USD o All; forex por sus divisas). Fail-open: si el feed falla y no hay
cache, no bloquea.
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_TTL_HOURS = 6
HIGH_IMPACT = "High"
DEFAULT_WINDOW_MINUTES = 90

_default_cache = {"events": None, "ts": None}


def _default_fetch():
    req = urllib.request.Request(
        FEED_URL, headers={"User-Agent": "Segundo-Cerebro-Fund/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_events(fetcher=None, cache=None):
    """Eventos parseados y ordenados. fetcher/cache inyectables para tests.

    fetcher explícito => modo puro: no lee ni escribe caché (ideal tests);
    solo la ruta de red real usa y actualiza la caché.
    """
    cache = _default_cache if cache is None else cache
    if fetcher is not None:
        try:
            raw = fetcher()
        except Exception:
            return cache.get("events") or []
        return _parse(raw)
    now = datetime.now(timezone.utc)
    ts = cache.get("ts")
    if (cache.get("events") is not None and ts
            and now - ts < timedelta(hours=CACHE_TTL_HOURS)):
        return cache["events"]
    try:
        raw = _default_fetch()
    except Exception:
        return cache.get("events") or []
    events = _parse(raw)
    cache["events"] = events
    cache["ts"] = now
    return events


def _parse(raw):
    events = []
    for e in raw or []:
        try:
            date = datetime.fromisoformat(e["date"])
        except (KeyError, TypeError, ValueError):
            continue
        events.append({"title": e.get("title", ""),
                       "country": e.get("country", ""),
                       "date": date, "impact": e.get("impact", "")})
    events.sort(key=lambda e: e["date"])
    return events


def upcoming_high_impact(now=None, hours_ahead=72, fetcher=None, cache=None):
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(hours=hours_ahead)
    return [e for e in fetch_events(fetcher=fetcher, cache=cache)
            if e["impact"] == HIGH_IMPACT and now <= e["date"] <= horizon]


def blocked_reason(symbol, now=None, window_minutes=DEFAULT_WINDOW_MINUTES,
                   fetcher=None, cache=None):
    """Motivo de bloqueo si hay un evento High cerca, o None."""
    now = now or datetime.now(timezone.utc)
    events = fetch_events(fetcher=fetcher, cache=cache)
    if not events:
        return None
    lo = now - timedelta(minutes=window_minutes)
    hi = now + timedelta(minutes=window_minutes)
    sym = (symbol or "").upper()
    for e in events:
        if e["impact"] != HIGH_IMPACT:
            continue
        if not (lo <= e["date"] <= hi):
            continue
        c = e["country"]
        if c in ("All", "USD") or (c and c in sym):
            return f"{e['title']} ({c}) {e['date'].isoformat()}"
    return None
