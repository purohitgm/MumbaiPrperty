import pandas as pd

def sector_strength(sector_map,data):

    results=[]

    for sector,stocks in sector_map.items():

        perf=[]

        for s in stocks:

            if s in data:

                df=data[s]

                change=(df.Close.iloc[-1]/df.Close.iloc[-5]-1)*100
                perf.append(change)

        if perf:
            results.append((sector,sum(perf)/len(perf)))

    return pd.DataFrame(results,columns=["Sector","Performance"])