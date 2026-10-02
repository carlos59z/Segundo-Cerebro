# Plan 4 — Binance Ejecución + Auto-trader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ejecutar órdenes del fondo contra Binance testnet (spot + futuros) con `EXECUTION_MODE` conmutable y correr un auto-trader loop autónomo que cada N minutos convierte señales cripto en órdenes pasando por el Director de Riesgo.

**Architecture:** El broker (`broker_binance.py`) es una capa nueva detrás de `POST /api/fund/orders`; la contabilidad (paper_portfolio, fases, risk gate) no cambia. El auto-trader es una tarea asyncio dentro del servidor que reutiliza `fund_mark` y `fund_orders` sin duplicar lógica. Modo `paper` (default) = cero cambio de comportamiento.

**Tech Stack:** Python 3.13, FastAPI, requests, HMAC-SHA256, pytest (sin red por defecto), testnet.binance.vision + testnet.binancefuture.com.

**Spec:** `docs/superpowers/specs/2026-10-02-binance-ejecucion-auto-design.md` (aprobada por Carlos 2026-10-02 — el plan argumenta desde la spec).

## Global Constraints

- Suite offline actual base: **86 tests** con `-m "not network"`; debe seguir en verde tras cada tarea (los tests existentes no se modifican; solo se añaden archivos nuevos).
- Comandos (PowerShell 5.1 — **nunca `&&`**, usar `;`):
  - Un archivo: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/<archivo> -v`
  - Completa: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
- `EXECUTION_MODE` default `paper` — con la variable ausente NO puede haber comportamiento nuevo (garantía de regresión).
- `.env` es gitignored: **nunca** `git add .env`; nunca imprimir secrets en logs ni commits.
- Mensajes al usuario/Telegram en español (estilo del codebase: "SL/TP obligatorios").
- Sin comentarios en el código (docstring de módulo corto sí, como el resto del repo).
- `tests/conftest.py` ya inserta `backend/` en sys.path y provee el fixture `client` (TestClient con fund.db en tmp).
- Tests de auto_trader se escriben síncronos con `asyncio.run(...)` (sin pytest-asyncio).

## Review Focus

Falla-modos que la spec implica pero que ningún test existente cubre — cada línea con su test dueño:

1. **Símbolo no-cripto o spot+short/leverage>1 llega al broker** (p.ej. `DIA` o `short BTC` en spot) → 422 **antes** de llamar al Director de Riesgo (no gastar LLM ni pegarle a Binance) → Task 4: `test_spot_constraints_422_before_review`.
2. **Broker falla después del risk gate** → 502 y **cero** posición registrada en paper (nunca libro divergente) → Task 4: `test_testnet_broker_failure_is_502_and_no_position`.
3. **Query sin timestamp/recvWindow/signature** → Binance responde -1021 y el sistema "opera" sin ejecutar nunca → Task 2: `test_request_query_is_signed`.
4. **El loop se salta el Director de Riesgo** (hoy el único gate) → toda orden automática llega con `review=True` → Task 7: `test_tick_happy_path` (assert `req.review is True`).
5. **Un tick que revienta mata la tarea asyncio** y el auto-trader muere en silencio → `safe_tick` captura, notifica y el loop sigue → Task 7: `test_safe_tick_isolates_errors`.
6. **Sync de cierres en `mark` falla** → la posición YA cerrada en paper NO se revierte; símbolo en `broker_sync_failed[]` + alerta → Task 5: `test_mark_sync_failure_keeps_close_and_reports`.

---

### Task 1: broker_binance.py — config, claves, mapeo de símbolos, firma

**Files:**
- Create: `AgentBiz/backend/broker_binance.py`
- Test: `AgentBiz/tests/test_broker_binance.py`

**Interfaces:**
- Consumes: env `EXECUTION_MODE`, `BINANCE_TESTNET_KEY/SECRET`, `BINANCE_API_KEY/SECRET`.
- Produces (usan Tasks 2-4): `BrokerError(Exception)`, `BrokerOrderInvalid(BrokerError)`, `execution_mode() -> str`, `load_keys(mode) -> dict`, `base_url(mode, market_type) -> str`, `to_binance_symbol(symbol, market_type="spot") -> str`, `validate_order(side, leverage, symbol, market_type) -> None`, `_sign(secret, query) -> str`.

- [ ] **Step 1: Escribir los tests fallidos**

```python
# AgentBiz/tests/test_broker_binance.py
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_broker_binance.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'broker_binance')

- [ ] **Step 3: Implementar `broker_binance.py` (parte 1 — config/firma)**

