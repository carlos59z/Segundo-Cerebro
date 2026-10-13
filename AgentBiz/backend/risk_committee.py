"""Comite de riesgo dinamico del fondo (determinista, sin LLM).

Modos: mantener / reducir / defensivo segun drawdown, daily loss y racha
de trades. Los limits efectivos gobiernan las aperturas en api/fund.py.
"""
import datetime
import json
import sqlite3

from paper_portfolio import PHASES

STREAK_LOSSES = 3


def _conn(db_path):
    c = sqlite3.connect(db_path, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS risk_committee(
        ts TEXT, mode TEXT, limits_json TEXT, reasons_json TEXT)""")
    return c


def evaluate(db_path="fund.db", pf=None):
    if pf is None:
        from paper_portfolio import Portfolio
        pf = Portfolio(db_path)
    phase = getattr(pf, "phase", "aggressive")
    rules = PHASES.get(phase, PHASES["aggressive"])
    st = pf.get_status()
    equity = float(st.get("equity") or 0.0)
    reasons = []
    mode = "mantener"

    curve = pf.get_equity_curve(limit=10000)
    peak = max((p["equity"] for p in curve), default=equity)
    dd = (equity - peak) / peak if peak > 0 else 0.0

    alert = rules["drawdown_alert"]  # negativo
    if dd <= alert:
        mode = "defensivo"
        reasons.append(f"drawdown {dd:.1%} alcanza la alerta de fase ({alert:.0%})")
    elif dd <= alert / 2:
        mode = "reducir"
        reasons.append(f"drawdown {dd:.1%} supera el 50% de la alerta ({alert:.0%})")

    daily_stop = rules["daily_loss_stop"]
    daily_frac = (float(st.get("daily_pnl") or 0.0) / equity) if equity > 0 else 0.0
    if daily_frac <= daily_stop:
        mode = "defensivo"
        reasons.append(f"daily loss stop ({daily_frac:.1%} <= {daily_stop:.0%})")

    if mode == "mantener":
        streak = 0
        for t in pf.get_trades(limit=10):
            if float(t.get("pnl") or 0.0) < 0:
                streak += 1
            else:
                break
        if streak >= STREAK_LOSSES:
            mode = "reducir"
            reasons.append(f"racha de {streak} trades perdedores consecutivos")

    lo, hi = rules["risk_pct"]
    if mode == "defensivo":
        limits = {"max_positions": 2, "max_leverage": 2.0,
                  "risk_pct": (round(lo * 0.5, 4), round(hi * 0.5, 4))}
    elif mode == "reducir":
        limits = {"max_positions": max(1, rules["max_positions"] - 1),
                  "max_leverage": min(3.0, rules["max_leverage"]),
                  "risk_pct": (round(lo * 0.75, 4), round(hi * 0.75, 4))}
    else:
        limits = {"max_positions": rules["max_positions"],
                  "max_leverage": rules["max_leverage"],
                  "risk_pct": (lo, hi)}

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out = {"mode": mode, "reasons": reasons, "limits": limits, "ts": ts}
    c = _conn(db_path)
    try:
        c.execute("INSERT INTO risk_committee VALUES(?,?,?,?)",
                  (ts, mode, json.dumps(limits), json.dumps(reasons)))
        c.commit()
    finally:
        c.close()
    return out


def history(db_path, limit=50):
    c = _conn(db_path)
    try:
        rows = c.execute(
            "SELECT ts, mode, limits_json, reasons_json FROM risk_committee "
            "ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    finally:
        c.close()
    return [{"ts": r[0], "mode": r[1],
             "limits": json.loads(r[2]), "reasons": json.loads(r[3])}
            for r in rows]
