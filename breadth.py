from utils import valid_df

def market_breadth(data):

    adv = 0
    dec = 0

    for ticker, df in data.items():

        if not valid_df(df):
            continue

        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])

        if last > prev:
            adv += 1
        else:
            dec += 1

    ratio = adv / (dec + 1)

    return adv, dec, ratio