```python
"""Cliente REST de Binance (spot + futuros USDT-M). Modos: paper/testnet/real."""
import hashlib
import hmac
import os
import time
import urllib.parse

import requests


class BrokerError(Exception):
    pass


class BrokerOrderInvalid(BrokerError):
    pass


_MODES = ("paper", "testnet", "real")
_BASE = {
    ("spot", "testnet"): "https://testnet.binance.vision",
    ("spot", "real"): "https://api.binance.com",
    ("futures", "testnet"): "https://testnet.binancefuture.com",
    ("futures", "real"): "https://fapi.binance.com",
}
_CRYPTO = ("BTC", "ETH", "XRP", "SOL", "BNB", "DOGE", "ADA", "AVAX", "LINK", "DOT")
_KEY_ENV = {
    "testnet": ("BINANCE_TESTNET_KEY", "BINANCE_TESTNET_SECRET"),
    "real": ("BINANCE_API_KEY", "BINANCE_API_SECRET"),
}


def execution_mode():
    m = os.getenv("EXECUTION_MODE", "paper")
    if m not in _MODES:
        raise BrokerError(f"EXECUTION_MODE invalido: {m}")
    return m


def load_keys(mode):
    if mode not in _KEY_ENV:
        raise BrokerError(f"load_keys no aplica en modo {mode}")
    k_env, s_env = _KEY_ENV[mode]
    key, secret = os.getenv(k_env), os.getenv(s_env)
    if not key or not secret:
        raise BrokerError(f"faltan {k_env}/{s_env} en .env")
    return {"key": key, "secret": secret}


def base_url(mode, market_type):
    try:
        return _BASE[(market_type, mode)]
    except KeyError:
        raise BrokerError(f"combinacion invalida market_type={market_type} mode={mode}")


def to_binance_symbol(symbol, market_type="spot"):
    s = symbol.upper()
    perp = s.endswith("-PERP")
    if perp:
        s = s[:-5]
    if perp and market_type == "spot":
        raise BrokerOrderInvalid("PERP solo disponible en futuros")
    base = s[:-4] if s.endswith("USDT") else s
    if base not in _CRYPTO:
        raise BrokerOrderInvalid(f"simbolo fuera del universo cripto: {symbol}")
    return f"{base}USDT"


def validate_order(side, leverage, symbol, market_type):
    to_binance_symbol(symbol, market_type)
    if market_type == "spot":
        if side == "short":
            raise BrokerOrderInvalid("spot no permite short (usa futures)")
        if leverage and leverage > 1.0:
            raise BrokerOrderInvalid("spot no permite apalancamiento")


def _sign(secret, query):
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
```

- [ ] **Step 4: Verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_broker_binance.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```powershell
git add AgentBiz/backend/broker_binance.py AgentBiz/tests/test_broker_binance.py
git commit -m "feat(broker): config modos paper/testnet/real, claves, mapeo simbolos y firma HMAC Binance"
```

---

### Task 2: broker_binance.py — capa HTTP firmada + place_order (spot y futuros)

**Files:**
- Modify: `AgentBiz/backend/broker_binance.py`
- Test: `AgentBiz/tests/test_broker_binance.py` (añadir)

**Interfaces:**
- Consumes: Task 1 (`execution_mode`, `load_keys`, `base_url`, `to_binance_symbol`, `validate_order`, `_sign`).
- Produces (usan Tasks 3-4): `_request(method, path, params, market_type, signed=True) -> dict`, `place_order(symbol, side, qty_usd, leverage, market_type, ref_price, stop_loss=None, take_profit=None) -> {"order_id": str, "fill_price": float, "protection_ok": bool}`, `_round_step(qty, step) -> float`, `_load_step(symbol, market_type) -> float`, `_STEP_CACHE: dict`.

- [ ] **Step 1: Escribir los tests fallidos (añadir al archivo)**

```python
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_broker_binance.py -v`
Expected: los nuevos FAIL (AttributeError: place_order/_request); los de Task 1 siguen PASS.

- [ ] **Step 3: Implementar capa HTTP + place_order (añadir a broker_binance.py)**

```python
from decimal import Decimal

_STEP_CACHE = {}


def _request(method, path, params, market_type, signed=True):
    mode = execution_mode()
    if mode == "paper":
        raise BrokerError("broker no aplica en modo paper")
    cfg = load_keys(mode)
    q = dict(params or {})
    q.update(timestamp=int(time.time() * 1000), recvWindow=5000)
    query = urllib.parse.urlencode(q)
    if signed:
        query += "&signature=" + _sign(cfg["secret"], query)
    url = f"{base_url(mode, market_type)}{path}?{query}"
    try:
        r = requests.request(method, url, timeout=15)
    except requests.RequestException as e:
        raise BrokerError(f"sin conexion con binance: {e}")
    js = r.json() if r.content else {}
    if r.status_code >= 400:
        raise BrokerError(f"binance {r.status_code}: {js}")
    return js


def _ticker_price(bsym, market_type):
    path = "/api/v3/ticker/price" if market_type == "spot" else "/fapi/v1/ticker/price"
    js = _request("GET", path, {"symbol": bsym}, market_type, signed=False)
    return float(js["price"])


def _avg_spot(js, bsym):
    fills = js.get("fills") or []
    if fills:
        q = sum(float(f["qty"]) for f in fills)
        if q > 0:
            return round(sum(float(f["price"]) * float(f["qty"]) for f in fills) / q, 8)
    executed = float(js.get("executedQty") or 0)
    cumm = float(js.get("cummulativeQuoteQty") or 0)
    if executed > 0 and cumm > 0:
        return round(cumm / executed, 8)
    return _ticker_price(bsym, "spot")


def _avg_futures(js, bsym):
    price = float(js.get("avgPrice") or 0)
    if price > 0:
        return price
    return _ticker_price(bsym, "futures")


def _round_step(qty, step):
    if not step or step <= 0:
        return qty
    d = Decimal(str(step))
    return float(int(Decimal(str(qty)) / d) * d)


def _load_step(symbol, market_type):
    if (symbol, market_type) in _STEP_CACHE:
        return _STEP_CACHE[(symbol, market_type)]
    path = "/api/v3/exchangeInfo" if market_type == "spot" else "/fapi/v1/exchangeInfo"
    js = _request("GET", path, {}, market_type, signed=False)
    step = 0.000001
    for s in js.get("symbols", []):
        if s.get("symbol") == symbol:
            wanted = "MARKET_LOT_SIZE" if market_type == "futures" else "LOT_SIZE"
            for f in s.get("filters", []):
                if f.get("filterType") == wanted:
                    step = float(f["stepSize"])
            break
    _STEP_CACHE[(symbol, market_type)] = step
    return step


def place_order(symbol, side, qty_usd, leverage, market_type, ref_price,
                stop_loss=None, take_profit=None):
    validate_order(side, leverage, symbol, market_type)
    mode = execution_mode()
    if mode == "paper":
        raise BrokerError("place_order no aplica en modo paper")
    bsym = to_binance_symbol(symbol, market_type)
    if market_type == "spot":
        js = _request("POST", "/api/v3/order", {
            "symbol": bsym, "side": "BUY", "type": "MARKET",
            "quoteOrderQty": round(qty_usd, 2)}, market_type)
        return {"order_id": str(js.get("orderId")),
                "fill_price": _avg_spot(js, bsym), "protection_ok": True}
    qty_base = _round_step(qty_usd * leverage / ref_price, _load_step(bsym, market_type))
    if qty_base <= 0:
        raise BrokerError("cantidad calculada <= 0")
    js = _request("POST", "/fapi/v1/order", {
        "symbol": bsym, "side": "BUY" if side == "long" else "SELL",
        "type": "MARKET", "quantity": qty_base}, market_type)
    protection_ok = True
    if stop_loss and take_profit:
        try:
            _request("POST", "/fapi/v1/order", {
                "symbol": bsym, "type": "STOP_MARKET",
                "stopPrice": stop_loss, "closePosition": "true"}, market_type)
            _request("POST", "/fapi/v1/order", {
                "symbol": bsym, "type": "TAKE_PROFIT_MARKET",
                "stopPrice": take_profit, "closePosition": "true"}, market_type)
        except BrokerError:
            protection_ok = False
    return {"order_id": str(js.get("orderId")),
            "fill_price": _avg_futures(js, bsym), "protection_ok": protection_ok}
```

