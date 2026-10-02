import os
import asyncio
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from paper_portfolio import Portfolio, PHASES, RiskError
from agents.ai_brain import risk_review
from backtester import rank_universe
from market_data import get_price
import research
from broker_binance import (BrokerError, BrokerOrderInvalid, execution_mode,
                            validate_order, place_order, close_on_exchange,
                            close_sync)
from notify import send_telegram

router = APIRouter(prefix="/api/fund", tags=["fund"])
FUND_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "fund.db"))


def _pf():
    return Portfolio(FUND_DB)


class PhaseRequest(BaseModel):
    phase: Literal["aggressive", "moderate"]


@router.get("/status")
async def fund_status():
    await asyncio.to_thread(research.init_research_db, FUND_DB)
    st = await asyncio.to_thread(lambda: _pf().get_status())
    standard = await asyncio.to_thread(research.get_standard, FUND_DB)
    signals = await asyncio.to_thread(research.latest_results, FUND_DB, 5)
    return {"portfolio": st, "standard": standard, "signals": signals,
            "phase_rules": PHASES[st["phase"]]}


@router.get("/portfolio")
async def fund_portfolio():
    def work():
        p = _pf()
        return (p.get_status(), p.get_positions(), p.get_trades(50))
    status, positions, trades = await asyncio.to_thread(work)
    return {"status": status, "positions": positions, "trades": trades}


@router.post("/phase")
async def fund_phase(req: PhaseRequest):
    try:
        st = await asyncio.to_thread(lambda: _pf().set_phase(req.phase))
    except RiskError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await asyncio.to_thread(lambda: _pf().record_equity())
    return st


@router.get("/performance")
async def fund_performance():
    def work():
        p = _pf()
        curve = p.get_equity_curve()
        st = p.get_status()
        if not curve:
            curve = [{"ts": "now", "equity": st["equity"]}]
        peak = research.get_meta(FUND_DB, "peak_equity", st["equity"]) or st["equity"]
        target = research.get_meta(FUND_DB, "target", st["capital"] * 2)
        return {"curve": curve, "equity": st["equity"], "peak": round(peak, 2),
                "drawdown": st["drawdown"], "target": target,
                "daily_pnl": st["daily_pnl"], "phase": st["phase"]}
    return await asyncio.to_thread(work)


class OrderRequest(BaseModel):
    action: Literal["open", "close"]
    symbol: str = ""
    side: Literal["long", "short"] = "long"
    qty_usd: float = 0.0
    leverage: float = 1.0
    entry: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy: str = "manual"
    market_type: Literal["spot", "futures"] = "spot"
    position_id: Optional[int] = None
    price: Optional[float] = None
    reason: str = "manual"
    review: bool = False


def _log_order(title, detail):
    from memory.database import get_db
    db = get_db()
    db.execute("INSERT INTO tasks (agent_id, title, description, status, result) "
               "VALUES ('trading', ?, ?, 'completed', ?)", (title, detail, detail))
    db.commit()
    db.close()


