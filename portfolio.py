import pandas as pd

portfolio = {
"RELIANCE.NS":10,
"INFY.NS":15
}

def portfolio_value(data):

    total=0
    rows=[]

    for stock,qty in portfolio.items():

        if stock in data:

            price=data[stock].Close.iloc[-1]
            value=price*qty

            total+=value
            rows.append((stock,qty,price,value))

    df=pd.DataFrame(rows,columns=["Stock","Qty","Price","Value"])

    return df,total