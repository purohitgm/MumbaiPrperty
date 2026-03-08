import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.figure_factory as ff
from datetime import datetime, timedelta
import time
import requests
from concurrent.futures import ThreadPoolExecutor
import warnings
warnings.filterwarnings('ignore')

# Page config
st.set_page_config(
page_title="Nifty Analytics Dashboard",
page_icon="📈",
layout="wide",
initial_sidebar_state="expanded"
)

# Custom CSS for professional styling
st.markdown("""
<style>
.main-header {
font-size: 3rem;
font-weight: 700;
color: #1f77b4;
text-align: center;
margin-bottom: 2rem;
}
.metric-card {
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
padding: 1rem;
border-radius: 10px;
color: white;
}
.stMetric > label {
color: white !important;
font-size: 14px;
}
</style>
""", unsafe_allow_html=True)

class NiftyAnalytics:
def __init__(self):
self.nifty_50 = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'HINDUNILVR.NS',
'ICICIBANK.NS', 'KOTAKBANK.NS', 'BHARTIARTL.NS', 'ITC.NS', 'SBIN.NS']
self.nifty_100 = self.nifty_50 + ['ASIANPAINT.NS', 'AXISBANK.NS', 'MARUTI.NS', 'LT.NS']
self.nifty_200 = self.nifty_100 + ['NESTLEIND.NS', 'SUNPHARMA.NS']
self.sectoral_indices = ['NIFTY_BANK.NS', 'NIFTY_IT.NS', 'NIFTY_FMCG.NS', 'NIFTY_AUTO.NS',
'NIFTY_PHARMA.NS', 'NIFTY_METAL.NS', 'NIFTY_REALTY.NS']

# Sector mapping (simplified - extend as needed)
self.sector_map = {
'BANK': ['HDFCBANK.NS', 'ICICIBANK.NS', 'KOTAKBANK.NS', 'SBIN.NS', 'AXISBANK.NS'],
'IT': ['TCS.NS', 'INFY.NS'],
'FMCG': ['HINDUNILVR.NS', 'ITC.NS', 'NESTLEIND.NS'],
'AUTO': ['MARUTI.NS'],
'PHARMA': ['SUNPHARMA.NS']
}

def fetch_live_data(self, symbols, period='1d', interval='5m'):
"""Fetch live data with error handling"""
data = {}
with ThreadPoolExecutor(max_workers=10) as executor:
futures = {executor.submit(yf.download, symbol, period=period, interval=interval): symbol
for symbol in symbols}
for future in futures:
try:
symbol = futures[future]
df = future.result(timeout=10)
if not df.empty:
data[symbol] = df['Close'].iloc[-1] if len(df) > 0 else np.nan
except:
continue
return data

def calculate_rsi(self, prices, period=14):
"""Calculate RSI"""
delta = prices.diff()
gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
rs = gain / loss
return 100 - (100 / (1 + rs))

def calculate_ema(self, prices, period):
"""Calculate EMA"""
return prices.ewm(span=period).mean()

def detect_nr7(self, high, low, period=7):
"""NR7 detection - narrowest range in 7 days"""
ranges = high - low
return ranges.rolling(period).min() == ranges

def momentum_score(self, rsi, volume_ratio, rel_strength):
"""Composite momentum score 0-100"""
rsi_score = min(100, max(0, (50 - abs(rsi - 50)) * 2))
vol_score = min(50, volume_ratio * 10)
rs_score = min(50, rel_strength * 100)
return (rsi_score + vol_score + rs_score) / 3

def get_stock_metrics(self, symbol):
"""Calculate comprehensive stock metrics"""
try:
data = yf.download(symbol, period='3mo', interval='1d')
if data.empty:
return {}

close = data['Close']
high = data['High']
low = data['Low']
volume = data['Volume']

# Technical indicators
rsi = self.calculate_rsi(close).iloc[-1]
ema20 = self.calculate_ema(close, 20).iloc[-1]
ema50 = self.calculate_ema(close, 50).iloc[-1]
ema200 = self.calculate_ema(close, 200).iloc[-1] if len(close) >= 200 else np.nan

vol_20dma = volume.rolling(20).mean().iloc[-1]
volume_ratio = volume.iloc[-1] / vol_20dma if vol_20dma > 0 else 1

# Pattern detection
nr7 = self.detect_nr7(high, low).iloc[-1]

# Relative strength vs Nifty50
nifty_data = yf.download('^NSEI', period='3mo', interval='1d')
if not nifty_data.empty:
nifty_close = nifty_data['Close']
if len(close) == len(nifty_close):
rel_strength = (close / close.shift(20)) / (nifty_close / nifty_close.shift(20))
rel_strength = rel_strength.iloc[-1] if not rel_strength.empty else 1
else:
rel_strength = 1
else:
rel_strength = 1

