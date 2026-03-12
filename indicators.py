import pandas as pd
import numpy as np

def add_indicators(df):

    df["SMA20"]=df.Close.rolling(20).mean()
    df["SMA50"]=df.Close.rolling(50).mean()
    df["SMA200"]=df.Close.rolling(200).mean()

    delta=df.Close.diff()

    gain=(delta.where(delta>0,0)).rolling(14).mean()
    loss=(-delta.where(delta<0,0)).rolling(14).mean()

    rs=gain/loss
    df["RSI"]=100-(100/(1+rs))

    df["Range"]=df.High-df.Low
    df["VolumeAvg"]=df.Volume.rolling(20).mean()

    return df