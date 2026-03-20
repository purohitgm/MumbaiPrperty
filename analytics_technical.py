# analytics/technical.py
# Core technical indicator calculations


import pandas as pd
import numpy as np
from config import RSI_PERIOD, EMA_SHORT, EMA_MID, EMA_LONG, VOLUME_MA_PERIOD




def calc_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.round(2)




def calc_ema(close: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return close.ewm(span=period, adjust=False).mean()




def calc_sma(close: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return close.rolling(window=period).mean()




def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int = 14) -> pd.Series:
    """Average True Range."""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()




def calc_volume_ratio(volume: pd.Series,
                      period: int = VOLUME_MA_PERIOD) -> pd.Series:
    """Current volume / N-day average volume."""
    vol_ma = volume.rolling(window=period).mean()
    return (volume / vol_ma.replace(0, np.nan)).round(2)




def calc_dma_status(close: pd.Series) -> dict:
    """
    Returns latest DMA values and whether price is above each.
    """
    if len(close) < EMA_LONG:
        return {}
    ema20 = calc_ema(close, EMA_SHORT).iloc[-1]
    ema50 = calc_ema(close, EMA_MID).iloc[-1]
    ema200 = calc_ema(close, EMA_LONG).iloc[-1]
    price = close.iloc[-1]
    return {
        "price": round(float(price), 2),
        "ema20": round(float(ema20), 2),
        "ema50": round(float(ema50), 2),
        "ema200": round(float(ema200), 2),
        "above_ema20": bool(price > ema20),
        "above_ema50": bool(price > ema50),
        "above_ema200": bool(price > ema200),
        "ema_score": sum([price > ema20, price > ema50, price > ema200]),
    }




def calc_relative_strength(stock_close: pd.Series,
                            benchmark_close: pd.Series,
                            period: int = 63) -> float:
    """
    Mansfield Relative Strength:
    RS = (stock_return / benchmark_return) - 1 over `period` bars.
    Returns a float ratio (positive = outperforming).
    """
    if len(stock_close) < period or len(benchmark_close) < period:
        return 0.0
    # Align on common dates
    common = stock_close.index.intersection(benchmark_close.index)
    if len(common) < period:
        return 0.0
    s = stock_close.loc[common]
    b = benchmark_close.loc[common]
    stock_ret = (s.iloc[-1] / s.iloc[-period]) - 1
    bench_ret = (b.iloc[-1] / b.iloc[-period]) - 1
    rs = float(stock_ret) - float(bench_ret)
    return round(rs * 100, 2) # expressed as %




def calc_rrg_metrics(stock_close: pd.Series,
                     benchmark_close: pd.Series,
                     short_period: int = 10,
                     long_period: int = 40) -> dict:
    """
    Relative Rotation Graph (RRG) metrics:
    - JdK RS-Ratio : relative strength vs benchmark (smoothed)
    - JdK RS-Momentum: rate-of-change of RS-Ratio
    Returns trail of (rs_ratio, rs_momentum) for last 12 weeks.
    """
    common = stock_close.index.intersection(benchmark_close.index)
    if len(common) < long_period + 10:
        return {"rs_ratio": [], "rs_momentum": [], "dates": []}


    s = stock_close.loc[common].copy()
    b = benchmark_close.loc[common].copy()


    # Raw RS line
    rs_line = s / b


    # Smooth with EMA
    rs_short = calc_ema(rs_line, short_period)
    rs_long = calc_ema(rs_line, long_period)


    # RS-Ratio: normalized to 100
    rs_ratio = 100 * (rs_short / rs_long)


    # RS-Momentum: ROC of RS-Ratio
    rs_momentum = 100 + rs_ratio.pct_change(periods=1) * 100


    # Last 12 weekly observations (approx 60 trading days → sample every 5)
    trail_len = min(60, len(rs_ratio))
    idx = range(len(rs_ratio) - trail_len, len(rs_ratio), 1)


    return {
        "rs_ratio": rs_ratio.iloc[list(idx)].round(3).tolist(),
        "rs_momentum": rs_momentum.iloc[list(idx)].round(3).tolist(),
        "dates": [str(d.date()) for d in rs_ratio.iloc[list(idx)].index],
        "current_rs_ratio": round(float(rs_ratio.iloc[-1]), 3),
        "current_rs_momentum": round(float(rs_momentum.iloc[-1]), 3),
    }




def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all standard indicators to an OHLCV DataFrame."""
    if df.empty or len(df) < EMA_LONG:
        return df
    df = df.copy()
    c = df["Close"]
    df["RSI"] = calc_rsi(c)
    df["EMA5"] = calc_ema(c, 5)
    df["EMA10"] = calc_ema(c, 10)
    df["EMA20"] = calc_ema(c, EMA_SHORT)
    df["EMA21"] = calc_ema(c, 21)
    df["EMA50"] = calc_ema(c, EMA_MID)
    df["EMA200"] = calc_ema(c, EMA_LONG)
    df["SMA200"] = calc_sma(c, EMA_LONG)
    df["ATR"] = calc_atr(df["High"], df["Low"], df["Close"])
    df["VolRatio"] = calc_volume_ratio(df["Volume"])
    df["VolMA20"] = df["Volume"].rolling(VOLUME_MA_PERIOD).mean()
    return df

