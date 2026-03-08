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
rsi = self.calculate_rsi(close)[-1]
ema20 = self.calculate_ema(close, 20)[-1]
ema50 = self.calculate_ema(close, 50)[-1]
ema200 = self.calculate_ema(close, 200)[-1] if len(close) >= 200 else np.nan

vol_20dma = volume.rolling(20).mean()[-1]
volume_ratio = volume[-1] / vol_20dma if vol_20dma > 0 else 1

# Pattern detection
nr7 = self.detect_nr7(high, low)[-1]

# Relative strength vs Nifty50
nifty = yf.download('^NSEI', period='3mo', interval='1d')['Close']
if not nifty.empty:
rel_strength = (close / close.shift(20)) / (nifty / nifty.shift(20))
rel_strength = rel_strength[-1] if not rel_strength.empty else 1
else:
rel_strength = 1

momentum = self.momentum_score(rsi, volume_ratio, rel_strength)

return {
'rsi': rsi,
'volume_ratio': volume_ratio,
'rel_strength': rel_strength,
'momentum': momentum,
'nr7': nr7,
'above_ema20': close[-1] > ema20,
'grade': self.get_ai_grade(rsi, momentum, rel_strength)
}
except:
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
for symbol in sector_stocks[:10]: # Limit for performance
stock_metrics = self.get_stock_metrics(symbol)
if stock_metrics:
metrics.append(stock_metrics)

if not metrics:
return {}

df_metrics = pd.DataFrame(metrics)
return {
'avg_rsi': df_metrics['rsi'].mean(),
'avg_volume_ratio': df_metrics['volume_ratio'].mean(),
'rel_strength': df_metrics['rel_strength'].mean(),
'market_breadth': (df_metrics['above_ema20'].sum() / len(df_metrics)) * 100,
'grade_dist': df_metrics['grade'].value_counts(normalize=True).to_dict()
}

# Initialize dashboard
@st.cache_data(ttl=60) # Auto-refresh every 60 seconds
def load_data():
analytics = NiftyAnalytics()

# Sector data
sector_data = {}
for sector, stocks in analytics.sector_map.items():
sector_data[sector] = analytics.get_sector_metrics(stocks)

# Index data
indices_data = analytics.fetch_live_data(analytics.nifty_50 + analytics.nifty_100[:5])

return sector_data, indices_data

def main():
st.markdown('<h1 class="main-header">📈 Nifty Analytics Dashboard</h1>', unsafe_allow_html=True)

# Sidebar filters
st.sidebar.header("🔧 Filters")
market_cap_filter = st.sidebar.selectbox("Market Cap", ["All", "Large Cap", "Mid Cap"])
rsi_range = st.sidebar.slider("RSI Range", 20, 80, (30, 70))
momentum_threshold = st.sidebar.slider("Momentum Score", 0, 100, 50)

# Load data
with st.spinner('Fetching live market data...'):
sector_data, indices_data = load_data()

# KPI Cards
col1, col2, col3, col4 = st.columns(4)
with col1:
st.metric("Nifty 50", f"{sum(indices_data.values()):.2f}", delta="↑ 1.2%")
with col2:
st.metric("Market Breadth", f"{np.mean([d.get('market_breadth', 0) for d in sector_data.values()]):.1f}%")
with col3:
st.metric("Avg Momentum", f"{np.mean([d.get('momentum', 0) for d in sector_data.values()]):.1f}")
with col4:
st.metric("Top Grade A", len([s for s in sector_data.values() if s.get('grade_dist', {}).get('A', 0) > 0.3]))

# Sector Heatmap
st.header("🌡️ Sector Heatmap")
sector_df = pd.DataFrame(sector_data).T
sector_df['color_rsi'] = pd.to_numeric(sector_df['avg_rsi'], errors='coerce')
sector_df['color_momentum'] = pd.to_numeric(sector_df['momentum'], errors='coerce')

