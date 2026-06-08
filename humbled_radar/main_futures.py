"""Humbled Radar Futures — CLI entry point."""
import argparse
import json
import sys
from datetime import date

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from utils.futures_data import load_daily, load_intraday, prior_settlement, build_synthetic_intraday
from strategies.futures_bias import classify_bias, daily_bias
from strategies.futures_setups import (
    setup_a_golden_reversal,
    setup_b_gap_vwap,
    setup_c_vwap_breakout,
    smt_divergence_check,
)
from indicators.futures_indicators import pivot_points
from risk.futures_sizing import size_contracts, scale_out_plan
from agent_brief.humbled_radar_brief import generate_brief, post_brief
from paper_trader import run_paper_trading


def cmd_scan(args):
    print("Loading ES daily...")
    es_daily = load_daily("ES", days=400)
    print("Loading NQ daily...")
    nq_daily = load_daily("NQ", days=400)

    es_bias = daily_bias(es_daily, "ES")
    nq_bias = daily_bias(nq_daily, "NQ")

    es_df = classify_bias(es_daily, "ES").iloc[-1]
    nq_df = classify_bias(nq_daily, "NQ").iloc[-1]

    smt_agree = es_bias == nq_bias and es_bias != "neutral"

    print(f"\n{'='*50}")
    print(f"  HUMBLED RADAR — SCAN SUMMARY  {date.today()}")
    print(f"{'='*50}")
    print(f"  ES  bias: {es_bias:>10}  |  SMA200: {es_df['sma_200']:.2f}  |  SMA20: {es_df['sma_20']:.2f}")
    print(f"  NQ  bias: {nq_bias:>10}  |  SMA200: {nq_df['sma_200']:.2f}  |  SMA20: {nq_df['sma_20']:.2f}")
    print(f"  SMT Agreement: {'YES' if smt_agree else 'NO — divergence risk'}")
    print(f"  ES squeeze: {bool(es_df['squeeze'])}  |  NQ squeeze: {bool(nq_df['squeeze'])}")
    if not smt_agree:
        print("  WARNING: ES/NQ not in agreement — reduce size or stand aside.")


def cmd_signal(args):
    instrument = args.instrument.upper()
    equity = args.equity

    print(f"Loading {instrument} intraday...")
    df_5min = load_intraday(instrument, interval="5m", days=5)
    df_daily = load_daily(instrument, days=400)

    settlement = prior_settlement(df_daily)
    pivots = pivot_points(df_daily)
    r2 = float(pivots["r2"].iloc[-1])

    signals = []
    for fn, kwargs in [
        (setup_a_golden_reversal, {"r2_pivot": r2, "instrument": instrument}),
        (setup_b_gap_vwap, {"prior_settlement": settlement, "r2_pivot": r2, "instrument": instrument}),
        (setup_c_vwap_breakout, {"r2_pivot": r2, "instrument": instrument}),
    ]:
        try:
            sig = fn(df_5min, **kwargs)
            if sig and sig.is_valid():
                signals.append(sig)
        except Exception as e:
            print(f"  {fn.__name__} error: {e}")

    print(f"\n{'='*50}")
    print(f"  SIGNALS — {instrument}  equity=${equity:,.0f}")
    print(f"{'='*50}")
    if not signals:
        print("  No valid signals found.")
    for sig in signals:
        contracts = size_contracts(equity, sig.entry, sig.stop, instrument)
        plan = scale_out_plan(contracts, sig.entry, sig.target1, sig.target2)
        print(f"\n  [{sig.setup}] {sig.direction.upper()}")
        print(f"    Entry:   {sig.entry}  Stop: {sig.stop}  R/R: {sig.rr:.2f}")
        print(f"    T1: {sig.target1}  T2: {sig.target2}")
        print(f"    Contracts: {contracts}  Scale: {plan}")
        print(f"    Meta: {sig.meta}")


def cmd_brief(args):
    instrument = args.instrument.upper()
    equity = args.equity

    df_5min = load_intraday(instrument, interval="5m", days=5)
    df_daily = load_daily(instrument, days=400)

    bias = daily_bias(df_daily, instrument)
    settlement = prior_settlement(df_daily)
    pivots = pivot_points(df_daily)
    r2 = float(pivots["r2"].iloc[-1])

    signals = []
    for fn, kwargs in [
        (setup_a_golden_reversal, {"r2_pivot": r2, "instrument": instrument}),
        (setup_b_gap_vwap, {"prior_settlement": settlement, "r2_pivot": r2, "instrument": instrument}),
        (setup_c_vwap_breakout, {"r2_pivot": r2, "instrument": instrument}),
    ]:
        try:
            sig = fn(df_5min, **kwargs)
            if sig and sig.is_valid():
                signals.append(sig)
        except Exception:
            pass

    brief = generate_brief(signals, bias, instrument, equity, str(date.today()))
    print(json.dumps(brief, indent=2))
    resp = post_brief(brief)
    if resp is not None:
        print(f"\nPOST -> {resp.status_code}")
    else:
        print("\nPOST failed or CAS dashboard unreachable (silent).")




