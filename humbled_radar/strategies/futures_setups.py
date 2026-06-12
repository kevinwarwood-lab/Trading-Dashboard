from dataclasses import dataclass, field
from datetime import time
from typing import Optional
import pandas as pd
import numpy as np

from indicators.futures_avwap import daily_avwap
from indicators.futures_indicators import tick_round, atr

_TICK = 0.25


@dataclass
class Signal:
    setup: str
    direction: str
    entry: float
    stop: float
    target1: float
    target2: Optional[float]
    instrument: str
    meta: dict = field(default_factory=dict)

    @property
    def rr(self) -> float:
        risk = abs(self.entry - self.stop)
        reward = abs(self.target1 - self.entry)
        return reward / risk if risk > 0 else 0.0

    def is_valid(self, min_rr: float = 2.0) -> bool:
        return abs(self.entry - self.stop) > 0 and self.rr >= min_rr


def _rel_vol(df: pd.DataFrame, window: int = 20) -> pd.Series:
    return df["volume"] / df["volume"].rolling(window).mean()


def _in_window(ts: pd.Timestamp, start: time, end: time) -> bool:
    t = ts.tz_convert("America/New_York").time() if ts.tzinfo else ts.time()
    return start <= t <= end


def setup_a_golden_reversal(
    df_5min: pd.DataFrame,
    r2_pivot: float,
    instrument: str = "ES",
    window_start: time = time(10, 30),
    window_end: time = time(11, 0),
) -> Optional[Signal]:
    """Morning sell-off reversal: double bottom / higher lows + VWAP reclaim."""
    df = df_5min.copy()
    avwap = daily_avwap(df)
    rel_v = _rel_vol(df)

    window_mask = df.index.map(lambda ts: _in_window(ts, window_start, window_end))
    window_df = df[window_mask]
    if len(window_df) < 3:
        return None

    lows = window_df["low"]
    if not (lows.iloc[-1] > lows.iloc[-2] > lows.iloc[0]):
        return None

    last = window_df.iloc[-1]
    last_idx = window_df.index[-1]
    last_avwap = avwap.loc[last_idx]

    if last["close"] <= last_avwap:
        return None
    if rel_v.loc[last_idx] < 1.5:
        return None
    if last["close"] >= r2_pivot:
        return None

    entry = tick_round(last["high"] + _TICK, _TICK)
    stop = tick_round(lows.min() - 2 * _TICK, _TICK)
    risk = entry - stop
    if risk <= 0:
        return None
    target1 = tick_round(entry + 2 * risk, _TICK)
    target2 = tick_round(entry + 3 * risk, _TICK)

    return Signal(
        setup="A_golden_reversal",
        direction="long",
        entry=entry,
        stop=stop,
        target1=target1,
        target2=target2,
        instrument=instrument,
        meta={"avwap": last_avwap, "rel_vol": rel_v.loc[last_idx]},
    )