- [ ] **Step 4: Verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_broker_binance.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```powershell
git add AgentBiz/backend/broker_binance.py AgentBiz/tests/test_broker_binance.py
git commit -m "feat(broker): HTTP firmado con timestamp/signature, place_order spot y futuros con SL/TP en exchange"
```

---

### Task 3: broker_binance.py — cierres idempotentes (close_on_exchange / close_sync)

**Files:**
- Modify: `AgentBiz/backend/broker_binance.py`
- Test: `AgentBiz/tests/test_broker_binance.py` (añadir)

**Interfaces:**
- Consumes: Task 2 (`_request`, `_round_step`, `_load_step`, `_avg_spot`, `_avg_futures`).
- Produces (usan Tasks 4-5): `close_on_exchange(symbol, market_type, side, qty_usd, leverage, entry) -> {"closed": bool, "fill_price": float|None, "reason": str}`, `close_sync(symbol, side, qty_usd, leverage, entry) -> dict + {"market_type": str|None}`.

- [ ] **Step 1: Escribir los tests fallidos (añadir)**

```python
def test_close_futures_already_flat_is_noop(monkeypatch):
    _env_testnet(monkeypatch)
    calls = []

    def fake(method, path, params, market_type, signed=True):
        calls.append(path)
        if path == "/fapi/v1/positionRisk":
            return {"symbol": "BTCUSDT", "amt": "0"}
        return {}

    monkeypatch.setattr(bb, "_request", fake)
    out = bb.close_on_exchange("BTC", "futures", "long", 100.0, 2.0, 100.0)
    assert out["closed"] is False
    assert calls == ["/fapi/v1/positionRisk"]


def test_close_futures_cancels_protection_and_closes(monkeypatch):
    _env_testnet(monkeypatch)
    monkeypatch.setattr(bb, "_load_step", lambda *a: 0.001)
    calls = []

    def fake(method, path, params, market_type, signed=True):
        calls.append({"method": method, "path": path, "params": params})
        if path == "/fapi/v1/positionRisk":
            return {"symbol": "BTCUSDT", "amt": "-0.25"}
        if path == "/fapi/v1/openOrders":
            return [{"orderId": 5}, {"orderId": 6}]
        if params.get("type") == "MARKET":
            return {"orderId": 77, "avgPrice": "101.0", "executedQty": "0.25"}
        return {}

    monkeypatch.setattr(bb, "_request", fake)
    out = bb.close_on_exchange("BTC", "futures", "long", 100.0, 2.0, 100.0)
    assert out["closed"] is True
    assert out["fill_price"] == 101.0
    methods = [(c["method"], c["path"]) for c in calls]
    assert methods[:3] == [("GET", "/fapi/v1/positionRisk"),
                           ("GET", "/fapi/v1/openOrders"),
                           ("DELETE", "/fapi/v1/order")]
    last = calls[-1]
    assert last["path"] == "/fapi/v1/order"
    assert last["params"]["side"] == "BUY"
    assert last["params"]["reduceOnly"] == "true"


def test_close_spot_without_balance_is_noop(monkeypatch):
    _env_testnet(monkeypatch)

    def fake(method, path, params, market_type, signed=True):
        if path == "/api/v3/account":
            return {"balances": [{"asset": "BTC", "free": "0.0", "locked": "0.0"}]}
        raise AssertionError(f"path inesperado {path}")

    monkeypatch.setattr(bb, "_request", fake)
    out = bb.close_on_exchange("BTC", "spot", "long", 100.0, 1.0, 100.0)
    assert out == {"closed": False, "fill_price": None, "reason": "sin saldo spot"}


def test_close_spot_sells_free_balance(monkeypatch):
    _env_testnet(monkeypatch)
    monkeypatch.setattr(bb, "_load_step", lambda *a: 0.0001)
    calls = []

    def fake(method, path, params, market_type, signed=True):
        calls.append({"path": path, "params": params})
        if path == "/api/v3/account":
            return {"balances": [{"asset": "ETH", "free": "0.5", "locked": "0"}]}
        if params.get("type") == "MARKET":
            return {"orderId": 3, "fills": [{"price": "2000.0", "qty": "0.05"}]}
        return {}

    monkeypatch.setattr(bb, "_request", fake)
    out = bb.close_on_exchange("ETH", "spot", "long", 100.0, 1.0, 2000.0)
    assert out["closed"] is True and out["fill_price"] == 2000.0
    sell = [c for c in calls if c["path"] == "/api/v3/order"][0]
    assert sell["params"]["side"] == "SELL"
    assert sell["params"]["quantity"] == 0.05


def test_close_sync_falls_back_to_spot(monkeypatch):
    _env_testnet(monkeypatch)
    seen = []

    def fake_close(symbol, market_type, side, qty_usd, leverage, entry):
        seen.append(market_type)
        if market_type == "futures":
            return {"closed": False, "fill_price": None,
                    "reason": "ya flat en el exchange"}
        return {"closed": True, "fill_price": 2000.0, "reason": "broker close"}

    monkeypatch.setattr(bb, "close_on_exchange", fake_close)
    out = bb.close_sync("ETH", "long", 100.0, 1.0, 2000.0)
    assert seen == ["futures", "spot"]
    assert out["closed"] is True
    assert out["market_type"] == "spot"


def test_close_sync_in_paper_returns_noop(monkeypatch):
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    out = bb.close_sync("BTC", "long", 100.0, 1.0, 100.0)
    assert out["closed"] is False
    assert out["reason"] == "paper"
```

