import pytest
import paper_portfolio as pp


@pytest.fixture
def pf(tmp_path):
    return pp.Portfolio(str(tmp_path / "t.db"), capital=2500.0, phase="aggressive")


def _open(p, symbol="BTC", entry=100.0):
    return p.open_position(symbol, "long", qty_usd=300.0, leverage=2.0,
                           entry=entry, stop_loss=95.0, take_profit=110.0,
                           strategy="sma_cross")


def test_initial_state(pf):
    s = pf.get_status()
    assert s["capital"] == 2500.0 and s["equity"] == 2500.0
    assert s["phase"] == "aggressive" and s["open_positions"] == 0


def test_max_positions_enforced(pf):
    for i in range(5):
        pf.open_position(f"SYM{i}", "long", 200.0, 1.0, 100.0, 95.0, 110.0, "s")
    ok, why = pf.can_open(0.05)
    assert not ok and "5" in why


def test_phase_change_keeps_positions_and_tightens_limits(pf):
    _open(pf)
    pf.set_phase("moderate")
    s = pf.get_status()
    assert s["phase"] == "moderate" and s["open_positions"] == 1
    ok, _ = pf.can_open(0.02)
    assert ok
    ok2, why2 = pf.can_open(0.09)
    assert not ok2


def test_sl_hit_closes_with_loss(pf):
    _open(pf, entry=100.0)
    pf.mark_to_market({}, bars={"BTC": (94.0, 99.0)})
    s = pf.get_status()
    assert s["open_positions"] == 0
    assert s["equity"] < 2500.0
    assert s["trades"] == 1 and s["win_rate"] == 0.0


def test_tp_hit_closes_with_profit(pf):
    _open(pf, entry=100.0)
    pf.mark_to_market({}, bars={"BTC": (101.0, 112.0)})
    s = pf.get_status()
    assert s["open_positions"] == 0 and s["equity"] > 2500.0
    assert s["win_rate"] == 1.0


def test_daily_loss_stop_blocks_new(pf):
    _open(pf, entry=100.0)
    pf.mark_to_market({}, bars={"BTC": (90.0, 91.0)})
    pf._force_daily_pnl(-260.0)
    ok, why = pf.can_open(0.05)
    assert not ok and "diaria" in why.lower()


def test_risk_error_raised(pf):
    with pytest.raises(pp.RiskError):
        pf.open_position("X", "long", 10_000.0, 50.0, 100.0, 1.0, 200.0, "s")


def test_unrealized_marks_equity(pf):
    _open(pf, entry=100.0)
    pf.mark_to_market({"BTC": 105.0})
    s = pf.get_status()
    assert s["unrealized"] == pytest.approx(30.0)
    assert s["equity"] == pytest.approx(2530.0)


def test_unrealized_included_in_drawdown(pf):
    _open(pf, entry=100.0)
    pf.mark_to_market({"BTC": 96.0})
    s = pf.get_status()
    assert s["equity"] == pytest.approx(2476.0)
    assert s["drawdown"] < 0


def test_daily_stop_rollover(pf):
    pf._force_daily_pnl(-260.0)
    pf._set_meta("daily_date", "2000-01-01")
    ok, why = pf.can_open(0.05)
    assert ok, why


def test_phase_change_preserves_daily_stop(pf):
    pf._force_daily_pnl(-260.0)
    pf.set_phase("moderate")
    ok, why = pf.can_open(0.02)
    assert not ok and "diaria" in why.lower()


def test_phase_persisted(tmp_path):
    db = str(tmp_path / "p.db")
    p1 = pp.Portfolio(db, phase="aggressive")
    p1.set_phase("moderate")
    p2 = pp.Portfolio(db)
    assert p2.phase == "moderate"


def test_short_sl_hit(pf):
    pf.open_position("ETH", "short", 300.0, 2.0, 100.0, 105.0, 90.0, "s")
    pf.mark_to_market({}, bars={"ETH": (101.0, 106.0)})
    s = pf.get_status()
    assert s["open_positions"] == 0
    assert s["equity"] == pytest.approx(2470.0)
    assert s["trades"] == 1 and s["win_rate"] == 0.0


def test_short_tp_hit(pf):
    pf.open_position("ETH", "short", 300.0, 2.0, 100.0, 105.0, 90.0, "s")
    pf.mark_to_market({}, bars={"ETH": (88.0, 89.0)})
    s = pf.get_status()
    assert s["open_positions"] == 0
    assert s["equity"] == pytest.approx(2560.0)
    assert s["win_rate"] == 1.0


def test_leverage_cap_reachable_in_range_risk(pf):
    pf.set_phase("moderate")
    with pytest.raises(pp.RiskError, match="apalancamiento"):
        pf.open_position("X", "long", 200.0, 3.0, 100.0, 99.0, 110.0, "s")


def test_margin_exceeds_equity_reachable(pf):
    with pytest.raises(pp.RiskError, match="margen"):
        pf.open_position("X", "long", 3000.0, 1.0, 100.0, 95.0, 110.0, "s")
