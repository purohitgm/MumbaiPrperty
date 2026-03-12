from utils import valid_df

def nr7(df):

    if not valid_df(df):
        return False

    if len(df) < 7:
        return False

    last = df["Range"].iloc[-1]

    prev = df["Range"].iloc[-7:-1]

    return last < prev.min()


def stock_score(df):

    if not valid_df(df):
        return 0

    score = 0

    if df["Close"].iloc[-1] > df["SMA50"].iloc[-1]:
        score += 40

    if df["RSI"].iloc[-1] > 60:
        score += 30

    if nr7(df):
        score += 30

    return score