- [ ] **Step 2: Verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_broker_binance.py -v`
Expected: los 6 nuevos FAIL (AttributeError); el resto PASS.

- [ ] **Step 3: Implementar cierres (añadir a broker_binance.py)**

```python
def close_on_exchange(symbol, market_type, side, qty_usd, leverage, entry):
    mode = execution_mode()
    if mode == "paper":
        raise BrokerError("close_on_exchange no aplica en modo paper")
    bsym = to_binance_symbol(symbol, market_type)
    if market_type == "futures":
        js = _request("GET", "/fapi/v1/positionRisk", {"symbol": bsym}, market_type)
        amt = float(js.get("amt") or 0)
        if abs(amt) < 1e-12:
            return {"closed": False, "fill_price": None,
                    "reason": "ya flat en el exchange"}
        for o in _request("GET", "/fapi/v1/openOrders", {"symbol": bsym},
                          market_type) or []:
            _request("DELETE", "/fapi/v1/order",
                     {"symbol": bsym, "orderId": o["orderId"]}, market_type)
        qty = _round_step(abs(amt), _load_step(bsym, market_type))
        js = _request("POST", "/fapi/v1/order", {
            "symbol": bsym, "side": "SELL" if amt > 0 else "BUY",
            "type": "MARKET", "quantity": qty, "reduceOnly": "true"}, market_type)
        return {"closed": True, "fill_price": _avg_futures(js, bsym),
                "reason": "broker close"}
    base = bsym[:-4]
    acct = _request("GET", "/api/v3/account", {}, market_type)
    free = 0.0
    for b in acct.get("balances", []):
        if b.get("asset") == base:
            free = float(b.get("free") or 0)
            break
    if free <= 0:
        return {"closed": False, "fill_price": None, "reason": "sin saldo spot"}
    qty = _round_step(min(free, qty_usd * leverage / entry),
                      _load_step(bsym, market_type))
    if qty <= 0:
        return {"closed": False, "fill_price": None, "reason": "cantidad <= step"}
    js = _request("POST", "/api/v3/order", {
        "symbol": bsym, "side": "SELL", "type": "MARKET", "quantity": qty},
        market_type)
    return {"closed": True, "fill_price": _avg_spot(js, bsym),
            "reason": "broker close"}


def close_sync(symbol, side, qty_usd, leverage, entry):
    mode = execution_mode()
    if mode == "paper":
        return {"closed": False, "fill_price": None, "reason": "paper",
                "market_type": None}
    try:
        r = close_on_exchange(symbol, "futures", side, qty_usd, leverage, entry)
        if r["closed"]:
            r["market_type"] = "futures"
            return r
    except BrokerOrderInvalid:
        pass
    r = close_on_exchange(symbol, "spot", side, qty_usd, leverage, entry)
    r["market_type"] = "spot"
    return r
```

- [ ] **Step 4: Verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_broker_binance.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```powershell
git add AgentBiz/backend/broker_binance.py AgentBiz/tests/test_broker_binance.py
git commit -m "feat(broker): cierres idempotentes futures (flat no-op, cancela protecciones) y spot (saldo), close_sync auto"
```

---

### Task 4: fund_orders con EXECUTION_MODE (paper/testnet/real) + market_type

**Files:**
- Modify: `AgentBiz/backend/api/fund.py` (imports 1-12; `OrderRequest` 69-82; `fund_orders` 94-141)
- Test: `AgentBiz/tests/test_fund_orders_mode.py` (nuevo)

**Interfaces:**
- Consumes: Tasks 1-3 (`execution_mode`, `validate_order`, `place_order`, `close_on_exchange`, `BrokerError`, `BrokerOrderInvalid`).
- Produces: `OrderRequest.market_type: Literal["spot","futures"] = "spot"`; respuestas open/close incluyen `"execution": {"mode": str, "broker": str|None, "order_id": str|None}`. Los tests existentes de `test_fund_api.py` deben seguir intactos.

- [ ] **Step 1: Escribir los tests fallidos**

```python
# AgentBiz/tests/test_fund_orders_mode.py
def _open(**over):
    body = {"action": "open", "symbol": "BTC", "side": "long", "qty_usd": 300.0,
            "leverage": 2.0, "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0,
            "strategy": "sma_cross"}
    body.update(over)
    return body


def test_paper_mode_never_calls_broker(client, monkeypatch):
    import api.fund as fmod

    def boom(*a, **k):
        raise AssertionError("broker no debe llamarse en modo paper")

    monkeypatch.setattr(fmod, "place_order", boom)
    r = client.post("/api/fund/orders", json=_open())
    assert r.status_code == 200
    d = r.json()
    assert d["execution"] == {"mode": "paper", "broker": None, "order_id": None}
    assert d["position"]["entry"] == 100.0


