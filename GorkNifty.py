# streamlit_vcp_nr7_test.py
# Run with: streamlit run streamlit_vcp_nr7_test.py

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

st.set_page_config(page_title="VCP + NR7 Screener & Chart", layout="wide")

# ────────────────────────────────────────────────
# Helper: detect NR7
# ────────────────────────────────────────────────
def is_nr7(df: pd.DataFrame, lookback: int = 7) -> bool:
if len(df) < lookback:
return False
recent = df.tail(lookback)
today_range = recent['High'].iloc[-1] - recent['Low'].iloc[-1]
prev_ranges = recent['High'] - recent['Low']
return today_range <= prev_ranges.iloc[:-1].min()


# ────────────────────────────────────────────────
# Simplified VCP detection (no scipy dependency)
# ────────────────────────────────────────────────
def detect_vcp_simple(df: pd.DataFrame, min_contractions=2, max_contractions=5,
contraction_ratio_th=0.70, min_pullback_pct=4.0,
lookback_bars=130) -> dict:
if len(df) < 50:
return {"is_vcp": False, "reason": "too few bars"}

df = df.tail(lookback_bars).copy()
df['range'] = df['High'] - df['Low']

# Very simple swing high/low detection (local max/min over window)
window = 6
df['is_high'] = df['High'] == df['High'].rolling(window*2+1, center=True).max()
df['is_low'] = df['Low'] == df['Low'].rolling(window*2+1, center=True).min()

highs = df[df['is_high']][['High']].reset_index()
lows = df[df['is_low']][['Low']].reset_index()

if len(highs) < 3 or len(lows) < 3:
return {"is_vcp": False, "reason": "not enough swings"}

# Build pullback sequence (high → low)
pullbacks = []
last_high_idx = None
last_high_p = None

for i, row in df.iterrows():
if row['is_high']:
last_high_idx = i
last_high_p = row['High']
elif row['is_low'] and last_high_idx is not None:
pb_pct = (last_high_p - row['Low']) / last_high_p * 100
if pb_pct >= min_pullback_pct:
pullbacks.append({
'high_time': last_high_idx,
'low_time': i,
'pullback_pct': pb_pct,
'high_price': last_high_p,
'low_price': row['Low']
})

if len(pullbacks) < min_contractions:
return {"is_vcp": False, "reason": f"only {len(pullbacks)} pullbacks"}

recent_pbs = pullbacks[-max_contractions:]
depths = [pb['pullback_pct'] for pb in recent_pbs]
ratios = [depths[i]/depths[i-1] for i in range(1, len(depths))]

if any(r > contraction_ratio_th for r in ratios):
return {"is_vcp": False, "reason": "not contracting enough"}

pivot_high = max(pb['high_price'] for pb in recent_pbs)

# Collect contraction zones for charting (high → low of each pullback)
zones = [(pb['high_time'], pb['low_time']) for pb in recent_pbs]

return {
"is_vcp": True,
"num_contractions": len(recent_pbs),
"contraction_ratios": [round(r,2) for r in ratios],
"latest_pullback_pct": round(depths[-1],1),
"pivot_high_price": round(pivot_high,1),
"vcp_score": min(100, 40 + 15*len(recent_pbs) + int(25*(1-np.mean(ratios)))),
"contraction_zones": zones, # list of (start_idx, end_idx)
"reason": "VCP detected"
}


# ────────────────────────────────────────────────
# Plotly chart with MULTI-contraction shading
# ────────────────────────────────────────────────
def plot_candles_with_vcp(df, symbol, vcp_result=None, ema_lengths=[10,21]):
fig = go.Figure()

# Candlestick
fig.add_trace(go.Candlestick(
x=df.index,
open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
name='OHLC', increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
))

# EMAs
for length in ema_lengths:
ema = df['Close'].ewm(span=length, adjust=False).mean()
fig.add_trace(go.Scatter(x=df.index, y=ema, name=f'EMA {length}', line=dict(width=1.6)))

# VCP annotations
if vcp_result and vcp_result.get('is_vcp'):
# Pivot high line
ph = vcp_result['pivot_high_price']
fig.add_hline(y=ph, line_dash="dash", line_color="#ffca28", line_width=1.8,
annotation_text=f" VCP Pivot ≈ {ph:.1f}", annotation_position="top right")

# MULTI-contraction rectangles
zones = vcp_result.get('contraction_zones', [])
colors = ['rgba(0, 230, 118, 0.14)', 'rgba(0, 230, 118, 0.18)', 'rgba(0, 230, 118, 0.24)',
'rgba(255, 213, 79, 0.20)', 'rgba(255, 213, 79, 0.28)']

for i, (start_idx, end_idx) in enumerate(zones[-5:]): # last 5 max
if start_idx in df.index and end_idx in df.index:
c = colors[i % len(colors)]
fig.add_vrect(
x0=start_idx, x1=end_idx,
fillcolor=c, line_width=0, layer="below",
opacity=0.9
)

