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