def test_testnet_order_uses_broker_fill_price(client, monkeypatch):
    import api.fund as fmod
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")
    monkeypatch.setattr(fmod, "place_order",
                        lambda *a, **k: {"order_id": "42", "fill_price": 98.5,
                                         "protection_ok": True})
    r = client.post("/api/fund/orders", json=_open())
    assert r.status_code == 200
    d = r.json()
    assert d["position"]["entry"] == 98.5
    assert d["execution"] == {"mode": "testnet", "broker": "binance-testnet",
                              "order_id": "42"}
    pf = client.get("/api/fund/portfolio").json()
    assert pf["status"]["open_positions"] == 1


def test_testnet_broker_failure_is_502_and_no_position(client, monkeypatch):
    import api.fund as fmod
    from broker_binance import BrokerError
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")

    def down(*a, **k):
        raise BrokerError("testnet caido")

    monkeypatch.setattr(fmod, "place_order", down)
    r = client.post("/api/fund/orders", json=_open())
    assert r.status_code == 502
    assert "broker" in r.json()["detail"]
    pf = client.get("/api/fund/portfolio").json()
    assert pf["positions"] == []


def test_spot_constraints_422_before_review(client, monkeypatch):
    import api.fund as fmod
    calls = []

    async def review(order):
        calls.append(order)
        return {"decision": "aprueba", "reason": ""}

    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")
    monkeypatch.setattr(fmod, "risk_review", review)
    r = client.post("/api/fund/orders", json=_open(side="short", review=True))
    assert r.status_code == 422
    assert "short" in r.json()["detail"]
    assert calls == []
    bad_lev = client.post("/api/fund/orders", json=_open(leverage=3.0, review=True))
    assert bad_lev.status_code == 422
    assert calls == []


def test_close_testnet_records_broker_fill(client, monkeypatch):
    import api.fund as fmod
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")
    monkeypatch.setattr(fmod, "place_order",
                        lambda *a, **k: {"order_id": "7", "fill_price": 100.0,
                                         "protection_ok": True})
    client.post("/api/fund/orders", json=_open())
    monkeypatch.setattr(
        fmod, "close_on_exchange",
        lambda *a: {"closed": True, "fill_price": 105.0, "reason": "x"})
    r = client.post("/api/fund/orders",
                    json={"action": "close", "position_id": 1, "price": 104.0,
                          "symbol": "BTC"})
    assert r.status_code == 200
    assert r.json()["trade"]["pnl"] == 30.0
    assert r.json()["execution"]["mode"] == "testnet"
```

- [ ] **Step 2: Verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_fund_orders_mode.py -v`
Expected: FAIL (validation error por `market_type` desconocido / AttributeError)

- [ ] **Step 3: Implementar en `api/fund.py`**

Imports (junto a los existentes de las líneas 6-9):

```python
from broker_binance import (BrokerError, BrokerOrderInvalid, execution_mode,
                            validate_order, place_order, close_on_exchange)
```

`OrderRequest` — añadir tras `strategy`:

```python
    market_type: Literal["spot", "futures"] = "spot"
```

Rama `open` de `fund_orders` — tras la validación `qty_usd/entry` (líneas 99-100), insertar:

```python
        mode = execution_mode()
        if mode != "paper":
            try:
                validate_order(req.side, req.leverage, req.symbol, req.market_type)
            except BrokerOrderInvalid as e:
                raise HTTPException(status_code=422, detail=str(e))
```

Tras el risk gate (bloque `if req.review:`) y **antes** de `open_position`, insertar:

```python
        order_id = None
        if mode != "paper":
            try:
                fill = await asyncio.to_thread(
                    place_order, req.symbol, req.side, req.qty_usd, req.leverage,
                    req.market_type, req.entry, req.stop_loss, req.take_profit)
            except BrokerError as e:
                raise HTTPException(status_code=502, detail=f"broker: {e}")
            req.entry = fill["fill_price"]
            order_id = fill["order_id"]
```

`return` de la rama open:

```python
        return {"position": pos, "risk_review": review_result,
                "execution": {"mode": mode,
                              "broker": f"binance-{mode}" if mode != "paper" else None,
                              "order_id": order_id}}
```

Rama `close` — tras la validación `position_id/price` (líneas 127-128), antes de `close_position`:

```python
    mode = execution_mode()
    exit_price = req.price
    if mode != "paper":
        p = _pf()
        row = next((x for x in p.get_positions("open")
                    if x["id"] == req.position_id), None)
        if not row:
            raise HTTPException(status_code=409,
                                detail=f"posicion {req.position_id} no abierta")
        try:
            bres = await asyncio.to_thread(
                close_on_exchange, row["symbol"], req.market_type, row["side"],
                row["qty_usd"], row["leverage"], row["entry"])
        except BrokerError as e:
            raise HTTPException(status_code=502, detail=f"broker: {e}")
        if bres.get("fill_price"):
            exit_price = bres["fill_price"]
```

`close_position(req.position_id, exit_price, req.reason)` (reemplaza `req.price`) y su return:

```python
    return {"trade": trade, "risk_review": None,
            "execution": {"mode": mode,
                          "broker": f"binance-{mode}" if mode != "paper" else None,
                          "order_id": None}}
```

