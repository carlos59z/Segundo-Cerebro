import os
import asyncio
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from paper_portfolio import Portfolio, PHASES, RiskError
from agents.ai_brain import risk_review
from backtester import rank_universe
import research

router = APIRouter(prefix="/api/fund", tags=["fund"])
FUND_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "fund.db"))


def _pf():
    return Portfolio(FUND_DB)


class PhaseRequest(BaseModel):
    phase: Literal["aggressive", "moderate"]


@router.get("/status")
async def fund_status():
    pf = _pf()
    await asyncio.to_thread(research.init_research_db, FUND_DB)
    st = await asyncio.to_thread(pf.get_status)
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
    pf = _pf()
    try:
        st = await asyncio.to_thread(lambda: pf.set_phase(req.phase))
    except RiskError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await asyncio.to_thread(pf.record_equity)
    return st


@router.get("/performance")
async def fund_performance():
    def work():
        p = _pf()
        curve = p.get_equity_curve()
        st = p.get_status()
        if not curve:
            curve = [{"ts": "now", "equity": st["equity"]}]
        peak = max(pt["equity"] for pt in curve)
        dd = (st["equity"] - peak) / peak if peak else 0.0
        target = research.get_meta(FUND_DB, "target", st["capital"] * 2)
        return {"curve": curve, "equity": st["equity"], "peak": round(peak, 2),
                "drawdown": round(dd, 6), "target": target,
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
    pf = _pf()
    if req.action == "open":
        if req.stop_loss is None or req.take_profit is None:
            raise HTTPException(status_code=422, detail="SL/TP obligatorios")
        if req.qty_usd <= 0 or req.entry <= 0:
            raise HTTPException(status_code=422, detail="qty_usd y entry deben ser > 0")
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
        try:
            pos = await asyncio.to_thread(
                pf.open_position, req.symbol, req.side, req.qty_usd, req.leverage,
                req.entry, req.stop_loss, req.take_profit, req.strategy)
        except RiskError as e:
            raise HTTPException(status_code=409, detail=str(e))
        await asyncio.to_thread(pf.record_equity)
        _log_order(f"Abrir {req.side} {req.symbol}",
                   f"{req.side} {req.symbol} qty={req.qty_usd} lev={req.leverage} "
                   f"sl={req.stop_loss} tp={req.take_profit} [{req.strategy}]")
        return {"position": pos, "risk_review": review_result}
    if req.position_id is None or req.price is None:
        raise HTTPException(status_code=422, detail="position_id y price requeridos para cerrar")
    try:
        trade = await asyncio.to_thread(pf.close_position, req.position_id, req.price, req.reason)
    except RiskError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await asyncio.to_thread(pf.record_equity)
    _log_order(f"Cerrar {req.symbol or trade['symbol']}",
               f"posicion {req.position_id} a {req.price} ({req.reason})")
    return {"trade": trade, "risk_review": None}


class BacktestRequest(BaseModel):
    phase: Optional[Literal["aggressive", "moderate"]] = None
    period: str = "1y"


class ResearchRequest(BaseModel):
    phase: Optional[Literal["aggressive", "moderate"]] = None
    period: str = "1y"


@router.post("/backtest")
async def fund_backtest(req: BacktestRequest):
    pf = _pf()
    await asyncio.to_thread(research.init_research_db, FUND_DB)
    phase = req.phase if req.phase else await asyncio.to_thread(lambda: pf.phase)
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
