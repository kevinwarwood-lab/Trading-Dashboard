"""Run the Padder Scalp backtest across the four micro futures symbols."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from config import PARAMS, SYMBOLS, params_for
from data_fetch import load_symbol
from engine import run_backtest

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def summarize(trades: pd.DataFrame, initial_capital: float, final_equity: float, equity_curve: pd.Series) -> dict:
    if trades.empty:
        return dict(n=0, win_rate=np.nan, avg_r=np.nan, total_r=np.nan,
                    total_pnl=0.0, profit_factor=np.nan, max_dd_pct=0.0,
                    return_pct=0.0)
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] <= 0]
    gross_win = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    roll_max = equity_curve.cummax()
    dd = (equity_curve - roll_max) / roll_max
    return dict(
        n=len(trades),
        win_rate=len(wins) / len(trades) * 100,
        avg_r=trades["r_multiple"].mean(),
        total_r=trades["r_multiple"].sum(),
        total_pnl=trades["pnl"].sum(),
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else np.nan,
        max_dd_pct=dd.min() * 100,
        return_pct=(final_equity / initial_capital - 1) * 100,
    )


def main(refresh: bool = False, symbols: dict | None = None, params: dict | None = None,
         tag: str = "", title: str = "Micro Futures"):
    symbols = symbols if symbols is not None else SYMBOLS
    params = params if params is not None else PARAMS
    suffix = f"_{tag}" if tag else ""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    all_summaries = []
    lines = [f"# Padder Scalp (PDS-01) Backtest — {title}\n",
             f"5-minute bars, ~60-day yfinance window. Base params: {params}\n"]

    for symbol, spec in symbols.items():
        sym_params = params_for(symbol, base=params)
        print(f"--- {symbol} ({spec['name']}) ---")
        m5, daily = load_symbol(symbol, refresh=refresh)
        if m5.empty or daily.empty:
            print(f"  no data for {symbol}, skipping")
            continue
        print(f"  {len(m5)} 5m bars from {m5.index.min()} to {m5.index.max()}")
        if sym_params != params:
            print(f"  overrides: { {k: v for k, v in sym_params.items() if params.get(k) != v} }")

        result = run_backtest(symbol, m5, daily, spec["tick_size"], spec["point_value"], sym_params)
        trades = result["trades"]
        summ = summarize(trades, sym_params["initial_capital"], result["final_equity"], result["equity_curve"])
        summ["symbol"] = symbol
        summ["name"] = spec["name"]
        all_summaries.append(summ)

        trades_path = os.path.join(REPORTS_DIR, f"{symbol.replace('=', '_')}_trades.csv")
        trades.to_csv(trades_path, index=False)

        print(f"  trades={summ['n']}  win_rate={summ['win_rate']:.1f}%  "
              f"avg_R={summ['avg_r']:.2f}  total_R={summ['total_r']:.2f}  "
              f"pnl=${summ['total_pnl']:.2f}  return={summ['return_pct']:.2f}%  "
              f"max_dd={summ['max_dd_pct']:.2f}%" if summ["n"] else "  no trades triggered")

        lines.append(f"\n## {symbol} — {spec['name']}\n")
        if sym_params != params:
            lines.append(f"Overrides: { {k: v for k, v in sym_params.items() if params.get(k) != v} }\n")
        if summ["n"] == 0:
            lines.append("No trades triggered in this window.\n")
        else:
            lines.append(f"- Trades: {summ['n']}\n")
            lines.append(f"- Win rate: {summ['win_rate']:.1f}%\n")
            lines.append(f"- Avg R: {summ['avg_r']:.2f}\n")
            lines.append(f"- Total R: {summ['total_r']:.2f}\n")
            lines.append(f"- Total PnL: ${summ['total_pnl']:.2f}\n")
            lines.append(f"- Profit factor: {summ['profit_factor']:.2f}\n")
            lines.append(f"- Return: {summ['return_pct']:.2f}%\n")
            lines.append(f"- Max drawdown: {summ['max_dd_pct']:.2f}%\n")

    summary_df = pd.DataFrame(all_summaries)
    summary_path = os.path.join(REPORTS_DIR, f"summary{suffix}.csv")
    summary_df.to_csv(summary_path, index=False)

    report_path = os.path.join(REPORTS_DIR, f"backtest_report{suffix}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"\nSaved: {summary_path}\nSaved: {report_path}")
    return summary_df


if __name__ == "__main__":
    main()
