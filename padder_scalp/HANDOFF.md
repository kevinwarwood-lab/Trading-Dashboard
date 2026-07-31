# Padder Scalp (PDS-01) — Session Handoff

**Read this first if you are a new Claude Code session picking up this work.**
It captures the full state, the reasoning behind every decision, and the exact
next step, because the original chat history does not transfer between machines.

---

## What this project is

An automated implementation of the **"Padder Scalp" / Box Theory** day-trading
strategy, for TradingView (live alerts) + a Python backtester (validation).

- **Strategy file (live):** `../PADDER-SCALP-01.pine` — Pine v6 `strategy()`.
- **Backtester (Python):** this `padder_scalp/` folder mirrors the Pine logic
  1:1 so results are comparable.

### The strategy in one paragraph
On a 5-minute chart, at the NY open (09:30–11:30 ET) draw a "box" from the
previous day's high/low (or, if price gaps outside that range, a "cheater box"
tracking the session's live extremes). Split the box into a top 20% Sell Zone,
bottom 20% Buy Zone, middle 60% no-trade. A day only trades if the first 15
minutes move ≥ 20% of the daily ATR ("manipulation confirmed"). In a zone, after
≥3 candles pushing into it, a **John Wick** (hammer, wick ≥50% of range) or
**Power Tower** (engulfing body ≥40% of prior range) signal candle *arms* a
setup. Entry only fires when a LATER candle closes beyond the signal candle's
close, within N bars. Stop below the signal wick; target = box midpoint; size
to a fixed risk. Flatten at box close.

---

## File map

| File | Purpose |
|---|---|
| `../PADDER-SCALP-01.pine` | Live TradingView strategy + alerts + Data-Window diagnostics |
| `config.py` | Symbol specs, params, per-symbol overrides (`SYMBOL_PARAM_OVERRIDES`), sessions |
| `engine.py` | Bar-by-bar backtest engine (mirrors Pine). `run_backtest()` + diag counters |
| `data_fetch.py` | yfinance loader (5m ≤60 days — this is the PROBLEM, see below) |
| `run_backtest.py` | Runs yfinance backtest for the futures universe |
| `sweep_zone_rr.py` | Zone% × min-R:R parameter sweep |
| `fetch_ibkr.py` | **Pulls REAL 5m+daily MES/MNQ from Interactive Brokers** (the fix) |
| `run_backtest_ibkr.py` | Runs the backtest on IBKR data (`data_ibkr/`) |
| `reports/` | Saved CSV/markdown backtest outputs |
| `cache/` | yfinance CSV cache (60-day 5m) |

---

## Tuning decisions already made (and why)

- **Universe:** narrowed to **MES** (Micro S&P) and **MNQ** (Micro Nasdaq).
  Gold (MGC), Russell (M2K), MYM (Micro Dow), 10 Nasdaq stocks, EUR/USD,
  USD/JPY, and London/Asian sessions were all tested and dropped — either the
  manipulation gate almost never confirmed, or the strategy lost money.
- **`arm_bars` (confirmation window), per symbol:** MES=4, MNQ=3. From a 1–10
  sweep: MES needed more patience (never benefited past 4), MNQ's good setups
  confirmed fast (extra bars added losers).
- **`min_rr`, per symbol:** MES=1.5, MNQ=2.0. The default 2.0 throttled MES —
  total_R rose monotonically across ALL zone sizes as R:R dropped toward ~1.25,
  so 1.5 is used as a sane floor. MNQ showed the opposite, kept 2.0.
- **Zone size:** stays 20%. Sweep showed widening above 20% does nothing (R:R
  filter is the real gate); only tightening below changes anything, marginally.
- **Single TP** at the box midpoint (a 2-TP variant was tested and lost).
- **Sizing:** whole-contract floor. `risk_mode` = `pct_equity` or
  `fixed_dollar`. A ~$500 live account is too small for MES's real stop
  distances at 1% — fixed-dollar ~$75 is the workable compromise; MNQ needs
  ~$300+ per trade so it is effectively untradeable on a small account.
- A **real bug was fixed**: trades opened on the session's last bar used to ride
  overnight instead of flattening at box close. Now flattens every bar.

All per-symbol overrides live in `config.py::SYMBOL_PARAM_OVERRIDES` and are
mirrored in the Pine script via the "Auto-tailor by symbol" toggle.

---

## THE CRITICAL OPEN ISSUE (this is why we're here)

The yfinance backtest showed MES/MNQ as modestly profitable (~+4–6R over 60
days). **But on the live TradingView `MES1!` feed, the strategy produced ZERO
trades** over the same window — even with the R:R filter OFF and sizing set to
% of equity (every gate removed).

Diagnosis (confirmed via the Pine Data-Window diagnostics): signals **arm**
(JW/PT labels appear) but **never confirm** — no candle closes beyond the signal
candle's close within the arm window. They are near-misses. On yfinance's
`MES=F` data the same setups DID confirm; on IBKR/TradingView's `MES1!` feed
they don't. **The two data feeds differ enough (continuous-contract stitching,
session boundaries) that the backtested edge does not transfer.** The strategy
is operating at a knife-edge where tick-level feed differences decide whether a
trade fires — i.e. the yfinance backtest is not trustworthy for this.

**Conclusion: must re-validate on the REAL feed (IBKR) before trusting anything
or trading live.** Do NOT tune parameters further against yfinance data — that
is curve-fitting a fragile setup.

---

## >>> NEXT STEP (resume here) <<<

Pull real IBKR 5-minute data and re-run the backtest on it.

1. Install deps (see `requirements.txt`):
   `pip install pandas numpy yfinance ib_async`
2. Download and install **IB Gateway** (lightweight, API-only — NOT "IBKR
   Desktop", which doesn't expose the classic API socket).
3. Launch IB Gateway, log in **Paper** (safer; inherits live data subs).
4. Enable API: `Configure → Settings → API → Settings` → tick "Enable ActiveX
   and Socket Clients", add `127.0.0.1` to Trusted IPs. Port = **4002** (paper)
   / 4001 (live) / TWS 7497 paper / 7496 live.
5. Run:  `python fetch_ibkr.py --port 4002`
   - Pulls 18 months 5m + 3y daily for MES & MNQ into `data_ibkr/`.
   - If it prints "empty, stopping early" → market-data subscription issue;
     change `whatToShow="TRADES"` to `"MIDPOINT"` in `fetch_ibkr.py`.
6. Run:  `python run_backtest_ibkr.py`  → this is the honest number.

**Interpreting the result:** if the edge holds on IBKR data, it's real and worth
pursuing. If it collapses (as the live chart suggests it might), the strategy as
specified is too fragile — and the confirmation rule is the prime suspect
(requiring a close beyond a strong signal candle's close sets an unreachable bar
exactly when the reversal is strongest). That would be a redesign, not a tweak.

---

## Environment notes
- Python 3.14, Windows. Deps: pandas 3.0.3, numpy 2.4.6, yfinance 1.4.0,
  ib_async 2.1.0.
- Live account is small (~$500) — sizing realism matters; see fixed-dollar mode.
- Original dev machine had the project under OneDrive; paths are relative within
  `padder_scalp/` so it runs from anywhere you `cd` into the folder.
