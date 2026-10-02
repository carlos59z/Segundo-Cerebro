"""Cliente REST de Binance (spot + futuros USDT-M). Modos: paper/testnet/real."""
import hashlib
import hmac
import os
import time
import urllib.parse

import requests


class BrokerError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


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


from decimal import Decimal

_STEP_CACHE = {}


def _request(method, path, params, market_type, signed=True):
    mode = execution_mode()
    if mode == "paper":
        raise BrokerError("broker no aplica en modo paper")
    cfg = load_keys(mode)
    q = dict(params or {})
    if signed:
        q.update(timestamp=int(time.time() * 1000), recvWindow=5000)
    query = urllib.parse.urlencode(q)
    if signed:
        query += "&signature=" + _sign(cfg["secret"], query)
    url = f"{base_url(mode, market_type)}{path}?{query}"
    try:
        r = requests.request(method, url, timeout=15,
                             headers={"X-MBX-APIKEY": cfg["key"]})
    except requests.RequestException as e:
        raise BrokerError(f"sin conexion con binance: {e}")
    js = r.json() if r.content else {}
    if r.status_code >= 400:
        raise BrokerError(f"binance {r.status_code}: {js}", status=r.status_code)
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


def close_on_exchange(symbol, market_type, side, qty_usd, leverage, entry):
    mode = execution_mode()
    if mode == "paper":
        raise BrokerError("close_on_exchange no aplica en modo paper")
    bsym = to_binance_symbol(symbol, market_type)
    if market_type == "futures":
        js = _request("GET", "/fapi/v2/positionRisk", {"symbol": bsym}, market_type)
        amt = float(js.get("positionAmt") or js.get("amt") or 0)
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
    except BrokerError as e:
        if e.status not in (401, 403, 404):
            raise
    r = close_on_exchange(symbol, "spot", side, qty_usd, leverage, entry)
    r["market_type"] = "spot"
    return r
