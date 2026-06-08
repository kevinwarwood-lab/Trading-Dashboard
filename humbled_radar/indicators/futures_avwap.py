import numpy as np
import pandas as pd


def _typical(df: pd.DataFrame) -> pd.Series:
    return (df["high"] + df["low"] + df["close"]) / 3


def _compute_avwap(df: pd.DataFrame, anchor_mask: pd.Series) -> pd.Series:
    tp = _typical(df)
    tp_vol = tp * df["volume"]
    avwap = pd.Series(index=df.index, dtype=float)
    cum_tv = 0.0
    cum_v = 0.0
    for i in range(len(df)):
        if anchor_mask.iloc[i]:
            cum_tv = 0.0
            cum_v = 0.0
        cum_tv += tp_vol.iloc[i]
        cum_v += df["volume"].iloc[i]
        avwap.iloc[i] = cum_tv / cum_v if cum_v > 0 else np.nan
    return avwap


def daily_avwap(df: pd.DataFrame) -> pd.Series:
    """Anchor VWAP to 09:30 bar each RTH day."""
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("DataFrame must have DatetimeIndex")
    eastern = idx.tz_convert("America/New_York") if idx.tzinfo else idx
    anchor = (eastern.time() == pd.Timestamp("09:30").time())
    return _compute_avwap(df, pd.Series(anchor, index=df.index))


def ytd_avwap(df: pd.DataFrame) -> pd.Series:
    """Anchor to first RTH bar of the calendar year."""
    eastern = df.index.tz_convert("America/New_York") if df.index.tzinfo else df.index
    rth_mask = (eastern.time() == pd.Timestamp("09:30").time())
    first_rth_of_year = pd.Series(False, index=df.index)
    seen_years = set()
    for i, (ts, is_rth) in enumerate(zip(eastern, rth_mask)):
        if is_rth and ts.year not in seen_years:
            seen_years.add(ts.year)
            first_rth_of_year.iloc[i] = True
    return _compute_avwap(df, first_rth_of_year)


def mtd_avwap(df: pd.DataFrame) -> pd.Series:
    """Anchor to first RTH bar of each calendar month."""
    eastern = df.index.tz_convert("America/New_York") if df.index.tzinfo else df.index
    rth_mask = eastern.time() == pd.Timestamp("09:30").time()
    anchor = pd.Series(False, index=df.index)
    seen = set()
    for i, (ts, is_rth) in enumerate(zip(eastern, rth_mask)):
        key = (ts.year, ts.month)
        if is_rth and key not in seen:
            seen.add(key)
            anchor.iloc[i] = True
    return _compute_avwap(df, anchor)


def wtd_avwap(df: pd.DataFrame) -> pd.Series:
    """Anchor to first RTH bar of each week (Monday)."""
    eastern = df.index.tz_convert("America/New_York") if df.index.tzinfo else df.index
    rth_mask = eastern.time() == pd.Timestamp("09:30").time()
    anchor = pd.Series(False, index=df.index)
    seen = set()
    for i, (ts, is_rth) in enumerate(zip(eastern, rth_mask)):
        iso = ts.isocalendar()
        key = (iso[0], iso[1])
        if is_rth and key not in seen:
            seen.add(key)
            anchor.iloc[i] = True
    return _compute_avwap(df, anchor)


def avwap_bands(avwap: pd.Series, df: pd.DataFrame, n_std: float = 1.0):
    """Return (upper, lower) standard-deviation bands around an AVWAP series."""
    tp = _typical(df)
    variance = pd.Series(index=df.index, dtype=float)
    anchor_indices = avwap.index[avwap.diff().abs() > 1e-10].tolist()

    cum_tv2 = 0.0
    cum_tv = 0.0
    cum_v = 0.0
    anchor_set = set(anchor_indices)

    for i in range(len(df)):
        idx = df.index[i]
        if idx in anchor_set:
            cum_tv2 = 0.0
            cum_tv = 0.0
            cum_v = 0.0
        v = df["volume"].iloc[i]
        t = tp.iloc[i]
        cum_v += v
        cum_tv += t * v
        cum_tv2 += t * t * v
        if cum_v > 0:
            vwap_val = cum_tv / cum_v
            variance.iloc[i] = (cum_tv2 / cum_v) - vwap_val ** 2
        else:
            variance.iloc[i] = np.nan

    std = np.sqrt(variance.clip(lower=0))
    upper = avwap + n_std * std
    lower = avwap - n_std * std
    return upper, lower