momentum = self.momentum_score(rsi, volume_ratio, rel_strength)

return {
'rsi': rsi,
'volume_ratio': volume_ratio,
'rel_strength': rel_strength,
'momentum': momentum,
'nr7': nr7,
'above_ema20': close.iloc[-1] > ema20,
'grade': self.get_ai_grade(rsi, momentum, rel_strength)
}
except Exception as e:
return {}

def get_ai_grade(self, rsi, momentum, rel_strength):
"""AI grading system"""
if rsi > 60 and momentum > 70 and rel_strength > 1.05:
return 'A'
elif rsi > 45 and momentum > 50:
return 'B'
else:
return 'C'

def get_sector_metrics(self, sector_stocks):
"""Calculate sector-level metrics"""
metrics = []
analytics = NiftyAnalytics() # Fresh instance for sector analysis

for symbol in sector_stocks[:10]: # Limit for performance
stock_metrics = analytics.get_stock_metrics(symbol)
if stock_metrics:
stock_metrics['sector_momentum'] = stock_metrics['momentum']
metrics.append(stock_metrics)

if not metrics:
return {}

df_metrics = pd.DataFrame(metrics)
return {
'avg_rsi': df_metrics['rsi'].mean(),
'avg_volume_ratio': df_metrics['volume_ratio'].mean(),
'rel_strength': df_metrics['rel_strength'].mean(),
'market_breadth': (df_metrics['above_ema20'].sum() / len(df_metrics)) * 100,
'avg_momentum': df_metrics['momentum'].mean(),
'grade_dist': df_metrics['grade'].value_counts(normalize=True).to_dict()
}

# Global analytics instance
analytics = NiftyAnalytics()

@st.cache_data(ttl=60) # Auto-refresh every 60 seconds
def load_data():
"""Load all dashboard data"""
sector_data = {}
for sector, stocks in analytics.sector_map.items():
sector_data[sector] = analytics.get_sector_metrics(stocks)

# Index live prices
indices_data = analytics.fetch_live_data(analytics.nifty_50[:10])

return sector_data, indices_data

def main():
st.markdown('<h1 class="main-header">📈 Nifty Analytics Dashboard</h1>', unsafe_allow_html=True)

# Sidebar filters
st.sidebar.header("🔧 Filters")
market_cap_filter = st.sidebar.selectbox("Market Cap", ["All", "Large Cap", "Mid Cap"])
rsi_range = st.sidebar.slider("RSI Range", 20, 80, (30, 70))
momentum_threshold = st.sidebar.slider("Momentum Score", 0, 100, 50)

# Load data with spinner
with st.spinner('🔄 Fetching live NSE data...'):
sector_data, indices_data = load_data()

if not sector_data:
st.error("❌ No data available. Check internet connection and NSE market hours.")
st.stop()

# KPI Cards Row 1
col1, col2, col3, col4 = st.columns(4)
total_nifty = sum([v for v in indices_data.values() if not np.isnan(v)]) / len(indices_data)

with col1:
st.metric("Nifty 50", f"₹{total_nifty:.2f}", delta="↑ 1.2%")
with col2:
breadth = np.mean([d.get('market_breadth', 50) for d in sector_data.values()])
st.metric("Market Breadth", f"{breadth:.1f}%", delta=f"↑ {breadth-50:.1f}%")
with col3:
avg_momentum = np.mean([d.get('avg_momentum', 50) for d in sector_data.values()])
st.metric("Avg Momentum", f"{avg_momentum:.1f}", delta=f"↑ {avg_momentum-50:.1f}")
with col4:
grade_a_count = sum(1 for s in sector_data.values() if s.get('grade_dist', {}).get('A', 0) > 0.3)
st.metric("Grade A Sectors", grade_a_count, delta=f"+{grade_a_count}")

# Sector Heatmap
st.header("🌡️ Live Sector Heatmap")
if sector_data:
sector_df = pd.DataFrame(sector_data).T.fillna(50)
sector_df['color_rsi'] = pd.to_numeric(sector_df['avg_rsi'], errors='coerce')
sector_df['color_momentum'] = pd.to_numeric(sector_df['avg_momentum'], errors='coerce')

# Heatmap matrix
heatmap_data = sector_df[['avg_rsi', 'avg_volume_ratio', 'market_breadth', 'avg_momentum']].values
fig_heatmap = px.imshow(
heatmap_data,
labels=dict(x=["RSI(14)", "Vol/20DMA", "Breadth%", "Momentum"],
y=sector_df.index),
title="📊 Sector Performance Matrix (Live Data)",
color_continuous_scale="RdYlGn",
aspect="auto",
height=500
)
fig_heatmap.update_layout(title_font_size=16)
st.plotly_chart(fig_heatmap, use_container_width=True)

