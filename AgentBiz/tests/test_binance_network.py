import os

import pytest

pytestmark = pytest.mark.network
needs_keys = pytest.mark.skipif(
    not os.getenv("BINANCE_TESTNET_KEY"), reason="sin keys de testnet")


@needs_keys
def test_ping_testnet_spot():
    import broker_binance as bb
    prev = os.environ.get("EXECUTION_MODE")
    os.environ["EXECUTION_MODE"] = "testnet"
    try:
        assert bb._request("GET", "/api/v3/ping", {}, "spot",
                           signed=False) == {}
    finally:
        if prev is None:
            os.environ.pop("EXECUTION_MODE", None)
        else:
            os.environ["EXECUTION_MODE"] = prev


@needs_keys
def test_ticker_and_account_testnet():
    import broker_binance as bb
    prev = os.environ.get("EXECUTION_MODE")
    os.environ["EXECUTION_MODE"] = "testnet"
    try:
        price = bb._ticker_price("BTCUSDT", "spot")
        assert price > 0
        acct = bb._request("GET", "/api/v3/account", {}, "spot")
        assert "balances" in acct
    finally:
        if prev is None:
            os.environ.pop("EXECUTION_MODE", None)
        else:
            os.environ["EXECUTION_MODE"] = prev
