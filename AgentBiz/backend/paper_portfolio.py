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
        c = sqlite3.connect(self.db, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    def _init_db(self, capital):
        c = self._conn()
        c.execute("""CREATE TABLE IF NOT EXISTS positions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT,
            qty_usd REAL, leverage REAL, entry REAL, stop_loss REAL, take_profit REAL,
            strategy TEXT, opened_at TEXT, status TEXT DEFAULT 'open', unrealized REAL DEFAULT 0)""")
        try:
            c.execute("ALTER TABLE positions ADD COLUMN unrealized REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
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
            c.execute("INSERT INTO meta VALUES('phase', ?)", (self.phase,))
            c.execute("INSERT INTO meta VALUES('daily_date', ?)",
                      (datetime.date.today().isoformat(),))
        c.commit()
        c.close()
        stored = self._meta_raw("phase")
        if stored:
            self.phase = stored

    def _meta_raw(self, key):
        c = self._conn()
        try:
            row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row[0] if row else None
        finally:
            c.close()

    def _meta(self, key):
        v = self._meta_raw(key)
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _set_meta(self, key, value):
        c = self._conn()
        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))
        c.commit()
        c.close()

    def _force_daily_pnl(self, v):
        self._set_meta("daily_pnl", v)

    def _rollover_day(self):
        today = datetime.date.today().isoformat()
        if self._meta_raw("daily_date") == today:
            return
        c = self._conn()
        try:
            c.execute("INSERT OR REPLACE INTO meta VALUES('daily_date', ?)", (today,))
            c.execute("INSERT OR REPLACE INTO meta VALUES('daily_pnl', 0.0)")
            c.commit()
        finally:
            c.close()

    def get_status(self):
        self._rollover_day()
        c = self._conn()
        try:
            open_n = c.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
            unrealized = c.execute(
                "SELECT COALESCE(SUM(unrealized),0) FROM positions WHERE status='open'").fetchone()[0]
            pnls = [t[0] for t in c.execute("SELECT pnl FROM trades").fetchall()]
        finally:
            c.close()
        wins = sum(1 for p in pnls if p > 0)
        capital = self._meta("capital")
        realized = sum(pnls)
        equity = capital + realized + unrealized
        peak = self._meta("peak_equity")
        if equity > peak:
            self._set_meta("peak_equity", equity)
            peak = equity
        drawdown = (equity - peak) / peak if peak else 0.0
        daily_pnl = self._meta("daily_pnl")
        rules = PHASES[self.phase]
        return {
            "capital": round(capital, 2), "equity": round(equity, 2),
            "cash": round(capital + realized, 2), "unrealized": round(unrealized, 2),
            "open_positions": open_n,
            "daily_pnl": round(daily_pnl, 2),
            "drawdown": round(drawdown, 6), "phase": self.phase,
            "trades": len(pnls),
            "win_rate": round(wins / len(pnls), 4) if pnls else 0.0,
            "daily_stop_hit": daily_pnl <= rules["daily_loss_stop"] * capital,
        }

    def get_positions(self, status="open"):
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT id,symbol,side,qty_usd,leverage,entry,stop_loss,take_profit,"
                "strategy,opened_at,unrealized FROM positions WHERE status=? ORDER BY id DESC",
                (status,)).fetchall()
        finally:
            c.close()
        cols = ["id", "symbol", "side", "qty_usd", "leverage", "entry", "stop_loss",
                "take_profit", "strategy", "opened_at", "unrealized"]
        return [dict(zip(cols, r)) for r in rows]

    def get_trades(self, limit=50):
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT id,position_id,symbol,side,entry,exit,pnl,reason,strategy,closed_at "
                "FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        finally:
            c.close()
        cols = ["id", "position_id", "symbol", "side", "entry", "exit", "pnl",
                "reason", "strategy", "closed_at"]
        return [dict(zip(cols, r)) for r in rows]

    def record_equity(self):
        st = self.get_status()
        c = self._conn()
        try:
            c.execute("INSERT INTO equity_curve VALUES(?,?)",
                      (datetime.datetime.now(datetime.timezone.utc).isoformat(), st["equity"]))
            c.commit()
        finally:
            c.close()
        return st["equity"]

    def get_equity_curve(self, limit=1000):
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT ts, equity FROM equity_curve ORDER BY rowid DESC LIMIT ?",
                (limit,)).fetchall()
        finally:
            c.close()
        return [{"ts": r[0], "equity": r[1]} for r in reversed(rows)]

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

    def preflight_open(self, qty_usd, leverage, entry, stop_loss):
        """Mismos checks de open_position sin insertar (validar antes del broker)."""
        risk_pct = abs(entry - stop_loss) / entry * leverage
        ok, why = self.can_open(risk_pct)
        if not ok:
            raise RiskError(why)
        if leverage > PHASES[self.phase]["max_leverage"]:
            raise RiskError(f"apalancamiento {leverage}x excede max {PHASES[self.phase]['max_leverage']}x")
        if qty_usd * leverage > self.get_status()["equity"]:
            raise RiskError("margen total excede equity")

    def open_position(self, symbol, side, qty_usd, leverage, entry, stop_loss, take_profit, strategy):
        self.preflight_open(qty_usd, leverage, entry, stop_loss)
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
            row = c.execute(
                "SELECT symbol,side,qty_usd,leverage,entry,stop_loss,take_profit,strategy "
                "FROM positions WHERE id=? AND status='open'", (position_id,)).fetchone()
            if not row:
                raise RiskError(f"posicion {position_id} no abierta")
            symbol, side, qty_usd, leverage, entry, sl, tp, strat = row
            sign = 1 if side == "long" else -1
            pnl = sign * (price - entry) / entry * qty_usd * leverage
            c.execute("UPDATE positions SET status='closed', unrealized=0 WHERE id=?", (position_id,))
            c.execute(
                "INSERT INTO trades(position_id,symbol,side,entry,exit,pnl,reason,strategy,closed_at,qty_usd,leverage) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (position_id, symbol, side, entry, price, pnl, reason, strat,
                 datetime.datetime.now(datetime.timezone.utc).isoformat(), qty_usd, leverage))
            c.commit()
        finally:
            c.close()
        self._set_meta("daily_pnl", self._meta("daily_pnl") + pnl)
        return {"pnl": round(pnl, 2), "reason": reason, "symbol": symbol,
                "position_id": position_id, "side": side, "entry": entry,
                "qty_usd": qty_usd, "leverage": leverage}

    def mark_to_market(self, prices, bars=None):
        """Marca unrealized con precios dados y cierra posiciones cuyo SL/TP toca la barra."""
        closed = []
        bars = bars or {}
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT id,symbol,side,entry,qty_usd,leverage,stop_loss,take_profit "
                "FROM positions WHERE status='open'"
            ).fetchall()
        finally:
            c.close()
        remaining = []
        for pid, symbol, side, entry, qty_usd, leverage, sl, tp in rows:
            low, high = bars.get(symbol, (None, None))
            if low is None:
                px = prices.get(symbol)
                if px is None:
                    remaining.append((pid, symbol, side, entry, qty_usd, leverage, None))
                    continue
                if side == "long":
                    if px <= sl:
                        closed.append(self.close_position(pid, sl, "sl"))
                        continue
                    elif px >= tp:
                        closed.append(self.close_position(pid, tp, "tp"))
                        continue
                else:
                    if px >= sl:
                        closed.append(self.close_position(pid, sl, "sl"))
                        continue
                    elif px <= tp:
                        closed.append(self.close_position(pid, tp, "tp"))
                        continue
                remaining.append((pid, symbol, side, entry, qty_usd, leverage, px))
                continue
            if side == "long":
                if low <= sl:
                    closed.append(self.close_position(pid, sl, "sl"))
                    continue
                elif high >= tp:
                    closed.append(self.close_position(pid, tp, "tp"))
                    continue
            else:
                if high >= sl:
                    closed.append(self.close_position(pid, sl, "sl"))
                    continue
                elif low <= tp:
                    closed.append(self.close_position(pid, tp, "tp"))
                    continue
            remaining.append((pid, symbol, side, entry, qty_usd, leverage, (low + high) / 2))
        c = self._conn()
        try:
            for pid, symbol, side, entry, qty_usd, leverage, mark in remaining:
                if mark is None:
                    continue
                sign = 1 if side == "long" else -1
                unrealized = sign * (mark - entry) / entry * qty_usd * leverage
                c.execute("UPDATE positions SET unrealized=? WHERE id=?", (unrealized, pid))
            c.commit()
        finally:
            c.close()
        return closed

    def set_phase(self, phase):
        if phase not in PHASES:
            raise RiskError(f"fase desconocida: {phase}")
        self.phase = phase
        self._set_meta("phase", phase)
        return self.get_status()
