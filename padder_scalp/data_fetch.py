"""Fetch + cache 5m and daily bars for a futures symbol via yfinance."""
from __future__ import annotations

import os

import pandas as pd
import yfinance as yf

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep]
    df = df[~df.index.duplicated(keep="first")]
    df = df.dropna(subset=["open", "high", "low", "close"], how="any")
    return df.sort_index()


def _cache_path(symbol: str, interval: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = symbol.replace("=", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{interval}.csv")


def fetch(symbol: str, interval: str, period: str, refresh: bool = False) -> pd.DataFrame:
    path = _cache_path(symbol, interval)
    if os.path.exists(path) and not refresh:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return _clean(df)
    df = yf.download(symbol, period=period, interval=interval,
                      auto_adjust=False, progress=False, threads=False)
    df = _clean(df)
    if not df.empty:
        df.to_csv(path)
    return df


def load_symbol(symbol: str, refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (five_min_df in America/New_York tz, daily_df)."""
    m5 = fetch(symbol, "5m", "60d", refresh=refresh)
    daily = fetch(symbol, "1d", "2y", refresh=refresh)

    if not m5.empty:
        if m5.index.tz is None:
            m5.index = m5.index.tz_localize("UTC")
        m5.index = m5.index.tz_convert("America/New_York")

    if not daily.empty and daily.index.tz is not None:
        daily.index = daily.index.tz_localize(None)

    return m5, daily
