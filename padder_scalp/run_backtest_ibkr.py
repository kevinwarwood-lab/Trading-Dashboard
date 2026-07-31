"""Run the Padder Scalp backtest on IBKR data (data_ibkr/) instead of yfinance.
Same engine, same per-symbol tuning — only the data source changes. This is the
apples-to-apples check: does the edge survive on the feed you actually trade?
"""
import os

import pandas as pd

from config import SYMBOLS, params_for
from engine import run_backtest

DATA_DIR = os.path.join(os.path.dirname(__file__), "data_ibkr")


def load(symbol: str):
    safe = symbol.replace("=", "_")
    p5 = os.path.join(DATA_DIR, f"{safe}_5m.csv")
    pd_ = os.path.join(DATA_DIR, f"{safe}_1d.csv")
    if not (os.path.exists(p5) and os.path.exists(pd_)):
        raise FileNotFoundError(f"Missing {p5} or {pd_}. Run fetch_ibkr.py first.")
    m5 = pd.read_csv(p5, index_col=0, parse_dates=True)
    daily = pd.read_csv(pd_, index_col=0, parse_dates=True)
    if m5.index.tz is None:
        m5.index = m5.index.tz_localize("America/New_York")
    else:
        m5.index = m5.index.tz_convert("America/New_York")
    if daily.index.tz is not None:
        daily.index = daily.index.tz_localize(None)
    return m5, daily


def main():
    for sym in ["MES=F", "MNQ=F"]:
        spec = SYMBOLS[sym]
        params = params_for(sym)
        m5, daily = load(sym)
        res = run_backtest(sym, m5, daily, spec["tick_size"], spec["point_value"], params)
        t = res["trades"]
        d = res["diag"]
        n = len(t)
        wins = (t["pnl"] > 0).sum() if n else 0
        sig = d["bull_signals"] + d["bear_signals"]
        print(f"=== {sym}  ({m5.index.min()} -> {m5.index.max()}, {len(m5)} bars) ===")
        print(f"  signals={sig} confirmed={d['confirmed']} "
              f"rr_block={d['blocked_rr']} qty_block={d['blocked_qty']} entered={n}")
        if n:
            print(f"  win_rate={wins/n*100:.1f}%  total_R={t['r_multiple'].sum():.2f}  "
                  f"avg_R={t['r_multiple'].mean():.2f}  pnl=${t['pnl'].sum():.2f}")
        print()


if __name__ == "__main__":
    main()
