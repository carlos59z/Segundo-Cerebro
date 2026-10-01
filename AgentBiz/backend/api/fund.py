import os
import asyncio
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from paper_portfolio import Portfolio, PHASES, RiskError
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
