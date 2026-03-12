import streamlit as st
import pandas as pd

from config import NIFTY_TICKERS,SECTOR_MAP
from data_engine import get_stock_data,get_bulk_data
from indicators import add_indicators
from screeners import stock_score,detect_nr7,vcp_pattern
from sector_analysis import sector_strength
from breadth import market_breadth
from ai_engine import generate_commentary
from charts import candle_chart
from portfolio import portfolio_value

st.set_page_config(layout="wide")

st.title("📊 NiftyQuant Terminal Pro")

menu=st.sidebar.radio("Navigation",
["Market Overview","Stock Charts","Momentum Radar","Sector Rotation","Portfolio","AI Commentary"])

data=get_bulk_data(NIFTY_TICKERS)

if menu=="Market Overview":

    adv,dec,ratio=market_breadth(data)

    col1,col2,col3=st.columns(3)

    col1.metric("Advancers",adv)
    col2.metric("Decliners",dec)
    col3.metric("Breadth Ratio",round(ratio,2))

if menu=="Stock Charts":

    ticker=st.selectbox("Stock",NIFTY_TICKERS)

    df=get_stock_data(ticker)

    df=add_indicators(df)

    fig=candle_chart(df)

    st.plotly_chart(fig,use_container_width=True)

if menu=="Momentum Radar":

    rows=[]

    for t,df in data.items():

        df=add_indicators(df)

        score=stock_score(df)

        nr7=detect_nr7(df)

        vcp=vcp_pattern(df)

        rows.append((t,score,nr7,vcp))

    table=pd.DataFrame(rows,columns=["Stock","Score","NR7","VCP"])

    table.sort_values("Score",ascending=False,inplace=True)

    st.dataframe(table)

if menu=="Sector Rotation":

    sector_df=sector_strength(SECTOR_MAP,data)

    st.bar_chart(sector_df.set_index("Sector"))

if menu=="Portfolio":

    pf,total=portfolio_value(data)

    st.dataframe(pf)

    st.metric("Portfolio Value",round(total,2))

if menu=="AI Commentary":

    adv,dec,ratio=market_breadth(data)

    sector_df=sector_strength(SECTOR_MAP,data)

    top_sector=sector_df.sort_values("Performance",ascending=False).iloc[0]["Sector"]

    text=generate_commentary(ratio,top_sector)

    st.write(text)