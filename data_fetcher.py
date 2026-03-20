# data/fetcher.py
# Centralized data fetching with error handling and rate-limit awareness

import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta
import time
import logging

from config import HISTORY_PERIOD, INTRADAY_PERIOD, INTRADAY_INTERVAL
from data.nse_indices import NSE_SECTORS, BROAD_INDICES, get_all_stocks

logger = logging.getLogger(__name__)

# ─── Cache TTL ───────────────────────────────────────────────────────────────
CACHE_TTL = 60 # seconds


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_history(ticker: str, period: str = HISTORY_PERIOD) -> pd.DataFrame:
"""Fetch OHLCV history for a single ticker."""
try:
df = yf.download(ticker, period=period, interval="1d",
auto_adjust=True, progress=False, threads=False)
if df.empty:
return pd.DataFrame()
df.index = pd.to_datetime(df.index)
# Flatten MultiIndex columns if present
if isinstance(df.columns, pd.MultiIndex):
df.columns = df.columns.get_level_values(0)
return df
except Exception as e:
logger.warning(f"fetch_history failed for {ticker}: {e}")
return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_intraday(ticker: str) -> pd.DataFrame:
"""Fetch intraday 5-min bars."""
try:
df = yf.download(ticker, period=INTRADAY_PERIOD,
interval=INTRADAY_INTERVAL,
auto_adjust=True, progress=False, threads=False)
if df.empty:
return pd.DataFrame()
if isinstance(df.columns, pd.MultiIndex):
df.columns = df.columns.get_level_values(0)
return df
except Exception as e:
logger.warning(f"fetch_intraday failed for {ticker}: {e}")
return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_bulk_history(tickers: tuple, period: str = HISTORY_PERIOD) -> dict:
"""
Fetch history for multiple tickers in one yf.download call.
Returns dict: {ticker: DataFrame}
"""
if not tickers:
return {}
try:
raw = yf.download(
list(tickers), period=period, interval="1d",
auto_adjust=True, progress=False, group_by="ticker", threads=True
)
result = {}
if len(tickers) == 1:
t = tickers[0]
if isinstance(raw.columns, pd.MultiIndex):
raw.columns = raw.columns.get_level_values(0)
result[t] = raw if not raw.empty else pd.DataFrame()
else:
for t in tickers:
try:
df = raw[t].copy() if t in raw.columns.get_level_values(0) else pd.DataFrame()
df.dropna(how="all", inplace=True)
result[t] = df
except Exception:
result[t] = pd.DataFrame()
return result
except Exception as e:
logger.warning(f"fetch_bulk_history failed: {e}")
return {t: pd.DataFrame() for t in tickers}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_quote(ticker: str) -> dict:
"""Fetch current price info."""
try:
t = yf.Ticker(ticker)
info = t.fast_info
return {
"ticker": ticker,
"price": getattr(info, "last_price", None),
"prev_close": getattr(info, "previous_close", None),
"volume": getattr(info, "last_volume", None),
"market_cap": getattr(info, "market_cap", None),
}
except Exception as e:
logger.warning(f"fetch_quote failed for {ticker}: {e}")
return {"ticker": ticker, "price": None, "prev_close": None,
"volume": None, "market_cap": None}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def fetch_sector_data() -> pd.DataFrame:
"""
Build a sector-level summary DataFrame.
Returns one row per sector with index performance.
"""
rows = []
for sector, meta in NSE_SECTORS.items():
idx_ticker = meta["index_ticker"]
df = fetch_history(idx_ticker, period="6mo")
if df.empty or len(df) < 5:
rows.append({
"sector": sector,
"change_pct": 0.0,
"ticker": idx_ticker,
})
continue
today_close = df["Close"].iloc[-1]
prev_close = df["Close"].iloc[-2]
change_pct = ((today_close - prev_close) / prev_close) * 100
rows.append({
"sector": sector,
"change_pct": round(float(change_pct), 2),
"ticker": idx_ticker,
"close": float(today_close),
})
return pd.DataFrame(rows)


def fetch_all_stock_history(sector: str = None) -> dict:
"""
Fetch history for all stocks (optionally filtered by sector).
Returns dict: {ticker: DataFrame}
"""
if sector and sector in NSE_SECTORS:
tickers = tuple(NSE_SECTORS[sector]["stocks"])
else:
tickers = tuple(get_all_stocks())
return fetch_bulk_history(tickers)
