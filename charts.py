import plotly.graph_objects as go

def candle_chart(df):

    fig=go.Figure()

    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df.Open,
        high=df.High,
        low=df.Low,
        close=df.Close
    ))

    fig.add_trace(go.Scatter(x=df.index,y=df.SMA20,name="SMA20"))
    fig.add_trace(go.Scatter(x=df.index,y=df.SMA50,name="SMA50"))

    fig.update_layout(template="plotly_dark",height=600)

    return fig