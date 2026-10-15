"""Auto-trader: señales cripto -> Trader API -> risk gate -> orden -> Telegram."""
import asyncio
import logging
import os
import time

import requests

import research
from agents.ai_brain import TRADER_API
from broker_binance import execution_mode, funding_rate, quote_volume_24h, to_binance_symbol
from notify import send_telegram
from paper_portfolio import PHASES, Portfolio

log = logging.getLogger("auto_trader")
COOLDOWN = {}
_LOOP_TASK = None


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


FUNDING_MAX = 0.0005
MIN_QUOTE_VOLUME = 50_000_000.0
MAINT_MARGIN = 0.004


def funding_ok(side, rate, threshold=FUNDING_MAX):
    if side == "long":
        return rate <= threshold
    return rate >= -threshold


def liq_behind_stop(entry, stop_loss, side, leverage,
                    buffer=0.0, maint_margin=MAINT_MARGIN):
    stop_dist = abs(entry - stop_loss) / entry
    liq_dist = 1.0 / leverage - maint_margin
    return liq_dist >= stop_dist + buffer


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


def operation_to_order(op, symbol, phase, market_type, equity,
                       funding=None, quote_volume=None):
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
    if market_type == "futures":
        if funding is not None and not funding_ok(side, funding):
            return None
        if quote_volume is not None and quote_volume < MIN_QUOTE_VOLUME:
            return None
    entry = float(op["entry_price"])
    stop_loss = float(op["stop_loss"]["price"])
    take_profit = float(op["take_profit_1"]["price"])
    fit = fit_to_phase(entry, stop_loss, side, phase, market_type)
    if not fit:
        return None
    leverage, stop_loss = fit
    if market_type == "futures" and not liq_behind_stop(entry, stop_loss,
                                                        side, leverage):
        return None
    qty_usd = size_order(equity, entry, stop_loss, leverage, phase)
    if qty_usd <= 0:
        return None
    return {"action": "open", "symbol": symbol, "side": side, "qty_usd": qty_usd,
            "leverage": leverage, "entry": entry, "stop_loss": stop_loss,
            "take_profit": take_profit, "strategy": "auto",
            "market_type": market_type, "review": True}


import api.fund as fmod


async def tick():
    summary = {"marked": 0, "ordered": 0, "skipped": 0, "skip_reason": None}
    try:
        m = await fmod.fund_mark()
        summary["marked"] = m.get("marked", 0)
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
    mt = market_type()
    for c in cands:
        if summary["ordered"] >= 1:
            break
        op = await asyncio.to_thread(get_operation, c["symbol"])
        funding = vol = None
        if mt == "futures":
            try:
                funding = await asyncio.to_thread(funding_rate, c["symbol"])
            except Exception as e:
                log.warning("funding fallo %s: %s", c["symbol"], e)
            try:
                vol = await asyncio.to_thread(quote_volume_24h, c["symbol"])
            except Exception as e:
                log.warning("volumen fallo %s: %s", c["symbol"], e)
        body = operation_to_order(op, c["symbol"], p.phase, mt,
                                  st["equity"], funding=funding,
                                  quote_volume=vol)
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
            COOLDOWN[body["symbol"]] = time.time()
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
    global _LOOP_TASK
    if os.getenv("AUTO_TRADER") != "1":
        return False
    _LOOP_TASK = asyncio.create_task(run_loop())
    return True
