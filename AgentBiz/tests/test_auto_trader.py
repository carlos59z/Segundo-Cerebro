import time

import auto_trader as at


def _res(symbol="BTC", market="crypto", eligible=True):
    return {"symbol": symbol, "market": market, "strategy": "sma_cross",
            "eligible": eligible, "sharpe": 1.2}


def test_select_candidates_filters_market_eligible_open_cooldown():
    now = time.time()
    results = [_res("BTC"), _res("SPY", "etf"), _res("ETH", eligible=False),
               _res("SOL"), _res("ADA")]
    cands = at.select_candidates(results, {"BTC"}, {"ADA": now}, now)
    assert [c["symbol"] for c in cands] == ["SOL"]
    expired = at.select_candidates(
        results, {"BTC"}, {"ADA": now - 100000}, now, cooldown_sec=86400)
    assert [c["symbol"] for c in expired] == ["SOL", "ADA"]


def test_fit_spot_widens_sl_to_band():
    leverage, sl = at.fit_to_phase(100.0, 98.0, "long", "aggressive", "spot")
    assert leverage == 1.0
    assert sl == 92.5


def test_fit_futures_picks_leverage_for_mid_band():
    leverage, sl = at.fit_to_phase(100.0, 98.0, "long", "aggressive", "futures")
    assert leverage == 3.75
    assert sl == 98.0
    lev2, _ = at.fit_to_phase(100.0, 99.0, "long", "aggressive", "futures")
    assert lev2 == 5.0


def test_fit_returns_none_when_impossible():
    assert at.fit_to_phase(100.0, 85.0, "long", "aggressive", "spot") is None
    assert at.fit_to_phase(100.0, 85.0, "long", "aggressive", "futures") is None


def test_size_order_capped_at_half_equity():
    q = at.size_order(2500.0, 100.0, 92.5, 1.0, "aggressive")
    assert q == 1250.0
    q2 = at.size_order(2500.0, 100.0, 80.0, 1.0, "aggressive")
    assert q2 == 937.5


def test_operation_to_order_none_on_hold_or_missing():
    assert at.operation_to_order(None, "BTC", "aggressive", "spot", 2500.0) is None
    assert at.operation_to_order({"signal": "HOLD"}, "BTC", "aggressive",
                                 "spot", 2500.0) is None


def test_operation_to_order_skips_short_on_spot():
    op = {"signal": "SELL", "entry_price": 100.0,
          "stop_loss": {"price": 107.5}, "take_profit_1": {"price": 90.0}}
    assert at.operation_to_order(op, "BTC", "aggressive", "spot", 2500.0) is None
    order = at.operation_to_order(op, "BTC", "aggressive", "futures", 2500.0)
    assert order["side"] == "short"
    assert order["review"] is True
    assert order["market_type"] == "futures"
    assert order["stop_loss"] == 107.5


def test_operation_to_order_builds_full_body():
    op = {"signal": "BUY", "entry_price": 100.0,
          "stop_loss": {"price": 92.5}, "take_profit_1": {"price": 115.0}}
    order = at.operation_to_order(op, "BTC", "aggressive", "spot", 2500.0)
    assert order == {"action": "open", "symbol": "BTC", "side": "long",
                     "qty_usd": 1250.0, "leverage": 1.0, "entry": 100.0,
                     "stop_loss": 92.5, "take_profit": 115.0,
                     "strategy": "auto", "market_type": "spot", "review": True}


import asyncio
from fastapi import HTTPException


def _op(signal="BUY"):
    return {"signal": signal, "entry_price": 100.0,
            "stop_loss": {"price": 92.5}, "take_profit_1": {"price": 115.0}}


