import yfinance as yf

def get_stock_data(ticker, period="6mo", interval="1d"):
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    return df

def get_bulk_data(tickers):
    data={}
    for t in tickers:
        try:
            data[t]=get_stock_data(t)
        except:
            pass
    return data