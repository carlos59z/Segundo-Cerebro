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
