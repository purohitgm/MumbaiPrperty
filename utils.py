def valid_df(df):

    if df is None:
        return False

    if df.empty:
        return False

    if "Close" not in df.columns:
        return False

    if len(df) < 3:
        return False

    return True