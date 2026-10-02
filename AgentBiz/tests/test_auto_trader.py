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
