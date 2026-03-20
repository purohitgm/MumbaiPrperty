# GorkNifty-1.py  — yfinance-free build
# Run with: streamlit run GorkNifty-1.py
# requirements.txt needs only: streamlit, pandas, numpy, plotly, requests

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import time

st.set_page_config(page_title="VCP + NR7 Screener & Chart", layout="wide")

# ─────────────────────────────────────────────────────────────────────────────
# Yahoo Finance v8 — direct requests layer (no yfinance)
# ─────────────────────────────────────────────────────────────────────────────
_YF_SESSION: requests.Session | None = None
_YF_CRUMB: str | None = None

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://finance.yahoo.com/",
}


def _get_session_and_crumb() -> tuple[requests.Session, str]:
    """Bootstrap a session cookie + crumb once per Streamlit process."""
    global _YF_SESSION, _YF_CRUMB
    if _YF_SESSION and _YF_CRUMB:
        return _YF_SESSION, _YF_CRUMB

    sess = requests.Session()
    sess.headers.update(_HEADERS)

    # Step 1: hit consent / main page to grab cookies
    sess.get("https://finance.yahoo.com/", timeout=10)

    # Step 2: fetch crumb
    resp = sess.get(
        "https://query1.finance.yahoo.com/v1/test/getcrumb",
        timeout=10,
    )
    crumb = resp.text.strip()

    # Fallback to query2 if crumb empty
    if not crumb:
        resp = sess.get(
            "https://query2.finance.yahoo.com/v1/test/getcrumb",
            timeout=10,
        )
        crumb = resp.text.strip()

    _YF_SESSION = sess
    _YF_CRUMB   = crumb
    return sess, crumb


@st.cache_data(ttl=900, show_spinner=False)
def fetch_ohlcv(symbol: str, period: str = "9mo") -> pd.DataFrame:
    """
    Fetch OHLCV from Yahoo Finance v8 chart API.
    Returns a DataFrame with DatetimeIndex and columns:
    Open, High, Low, Close, Volume
    Returns empty DataFrame on any failure.
    """
    try:
        sess, crumb = _get_session_and_crumb()

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {
            "interval":       "1d",
            "range":          period,
            "includePrePost": "false",
            "crumb":          crumb,
        }

        r = sess.get(url, params=params, timeout=15)
        r.raise_for_status()
        js = r.json()

        result = js["chart"]["result"]
        if not result:
            return pd.DataFrame()

        res       = result[0]
        ts        = res["timestamp"]
        q         = res["indicators"]["quote"][0]
        adj_close = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")

        df = pd.DataFrame({
            "Open":   q["open"],
            "High":   q["high"],
            "Low":    q["low"],
            "Close":  adj_close if adj_close else q["close"],
            "Volume": q["volume"],
        }, index=pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Kolkata"))

        df.index = df.index.normalize()          # strip time component
        df.index.name = "Date"
        df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)
        return df

    except Exception:
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# NR7 detection
# ─────────────────────────────────────────────────────────────────────────────
def is_nr7(df: pd.DataFrame, lookback: int = 7) -> bool:
    if len(df) < lookback:
        return False
    recent      = df.tail(lookback)
    today_range = recent["High"].iloc[-1] - recent["Low"].iloc[-1]
    prev_ranges = recent["High"] - recent["Low"]
    return bool(today_range <= prev_ranges.iloc[:-1].min())