# Summary annotation
fig.add_annotation(
x=df.index[-1], y=df['High'].max()*1.02,
text=f"VCP • {vcp_result['num_contractions']} contractions • Score {vcp_result['vcp_score']}",
showarrow=False, font=dict(size=13, color="#26a69a"), align="left"
)

fig.update_layout(
title=f"{symbol} — VCP + NR7 Detection",
template="plotly_dark",
height=620,
xaxis_rangeslider_visible=False,
hovermode="x unified",
legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)

return fig


# ────────────────────────────────────────────────
# Main App
# ────────────────────────────────────────────────
st.title("VCP + NR7 Screener & Chart — Quick Test")
st.caption("Simplified version — uses yfinance & native pandas (no pandas_ta / scipy)")

# Cache data fetching
@st.cache_data(ttl=900) # 15 min
def get_nifty50_data():
# Very small subset for fast testing — expand in production
symbols = ["RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "ICICIBANK.NS",
"BHARTIARTL.NS", "SBIN.NS", "ITC.NS", "HINDUNILVR.NS", "LT.NS"]
data = []
for sym in symbols:
try:
ticker = yf.Ticker(sym)
hist = ticker.history(period="9mo")
if len(hist) < 100:
continue

last = hist.iloc[-1]
prev_close = hist.iloc[-2]['Close'] if len(hist)>1 else last['Close']

row = {
'symbol': sym.replace('.NS',''),
'last': round(last['Close'],1),
'%chg': round((last['Close']/prev_close - 1)*100, 2),
'volume': int(last['Volume']/1e5)/10, # lakh
}
data.append(row)
except:
pass
return pd.DataFrame(data)


df_base = get_nifty50_data()

if df_base.empty:
st.error("Could not load any data. Check internet / yfinance.")
st.stop()

# ── Filters ───────────────────────────────────────
with st.sidebar:
st.header("Filters")
min_chg = st.slider("% Change Today >", -10.0, 15.0, 0.0, step=0.5)
min_vcp_score = st.slider("Min VCP Score", 0, 100, 55, step=5)
show_only_strong_combo = st.checkbox("Only Strong NR7 + VCP", value=False)
selected_symbol = st.selectbox("View Chart", ["None"] + df_base['symbol'].tolist())

# Apply basic filter
df_screen = df_base[df_base['%chg'] >= min_chg].copy()

# ── Enrich with VCP / NR7 (expensive — cache per symbol in production) ──
if 'vcp_score' not in df_screen.columns:
progress = st.progress(0)
results = []

for i, row in df_screen.iterrows():
progress.progress((i+1)/len(df_screen), text=f"Scanning {row['symbol']} ...")
try:
df_hist = yf.download(row['symbol'] + ".NS", period="9mo", progress=False)
if len(df_hist) < 80:
results.append({"vcp_score":0, "is_vcp":False, "is_nr7":False, "combo":"None"})
continue

vcp = detect_vcp_simple(df_hist)
nr7_today = is_nr7(df_hist)

combo = "None"
if vcp['is_vcp'] and nr7_today:
combo = "Strong" if vcp['vcp_score'] >= 70 else "Moderate"

results.append({
"vcp_score": vcp.get('vcp_score', 0),
"is_vcp": vcp['is_vcp'],
"is_nr7": nr7_today,
"combo": combo,
"num_contract": vcp.get('num_contractions', 0),
"pivot_high": vcp.get('pivot_high_price')
})
except:
results.append({"vcp_score":0, "is_vcp":False, "is_nr7":False, "combo":"None"})

enrich_df = pd.DataFrame(results)
df_screen = pd.concat([df_screen.reset_index(drop=True), enrich_df], axis=1)

# Apply advanced filters
df_screen = df_screen[df_screen['vcp_score'] >= min_vcp_score]
if show_only_strong_combo:
df_screen = df_screen[df_screen['combo'] == "Strong"]

# ── Display Screener ───────────────────────────────
st.subheader("Screener Results")
if df_screen.empty:
st.info("No stocks match current filters.")
else:
st.dataframe(
df_screen.style
.format(precision=2)
.background_gradient(subset=['%chg'], cmap='RdYlGn')
.background_gradient(subset=['vcp_score'], cmap='YlGn')
.highlight_max(subset=['vcp_score'], color='#c8e6c9')
)

# ── Chart for selected symbol ──────────────────────
if selected_symbol != "None":
st.subheader(f"Chart: {selected_symbol}.NS")
try:
df_chart = yf.download(selected_symbol + ".NS", period="9mo", progress=False)
vcp_res = detect_vcp_simple(df_chart)
nr7 = is_nr7(df_chart)

st.caption(f"NR7 today = **{nr7}** | VCP detected = **{vcp_res.get('is_vcp')}** | Score = **{vcp_res.get('vcp_score',0)}**")

fig = plot_candles_with_vcp(
df_chart,
selected_symbol,
vcp_res,
ema_lengths=[10, 21, 50] # you can make this dynamic later
)
st.plotly_chart(fig, use_container_width=True)

except Exception as e:
st.error(f"Could not load chart: {e}")

st.markdown("---")
st.caption("Quick test version • Multi-contraction zones shaded • Simplified swing detection • 2025")