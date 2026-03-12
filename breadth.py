def market_breadth(data):

    adv=0
    dec=0

    for t,df in data.items():

        if df.Close.iloc[-1] > df.Close.iloc[-2]:
            adv+=1
        else:
            dec+=1

    ratio = adv/(dec+1)

    return adv,dec,ratio