def setup_b_gap_vwap(
    df_5min: pd.DataFrame,
    prior_settlement: float,
    r2_pivot: float,
    instrument: str = "ES",
    min_gap_pct: float = 0.002,
) -> Optional[Signal]:
    """Gap + VWAP pullback setup with Two-Bar Rule on 2-tick consolidation."""
    df = df_5min.copy()
    avwap = daily_avwap(df)
    rel_v = _rel_vol(df)

    first_bar = df.iloc[0]
    gap_pct = (first_bar["open"] - prior_settlement) / prior_settlement

    if abs(gap_pct) < min_gap_pct:
        return None

    direction = "long" if gap_pct > 0 else "short"

    rth_mask = df.index.map(lambda ts: _in_window(ts, time(9, 30), time(11, 30)))
    rth_df = df[rth_mask]
    if len(rth_df) < 5:
        return None

    for i in range(2, len(rth_df) - 1):
        bar = rth_df.iloc[i]
        bar_idx = rth_df.index[i]
        bar_avwap = avwap.loc[bar_idx]
        bar_rel_v = rel_v.loc[bar_idx]

        near_vwap = abs(bar["close"] - bar_avwap) <= 2 * _TICK
        if not near_vwap or bar_rel_v < 1.5:
            continue

        prev2_range = rth_df["high"].iloc[i - 2:i].max() - rth_df["low"].iloc[i - 2:i].min()
        if prev2_range > 2 * _TICK * 3:
            continue

        confirm = rth_df.iloc[i + 1]

        if direction == "long" and confirm["close"] > bar["high"]:
            entry = tick_round(bar["high"] + _TICK, _TICK)
            stop = tick_round(rth_df["low"].iloc[max(0, i - 3):i + 1].min() - 2 * _TICK, _TICK)
            risk = entry - stop
            if risk <= 0:
                continue
            t1 = tick_round(entry + 2 * risk, _TICK)
            t2 = tick_round(entry + 3 * risk, _TICK)
            return Signal(
                setup="B_gap_vwap",
                direction="long",
                entry=entry,
                stop=stop,
                target1=t1,
                target2=t2,
                instrument=instrument,
                meta={"gap_pct": gap_pct, "avwap": bar_avwap, "rel_vol": bar_rel_v},
            )
        elif direction == "short" and confirm["close"] < bar["low"]:
            entry = tick_round(bar["low"] - _TICK, _TICK)
            stop = tick_round(rth_df["high"].iloc[max(0, i - 3):i + 1].max() + 2 * _TICK, _TICK)
            risk = stop - entry
            if risk <= 0:
                continue
            t1 = tick_round(entry - 2 * risk, _TICK)
            t2 = tick_round(entry - 3 * risk, _TICK)
            return Signal(
                setup="B_gap_vwap",
                direction="short",
                entry=entry,
                stop=stop,
                target1=t1,
                target2=t2,
                instrument=instrument,
                meta={"gap_pct": gap_pct, "avwap": bar_avwap, "rel_vol": bar_rel_v},
            )
    return None


def setup_c_vwap_breakout(
    df_5min: pd.DataFrame,
    r2_pivot: float,
    instrument: str = "ES",
) -> Optional[Signal]:
    """Breakout candle → pullback to VWAP → confirmation bar overtakes pullback high."""
    df = df_5min.copy()
    avwap = daily_avwap(df)
    rel_v = _rel_vol(df)

    if len(df) < 6:
        return None

    for i in range(3, len(df) - 2):
        bar = df.iloc[i]
        bar_idx = df.index[i]
        bar_avwap = avwap.loc[bar_idx]
        bar_rel_v = rel_v.loc[bar_idx]

        breakout_up = bar["close"] > bar_avwap and bar_rel_v > 1.5

        if not breakout_up:
            continue

        pullback = df.iloc[i + 1]
        pb_idx = df.index[i + 1]
        pb_avwap = avwap.loc[pb_idx]

        near_vwap_pb = abs(pullback["low"] - pb_avwap) <= 4 * _TICK and pullback["close"] > pb_avwap * 0.999

        if not near_vwap_pb:
            continue

        confirm = df.iloc[i + 2]
        if confirm["close"] <= pullback["high"]:
            continue

        entry = tick_round(pullback["high"] + _TICK, _TICK)
        stop = tick_round(pullback["low"] - 2 * _TICK, _TICK)
        risk = entry - stop
        if risk <= 0:
            continue

        t1 = tick_round(entry + 2 * risk, _TICK)
        t2 = tick_round(min(r2_pivot, entry + 3 * risk), _TICK)

        sig = Signal(
            setup="C_vwap_breakout",
            direction="long",
            entry=entry,
            stop=stop,
            target1=t1,
            target2=t2,
            instrument=instrument,
            meta={"avwap": bar_avwap, "rel_vol": bar_rel_v},
        )
        if sig.is_valid():
            return sig
    return None


def detect_short_trap(df_5min: pd.DataFrame) -> bool:
    """True if price undercuts a prior low then reverses sharply higher."""
    if len(df_5min) < 4:
        return False
    recent = df_5min.iloc[-4:]
    prior_low = recent["low"].iloc[:-1].min()
    last = recent.iloc[-1]
    undercut = last["low"] < prior_low
    reversal = last["close"] > recent["open"].iloc[-1] and last["close"] > prior_low
    return bool(undercut and reversal)


def smt_divergence_check(
    df_es_5min: pd.DataFrame,
    df_nq_5min: pd.DataFrame,
) -> bool:
    """True if ES and NQ disagree in direction near key level (avoid trading)."""
    def _trend(df):
        if len(df) < 5:
            return 0
        closes = df["close"].iloc[-5:]
        return 1 if closes.iloc[-1] > closes.iloc[0] else -1

    es_trend = _trend(df_es_5min)
    nq_trend = _trend(df_nq_5min)
    return es_trend != nq_trend
