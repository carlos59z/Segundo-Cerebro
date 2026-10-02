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