# ─────────────────────────────────────────────────────────────────────────────
# VCP detection (no scipy, no pandas_ta)
# ─────────────────────────────────────────────────────────────────────────────
def detect_vcp_simple(
    df: pd.DataFrame,
    min_contractions: int   = 2,
    max_contractions: int   = 5,
    min_pullback_pct: float = 4.0,
    lookback_bars:    int   = 130,
) -> dict:
    if len(df) < 50:
        return {"is_vcp": False, "reason": "too few bars"}

    df = df.tail(lookback_bars).copy()
    df["range"] = df["High"] - df["Low"]

    window = 6
    df["is_high"] = df["High"] == df["High"].rolling(window * 2 + 1, center=True).max()
    df["is_low"]  = df["Low"]  == df["Low"].rolling(window * 2 + 1, center=True).min()

    highs = df[df["is_high"]][["High"]].reset_index()
    lows  = df[df["is_low"]][["Low"]].reset_index()

    if len(highs) < 3 or len(lows) < 3:
        return {"is_vcp": False, "reason": "not enough swings"}

    pullbacks      = []
    last_high_idx  = None
    last_high_p    = None

    for i, row in df.iterrows():
        if row["is_high"]:
            last_high_idx = i
            last_high_p   = row["High"]
        elif row["is_low"] and last_high_idx is not None:
            pb_pct = (last_high_p - row["Low"]) / last_high_p * 100
            if pb_pct >= min_pullback_pct:
                pullbacks.append({
                    "high_time":    last_high_idx,
                    "low_time":     i,
                    "pullback_pct": pb_pct,
                    "high_price":   last_high_p,
                    "low_price":    row["Low"],
                })

    if len(pullbacks) < min_contractions:
        return {"is_vcp": False, "reason": f"only {len(pullbacks)} pullbacks"}

    recent_pbs = pullbacks[-max_contractions:]
    depths     = [pb["pullback_pct"] for pb in recent_pbs]
    ratios     = [depths[i] / depths[i - 1] for i in range(1, len(depths))]

    # Reject if any pullback is NOT smaller than its predecessor
    if any(r >= 1.0 for r in ratios):
        return {"is_vcp": False, "reason": "pullbacks not contracting"}

    pivot_high = max(pb["high_price"] for pb in recent_pbs)
    zones      = [(pb["high_time"], pb["low_time"]) for pb in recent_pbs]

    return {
        "is_vcp":              True,
        "num_contractions":    len(recent_pbs),
        "contraction_ratios":  [round(r, 2) for r in ratios],
        "latest_pullback_pct": round(depths[-1], 1),
        "pivot_high_price":    round(pivot_high, 1),
        "vcp_score":           min(100, 40 + 15 * len(recent_pbs) + int(25 * (1 - np.mean(ratios)))),
        "contraction_zones":   zones,
        "reason":              "VCP detected",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Plotly candlestick + VCP overlay
# ─────────────────────────────────────────────────────────────────────────────
def plot_candles_with_vcp(df, symbol, vcp_result=None, ema_lengths=None):
    if ema_lengths is None:
        ema_lengths = [10, 21]

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="OHLC",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ))

    for length in ema_lengths:
        ema = df["Close"].ewm(span=length, adjust=False).mean()
        fig.add_trace(go.Scatter(
            x=df.index, y=ema,
            name=f"EMA {length}",
            line=dict(width=1.6),
        ))

    if vcp_result and vcp_result.get("is_vcp"):
        ph = vcp_result["pivot_high_price"]
        fig.add_hline(
            y=ph, line_dash="dash", line_color="#ffca28", line_width=1.8,
            annotation_text=f" VCP Pivot ≈ {ph:.1f}",
            annotation_position="top right",
        )

        zone_colors = [
            "rgba(0, 230, 118, 0.14)",
            "rgba(0, 230, 118, 0.18)",
            "rgba(0, 230, 118, 0.24)",
            "rgba(255, 213, 79, 0.20)",
            "rgba(255, 213, 79, 0.28)",
        ]

        for i, (start_idx, end_idx) in enumerate(vcp_result.get("contraction_zones", [])[-5:]):
            if start_idx in df.index and end_idx in df.index:
                fig.add_vrect(
                    x0=start_idx, x1=end_idx,
                    fillcolor=zone_colors[i % len(zone_colors)],
                    line_width=0,
                    layer="below",
                )

        fig.add_annotation(
            x=df.index[-1], y=df["High"].max() * 1.02,
            text=(
                f"VCP • {vcp_result['num_contractions']} contractions "
                f"• Score {vcp_result['vcp_score']}"
            ),
            showarrow=False,
            font=dict(size=13, color="#26a69a"),
            align="left",
        )

    fig.update_layout(
        title=f"{symbol} — VCP + NR7 Detection",
        template="plotly_dark",
        height=620,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Base screener data (last price / % chg) via v8
# ─────────────────────────────────────────────────────────────────────────────
SYMBOLS = [
    "RELIANCE", "HDFCBANK", "TCS", "INFY", "ICICIBANK",
    "BHARTIARTL", "SBIN", "ITC", "HINDUNILVR", "LT",
]

@st.cache_data(ttl=900, show_spinner=False)
def get_base_data() -> pd.DataFrame:
    rows = []
    for sym in SYMBOLS:
        df = fetch_ohlcv(sym + ".NS", period="5d")   # short range for speed
        if df.empty or len(df) < 2:
            continue
        last       = df.iloc[-1]
        prev_close = df.iloc[-2]["Close"]
        rows.append({
            "symbol": sym,
            "last":   round(last["Close"], 1),
            "%chg":   round((last["Close"] / prev_close - 1) * 100, 2),
            "volume": round(last["Volume"] / 1e5, 1),   # in lakhs
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# App Layout
# ─────────────────────────────────────────────────────────────────────────────
st.title("VCP + NR7 Screener & Chart")
st.caption("No yfinance — direct Yahoo Finance v8 API • no pandas_ta / scipy")

with st.spinner("Loading base data …"):
    df_base = get_base_data()

if df_base.empty:
    st.error("Could not load any data. Check network / Yahoo Finance availability.")
    st.stop()

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    min_chg               = st.slider("% Change Today >",  -10.0, 15.0,  0.0, step=0.5)
    min_vcp_score         = st.slider("Min VCP Score",          0,  100,   55, step=5)
    show_only_strong_combo = st.checkbox("Only Strong NR7 + VCP", value=False)
    selected_symbol        = st.selectbox("View Chart", ["None"] + df_base["symbol"].tolist())

df_screen = df_base[df_base["%chg"] >= min_chg].copy()

# ── VCP / NR7 enrichment ─────────────────────────────────────────────────────
if "vcp_score" not in df_screen.columns:
    progress = st.progress(0, text="Starting scan …")
    results  = []

    rows = list(df_screen.iterrows())   # materialise so counter stays 0-based
    for counter, (_, row) in enumerate(rows):
        progress.progress(
            (counter + 1) / len(rows),
            text=f"Scanning {row['symbol']} ({counter+1}/{len(rows)}) …",
        )

        df_hist = fetch_ohlcv(row["symbol"] + ".NS", period="9mo")

        if df_hist.empty or len(df_hist) < 80:
            results.append({"vcp_score": 0, "is_vcp": False, "is_nr7": False, "combo": "None"})
            time.sleep(0.25)   # gentle rate limit
            continue

        vcp       = detect_vcp_simple(df_hist)
        nr7_today = is_nr7(df_hist)

        combo = "None"
        if vcp["is_vcp"] and nr7_today:
            combo = "Strong" if vcp["vcp_score"] >= 70 else "Moderate"

        results.append({
            "vcp_score":    vcp.get("vcp_score", 0),
            "is_vcp":       vcp["is_vcp"],
            "is_nr7":       nr7_today,
            "combo":        combo,
            "num_contract": vcp.get("num_contractions", 0),
            "pivot_high":   vcp.get("pivot_high_price"),
        })
        time.sleep(0.25)

    progress.empty()
    enrich_df = pd.DataFrame(results)
    df_screen = pd.concat([df_screen.reset_index(drop=True), enrich_df], axis=1)

df_screen = df_screen[df_screen["vcp_score"] >= min_vcp_score]
if show_only_strong_combo:
    df_screen = df_screen[df_screen["combo"] == "Strong"]

# ── Screener Table ───────────────────────────────────────────────────────────
st.subheader("Screener Results")
if df_screen.empty:
    st.info("No stocks match current filters.")
else:
    fmt_cols = {c: "{:.2f}" for c in ["%chg", "vcp_score"] if c in df_screen.columns}
    st.dataframe(
        df_screen.style
        .format(fmt_cols)
        .background_gradient(subset=["%chg"],      cmap="RdYlGn")
        .background_gradient(subset=["vcp_score"], cmap="YlGn")
        .highlight_max(subset=["vcp_score"],        color="#c8e6c9"),
        use_container_width=True,
    )

# ── Chart Panel ──────────────────────────────────────────────────────────────
if selected_symbol != "None":
    st.subheader(f"Chart: {selected_symbol}.NS")
    with st.spinner(f"Loading chart for {selected_symbol} …"):
        df_chart = fetch_ohlcv(selected_symbol + ".NS", period="9mo")

    if df_chart.empty:
        st.error("Could not fetch chart data. Try again in a moment.")
    else:
        vcp_res = detect_vcp_simple(df_chart)
        nr7     = is_nr7(df_chart)

        st.caption(
            f"NR7 today = **{nr7}** | "
            f"VCP detected = **{vcp_res.get('is_vcp')}** | "
            f"Score = **{vcp_res.get('vcp_score', 0)}**"
        )

        fig = plot_candles_with_vcp(
            df_chart,
            selected_symbol,
            vcp_res,
            ema_lengths=[10, 21, 50],
        )
        st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.caption("yfinance-free build • Yahoo Finance v8 API • Multi-contraction zones shaded")
