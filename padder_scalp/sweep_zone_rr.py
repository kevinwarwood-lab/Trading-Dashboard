"""Parameter sweeps for the R:R geometry question:
  1) zone_pct (sweet-spot zone size)  vs edge, minRR fixed
  2) min_rr                            vs edge, zone fixed
  3) joint zone_pct x min_rr grid      -> sweet spot

Sized with a huge fixed-dollar budget so whole-contract affordability never
zeros a symbol out — this isolates the STRATEGY edge. R-multiples and win rate
are qty-independent; only trade COUNT/quality matter for parameter choice.
"""
import numpy as np
import pandas as pd

from config import SYMBOLS, params_for
from data_fetch import load_symbol
from engine import run_backtest

pd.set_option("display.width", 200)

BIG = {"risk_mode": "fixed_dollar", "fixed_risk_usd": 100_000.0}
ZONES = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
RRS = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]

data = {s: load_symbol(s) for s in ["MES=F", "MNQ=F"]}


def summ(res):
    t = res["trades"]
    n = len(t)
    if n == 0:
        return 0, np.nan, 0.0, np.nan
    wins = (t["pnl"] > 0).sum()
    return n, wins / n * 100, t["r_multiple"].sum(), t["r_multiple"].mean()


def run(sym, **over):
    spec = SYMBOLS[sym]
    m5, daily = data[sym]
    p = {**params_for(sym), **BIG, "enforce_rr": True, **over}
    return summ(run_backtest(sym, m5, daily, spec["tick_size"], spec["point_value"], p))


print("=" * 70)
print("TEST 1: zone size sweep (minRR fixed 2.0)")
print("=" * 70)
for sym in ["MES=F", "MNQ=F"]:
    rows = [dict(zip(["trades", "win_rate", "total_R", "avg_R"],
                     run(sym, zone_pct=z, min_rr=2.0)), zone_pct=z) for z in ZONES]
    df = pd.DataFrame(rows)[["zone_pct", "trades", "win_rate", "total_R", "avg_R"]]
    print(f"\n--- {sym} ---")
    print(df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

print("\n" + "=" * 70)
print("TEST 2: min R:R sweep (zone fixed 20%)")
print("=" * 70)
for sym in ["MES=F", "MNQ=F"]:
    rows = [dict(zip(["trades", "win_rate", "total_R", "avg_R"],
                     run(sym, zone_pct=0.20, min_rr=r)), min_rr=r) for r in RRS]
    df = pd.DataFrame(rows)[["min_rr", "trades", "win_rate", "total_R", "avg_R"]]
    print(f"\n--- {sym} ---")
    print(df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

print("\n" + "=" * 70)
print("TEST 3: joint zone x min_rr grid  (cell = total_R  [trades])")
print("=" * 70)
for sym in ["MES=F", "MNQ=F"]:
    print(f"\n--- {sym} ---   rows=zone_pct, cols=min_rr")
    grid = pd.DataFrame(index=ZONES, columns=RRS, dtype=object)
    best = (None, None, -1e9, 0)
    for z in ZONES:
        for r in RRS:
            n, wr, tr, ar = run(sym, zone_pct=z, min_rr=r)
            grid.loc[z, r] = f"{tr:5.1f}[{n}]"
            if tr > best[2] and n >= 4:   # require >=4 trades to be worth considering
                best = (z, r, tr, n)
    print(grid.to_string())
    if best[0] is not None:
        print(f"  best total_R (>=4 trades): zone_pct={best[0]}, min_rr={best[1]} -> {best[2]:.2f}R over {best[3]} trades")
