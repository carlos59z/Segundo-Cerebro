import pytest
from broker_binance import (
    BrokerError, BrokerOrderInvalid, execution_mode, load_keys,
    base_url, to_binance_symbol, validate_order, _sign,
)


def test_execution_mode_default_paper(monkeypatch):
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    assert execution_mode() == "paper"


def test_execution_mode_invalid_raises(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "yolo")
    with pytest.raises(BrokerError):
        execution_mode()


def test_load_keys_missing_testnet_raises(monkeypatch):
    monkeypatch.delenv("BINANCE_TESTNET_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_SECRET", raising=False)
    with pytest.raises(BrokerError):
        load_keys("testnet")


def test_load_keys_returns_key_pair(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET_KEY", "kk")
    monkeypatch.setenv("BINANCE_TESTNET_SECRET", "ss")
    assert load_keys("testnet") == {"key": "kk", "secret": "ss"}


def test_base_urls_by_mode_and_market():
    assert base_url("testnet", "spot") == "https://testnet.binance.vision"
    assert base_url("testnet", "futures") == "https://testnet.binancefuture.com"
    assert base_url("real", "spot") == "https://api.binance.com"
    assert base_url("real", "futures") == "https://fapi.binance.com"
    with pytest.raises(BrokerError):
        base_url("paper", "spot")


def test_to_binance_symbol_mapping():
    assert to_binance_symbol("BTC", "spot") == "BTCUSDT"
    assert to_binance_symbol("btc", "futures") == "BTCUSDT"
    assert to_binance_symbol("BTCUSDT", "spot") == "BTCUSDT"
    assert to_binance_symbol("BTCUSDT-PERP", "futures") == "BTCUSDT"
    with pytest.raises(BrokerOrderInvalid):
        to_binance_symbol("BTCUSDT-PERP", "spot")
    with pytest.raises(BrokerOrderInvalid):
        to_binance_symbol("DIA", "spot")
    with pytest.raises(BrokerOrderInvalid):
        to_binance_symbol("USDJPY", "spot")


def test_validate_order_spot_constraints():
    validate_order("long", 1.0, "BTC", "spot")
    validate_order("short", 3.0, "BTC", "futures")
    with pytest.raises(BrokerOrderInvalid):
        validate_order("short", 1.0, "BTC", "spot")
    with pytest.raises(BrokerOrderInvalid):
        validate_order("long", 2.0, "BTC", "spot")
    with pytest.raises(BrokerOrderInvalid):
        validate_order("long", 1.0, "ETHUSDT-PERP", "spot")


def test_sign_hmac_sha256_known_vector():
    assert _sign("key", "The quick brown fox jumps over the lazy dog") == (
        "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8")
