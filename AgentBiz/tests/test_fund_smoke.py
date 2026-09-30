import paper_portfolio as pp
import fund_smoke


def test_smoke_module_imports():
    assert callable(fund_smoke.main)


def test_smoke(tmp_path):
    pf = pp.Portfolio(str(tmp_path / "s.db"))
    pf.open_position("BTC", "long", 500.0, 2.0, 100.0, 95.0, 110.0, "sma_cross")
    pf.mark_to_market({}, bars={"BTC": (101.0, 111.0)})
    st = pf.get_status()
    assert st["trades"] == 1 and st["equity"] > 2500.0
