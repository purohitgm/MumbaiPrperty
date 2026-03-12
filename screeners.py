def detect_nr7(df):

    if len(df)<7:
        return False

    last=df.Range.iloc[-1]
    prev=df.Range.iloc[-7:-1]

    return last<prev.min()

def volume_spike(df):
    return df.Volume.iloc[-1] > 2*df.VolumeAvg.iloc[-1]

def vcp_pattern(df):
    ranges=df.Range.tail(10)
    return ranges.is_monotonic_decreasing

def stock_score(df):

    score=0

    if df.Close.iloc[-1]>df.SMA50.iloc[-1]:
        score+=25

    if df.SMA50.iloc[-1]>df.SMA200.iloc[-1]:
        score+=25

    if df.RSI.iloc[-1]>60:
        score+=20

    if volume_spike(df):
        score+=15

    if detect_nr7(df):
        score+=15

    return score