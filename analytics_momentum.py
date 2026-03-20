# analytics/momentum.py
# Composite momentum scoring (0-100)


import pandas as pd
import numpy as np
from analytics.technical import (
    calc_rsi, calc_ema, calc_volume_ratio, calc_relative_strength
)
from config import MOMENTUM_WEIGHTS, RSI_PERIOD, VOLUME_MA_PERIOD




def _normalize(value: float, min_val: float, max_val: float) -> float:
    """Clip & normalize to 0-100."""
    if max_val == min_val:
        return 50.0
    return float(np.clip((value - min_val) / (max_val - min_val) * 100, 0, 100))




def score_rsi(rsi_val: float) -> float:
    """RSI score: 50→0, 80→100, 20→0 (optimal in 60-80 range)."""
    if pd.isna(rsi_val):
        return 0.0
    if rsi_val >= 80:
        return 90.0 # slightly penalize overbought
    if rsi_val >= 60:
        return _normalize(rsi_val, 60, 80) * 1.0 + 60
    if rsi_val >= 40:
        return _normalize(rsi_val, 40, 60) * 0.6 + 20
    return _normalize(rsi_val, 0, 40) * 0.2




def score_relative_strength(rs_pct: float) -> float:
    """RS score: clamp -20% to +20% → 0-100."""
    return float(np.clip((rs_pct + 20) / 40 * 100, 0, 100))




def score_ema_position(close: float, ema20: float,
                        ema50: float, ema200: float) -> float:
    """
    Perfect alignment: price > EMA20 > EMA50 > EMA200 = 100
    Each condition contributes 33 points.
    """
    score = 0.0
    if close > ema20: score += 34
    if close > ema50: score += 33
    if close > ema200: score += 33
    if ema20 > ema50 > ema200: score = min(score + 10, 100)
    return score




def score_volume(vol_ratio: float) -> float:
    """Volume vs 20DMA: >2x = 100, 1x = 50, 0.5x = 0."""
    return float(np.clip((vol_ratio - 0.5) / 1.5 * 100, 0, 100))




def calc_momentum_score(df: pd.DataFrame,
                         benchmark_close: pd.Series = None) -> dict:
    """
    Compute composite momentum score for a stock.
    Returns dict with component scores and final score.
    """
    if df.empty or len(df) < 200:
        return {
            "momentum_score": 0, "rsi": 0, "rs_pct": 0,
            "ema_score_raw": 0, "vol_ratio": 0, "grade": "C"
        }


    close = df["Close"]
    rsi_s = calc_rsi(close)
    ema20 = calc_ema(close, 20)
    ema50 = calc_ema(close, 50)
    ema200 = calc_ema(close, 200)
    vol_r = calc_volume_ratio(df["Volume"])


    # Latest values
    latest_rsi = float(rsi_s.iloc[-1]) if not rsi_s.isna().all() else 50.0
    latest_ema20 = float(ema20.iloc[-1])
    latest_ema50 = float(ema50.iloc[-1])
    latest_ema200 = float(ema200.iloc[-1])
    latest_vol = float(vol_r.iloc[-1]) if not vol_r.isna().all() else 1.0
    latest_close = float(close.iloc[-1])


    # RS vs Nifty 50
    rs_pct = 0.0
    if benchmark_close is not None and not benchmark_close.empty:
        rs_pct = calc_relative_strength(close, benchmark_close)


    # Component scores
    s_rsi = score_rsi(latest_rsi)
    s_rs = score_relative_strength(rs_pct)
    s_ema = score_ema_position(latest_close, latest_ema20, latest_ema50, latest_ema200)
    s_vol = score_volume(latest_vol)


    # Weighted total
    total = (
        s_rsi * MOMENTUM_WEIGHTS["rsi_score"] +
        s_rs * MOMENTUM_WEIGHTS["rs_score"] +
        s_ema * MOMENTUM_WEIGHTS["ema_score"] +
        s_vol * MOMENTUM_WEIGHTS["volume_score"]
    )
    total = round(float(np.clip(total, 0, 100)), 1)


    return {
        "momentum_score": total,
        "rsi": round(latest_rsi, 1),
        "rs_pct": round(rs_pct, 2),
        "ema_score_raw": s_ema,
        "vol_ratio": round(latest_vol, 2),
        "above_ema20": latest_close > latest_ema20,
        "above_ema50": latest_close >

