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


from types import SimpleNamespace
import broker_binance as bb


class _Resp:
    def __init__(self, status=200, js=None):
        self.status_code = status
        self._js = js if js is not None else {}
        self.content = b"{}"

    def json(self):
        return self._js


def _env_testnet(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "testnet")
    monkeypatch.setenv("BINANCE_TESTNET_KEY", "kk")
    monkeypatch.setenv("BINANCE_TESTNET_SECRET", "ss")


def test_place_order_rejected_in_paper_mode(monkeypatch):
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    with pytest.raises(BrokerError):
        bb.place_order("BTC", "long", 50.0, 1.0, "spot", 100.0)


def test_request_query_is_signed(monkeypatch):
    _env_testnet(monkeypatch)
    seen = {}

    def fake_request(method, url, timeout=None):
        seen["url"] = url
        return _Resp(200, {})

    monkeypatch.setattr(bb, "requests", SimpleNamespace(request=fake_request))
    out = bb._request("GET", "/api/v3/ping", {}, "spot", signed=False)
    assert out == {}
    url = seen["url"]
    assert url.startswith("https://testnet.binance.vision/api/v3/ping?")
    assert "timestamp=" in url and "recvWindow=5000" in url

    bb._request("GET", "/api/v3/time", {}, "spot")
    url = seen["url"]
    assert "signature=" in url and "timestamp=" in url


def test_http_error_maps_to_broker_error(monkeypatch):
    _env_testnet(monkeypatch)

    def fake_request(method, url, timeout=None):
        return _Resp(400, {"code": -1121, "msg": "Invalid symbol."})

    monkeypatch.setattr(bb, "requests", SimpleNamespace(request=fake_request))
    with pytest.raises(BrokerError) as e:
        bb._request("GET", "/api/v3/ping", {}, "spot")
    assert "-1121" in str(e.value)


def test_place_spot_buy_market_order(monkeypatch):
    _env_testnet(monkeypatch)
    calls = []

    def fake(method, path, params, market_type, signed=True):
        calls.append({"method": method, "path": path, "params": params})
        return {"orderId": 99, "fills": [{"price": "100.0", "qty": "1.0"}]}

    monkeypatch.setattr(bb, "_request", fake)
    out = bb.place_order("BTC", "long", 50.0, 1.0, "spot", 100.0, 95.0, 110.0)
    assert calls[0]["path"] == "/api/v3/order"
    assert calls[0]["params"] == {
        "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quoteOrderQty": 50.0}
    assert out["order_id"] == "99"
    assert out["fill_price"] == 100.0
    assert out["protection_ok"] is True


def test_place_futures_entry_with_protection(monkeypatch):
    _env_testnet(monkeypatch)
    monkeypatch.setattr(bb, "_load_step", lambda *a: 0.001)
    calls = []

    def fake(method, path, params, market_type, signed=True):
        calls.append({"path": path, "params": params})
        if params.get("type") == "MARKET":
            return {"orderId": 7, "avgPrice": "100.5", "executedQty": "2.0"}
        return {}

    monkeypatch.setattr(bb, "_request", fake)
    out = bb.place_order("BTC", "long", 100.0, 2.0, "futures", 100.0, 95.0, 110.0)
    assert calls[0]["params"]["quantity"] == 2.0
    types = [c["params"].get("type") for c in calls]
    assert types == ["MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"]
    assert calls[1]["params"]["stopPrice"] == 95.0
    assert calls[2]["params"]["stopPrice"] == 110.0
    assert out == {"order_id": "7", "fill_price": 100.5, "protection_ok": True}


def test_futures_protection_failure_does_not_raise(monkeypatch):
    _env_testnet(monkeypatch)
    monkeypatch.setattr(bb, "_load_step", lambda *a: 0.001)

    def fake(method, path, params, market_type, signed=True):
        if params.get("type") == "STOP_MARKET":
            raise BrokerError("protection down")
        return {"orderId": 8, "avgPrice": "99.0", "executedQty": "1.0"}

    monkeypatch.setattr(bb, "_request", fake)
    out = bb.place_order("BTC", "long", 100.0, 1.0, "futures", 99.0, 95.0, 110.0)
    assert out["order_id"] == "8"
    assert out["protection_ok"] is False


def test_round_step_and_load_step(monkeypatch):
    assert bb._round_step(0.123456, 0.001) == 0.123
    assert bb._round_step(19.7, 1.0) == 19.0
    assert bb._round_step(5.0, 0) == 5.0
    info = {"symbols": [{"symbol": "BTCUSDT", "filters": [
        {"filterType": "LOT_SIZE", "stepSize": "0.00001"}]}]}
    monkeypatch.setattr(bb, "_request", lambda *a, **k: info)
    bb._STEP_CACHE.clear()
    assert bb._load_step("BTCUSDT", "spot") == 0.00001
    assert bb._load_step("BTCUSDT", "spot") == 0.00001
