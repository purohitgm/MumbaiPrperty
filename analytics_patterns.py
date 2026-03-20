# analytics/patterns.py
# NR7, VCP, Pocket Pivot pattern detection


import pandas as pd
import numpy as np




def detect_nr7(df: pd.DataFrame) -> pd.Series:
    """
    NR7: Narrowest Range of the last 7 bars.
    Returns a boolean Series (True on NR7 bar).
    """
    if df.empty or len(df) < 7:
        return pd.Series(dtype=bool)
    bar_range = df["High"] - df["Low"]
    nr7 = bar_range == bar_range.rolling(7).min()
    return nr7




def detect_pocket_pivot(df: pd.DataFrame,
                        lookback: int = 10) -> pd.Series:
    """
    Pocket Pivot (Gil Morales):
    A pocket pivot occurs when:
      1. Stock closes above the 10-day EMA
      2. Up-day volume > any down-day volume in prior `lookback` days
    Returns boolean Series.
    """
    if df.empty or len(df) < lookback + 5:
        return pd.Series(dtype=bool)


    df = df.copy()
    df["EMA10"] = df["Close"].ewm(span=10, adjust=False).mean()
    df["is_up"] = df["Close"] > df["Close"].shift(1)


    # Max down-day volume over prior lookback bars (excluding today)
    def max_down_vol(idx: int) -> float:
        start = max(0, idx - lookback)
        window = df.iloc[start:idx]
        down_vols = window.loc[~window["is_up"], "Volume"]
        return float(down_vols.max()) if not down_vols.empty else 0.0


    signals = []
    for i in range(len(df)):
        if i < lookback:
            signals.append(False)
            continue
        row = df.iloc[i]
        above_ema = row["Close"] > row["EMA10"]
        is_up_day = row["is_up"]
        mdv = max_down_vol(i)
        vol_condition = row["Volume"] > mdv
        signals.append(bool(above_ema and is_up_day and vol_condition))


    return pd.Series(signals, index=df.index)




def detect_vcp(df: pd.DataFrame,
               contractions: int = 3,
               min_weeks: int = 5) -> pd.Series:
    """
    Volatility Contraction Pattern (Mark Minervini):
    Detects VCP in a rolling window:
      - Price pulled back X%, then X/2%, then X/4% (3 contractions)
      - Each contraction lower than previous
      - Volume dries up on each contraction
    Returns boolean Series (True on potential breakout bar of VCP).
    """
    if df.empty or len(df) < min_weeks * 5:
        return pd.Series(False, index=df.index)


    signals = pd.Series(False, index=df.index)
    window = min_weeks * 5


    for i in range(window, len(df)):
        segment = df.iloc[i - window: i + 1]
        highs = segment["High"].values
        lows = segment["Low"].values
        vols = segment["Volume"].values


        # Find local peaks and troughs
        from scipy.signal import argrelextrema
        pk_idx = argrelextrema(highs, np.greater, order=3)[0]
        tr_idx = argrelextrema(lows, np.less, order=3)[0]


        if len(pk_idx) < contractions or len(tr_idx) < contractions:
            continue


        # Measure depth of last N contractions
        depths = []
        vcp_vols = []
        for k in range(min(contractions, len(pk_idx), len(tr_idx))):
            pk = highs[pk_idx[-(k+1)]]
            tr = lows[tr_idx[-(k+1)]] if k < len(tr_idx) else lows.min()
            depth = (pk - tr) / pk * 100
            depths.append(depth)
            # Volume in trough window
            if k < len(tr_idx):
                vcp_vols.append(vols[tr_idx[-(k+1)]])


        if len(depths) < 2:
            continue


        # Contractions should be decreasing in depth
        depths_ok = all(depths[j] > depths[j+1] for j in range(len(depths)-1))
        # Volume should be declining
        vols_ok = len(vcp_vols) < 2 or all(
            vcp_vols[j] > vcp_vols[j+1] for j in range(len(vcp_vols)-1)
        )


        if depths_ok and vols_ok and depths[-1] < depths[0] * 0.5:
            signals.iloc[i] = True


    return signals




def detect_rs_high_before_price_high(df: pd.DataFrame,
                                      benchmark_close: pd.Series,
                                      lookback: int = 60) -> pd.Series:
    """
    RS New High Before Price High:
    Identifies bars where the RS line (stock/benchmark) makes a new high
    while the price has NOT yet made a new high.
    This is a leading indicator of future price breakout.
    Returns boolean Series.
    """
    if df.empty or benchmark_close.empty:
        return pd.Series(dtype=bool)


    common = df.index.intersection(benchmark_close.index)
    if len(common) < lookback:
        return pd.Series(False, index=df.index)


    stock_c = df["Close"].loc[common]
    bench_c = benchmark_close.loc[common]
    rs_line = (stock_c / bench_c)


    signals = pd.Series(False, index=df.index)


    for i in range(lookback, len(common)):
        window_rs = rs_line.iloc[i - lookback: i + 1]
        window_price = stock_c.iloc[i - lookback: i + 1]


        rs_new_high = rs_line.iloc[i] >= window_rs.max()
        price_new_high = stock_c.iloc[i] >= window_price.max()


        # RS new high but price NOT at new high yet → leading signal
        if rs_new_high and not price_new_high:
            signals.loc[common[i]] = True


    return signals




def get_pattern_summary(df: pd.DataFrame,
                         benchmark_close: pd.Series = None) -> dict:
    """
    Run all pattern detections on a DataFrame.
    Returns dict with latest signal status and signal indices.
    """
    if df.empty:
        return {}


    nr7_signals = detect_nr7(df)
    pp_signals = detect_pocket_pivot(df)
    vcp_signals = detect_vcp(df)


    result = {
        "nr7_latest": bool(nr7_signals.iloc[-1]) if not nr7_signals.empty else False,
        "pp_latest": bool(pp_signals.iloc[-1]) if not pp_signals.empty else False,
        "vcp_latest": bool(vcp_signals.iloc[-1]) if not vcp_signals.empty else False,
        "nr7_indices": nr7_signals[nr7_signals].index.tolist(),
        "pp_indices": pp_signals[pp_signals].index.tolist() if not pp_signals.empty else [],
        "vcp_indices": vcp_signals[vcp_signals].index.tolist(),
    }


    if benchmark_close is not None and not benchmark_close.empty:
        rs_sig = detect_rs_high_before_price_high(df, benchmark_close)
        result["rs_high_before_price"] = rs_sig[rs_sig].index.tolist() if not rs_sig.empty else []
        result["rs_high_latest"] = bool(rs_sig.iloc[-1]) if not rs_sig.empty else False


    return result