- [ ] **Step 4: Verificar — nuevos + regresión completa**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_fund_orders_mode.py -v`
Expected: PASS (5)

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: PASS — base 86 + nuevos en verde.

- [ ] **Step 5: Commit**

```powershell
git add AgentBiz/backend/api/fund.py AgentBiz/tests/test_fund_orders_mode.py
git commit -m "feat(fund): EXECUTION_MODE en orders — broker testnet con fill real, 502 sin libro, 422 validacion spot, campo execution"
```

### Task 5: mark sincroniza cierres con el broker + notify.py

**Files:**
- Modify: `AgentBiz/backend/paper_portfolio.py:229` (`close_position` return, aditivo)
- Modify: `AgentBiz/backend/api/fund.py` (imports + `fund_mark` 144-171)
- Create: `AgentBiz/backend/notify.py`
- Test: `AgentBiz/tests/test_fund_mark_sync.py` (nuevo)

**Interfaces:**
- Consumes: Tasks 1-3 (`execution_mode`, `close_sync`, `BrokerError`).
- Produces: `notify.send_telegram(text) -> bool` (lo usa Task 7); `close_position` devuelve además `position_id, side, entry, qty_usd, leverage` (aditivo); `POST /api/fund/mark` responde también `"broker_sync_failed": list[str]`.

- [ ] **Step 1: Escribir los tests fallidos**

```python
# AgentBiz/tests/test_fund_mark_sync.py
def _open(client, **over):
    body = {"action": "open", "symbol": "BTC", "side": "long", "qty_usd": 300.0,
            "leverage": 2.0, "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0,
            "strategy": "sma_cross"}
    body.update(over)
    return client.post("/api/fund/orders", json=body)


def test_mark_sync_calls_close_sync_per_closed_position(client, monkeypatch):
    import api.fund as fmod
    _open(client)
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")
    calls = []

    def fake_sync(symbol, side, qty_usd, leverage, entry):
        calls.append({"symbol": symbol, "side": side, "qty_usd": qty_usd,
                      "leverage": leverage, "entry": entry})
        return {"closed": True, "fill_price": 95.0, "reason": "x",
                "market_type": "spot"}

    monkeypatch.setattr(fmod, "close_sync", fake_sync)
    monkeypatch.setattr(fmod, "get_price", lambda s: 94.0)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    d = r.json()
    assert d["closed"] == 1
    assert d["broker_sync_failed"] == []
    assert calls and calls[0]["symbol"] == "BTC"
    assert calls[0]["entry"] == 100.0
    pf = client.get("/api/fund/portfolio").json()
    assert len(pf["trades"]) == 1


def test_mark_sync_failure_keeps_close_and_reports(client, monkeypatch):
    import api.fund as fmod
    from broker_binance import BrokerError
    _open(client)
    monkeypatch.setattr(fmod, "execution_mode", lambda: "testnet")

    def down(*a, **k):
        raise BrokerError("testnet caido")

    monkeypatch.setattr(fmod, "close_sync", down)
    monkeypatch.setattr(fmod, "get_price", lambda s: 94.0)
    msgs = []
    monkeypatch.setattr(fmod, "send_telegram", msgs.append)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    d = r.json()
    assert d["closed"] == 1
    assert d["broker_sync_failed"] == ["BTC"]
    assert msgs and "BTC" in msgs[0]
    pf = client.get("/api/fund/portfolio").json()
    assert len(pf["trades"]) == 1


def test_mark_paper_mode_skips_sync(client, monkeypatch):
    import api.fund as fmod
    _open(client)

    def boom(*a, **k):
        raise AssertionError("close_sync no debe llamarse en paper")

    monkeypatch.setattr(fmod, "close_sync", boom)
    monkeypatch.setattr(fmod, "get_price", lambda s: 94.0)
    r = client.post("/api/fund/mark")
    assert r.status_code == 200
    assert r.json()["broker_sync_failed"] == []
```

- [ ] **Step 2: Verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_fund_mark_sync.py -v`
Expected: FAIL (KeyError `broker_sync_failed` / AttributeError close_sync)

- [ ] **Step 3: Implementar**

`AgentBiz/backend/notify.py` (nuevo):

```python
"""Notificaciones Telegram directas (best-effort, nunca lanzan)."""
import os

import requests


def send_telegram(text):
    token = os.getenv("TELEGRAM_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000]}, timeout=10)
        return bool(r.ok)
    except requests.RequestException:
        return False
```

`paper_portfolio.py` — `close_position` return (línea 229) pasa a:

```python
        return {"pnl": round(pnl, 2), "reason": reason, "symbol": symbol,
                "position_id": position_id, "side": side, "entry": entry,
                "qty_usd": qty_usd, "leverage": leverage}
```

`api/fund.py` — añadir `close_sync` al import de broker_binance y:

```python
from notify import send_telegram
```

`fund_mark.work()` — tras `if prices or not positions: p.record_equity()` (línea 167), insertar:

```python
        sync_failed = []
        mode = execution_mode()
        if mode != "paper" and closed:
            for c in closed:
                try:
                    close_sync(c["symbol"], c["side"], c["qty_usd"],
                               c["leverage"], c["entry"])
                except BrokerError as e:
                    sync_failed.append(c["symbol"])
                    send_telegram(f"mark: sync broker fallo {c['symbol']}: {e}")
```

Y el return de `work()` añade `"broker_sync_failed": sync_failed` (tras `"failed": failed`).

- [ ] **Step 4: Verificar — nuevos + regresión completa**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_fund_mark_sync.py -v`
Expected: PASS (3)

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: PASS (base + Tasks 1-5)

- [ ] **Step 5: Commit**

```powershell
git add AgentBiz/backend/notify.py AgentBiz/backend/paper_portfolio.py AgentBiz/backend/api/fund.py AgentBiz/tests/test_fund_mark_sync.py
git commit -m "feat(fund): mark sincroniza cierres con broker (best-effort + broker_sync_failed) y notify.send_telegram"
```

---

### Task 6: auto_trader — lógica pura (candidatos, fit de riesgo, sizing, orden)

**Files:**
- Create: `AgentBiz/backend/auto_trader.py`
- Test: `AgentBiz/tests/test_auto_trader.py` (nuevo)

**Interfaces:**
- Consumes: `paper_portfolio.PHASES`.
- Produces (usa Task 7): `COOLDOWN: dict`, `select_candidates(results, open_symbols, cooldown, now, cooldown_sec=86400) -> list[dict]`, `fit_to_phase(entry, stop_loss, side, phase, market_type) -> (float, str)|None`, `size_order(equity, entry, stop_loss, leverage, phase) -> float`, `operation_to_order(op, symbol, phase, market_type, equity) -> dict|None`, `get_operation(symbol, interval="1h") -> dict|None`.

- [ ] **Step 1: Escribir los tests fallidos**

```python
# AgentBiz/tests/test_auto_trader.py
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
        results, set(), {"ADA": now - 100000}, now, cooldown_sec=86400)
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_auto_trader.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'auto_trader')

