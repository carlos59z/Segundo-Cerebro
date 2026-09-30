"""Humo del motor: ranking real + 1 operacion paper.  python backend/fund_smoke.py"""
import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtester import rank_universe
from paper_portfolio import Portfolio
from market_data import get_price


def main():
    print("== Ranking (agresivo) ==")
    rows = rank_universe(phase="aggressive")
    for r in rows[:5]:
        print(f"  {r['symbol']:14} {r['strategy']:18} sharpe={r['sharpe']:+.2f} "
              f"ret={r['total_return']:+.1%} dd={r['max_drawdown']:.1%} eligible={r['eligible']}")
    print("\n== Portfolio paper ==")
    pf = Portfolio("fund.db")
    px = get_price("BTC")
    pf.open_position("BTC", "long", 400.0, 2.0, px, px * 0.97, px * 1.06, "sma_cross")
    pf.mark_to_market({"BTC": px})
    print(pf.get_status())


if __name__ == "__main__":
    main()
