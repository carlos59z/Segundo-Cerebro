"""Portafolio paper de $2,500 con limites por fase y cierre automatico SL/TP."""
import sqlite3
import datetime

PHASES = {
    "aggressive": {"risk_pct": (0.05, 0.10), "max_positions": 5, "max_leverage": 5.0,
                   "daily_loss_stop": -0.10, "drawdown_alert": -0.20},
    "moderate": {"risk_pct": (0.02, 0.03), "max_positions": 4, "max_leverage": 2.0,
                 "daily_loss_stop": -0.05, "drawdown_alert": -0.10},
}


class RiskError(Exception):
    pass


class Portfolio:
    def __init__(self, db_path, capital=2500.0, phase="aggressive"):
        self.db = db_path
        self.phase = phase if phase in PHASES else "aggressive"
        self._init_db(capital)

    def _conn(self):
        return sqlite3.connect(self.db)

    def _init_db(self, capital):
        c = self._conn()
        c.execute("""CREATE TABLE IF NOT EXISTS positions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT,
            qty_usd REAL, leverage REAL, entry REAL, stop_loss REAL, take_profit REAL,
            strategy TEXT, opened_at TEXT, status TEXT DEFAULT 'open')""")
        c.execute("""CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT, position_id INTEGER, symbol TEXT,
            side TEXT, entry REAL, exit REAL, pnl REAL, reason TEXT, strategy TEXT,
            closed_at TEXT, qty_usd REAL, leverage REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS equity_curve(
            ts TEXT, equity REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value REAL)""")
        row = c.execute("SELECT value FROM meta WHERE key='capital'").fetchone()
        if row is None:
            c.execute("INSERT INTO meta VALUES('capital', ?)", (capital,))
            c.execute("INSERT INTO meta VALUES('daily_pnl', 0.0)")
        c.commit()
        c.close()

    def _meta(self, key):
        c = self._conn()
        try:
            row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return float(row[0]) if row else 0.0
        finally:
            c.close()

    def _set_meta(self, key, value):
        c = self._conn()
        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, float(value)))
        c.commit()
        c.close()

    def _force_daily_pnl(self, v):
        self._set_meta("daily_pnl", v)

    def get_status(self):
        c = self._conn()
        try:
            open_n = c.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
            pnls = [t[0] for t in c.execute("SELECT pnl FROM trades").fetchall()]
        finally:
            c.close()
        wins = sum(1 for p in pnls if p > 0)
        capital = self._meta("capital")
        realized = sum(pnls)
        equity = capital + realized
        peak = self._meta("peak_equity")
        if equity > peak:
            self._set_meta("peak_equity", equity)
            peak = equity
        drawdown = (equity - peak) / peak if peak else 0.0
        daily_pnl = self._meta("daily_pnl")
        rules = PHASES[self.phase]
        return {
            "capital": round(capital, 2), "equity": round(equity, 2),
            "cash": round(equity, 2), "open_positions": open_n,
            "daily_pnl": round(daily_pnl, 2),
            "drawdown": round(drawdown, 6), "phase": self.phase,
            "trades": len(pnls),
            "win_rate": round(wins / len(pnls), 4) if pnls else 0.0,
            "daily_stop_hit": daily_pnl <= rules["daily_loss_stop"] * capital,
        }

    def can_open(self, risk_pct):
        rules = PHASES[self.phase]
        if not (rules["risk_pct"][0] <= risk_pct <= rules["risk_pct"][1]):
            return False, (f"riesgo {risk_pct:.0%} fuera de rango de fase {self.phase} "
                           f"({rules['risk_pct'][0]:.0%}-{rules['risk_pct'][1]:.0%})")
        st = self.get_status()
        if st["open_positions"] >= rules["max_positions"]:
            return False, f"maximo {rules['max_positions']} posiciones abiertas"
        if st["daily_stop_hit"]:
            return False, "stop de perdida diaria activo"
        return True, "ok"

    def open_position(self, symbol, side, qty_usd, leverage, entry, stop_loss, take_profit, strategy):
        risk_pct = abs(entry - stop_loss) / entry * leverage
        ok, why = self.can_open(risk_pct)
        if not ok:
            raise RiskError(why)
        if leverage > PHASES[self.phase]["max_leverage"]:
            raise RiskError(f"apalancamiento {leverage}x excede max {PHASES[self.phase]['max_leverage']}x")
        if qty_usd * leverage > self.get_status()["equity"]:
            raise RiskError("margen total excede equity")
        c = self._conn()
        try:
            cur = c.execute(
                "INSERT INTO positions(symbol,side,qty_usd,leverage,entry,stop_loss,take_profit,strategy,opened_at,status) "
                "VALUES(?,?,?,?,?,?,?,?,?, 'open')",
                (symbol, side, qty_usd, leverage, entry, stop_loss, take_profit, strategy,
                 datetime.datetime.now(datetime.timezone.utc).isoformat()))
            c.commit()
            return {"id": cur.lastrowid, "symbol": symbol, "side": side, "entry": entry}
        finally:
            c.close()

    def close_position(self, position_id, price, reason):
        c = self._conn()
        try:
            row = c.execute("SELECT * FROM positions WHERE id=? AND status='open'", (position_id,)).fetchone()
            if not row:
                raise RiskError(f"posicion {position_id} no abierta")
            _, symbol, side, qty_usd, leverage, entry, sl, tp, strat, _, _ = row
            sign = 1 if side == "long" else -1
            pnl = sign * (price - entry) / entry * qty_usd * leverage
            c.execute("UPDATE positions SET status='closed' WHERE id=?", (position_id,))
            c.execute(
                "INSERT INTO trades(position_id,symbol,side,entry,exit,pnl,reason,strategy,closed_at,qty_usd,leverage) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (position_id, symbol, side, entry, price, pnl, reason, strat,
                 datetime.datetime.now(datetime.timezone.utc).isoformat(), qty_usd, leverage))
            c.commit()
        finally:
            c.close()
        self._set_meta("daily_pnl", self._meta("daily_pnl") + pnl)
        return {"pnl": round(pnl, 2), "reason": reason, "symbol": symbol}

    def mark_to_market(self, prices, bars=None):
        """Cierra posiciones cuyo SL/TP toca la barra (low<=SL o high>=TP)."""
        closed = []
        bars = bars or {}
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT id,symbol,side,entry,stop_loss,take_profit FROM positions WHERE status='open'"
            ).fetchall()
        finally:
            c.close()
        for pid, symbol, side, entry, sl, tp in rows:
            low, high = bars.get(symbol, (None, None))
            if low is None:
                px = prices.get(symbol)
                if px is None:
                    continue
                if side == "long":
                    if px <= sl:
                        closed.append(self.close_position(pid, sl, "sl"))
                    elif px >= tp:
                        closed.append(self.close_position(pid, tp, "tp"))
                else:
                    if px >= sl:
                        closed.append(self.close_position(pid, sl, "sl"))
                    elif px <= tp:
                        closed.append(self.close_position(pid, tp, "tp"))
                continue
            if side == "long":
                if low <= sl:
                    closed.append(self.close_position(pid, sl, "sl"))
                elif high >= tp:
                    closed.append(self.close_position(pid, tp, "tp"))
            else:
                if high >= sl:
                    closed.append(self.close_position(pid, sl, "sl"))
                elif low <= tp:
                    closed.append(self.close_position(pid, tp, "tp"))
        return closed

    def set_phase(self, phase):
        if phase not in PHASES:
            raise RiskError(f"fase desconocida: {phase}")
        self.phase = phase
        self._set_meta("daily_pnl", 0.0)
        return self.get_status()
