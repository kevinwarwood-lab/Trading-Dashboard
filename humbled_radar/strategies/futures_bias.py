import pandas as pd
from indicators.futures_indicators import sma, ema
from indicators.futures_avwap import ytd_avwap


def classify_bias(df_daily: pd.DataFrame, instrument: str = "ES") -> pd.DataFrame:
    close = df_daily["close"]
    s200 = sma(close, 200)
    s20 = sma(close, 20)
    e8 = ema(close, 8)

    try:
        ytd = ytd_avwap(df_daily)
    except Exception:
        ytd = pd.Series(float("nan"), index=df_daily.index)

    squeeze = (s20 > s20.shift(1)) & ((s200 - s200.shift(5)).abs() / s200.shift(5) < 0.0005)
    hugging_8ema = (close - e8).abs() / e8 < 0.002

    def _bias(row):
        if pd.isna(row["sma_200"]) or pd.isna(row["ytd_avwap"]):
            return "neutral"
        if row["close"] > row["sma_200"] and row["close"] > row["ytd_avwap"]:
            return "bullish"
        if row["close"] < row["sma_200"] and row["close"] < row["ytd_avwap"]:
            return "bearish"
        return "neutral"

    result = pd.DataFrame({
        "close": close,
        "sma_200": s200,
        "sma_20": s20,
        "ema_8": e8,
        "ytd_avwap": ytd,
        "squeeze": squeeze,
        "hugging_8ema": hugging_8ema,
    })
    result["bias"] = result.apply(_bias, axis=1)
    return result


def daily_bias(df_daily: pd.DataFrame, instrument: str = "ES") -> str:
    result = classify_bias(df_daily, instrument)
    if result.empty:
        return "neutral"
    return result["bias"].iloc[-1]