def _wire_tick(monkeypatch, client, results=None, op=None):
    import api.fund as fmod

    async def fake_mark():
        return {"closed": 0}

    monkeypatch.setattr(fmod, "fund_mark", fake_mark)
    monkeypatch.setattr(at.research, "latest_results",
                        lambda db, n: results if results is not None else [
                            {"symbol": "BTC", "market": "crypto",
                             "strategy": "sma", "eligible": True, "sharpe": 1}])
    if op is not None:
        monkeypatch.setattr(at, "get_operation", lambda s, interval="1h": op)
    msgs = []
    monkeypatch.setattr(at, "send_telegram", msgs.append)
    at.COOLDOWN.clear()
    return msgs


def test_tick_happy_path_passes_risk_review(client, monkeypatch):
    import api.fund as fmod
    msgs = _wire_tick(monkeypatch, client, op=_op())
    captured = {}

    async def fake_orders(req):
        captured["req"] = req
        return {"position": {"id": 1}}

    monkeypatch.setattr(fmod, "fund_orders", fake_orders)
    summary = asyncio.run(at.tick())
    assert summary["ordered"] == 1
    assert captured["req"].review is True
    assert captured["req"].entry == 100.0
    assert captured["req"].stop_loss == 92.5
    assert captured["req"].market_type == "spot"
    assert msgs and "auto-trader" in msgs[0] and "BTC" in msgs[0]


def test_tick_skips_all_when_limits_hit_before_trader(client, monkeypatch):
    import api.fund as fmod
    msgs = _wire_tick(monkeypatch, client, op=_op())
    op_called = []
    monkeypatch.setattr(at, "get_operation",
                        lambda *a, **k: op_called.append(1))

    class FakePortfolio:
        phase = "aggressive"

        def __init__(self, db):
            pass

        def get_status(self):
            return {"equity": 2500.0}

        def can_open(self, risk_pct):
            return False, "stop de perdida diaria activo"

        def get_positions(self, status):
            return []

    monkeypatch.setattr(at, "Portfolio", FakePortfolio)
    summary = asyncio.run(at.tick())
    assert summary["ordered"] == 0
    assert summary["skip_reason"] == "stop de perdida diaria activo"
    assert op_called == []


def test_tick_rejection_notifies_telegram(client, monkeypatch):
    import api.fund as fmod
    msgs = _wire_tick(monkeypatch, client, op=_op())

    async def fake_orders(req):
        raise HTTPException(status_code=403,
                            detail="Director de Riesgo rechaza: senal debil")

    monkeypatch.setattr(fmod, "fund_orders", fake_orders)
    summary = asyncio.run(at.tick())
    assert summary["ordered"] == 0
    assert summary["skipped"] == 1
    assert msgs and "rechaza" in msgs[0]


def test_tick_skips_hold_signal(client, monkeypatch):
    import api.fund as fmod
    _wire_tick(monkeypatch, client, op=None)
    monkeypatch.setattr(at, "get_operation", lambda *a, **k: None)
    called = []

    async def fake_orders(req):
        called.append(req)

    monkeypatch.setattr(fmod, "fund_orders", fake_orders)
    summary = asyncio.run(at.tick())
    assert summary["ordered"] == 0
    assert called == []


def test_safe_tick_isolates_errors(monkeypatch):
    async def boom():
        raise RuntimeError("explosion")

    monkeypatch.setattr(at, "tick", boom)
    msgs = []
    monkeypatch.setattr(at, "send_telegram", msgs.append)
    assert asyncio.run(at.safe_tick()) is None
    assert msgs and "explosion" in msgs[0]


def test_start_autotrader_env_switch(monkeypatch):
    monkeypatch.setenv("AUTO_TRADER", "0")
    assert at.start_auto_trader() is False
    monkeypatch.setenv("AUTO_TRADER", "1")

    async def fake_loop():
        await asyncio.sleep(0)

    monkeypatch.setattr(at, "run_loop", fake_loop)

    async def main():
        started = at.start_auto_trader()
        await asyncio.sleep(0.01)
        return started

    assert asyncio.run(main()) is True
