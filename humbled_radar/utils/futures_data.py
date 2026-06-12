import numpy as np
import pandas as pd
import yfinance as yf

_SYMBOL_MAP = {"ES": "ES=F", "NQ": "NQ=F", "MES": "MES=F", "MNQ": "MNQ=F"}
_RTH_OPEN = "09:30"
_RTH_CLOSE = "16:15"


def _yf_symbol(symbol: str) -> str:
    return _SYMBOL_MAP.get(symbol.upper(), symbol)


def load_daily(symbol: str, days: int = 400) -> pd.DataFrame:
    ticker = _yf_symbol(symbol)
    df = yf.download(ticker, period=f"{days}d", interval="1d", auto_adjust=True, progress=False)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"adj close": "close"}) if "adj close" in df.columns else df
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    return df


def load_intraday(symbol: str, interval: str = "5m", days: int = 5) -> pd.DataFrame:
    ticker = _yf_symbol(symbol)
    df = yf.download(ticker, period=f"{days}d", interval=interval, auto_adjust=True, progress=False)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"adj close": "close"}) if "adj close" in df.columns else df
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    return rth_session(df)


def rth_session(df: pd.DataFrame) -> pd.DataFrame:
    eastern = df.index.tz_convert("America/New_York")
    mask = (eastern.time >= pd.Timestamp(_RTH_OPEN).time()) & \
           (eastern.time <= pd.Timestamp(_RTH_CLOSE).time())
    return df[mask]


def prior_settlement(df_daily: pd.DataFrame) -> float:
    """Close of the most recent complete RTH session."""
    return float(df_daily["close"].iloc[-2]) if len(df_daily) >= 2 else float("nan")


def build_synthetic_intraday(
    daily_bar: pd.Series,
    n_bars: int = 82,
    seed: int = 42,
) -> pd.DataFrame:
    """Build 82 x 5-min synthetic bars spanning a single RTH session."""
    rng = np.random.default_rng(seed)
    op = float(daily_bar["open"])
    hi = float(daily_bar["high"])
    lo = float(daily_bar["low"])
    cl = float(daily_bar["close"])

    prices = np.zeros(n_bars + 1)
    prices[0] = op
    steps = rng.normal(0, (hi - lo) / (2 * np.sqrt(n_bars)), n_bars)
    for i in range(n_bars):
        prices[i + 1] = prices[i] + steps[i]

    scale = (hi - lo) / (max(prices) - min(prices) + 1e-9)
    prices = (prices - min(prices)) * scale + lo
    prices[-1] = cl

    opens = prices[:-1]
    closes = prices[1:]
    highs = np.maximum(opens, closes) + rng.uniform(0, (hi - lo) * 0.05, n_bars)
    lows = np.minimum(opens, closes) - rng.uniform(0, (hi - lo) * 0.05, n_bars)
    volumes = rng.integers(500, 3000, n_bars).astype(float)

    date = daily_bar.name if hasattr(daily_bar, "name") and daily_bar.name is not None else pd.Timestamp.today()
    base = pd.Timestamp(date).normalize().tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30)
    idx = pd.date_range(base, periods=n_bars, freq="5min")

    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}, index=idx)
