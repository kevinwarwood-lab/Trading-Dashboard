import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def pivot_points(df_daily: pd.DataFrame) -> pd.DataFrame:
    """Classic floor pivots from prior day settlement (close)."""
    prev = df_daily[["high", "low", "close"]].shift(1)
    pp = (prev["high"] + prev["low"] + prev["close"]) / 3
    r1 = 2 * pp - prev["low"]
    s1 = 2 * pp - prev["high"]
    r2 = pp + (prev["high"] - prev["low"])
    s2 = pp - (prev["high"] - prev["low"])
    r3 = prev["high"] + 2 * (pp - prev["low"])
    s3 = prev["low"] - 2 * (prev["high"] - pp)
    return pd.DataFrame({"pp": pp, "r1": r1, "r2": r2, "r3": r3,
                         "s1": s1, "s2": s2, "s3": s3})


def squeeze_setup(df: pd.DataFrame, fast: int = 20, slow: int = 200) -> pd.Series:
    """20 SMA rising and 200 SMA flat (slope < 0.05% per bar)."""
    close = df["close"]
    s20 = sma(close, fast)
    s200 = sma(close, slow)
    rising_20 = s20 > s20.shift(1)
    slope_200 = (s200 - s200.shift(5)).abs() / s200.shift(5)
    flat_200 = slope_200 < 0.0005
    return (rising_20 & flat_200).fillna(False)


def tick_round(price: float, tick_size: float = 0.25) -> float:
    return round(round(price / tick_size) * tick_size, 10)
