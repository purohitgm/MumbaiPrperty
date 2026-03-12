import streamlit as st
import pandas as pd

from config import NIFTY_TICKERS
from data_engine import load_bulk, get_stock_data
from indicators import add_indicators
from screeners import stock_score, nr7
from breadth import market_breadth
from charts import candle_chart

st.set_page_config(layout="wide")

st.title("NiftyQuant Terminal v2")

menu = st.sidebar.selectbox(
    "Navigation",
    ["Market Overview","Charts","Momentum Scanner"]
)

data = load_bulk(NIFTY_TICKERS)

if menu == "Market Overview":

    adv, dec, ratio = market_breadth(data)

    col1, col2, col3 = st.columns(3)

    col1.metric("Advancers", adv)
    col2.metric("Decliners", dec)
    col3.metric("Breadth Ratio", round(ratio,2))

if menu == "Charts":

    ticker = st.selectbox("Select Stock", NIFTY_TICKERS)

    df = get_stock_data(ticker)

    if df is not None:

        df = add_indicators(df)

        fig = candle_chart(df)

        st.plotly_chart(fig, use_container_width=True)

    else:

        st.warning("Data not available")

if menu == "Momentum Scanner":

    rows = []

    for ticker, df in data.items():

        df = add_indicators(df)

        score = stock_score(df)

        pattern = nr7(df)

        rows.append((ticker, score, pattern))

    table = pd.DataFrame(
        rows,
        columns=["Stock","Score","NR7"]
    )

    table = table.sort_values("Score", ascending=False)

    st.dataframe(table)