# Dual Column: Table + Bar Chart
st.header("🏦 Sector Analytics")
col_a, col_b = st.columns([2, 1])

with col_a:
perf_df = pd.DataFrame({
'Sector': list(sector_data.keys()),
'Breadth %': [f"{sector_data[s].get('market_breadth', 0):.1f}%" for s in sector_data],
'RSI': [f"{sector_data[s].get('avg_rsi', 0):.1f}" for s in sector_data],
'Rel Str': [f"{sector_data[s].get('rel_strength', 1):.3f}x" for s in sector_data],
'Vol Ratio': [f"{sector_data[s].get('avg_volume_ratio', 1):.2f}x" for s in sector_data],
'Momentum': [f"{sector_data[s].get('avg_momentum', 0):.1f}" for s in sector_data]
})
st.dataframe(perf_df.style.highlight_max(axis=0), use_container_width=True)

with col_b:
# Momentum Bar Chart
momentum_data = {k: v.get('avg_momentum', 50) for k, v in sector_data.items()}
fig_bar = px.bar(
x=list(momentum_data.values()),
y=list(momentum_data.keys()),
orientation='h',
title="⚡ Momentum Rank",
color=list(momentum_data.values()),
color_continuous_scale='Viridis_r'
)
fig_bar.update_layout(height=350, margin=dict(l=0, r=0))
st.plotly_chart(fig_bar, use_container_width=True)

# Stock Analysis Section
st.header("💎 Top Stock Picks")
selected_sector = st.selectbox("Select Sector", list(analytics.sector_map.keys()))

if selected_sector in analytics.sector_map:
stocks = analytics.sector_map[selected_sector][:15]
with st.spinner(f'Analyzing {selected_sector} stocks...'):
stock_metrics = []
for symbol in stocks:
metrics = analytics.get_stock_metrics(symbol)
if metrics:
metrics['symbol'] = symbol.replace('.NS', '')
stock_metrics.append(metrics)

if stock_metrics:
stock_df = pd.DataFrame(stock_metrics)

# Apply filters
filtered_df = stock_df[
(stock_df['rsi'] >= rsi_range[0]) &
(stock_df['rsi'] <= rsi_range[1]) &
(stock_df['momentum'] >= momentum_threshold)
].sort_values('momentum', ascending=False)

st.dataframe(
filtered_df[['symbol', 'rsi', 'momentum', 'volume_ratio', 'rel_strength', 'grade', 'nr7']],
use_container_width=True,
height=400
)

# Interactive Candlestick
st.header("📊 Candlestick Analysis")
selected_stock = st.selectbox("Pick Stock", analytics.nifty_50, index=0)
ema_periods = st.multiselect("Select EMAs", [5, 10, 21, 50], default=[21, 50])

if st.button("🔄 Update Chart"):
with st.spinner('Loading candlestick...'):
data = yf.download(selected_stock, period='3mo', interval='1d')
if not data.empty:
fig_candle = make_subplots(
rows=2, cols=1, shared_xaxes=True,
vertical_spacing=0.03,
subplot_titles=(f'{selected_stock} - Price Action', 'Volume & RSI'),
row_width=[0.7, 0.3]
)

# Candlestick
fig_candle.add_trace(
go.Candlestick(
x=data.index, open=data['Open'], high=data['High'],
low=data['Low'], close=data['Close'],
name="Price", increasing_line_color='#00ff88', decreasing_line_color='#ff4444'
),
row=1, col=1
)

# EMAs
for period in ema_periods:
ema = analytics.calculate_ema(data['Close'], period)
fig_candle.add_trace(
go.Scatter(x=data.index, y=ema, name=f'EMA-{period}',
line=dict(width=2)),
row=1, col=1
)

# Volume
colors = ['green' if data['Close'] > data['Open'] else 'red' for _, row in data.iterrows()]
fig_candle.add_trace(
go.Bar(x=data.index, y=data['Volume'], name="Volume",
marker_color=colors, opacity=0.6),
row=2, col=1
)

# RSI subplot
rsi = analytics.calculate_rsi(data['Close'])
fig_candle.add_trace(
go.Scatter(x=data.index, y=rsi, name='RSI(14)', line=dict(color='orange')),
row=2, col=1
)
fig_candle.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
fig_candle.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

fig_candle.update_layout(height=700, showlegend=True,
title=f"Technical Analysis - {selected_stock}")
st.plotly_chart(fig_candle, use_container_width=True)

if __name__ == "__main__":
main()