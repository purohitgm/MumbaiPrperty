import pandas as pd

def add_indicators(df):

    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()

    delta = df["Close"].diff()

    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()

    rs = gain / loss

    df["RSI"] = 100 - (100 / (1 + rs))

    df["Range"] = df["High"] - df["Low"]

    return df