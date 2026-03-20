# data/nse_indices.py
# Complete NSE sectoral indices and their constituent tickers


# Each sector maps to:
# "index_ticker" : Yahoo Finance ticker for the index
# "stocks" : list of constituent Yahoo Finance tickers
# "industries" : sub-grouping of stocks by industry


NSE_SECTORS = {
    "Nifty Bank": {
        "index_ticker": "^NSEBANK",
        "color": "#1E88E5",
        "stocks": [
            "HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS",
            "SBIN.NS", "BANKBARODA.NS", "FEDERALBNK.NS", "IDFCFIRSTB.NS",
            "INDUSINDBK.NS", "BANDHANBNK.NS", "AUBANK.NS", "PNB.NS",
        ],
        "industries": {
            "Private Banks": ["HDFCBANK.NS","ICICIBANK.NS","KOTAKBANK.NS",
                              "AXISBANK.NS","INDUSINDBK.NS","BANDHANBNK.NS",
                              "FEDERALBNK.NS","IDFCFIRSTB.NS","AUBANK.NS"],
            "Public Banks": ["SBIN.NS","BANKBARODA.NS","PNB.NS"],
        },
    },
    "Nifty IT": {
        "index_ticker": "^CNXIT",
        "color": "#43A047",
        "stocks": [
            "TCS.NS","INFY.NS","HCLTECH.NS","WIPRO.NS","TECHM.NS",
            "LTIM.NS","MPHASIS.NS","PERSISTENT.NS","COFORGE.NS","OFSS.NS",
        ],
        "industries": {
            "Large-Cap IT": ["TCS.NS","INFY.NS","HCLTECH.NS","WIPRO.NS"],
            "Mid-Cap IT": ["TECHM.NS","LTIM.NS","MPHASIS.NS",
                              "PERSISTENT.NS","COFORGE.NS","OFSS.NS"],
        },
    },
    "Nifty FMCG": {
        "index_ticker": "^CNXFMCG",
        "color": "#FB8C00",
        "stocks": [
            "HINDUNILVR.NS","ITC.NS","NESTLEIND.NS","BRITANNIA.NS",
            "DABUR.NS","MARICO.NS","COLPAL.NS","GODREJCP.NS",
            "EMAMILTD.NS","TATACONSUM.NS",
        ],
        "industries": {
            "Household Products": ["HINDUNILVR.NS","GODREJCP.NS","COLPAL.NS","MARICO.NS"],
            "Food & Beverages": ["ITC.NS","NESTLEIND.NS","BRITANNIA.NS",
                                    "DABUR.NS","EMAMILTD.NS","TATACONSUM.NS"],
        },
    },
    "Nifty Auto": {
        "index_ticker": "^CNXAUTO",
        "color": "#E53935",
        "stocks": [
            "MARUTI.NS","TATAMOTORS.NS","M&M.NS","BAJAJ-AUTO.NS",
            "HEROMOTOCO.NS","EICHERMOT.NS","TVSMOTOR.NS","ASHOKLEY.NS",
            "BALKRISIND.NS","MOTHERSON.NS","BOSCHLTD.NS",
        ],
        "industries": {
            "Passenger Vehicles": ["MARUTI.NS","TATAMOTORS.NS","M&M.NS"],
            "Two Wheelers": ["BAJAJ-AUTO.NS","HEROMOTOCO.NS","EICHERMOT.NS","TVSMOTOR.NS"],
            "Commercial Vehicles":["ASHOKLEY.NS"],
            "Auto Ancillaries": ["BALKRISIND.NS","MOTHERSON.NS","BOSCHLTD.NS"],
        },
    },
    "Nifty Pharma": {
        "index_ticker": "^CNXPHARMA",
        "color": "#8E24AA",
        "stocks": [
            "SUNPHARMA.NS","DRREDDY.NS","CIPLA.NS","DIVISLAB.NS",
            "APOLLOHOSP.NS","TORNTPHARM.NS","ALKEM.NS","LUPIN.NS",
            "BIOCON.NS","AUROPHARMA.NS",
        ],
        "industries": {
            "Pharma Majors": ["SUNPHARMA.NS","DRREDDY.NS","CIPLA.NS","LUPIN.NS"],
            "Specialty Pharma":["DIVISLAB.NS","TORNTPHARM.NS","ALKEM.NS","AUROPHARMA.NS"],
            "Healthcare": ["APOLLOHOSP.NS","BIOCON.NS"],
        },
    },
    "Nifty Metal": {
        "index_ticker": "^CNXMETAL",
        "color": "#607D8B",
        "stocks": [
            "TATASTEEL.NS","JSWSTEEL.NS","HINDALCO.NS","VEDL.NS",
            "COAL INDIA.NS","NMDC.NS","SAIL.NS","NATIONALUM.NS",
            "HINDCOPPER.NS","APLAPOLLO.NS",
        ],
        "industries": {
            "Steel": ["TATASTEEL.NS","JSWSTEEL.NS","SAIL.NS","APLAPOLLO.NS"],
            "Aluminium/Mining":["HINDALCO.NS","VEDL.NS","NATIONALUM.NS","HINDCOPPER.NS"],
            "Mining": ["COALINDIA.NS","NMDC.NS"],
        },
    },
    "Nifty Realty": {
        "index_ticker": "^CNXREALTY",
        "color": "#795548",
        "stocks": [
            "DLF.NS","GODREJPROP.NS","OBEROIRLTY.NS","PRESTIGE.NS",
            "LODHA.NS","PHOENIXLTD.NS","SOBHA.NS","BRIGADE.NS",
        ],
        "industries": {
            "Residential": ["DLF.NS","GODREJPROP.NS","LODHA.NS","SOBHA.NS","BRIGADE.NS"],
            "Commercial": ["OBEROIRLTY.NS","PRESTIGE.NS","PHOENIXLTD.NS"],
        },
    },
    "Nifty Energy": {
        "index_ticker": "^CNXENERGY",
        "color": "#F4511E",
        "stocks": [
            "RELIANCE.NS","ONGC.NS","NTPC.NS","POWERGRID.NS",
            "BPCL.NS","IOC.NS","GAIL.NS","ADANIGREEN.NS",
            "TATAPOWER.NS","ADANIPORTS.NS",
        ],
        "industries": {
            "Oil & Gas": ["RELIANCE.NS","ONGC.NS","BPCL.NS","IOC.NS","GAIL.NS"],
            "Power": ["NTPC.NS","POWERGRID.NS","ADANIGREEN.NS","TATAPOWER.NS"],
            "Infrastructure":["ADANIPORTS.NS"],
        },
    },
    "Nifty Financial Services": {
        "index_ticker": "^CNXFINANCE",
        "color": "#00ACC1",
        "stocks": [
            "HDFCBANK.NS","ICICIBANK.NS","BAJFINANCE.NS","BAJAJFINSV.NS",
            "SBILIFE.NS","HDFCLIFE.NS","ICICIGI.NS","MUTHOOTFIN.NS",
            "CHOLAFIN.NS","MANAPPURAM.NS",
        ],
        "industries": {
            "NBFCs": ["BAJFINANCE.NS","BAJAJFINSV.NS","MUTHOOTFIN.NS",
                              "CHOLAFIN.NS","MANAPPURAM.NS"],
            "Insurance": ["SBILIFE.NS","HDFCLIFE.NS","ICICIGI.NS"],
            "Banks": ["HDFCBANK.NS","ICICIBANK.NS"],
        },
    },
    "Nifty Consumer Durables": {
        "index_ticker": "^CNXCONSUMER",
        "color": "#26A69A",
        "stocks": [
            "TITAN.NS","VGUARD.NS","HAVELLS.NS","VOLTAS.NS",
            "BLUESTARCO.NS","WHIRLPOOL.NS","KAJARIACER.NS","CERA.NS",
        ],
        "industries": {
            "Consumer Electronics": ["VOLTAS.NS","BLUESTARCO.NS","WHIRLPOOL.NS"],
            "Electricals": ["HAVELLS.NS","VGUARD.NS"],
            "Accessories": ["TITAN.NS","KAJARIACER.NS","CERA.NS"],
        },
    },
}


# ─── Broad index tickers ─────────────────────────────────────────────────────
BROAD_INDICES = {
    "Nifty 50": "^NSEI",
    "Nifty 100": "^CNX100",
    "Nifty 200": "^CNX200",
    "Nifty 500": "^CNX500",
}


# ─── All unique stocks across sectors ────────────────────────────────────────
def get_all_stocks() -> list:
    stocks = set()
    for sector_data in NSE_SECTORS.values():
        stocks.update(sector_data["stocks"])
    return sorted(list(stocks))


def get_sector_for_stock(ticker: str) -> str:
    for sector, data in NSE_SECTORS.items():
        if ticker in data["stocks"]:
            return sector
    return "Unknown"

