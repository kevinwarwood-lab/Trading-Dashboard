"""
Fetch REAL 5-minute + daily futures history from Interactive Brokers, so the
Padder Scalp backtest runs on the same feed you trade — not yfinance.

WHY THIS EXISTS: yfinance only serves ~60 days of 5m futures data, and its
continuous-contract stitching differs enough from IBKR/TradingView that
backtested trades did not reproduce live. This pulls IBKR's own bars.

REQUIREMENTS (must be done on YOUR machine, once):
  1. Launch Trader Workstation (TWS) OR IB Gateway and log in.
     - The "Interactive Brokers" link inside TradingView does NOT count — that
       is a separate integration and does not open a local API port.
  2. Enable the API:  TWS/Gateway -> File/Edit -> Global Config -> API ->
     Settings -> tick "Enable ActiveX and Socket Clients". Note the "Socket
     port". Defaults:
        TWS live     7496     TWS paper     7497
        Gateway live 4001     Gateway paper 4002
  3. Add 127.0.0.1 to "Trusted IPs" (or leave API auth on and accept the
     connection prompt the first time this runs).
  4. Run:  python fetch_ibkr.py --port 7497        (use YOUR port)

Micros vs full-size: MES 5m price action == ES, MNQ == NQ (identical index,
identical ticks; only the $ multiplier differs). We fetch the MICRO contracts
directly here so there is zero proxy assumption. Sizing multipliers live in
config.py.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime

import pandas as pd

from ib_async import IB, ContFuture, util

OUT_DIR = os.path.join(os.path.dirname(__file__), "data_ibkr")

# yfinance-style keys kept so the rest of the pipeline (config point_values,
# report names) lines up 1:1 with what we already validated.
SYMBOLS = {
    "MES=F": {"ib_symbol": "MES", "exchange": "CME", "currency": "USD"},
    "MNQ=F": {"ib_symbol": "MNQ", "exchange": "CME", "currency": "USD"},
}


def _bars_to_df(bars) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()
    df = util.df(bars)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"date": "ts"})
    df = df[["ts", "open", "high", "low", "close", "volume"]].copy()
    df["ts"] = pd.to_datetime(df["ts"])
    return df.set_index("ts")


def fetch_5m(ib: IB, contract, months: int) -> pd.DataFrame:
    """Walk backwards in 1-month chunks; IBKR caps 5m requests and paces hard."""
    frames = []
    end = ""  # empty => now
    for i in range(months):
        bars = ib.reqHistoricalData(
            contract, endDateTime=end, durationStr="1 M",
            barSizeSetting="5 mins", whatToShow="TRADES",
            useRTH=False, formatDate=1)
        df = _bars_to_df(bars)
        if df.empty:
            print(f"    chunk {i+1}/{months}: empty, stopping early")
            break
        frames.append(df)
        earliest = df.index.min()
        print(f"    chunk {i+1}/{months}: {len(df)} bars back to {earliest}")
        end = earliest.strftime("%Y%m%d %H:%M:%S")
        time.sleep(12)  # respect IBKR historical pacing limits
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames)
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out


def fetch_daily(ib: IB, contract, years: int) -> pd.DataFrame:
    bars = ib.reqHistoricalData(
        contract, endDateTime="", durationStr=f"{years} Y",
        barSizeSetting="1 day", whatToShow="TRADES",
        useRTH=False, formatDate=1)
    return _bars_to_df(bars)


def to_ny(df: pd.DataFrame) -> pd.DataFrame:
    """5m -> America/New_York tz-aware (matches yfinance loader output)."""
    if df.empty:
        return df
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    df = df.copy()
    df.index = idx.tz_convert("America/New_York")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True,
                    help="TWS 7496 live / 7497 paper; Gateway 4001 live / 4002 paper")
    ap.add_argument("--client-id", type=int, default=17)
    ap.add_argument("--months", type=int, default=18, help="months of 5m history")
    ap.add_argument("--daily-years", type=int, default=3)
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    ib = IB()
    print(f"Connecting to {args.host}:{args.port} (clientId={args.client_id})...")
    ib.connect(args.host, args.port, clientId=args.client_id, timeout=15)
    print("Connected.\n")

    try:
        for key, spec in SYMBOLS.items():
            print(f"=== {key} ({spec['ib_symbol']} @ {spec['exchange']}) ===")
            c = ContFuture(spec["ib_symbol"], spec["exchange"], currency=spec["currency"])
            ib.qualifyContracts(c)
            print(f"  qualified: {c.localSymbol or c.symbol}")

            print(f"  fetching {args.months} months of 5m bars...")
            m5 = to_ny(fetch_5m(ib, c, args.months))
            print(f"  fetching {args.daily_years}y of daily bars...")
            daily = fetch_daily(ib, c, args.daily_years)
            if daily.index.tz is not None:
                daily.index = daily.index.tz_localize(None)

            safe = key.replace("=", "_")
            p5 = os.path.join(OUT_DIR, f"{safe}_5m.csv")
            pd_ = os.path.join(OUT_DIR, f"{safe}_1d.csv")
            m5.to_csv(p5)
            daily.to_csv(pd_)
            span = f"{m5.index.min()} -> {m5.index.max()}" if not m5.empty else "EMPTY"
            print(f"  saved {len(m5)} 5m bars ({span})")
            print(f"  saved {len(daily)} daily bars -> {pd_}\n")
    finally:
        ib.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    main()
