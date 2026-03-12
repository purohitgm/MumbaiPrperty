import yfinance as yf
import streamlit as st

@st.cache_data(ttl=900)
def get_stock_data(ticker):

    try:

        df = yf.download(
            ticker,
            period="6mo",
            interval="1d",
            progress=False
        )

        if df is None or df.empty:
            return None

        df = df.dropna()

        return df

    except:

        return None


@st.cache_data(ttl=900)
def load_bulk(tickers):

    data = {}

    for t in tickers:

        df = get_stock_data(t)

        if df is not None:

            data[t] = df

    return data