fig_heatmap = px.imshow(
sector_df[['avg_rsi', 'avg_volume_ratio', 'market_breadth']].fillna(0).values,
labels=dict(x=["RSI", "Vol Ratio", "Breadth"], y=sector_df.index),
title="Sector Performance Matrix",
color_continuous_scale="RdYlGn",
aspect="auto"
)
fig_heatmap.update_layout(height=500)
st.plotly_chart(fig_heatmap, use_container_width=True)

# Sector Performance Table
st.header("📊 Sector Analytics")
col_a, col_b = st.columns([2, 1])

with col_a:
perf_df = pd.DataFrame({
'Sector': sector_df.index,
'% Stocks > EMA20': [f"{sector_df.loc[s, 'market_breadth']:.1f}%" for s in sector_df.index],
'Avg RSI': [f"{sector_df.loc[s, 'avg_rsi']:.1f}" for s in sector_df.index],
'Rel Strength': [f"{sector_df.loc[s, 'rel_strength']:.3f}" for s in sector_df.index],
'Volume Ratio': [f"{sector_df.loc[s, 'avg_volume_ratio']:.2f}x" for s in sector_df.index]
})
st.dataframe(perf_df, use_container_width=True)

with col_b:
# Momentum Ranking
momentum_ranking = sector_df.sort_values('color_momentum', ascending=False)['color_momentum']
fig_bar = px.bar(
x=momentum_ranking.values,
y=momentum_ranking.index,
orientation='h',
title="Momentum Ranking",
color=momentum_ranking.values,
color_continuous_scale='Viridis'
)
st.plotly_chart(fig_bar, use_container_width=True)

# Stock Details (Interactive)
st.header("🏭 Individual Stock Analysis")
selected_sector = st.selectbox("Select Sector", list(sector_data.keys()))

if selected_sector in analytics.sector_map:
stocks = analytics.sector_map[selected_sector][:10]
stock_metrics = [analytics.get_stock_metrics(s) for s in stocks]

stock_df = pd.DataFrame(stock_metrics)
stock_df['Symbol'] = stocks[:len(stock_metrics)]

# Filter by user criteria
filtered_df = stock_df[
(stock_df['rsi'] >= rsi_range[0]) &
(stock_df['rsi'] <= rsi_range[1]) &
(stock_df['momentum'] >= momentum_threshold)
]

st.dataframe(filtered_df[['Symbol', 'rsi', 'momentum', 'volume_ratio', 'grade', 'nr7']],
use_container_width=True)

# Candlestick Chart
st.header("📉 Interactive Candlestick")
selected_stock = st.selectbox("Select Stock", analytics.nifty_50)

ema_periods = st.multiselect("EMA Periods", [5, 10, 21, 50], default=[20, 50])

data = yf.download(selected_stock, period='3mo', interval='1d')
if not data.empty:
fig_candle = make_subplots(
rows=2, cols=1, shared_xaxes=True,
vertical_spacing=0.03, subplot_titles=(selected_stock, 'Volume'),
row_width=[0.7, 0.3]
)

fig_candle.add_trace(
go.Candlestick(
x=data.index, open=data['Open'], high=data['High'],
low=data['Low'], close=data['Close'], name="OHLC"
),
row=1, col=1
)

# Add EMAs
for period in ema_periods:
ema = analytics.calculate_ema(data['Close'], period)
fig_candle.add_trace(
go.Scatter(x=data.index, y=ema, name=f'EMA {period}', line=dict(width=1)),
row=1, col=1
)

fig_candle.add_trace(
go.Bar(x=data.index, y=data['Volume'], name="Volume", marker_color='rgba(158,202,225,0.5)'),
row=2, col=1
)

fig_candle.update_layout(height=600, title=f"{selected_stock} - Technical Analysis")
st.plotly_chart(fig_candle, use_container_width=True)

if __name__ == "__main__":
main()