def cmd_paper_trade(args):
    """Run live paper trading."""
    run_paper_trading(
        instruments=args.instruments,
        equity=args.equity,
        scan_interval=args.scan_interval,
        max_duration=args.max_duration,
        log_dir=args.log_dir,
    )

def cmd_backtest(args):
    instrument = args.instrument.upper()
    equity = args.equity
    days = args.days

    print(f"Loading {instrument} daily ({days} bars)...")
    df_daily = load_daily(instrument, days=days + 50)
    if len(df_daily) < 10:
        print("Insufficient data.")
        return

    wins = losses = total_pnl = 0
    pivots = pivot_points(df_daily)

    for i in range(200, min(len(df_daily) - 1, days + 200)):
        day_bar = df_daily.iloc[i]
        r2 = float(pivots["r2"].iloc[i])
        settlement = float(df_daily["close"].iloc[i - 1])

        df_intra = build_synthetic_intraday(day_bar, n_bars=82, seed=i)

        for fn, kwargs in [
            (setup_a_golden_reversal, {"r2_pivot": r2, "instrument": instrument}),
            (setup_b_gap_vwap, {"prior_settlement": settlement, "r2_pivot": r2, "instrument": instrument}),
            (setup_c_vwap_breakout, {"r2_pivot": r2, "instrument": instrument}),
        ]:
            try:
                sig = fn(df_intra, **kwargs)
            except Exception:
                sig = None
            if not sig or not sig.is_valid():
                continue

            contracts = size_contracts(equity, sig.entry, sig.stop, instrument, risk_pct=0.01)
            if contracts == 0:
                continue

            from risk.futures_sizing import CONTRACT_SPECS
            pv = CONTRACT_SPECS[instrument]["point_value"]

            hi = float(day_bar["high"])
            lo = float(day_bar["low"])

            if sig.direction == "long":
                hit_t1 = hi >= sig.target1
                hit_stop = lo <= sig.stop
                if hit_t1 and (not hit_stop or sig.target1 > sig.stop):
                    pnl = contracts * (sig.target1 - sig.entry) * pv
                    wins += 1
                elif hit_stop:
                    pnl = contracts * (sig.stop - sig.entry) * pv
                    losses += 1
                else:
                    continue
            else:
                hit_t1 = lo <= sig.target1
                hit_stop = hi >= sig.stop
                if hit_t1 and (not hit_stop or sig.target1 < sig.stop):
                    pnl = contracts * (sig.entry - sig.target1) * pv
                    wins += 1
                elif hit_stop:
                    pnl = contracts * (sig.entry - sig.stop) * pv
                    losses += 1
                else:
                    continue

            total_pnl += pnl

    total_trades = wins + losses
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0

    print(f"\n{'='*50}")
    print(f"  BACKTEST — {instrument}  equity=${equity:,.0f}  days={days}")
    print(f"{'='*50}")
    print(f"  Trades:   {total_trades}  (wins={wins}, losses={losses})")
    print(f"  Win rate: {win_rate:.1f}%")
    print(f"  Total P&L: ${total_pnl:,.2f}")
    print(f"  Avg P&L/trade: ${total_pnl / total_trades:,.2f}" if total_trades else "  No trades.")


def main():
    parser = argparse.ArgumentParser(description="Humbled Radar Futures Strategy")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("scan", help="Classify ES/NQ bias and check SMT agreement")

    p_sig = sub.add_parser("signal", help="Run setup scans and print signals")
    p_sig.add_argument("--instrument", default="ES", choices=["ES", "NQ"])
    p_sig.add_argument("--equity", type=float, default=100_000)

    p_brief = sub.add_parser("brief", help="Generate and POST CAS brief")
    p_brief.add_argument("--instrument", default="ES", choices=["ES", "NQ"])
    p_brief.add_argument("--equity", type=float, default=100_000)

    p_bt = sub.add_parser("backtest", help="Walk-forward backtest")
    p_bt.add_argument("--instrument", default="ES", choices=["ES", "NQ"])
    p_bt.add_argument("--equity", type=float, default=100_000)
    p_bt.add_argument("--days", type=int, default=252)
    p_pt = sub.add_parser("paper-trade", help="Run live paper trading")
    p_pt.add_argument("--instruments", nargs="+", default=["ES", "NQ"], help="Instruments to trade")
    p_pt.add_argument("--equity", type=float, default=100_000, help="Account equity")
    p_pt.add_argument("--scan-interval", type=int, default=300, help="Scan interval in seconds")
    p_pt.add_argument("--max-duration", type=int, default=16*3600, help="Max duration in seconds (default 16 hours)")
    p_pt.add_argument("--log-dir", type=str, default=None, help="Log directory")


    args = parser.parse_args()

    dispatch = {
        "scan": cmd_scan,
        "signal": cmd_signal,
        "brief": cmd_brief,
        "backtest": cmd_backtest,
        "paper-trade": cmd_paper_trade,
    }

    if args.cmd not in dispatch:
        parser.print_help()
        return

    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
