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
    leverage = round(max(1.0, min(leverage, rules["max_leverage"])), 2)
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