@router.post("/orders")
async def fund_orders(req: OrderRequest):
    if req.action == "open":
        if req.stop_loss is None or req.take_profit is None:
            raise HTTPException(status_code=422, detail="SL/TP obligatorios")
        if req.qty_usd <= 0 or req.entry <= 0:
            raise HTTPException(status_code=422, detail="qty_usd y entry deben ser > 0")
        mode = execution_mode()
        if mode != "paper":
            try:
                validate_order(req.side, req.leverage, req.symbol, req.market_type)
            except BrokerOrderInvalid as e:
                raise HTTPException(status_code=422, detail=str(e))
        review_result = None
        if req.review:
            review_result = await risk_review({
                "symbol": req.symbol, "side": req.side, "qty_usd": req.qty_usd,
                "leverage": req.leverage, "entry": req.entry,
                "stop_loss": req.stop_loss, "take_profit": req.take_profit,
                "strategy": req.strategy})
            if review_result["decision"] == "rechaza":
                raise HTTPException(status_code=403,
                                    detail=f"Director de Riesgo rechaza: {review_result['reason']}")
        order_id = None
        if mode != "paper":
            try:
                await asyncio.to_thread(
                    lambda: _pf().preflight_open(
                        req.qty_usd, req.leverage, req.entry, req.stop_loss))
            except RiskError as e:
                raise HTTPException(status_code=409, detail=str(e))
            try:
                fill = await asyncio.to_thread(
                    place_order, req.symbol, req.side, req.qty_usd, req.leverage,
                    req.market_type, req.entry, req.stop_loss, req.take_profit)
            except BrokerError as e:
                raise HTTPException(status_code=502, detail=f"broker: {e}")
            req.entry = fill["fill_price"]
            order_id = fill["order_id"]
        try:
            pos = await asyncio.to_thread(
                lambda: _pf().open_position(
                    req.symbol, req.side, req.qty_usd, req.leverage,
                    req.entry, req.stop_loss, req.take_profit, req.strategy))
        except RiskError as e:
            if mode != "paper":
                try:
                    bres = await asyncio.to_thread(
                        close_on_exchange, req.symbol, req.market_type,
                        req.side, req.qty_usd, req.leverage, req.entry)
                    send_telegram(f"orden {req.symbol} rechazada post-fill; "
                                  f"compensacion: {bres}")
                except Exception as ce:
                    send_telegram(f"CRITICO: fill huerfano {req.symbol}: {ce}")
            raise HTTPException(status_code=409, detail=str(e))
        await asyncio.to_thread(lambda: _pf().record_equity())
        try:
            await asyncio.to_thread(
                _log_order, f"Abrir {req.side} {req.symbol}",
                f"{req.side} {req.symbol} qty={req.qty_usd} lev={req.leverage} "
                f"sl={req.stop_loss} tp={req.take_profit} [{req.strategy}]")
        except Exception:
            pass  # auditoria best-effort: no falla la orden
        return {"position": pos, "risk_review": review_result,
                "execution": {"mode": mode,
                              "broker": f"binance-{mode}" if mode != "paper" else None,
                              "order_id": order_id}}
    if req.position_id is None or req.price is None:
        raise HTTPException(status_code=422, detail="position_id y price requeridos para cerrar")
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
                close_sync, row["symbol"], row["side"], row["qty_usd"],
                row["leverage"], row["entry"])
        except BrokerError as e:
            raise HTTPException(status_code=502, detail=f"broker: {e}")
        if bres.get("fill_price"):
            exit_price = bres["fill_price"]
    try:
        trade = await asyncio.to_thread(
            lambda: _pf().close_position(req.position_id, exit_price, req.reason))
    except RiskError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await asyncio.to_thread(lambda: _pf().record_equity())
    try:
        await asyncio.to_thread(
            _log_order, f"Cerrar {req.symbol or trade['symbol']}",
            f"posicion {req.position_id} a {exit_price} ({req.reason})")
    except Exception:
        pass
    return {"trade": trade, "risk_review": None,
            "execution": {"mode": mode,
                          "broker": f"binance-{mode}" if mode != "paper" else None,
                          "order_id": None}}


@router.post("/mark")
async def fund_mark():
    def work():
        p = _pf()
        if not p.get_equity_curve():
            p.record_equity()  # linea base: capital inicial antes del 1er marcado
        positions = p.get_positions("open")
        prices = {}
        failed = []
        marked = 0
        for pos in positions:
            sym = pos["symbol"]
            try:
                prices[sym] = get_price(sym)
                marked += 1
            except Exception:
                if sym not in failed:
                    failed.append(sym)
        try:
            closed = p.mark_to_market(prices)
        except RiskError as e:
            raise HTTPException(status_code=409, detail=str(e))
        if prices or not positions:
            p.record_equity()
        sync_failed = []
        mode = execution_mode()
        if mode != "paper" and closed:
            for c in closed:
                try:
                    close_sync(c["symbol"], c["side"], c["qty_usd"],
                               c["leverage"], c["entry"])
                except Exception as e:
                    sync_failed.append(c["symbol"])
                    send_telegram(f"mark: sync broker fallo {c['symbol']}: {e}")
        st = p.get_status()
        return {"marked": marked, "open": st["open_positions"],
                "closed": closed, "failed": failed, "broker_sync_failed": sync_failed,
                "status": st}
    return await asyncio.to_thread(work)


class BacktestRequest(BaseModel):
    phase: Optional[Literal["aggressive", "moderate"]] = None
    period: str = "1y"


class ResearchRequest(BaseModel):
    phase: Optional[Literal["aggressive", "moderate"]] = None
    period: str = "1y"


@router.post("/backtest")
async def fund_backtest(req: BacktestRequest):
    await asyncio.to_thread(research.init_research_db, FUND_DB)
    phase = req.phase if req.phase else await asyncio.to_thread(lambda: _pf().phase)
    rows = await asyncio.to_thread(
        lambda: rank_universe(phase=phase, period=req.period))
    await asyncio.to_thread(research.insert_strategy_results, FUND_DB, rows, phase)
    return {"count": len(rows), "phase": phase, "top": rows[:20]}


@router.get("/strategies")
async def fund_strategies():
    def work():
        research.init_research_db(FUND_DB)
        return {"standard": research.get_standard(FUND_DB),
                "ranking": research.latest_results(FUND_DB, 50),
                "history": research.research_history(FUND_DB, 20)}
    return await asyncio.to_thread(work)


@router.post("/research")
async def fund_research(req: ResearchRequest):
    try:
        out = await asyncio.to_thread(
            lambda: research.run_research(db_path=FUND_DB, phase=req.phase,
                                          period=req.period))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return out