- [ ] **Step 3: Implementar `auto_trader.py` (parte 1 — lógica pura)**

```python
"""Auto-trader: señales cripto -> Trader API -> risk gate -> orden -> Telegram."""
import asyncio
import logging
import os
import time

import requests

import research
from agents.ai_brain import TRADER_API
from broker_binance import execution_mode, to_binance_symbol
from notify import send_telegram
from paper_portfolio import PHASES, Portfolio

log = logging.getLogger("auto_trader")
COOLDOWN = {}


def market_type():
    return os.getenv("BINANCE_MARKET_TYPE", "spot")


def select_candidates(results, open_symbols, cooldown, now, cooldown_sec=21600):
    out = []
    for r in results:
        if r.get("market") != "crypto" or not r.get("eligible"):
            continue
        sym = r["symbol"]
        if sym in open_symbols:
            continue
        last = cooldown.get(sym)
        if last and (now - last) < cooldown_sec:
            continue
        out.append(r)
    return out


def fit_to_phase(entry, stop_loss, side, phase, market_type):
    rules = PHASES[phase]
    lo, hi = rules["risk_pct"]
    mid = (lo + hi) / 2
    dist = abs(entry - stop_loss) / entry
    if dist <= 0:
        return None
    if market_type == "spot":
        if dist > hi:
            return None
        if dist < lo:
            stop_loss = entry * (1 - mid) if side == "long" else entry * (1 + mid)
            dist = mid
        return 1.0, stop_loss
    leverage = mid / dist
    leverage = max(1.0, min(leverage, rules["max_leverage"]))
    if not (lo <= dist * leverage <= hi):
        return None
    return leverage, stop_loss


def size_order(equity, entry, stop_loss, leverage, phase):
    lo, hi = PHASES[phase]["risk_pct"]
    mid = (lo + hi) / 2
    dist = abs(entry - stop_loss) / entry
    risk = dist * leverage
    if risk <= 0:
        return 0.0
    qty = equity * mid / risk
    return round(min(qty, equity * 0.5), 2)


def get_operation(symbol, interval="1h"):
    bsym = to_binance_symbol(symbol, "futures")
    try:
        r = requests.get(f"{TRADER_API}/api/operation/{bsym}",
                         params={"interval": interval, "risk": "medium"},
                         timeout=30)
        r.raise_for_status()
        return r.json().get("operation")
    except requests.RequestException as e:
        log.warning("trader api fallo %s: %s", symbol, e)
        return None


def operation_to_order(op, symbol, phase, market_type, equity):
    if not op:
        return None
    signal = op.get("signal")
    if signal == "BUY":
        side = "long"
    elif signal == "SELL":
        side = "short"
    else:
        return None
    if market_type == "spot" and side == "short":
        return None
    entry = float(op["entry_price"])
    stop_loss = float(op["stop_loss"]["price"])
    take_profit = float(op["take_profit_1"]["price"])
    fit = fit_to_phase(entry, stop_loss, side, phase, market_type)
    if not fit:
        return None
    leverage, stop_loss = fit
    qty_usd = size_order(equity, entry, stop_loss, leverage, phase)
    if qty_usd <= 0:
        return None
    return {"action": "open", "symbol": symbol, "side": side, "qty_usd": qty_usd,
            "leverage": leverage, "entry": entry, "stop_loss": stop_loss,
            "take_profit": take_profit, "strategy": "auto",
            "market_type": market_type, "review": True}
```

- [ ] **Step 4: Verificar que pasan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_auto_trader.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```powershell
git add AgentBiz/backend/auto_trader.py AgentBiz/tests/test_auto_trader.py
git commit -m "feat(auto-trader): seleccion de candidatos cripto, fit de riesgo por fase, sizing con cap y construccion de orden"
```

---

### Task 7: auto_trader — tick, loop con aislamiento de errores, startup

**Files:**
- Modify: `AgentBiz/backend/auto_trader.py`
- Modify: `AgentBiz/backend/api/main.py:56-58` (startup)
- Test: `AgentBiz/tests/test_auto_trader.py` (añadir)

**Interfaces:**
- Consumes: Task 6 (funciones puras), Task 5 (`send_telegram`), `api.fund.fund_mark/fund_orders/OrderRequest/FUND_DB`.
- Produces: `async tick() -> dict` (`{"marked","ordered","skipped","skip_reason"}`), `async safe_tick()`, `async run_loop()`, `start_auto_trader() -> bool`.

- [ ] **Step 1: Escribir los tests fallidos (añadir)**

```python
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
```

Nota: `_wire_tick` con `op=None` NO parchea `get_operation` — para el test HOLD parchea `get_operation` explícitamente con `lambda *a, **k: None`:

```python
    monkeypatch.setattr(at, "get_operation", lambda *a, **k: None)
```

(agregar esa línea en `test_tick_skips_hold_signal` tras `_wire_tick`).

- [ ] **Step 2: Verificar que fallan**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_auto_trader.py -v`
Expected: los nuevos FAIL (AttributeError tick/start_auto_trader); los de Task 6 PASS.

- [ ] **Step 3: Implementar tick/loop (añadir a auto_trader.py)**

```python
import api.fund as fmod


