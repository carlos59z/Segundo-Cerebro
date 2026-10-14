import json
from datetime import datetime, timedelta, timezone

import pytest

import econ_calendar as ec


def _feed(events):
    """Fetcher fake que devuelve la lista cruda como el feed real."""
    def fetcher():
        return events
    return fetcher


def _ev(title, country, date, impact="High"):
    return {"title": title, "country": country, "date": date,
            "impact": impact, "forecast": "", "previous": ""}


def test_parse_y_upcoming_high_impact():
    events = [
        _ev("CPI y/y", "USD", "2026-10-14T08:30:00-04:00", "High"),
        _ev("PPI", "USD", "2026-10-14T08:30:00-04:00", "Low"),
        _ev("GDP", "GBP", "2026-10-15T02:00:00-04:00", "High"),
    ]
    now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
    hi = ec.upcoming_high_impact(now=now, hours_ahead=48, fetcher=_feed(events))
    assert [e["title"] for e in hi] == ["CPI y/y", "GDP"]
    # orden cronologico
    assert hi[0]["date"] < hi[1]["date"]


def test_blocked_btc_ventana_usd():
    # CPI 12:30 UTC; now 12:00 UTC -> 30 min antes -> bloquea
    events = [_ev("CPI y/y", "USD", "2026-10-14T08:30:00-04:00", "High")]
    now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    reason = ec.blocked_reason("BTC", now=now, fetcher=_feed(events))
    assert reason and "CPI" in reason
    reason2 = ec.blocked_reason("SPY", now=now, fetcher=_feed(events))
    assert reason2


def test_no_bloquea_fuera_de_ventana():
    events = [_ev("CPI y/y", "USD", "2026-10-14T08:30:00-04:00", "High")]
    now = datetime(2026, 10, 14, 9, 30, tzinfo=timezone.utc)  # 3h despues
    assert ec.blocked_reason("BTC", now=now, fetcher=_feed(events)) is None


def test_impacto_low_y_medium_no_bloquean():
    events = [
        _ev("Beige Book", "USD", "2026-10-14T14:00:00-04:00", "Low"),
        _ev("Lagarde Speaks", "EUR", "2026-10-14T12:00:00-04:00", "Medium"),
    ]
    now = datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)
    assert ec.blocked_reason("ETH", now=now, fetcher=_feed(events)) is None


def test_forex_bloquea_por_divisa():
    # evento High EUR bloquea EURUSD pero no USDJPY
    events = [_ev("GDP", "EUR", "2026-10-15T02:00:00-04:00", "High")]
    now = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)  # 40 min despues
    assert ec.blocked_reason("EURUSD", now=now, fetcher=_feed(events))
    assert ec.blocked_reason("USDJPY", now=now, fetcher=_feed(events)) is None


def test_eventos_all_bloquean_todo():
    events = [_ev("IMF Meetings", "All", "2026-10-14T10:15:00-04:00", "High")]
    now = datetime(2026, 10, 14, 14, 10, tzinfo=timezone.utc)
    assert ec.blocked_reason("BTC", now=now, fetcher=_feed(events))


def test_fail_open_si_fetch_falla():
    def boom():
        raise RuntimeError("red caida")
    now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    assert ec.blocked_reason("BTC", now=now, fetcher=boom,
                             cache={}) is None


def test_usa_cache_si_fetch_falla():
    cached = [{"title": "NFP", "country": "USD",
               "date": datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc),
               "impact": "High"}]
    cache = {"events": cached, "ts": datetime(2026, 10, 14, 11, 0,
                                              tzinfo=timezone.utc)}

    def boom():
        raise RuntimeError("red caida")

    now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    reason = ec.blocked_reason("BTC", now=now, fetcher=boom, cache=cache)
    assert reason and "NFP" in reason


def test_calendar_endpoint(client, monkeypatch):
    import econ_calendar as ec_mod
    # fecha relativa: un evento High en el futuro, inmune al reloj real
    future = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    events = [_ev("CPI y/y", "USD", future, "High")]
    # la ruta real de otros tests puede haber calentado el cache global
    ec_mod._default_cache["events"] = None
    ec_mod._default_cache["ts"] = None
    monkeypatch.setattr(ec_mod, "_default_fetch", lambda: events)
    r = client.get("/api/fund/calendar")
    assert r.status_code == 200
    body = r.json()
    assert body["high_impact"] and body["high_impact"][0]["title"] == "CPI y/y"
    assert body["source"] == "forexfactory"


def test_orders_open_bloqueado_por_calendario(client, monkeypatch):
    monkeypatch.setattr(ec, "blocked_reason",
                        lambda symbol, **kw: "CPI y/y en 30 min")
    r = client.post("/api/fund/orders", json={
        "action": "open", "symbol": "BTC", "side": "long", "qty_usd": 100,
        "leverage": 1, "entry": 100000, "stop_loss": 95000,
        "take_profit": 120000, "strategy": "test"})
    assert r.status_code == 409
    assert "calendario" in r.json()["detail"]
