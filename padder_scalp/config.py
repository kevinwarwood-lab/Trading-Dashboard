"""Symbol specs + strategy params — mirrors the Pine inputs 1:1."""

# Micro futures: yfinance ticker -> CME contract specs
# Focused down to Nasdaq + S&P 500 micros — Gold dropped (manipulation gate
# almost never confirmed at this timeframe/threshold, see MGC exploration).
SYMBOLS = {
    "MES=F": {"name": "Micro E-mini S&P 500", "tick_size": 0.25, "point_value": 5.0},
    "MNQ=F": {"name": "Micro E-mini Nasdaq 100", "tick_size": 0.25, "point_value": 2.0},
}

# Top 10 Nasdaq stocks by market cap (as of assembly time — reorder/replace as needed)
STOCK_SYMBOLS = {
    "AAPL": {"name": "Apple", "tick_size": 0.01, "point_value": 1.0},
    "MSFT": {"name": "Microsoft", "tick_size": 0.01, "point_value": 1.0},
    "NVDA": {"name": "NVIDIA", "tick_size": 0.01, "point_value": 1.0},
    "AMZN": {"name": "Amazon", "tick_size": 0.01, "point_value": 1.0},
    "GOOGL": {"name": "Alphabet (Class A)", "tick_size": 0.01, "point_value": 1.0},
    "META": {"name": "Meta Platforms", "tick_size": 0.01, "point_value": 1.0},
    "AVGO": {"name": "Broadcom", "tick_size": 0.01, "point_value": 1.0},
    "TSLA": {"name": "Tesla", "tick_size": 0.01, "point_value": 1.0},
    "COST": {"name": "Costco", "tick_size": 0.01, "point_value": 1.0},
    "NFLX": {"name": "Netflix", "tick_size": 0.01, "point_value": 1.0},
}

PARAMS = dict(
    atr_len=14,
    manip_pct=0.20,
    session_start="09:30",
    session_end="11:30",
    zone_pct=0.20,
    min_run=3,
    wick_pct=0.50,
    tower_pct=0.40,
    arm_bars=5,   # base/fallback default; MES and MNQ get tailored overrides below
    risk_mode="pct_equity",    # "pct_equity" or "fixed_dollar"
    risk_pct=0.01,             # used when risk_mode == "pct_equity"
    fixed_risk_usd=25.0,       # used when risk_mode == "fixed_dollar"; qty is floored to whole contracts
    stop_mode="signal_wick",   # "signal_wick" or "box_edge"
    stop_buf_ticks=2,
    min_rr=2.0,
    enforce_rr=True,
    flat_at_end=True,
    initial_capital=10_000.0,
    commission_per_contract=1.24,  # round-turn micro futures commission incl. fees, approx
)

# Same strategy params, but commission modeled as ~$0.005/share (SEC/TAF fees;
# most retail brokers charge $0 commission on equities).
STOCK_PARAMS = {**PARAMS, "commission_per_contract": 0.005}

# Per-symbol overrides, layered on top of PARAMS/STOCK_PARAMS.
#
# arm_bars (from the 1-10 bar sweep): MES's setups needed up to 4 bars to
# confirm and never benefited from more; MNQ's best setups confirmed fast, and
# extra patience just let in weaker trades. Picked the more conservative
# win-rate peak (3) for MNQ over the noisier arm=1 total-R peak (n=6 trades).
#
# min_rr (from the zone x R:R grid): the default 2.0 throttled MES hard —
# across ALL zone sizes, total_R rose monotonically as min_rr dropped toward
# ~1.25 (10 trades/+6.63R at 1.5 vs 7/+4.62R at 2.0). That's a directional
# trend across 7 independent zone settings, not one lucky cell, so it's
# trustworthy. Chose 1.5 (not the raw-optimal ~1.25) as a sane R:R floor.
# MNQ showed the OPPOSITE: loosening below 1.5 only added losing trades, so
# it keeps the 2.0 default. Same per-instrument-divergence pattern as arm_bars.
SYMBOL_PARAM_OVERRIDES = {
    "MES=F": {"arm_bars": 4, "min_rr": 1.5},
    "MNQ=F": {"arm_bars": 3, "min_rr": 2.0},
}


def params_for(symbol: str, base: dict = PARAMS) -> dict:
    return {**base, **SYMBOL_PARAM_OVERRIDES.get(symbol, {})}


# Alternate session boxes (all New York time — the engine/data are tz-aligned
# to America/New_York throughout). 2-hour box length kept the same as the NY
# variant for a fair comparison. session_weekdays handles the fact that the
# Asian open (7pm ET) trades Sun-Thu evenings, not Mon-Fri — CME Globex is
# closed Friday evening through Sunday 6pm ET.
SESSIONS = {
    "NY":     dict(session_start="09:30", session_end="11:30", session_weekdays=(0, 1, 2, 3, 4)),
    "LONDON": dict(session_start="03:00", session_end="05:00", session_weekdays=(0, 1, 2, 3, 4)),
    "ASIA":   dict(session_start="19:00", session_end="21:00", session_weekdays=(6, 0, 1, 2, 3)),
}


def params_for_session(symbol: str, session: str, base: dict = PARAMS) -> dict:
    return {**params_for(symbol, base), **SESSIONS[session]}


# For testing whether the box/manipulation logic finds an edge outside NY
# hours on instruments whose volatility is actually global rather than
# US-cash-session-driven. point_value is an approximate USD-per-unit-move
# scalar (r_multiple/win_rate are point_value-invariant given the risk-based
# sizing; only the $ pnl column is affected by this being approximate).
FX_SYMBOLS = {
    "EURUSD=X": {"name": "EUR/USD", "tick_size": 0.0001, "point_value": 1.0},
    "JPY=X": {"name": "USD/JPY", "tick_size": 0.01, "point_value": 1 / 159.0},
    "MGC=F": {"name": "Micro Gold", "tick_size": 0.10, "point_value": 10.0},
}