async def tick():
    summary = {"marked": 0, "ordered": 0, "skipped": 0, "skip_reason": None}
    try:
        m = await fmod.fund_mark()
        summary["marked"] = m.get("closed", 0)
    except Exception as e:
        log.warning("mark fallo: %s", e)
    p = Portfolio(fmod.FUND_DB)
    st = p.get_status()
    lo, hi = PHASES[p.phase]["risk_pct"]
    ok, why = p.can_open((lo + hi) / 2)
    if not ok:
        summary["skip_reason"] = why
        log.info("tick skip: %s", why)
        return summary
    open_symbols = {x["symbol"] for x in p.get_positions("open")}
    results = research.latest_results(fmod.FUND_DB, 20)
    cands = select_candidates(results, open_symbols, COOLDOWN, time.time())
    for c in cands[:1]:
        op = await asyncio.to_thread(get_operation, c["symbol"])
        body = operation_to_order(op, c["symbol"], p.phase, market_type(),
                                  st["equity"])
        if not body:
            summary["skipped"] += 1
            continue
        body["strategy"] = f"auto-{c.get('strategy', 'x')}"
        try:
            await fmod.fund_orders(fmod.OrderRequest(**body))
        except Exception as e:
            detail = getattr(e, "detail", str(e))
            send_telegram(f"auto-trader X {body['symbol']}: {detail}")
            summary["skipped"] += 1
            continue
        COOLDOWN[body["symbol"]] = time.time()
        send_telegram(
            f"auto-trader OK {body['side']} {body['symbol']} @ {body['entry']} "
            f"sl={body['stop_loss']} tp={body['take_profit']} "
            f"qty=${body['qty_usd']} lev={body['leverage']}x "
            f"[{execution_mode()}/{market_type()}]")
        summary["ordered"] += 1
    return summary


async def safe_tick():
    try:
        return await tick()
    except Exception as e:
        log.exception("tick revienta")
        send_telegram(f"auto-trader ERROR: {e}")
        return None


async def run_loop():
    log.info("auto-trader iniciado mode=%s interval=%s",
             execution_mode(), os.getenv("AUTO_TRADER_INTERVAL_MIN", "15"))
    while True:
        await safe_tick()
        try:
            mins = float(os.getenv("AUTO_TRADER_INTERVAL_MIN", "15"))
        except ValueError:
            mins = 15.0
        await asyncio.sleep(max(1.0, mins) * 60)


def start_auto_trader():
    if os.getenv("AUTO_TRADER") != "1":
        return False
    asyncio.create_task(run_loop())
    return True
```

(Nota: en los mensajes se usa `OK`/`X` en vez de emojis para no depender de encoding.)

`api/main.py` — en el startup (líneas 56-58):

```python
from auto_trader import start_auto_trader

@app.on_event("startup")
async def startup():
    init_db()
    start_auto_trader()
```

- [ ] **Step 4: Verificar — nuevos + regresión completa**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_auto_trader.py -v`
Expected: PASS (todos)

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: PASS sin errores; suite offline crecida (reportar conteo final).

- [ ] **Step 5: Commit**

```powershell
git add AgentBiz/backend/auto_trader.py AgentBiz/backend/api/main.py AgentBiz/tests/test_auto_trader.py
git commit -m "feat(auto-trader): tick con risk gate y cooldown, loop con aislamiento de errores, arranque en startup"
```

---

### Task 8: env, tests de red (testnet) y regresión final

**Files:**
- Modify: `.env` (gitignored — nunca se commitea)
- Test: `AgentBiz/tests/test_binance_network.py` (nuevo, marker `network`)

**Interfaces:**
- Consumes: Tasks 1-7 completos.
- Produce: suite final verde; smoke manual pendiente de keys de Carlos (spec §9).

- [ ] **Step 1: Escribir los tests de red (skip sin keys)**

```python
# AgentBiz/tests/test_binance_network.py
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
```

- [ ] **Step 2: Verificar que corren (skip sin keys)**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/test_binance_network.py -v`
Expected: 2 SKIP (sin keys) — con keys futuras: 2 PASS.

- [ ] **Step 3: Variables de entorno explícitas en `.env`**

PowerShell (no imprime secrets, solo agrega defaults):

```powershell
$e = Get-Content .env -Raw
if ($e -notmatch 'EXECUTION_MODE') { Add-Content .env "`nEXECUTION_MODE=paper`nAUTO_TRADER=0`nBINANCE_MARKET_TYPE=spot`nAUTO_TRADER_INTERVAL_MIN=15" }
git check-ignore .env
```

Expected: la segunda línea imprime `.env` (confirmación de que está gitignored).

- [ ] **Step 4: Regresión final completa**

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -m "not network" -q`
Expected: PASS — base 86 + todos los nuevos (reportar conteo exacto final).

Run: `$env:PYTHONUTF8="1"; C:/Python313/python.exe -m pytest AgentBiz/tests/ -q`
Expected: PASS — con red incluida (los tests network saltan sin keys).

- [ ] **Step 5: Commit (solo el test de red)**

```powershell
git add AgentBiz/tests/test_binance_network.py
git commit -m "test(broker): tests de red contra testnet (skip sin BINANCE_TESTNET_KEY)"
```

Nota post-plan (manual, fuera de tests): reiniciar uvicorn para que cargue el auto-trader; smoke con keys de Carlos según spec §8.

---

## Post-plan — acciones de Carlos (spec §9)

1. Crear keys en `https://testnet.binance.vision` (login GitHub) → pegarlas en `.env` (`BINANCE_TESTNET_KEY/SECRET`).
2. Smoke: con `EXECUTION_MODE=testnet` enviar una orden manual y verificar en el panel de testnet + `/api/fund/portfolio`.
3. Activar `AUTO_TRADER=1` y dejar correr ≥1 tick (Telegram debe notificar).
4. Decidir cuando aplique: semiauto con dinero real (spec §10).

