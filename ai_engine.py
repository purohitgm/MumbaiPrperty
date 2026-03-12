def generate_commentary(breadth_ratio,top_sector):

    if breadth_ratio>1.5:
        mood="Bullish"
    elif breadth_ratio<0.7:
        mood="Bearish"
    else:
        mood="Neutral"

    text=f"""
Market Sentiment: {mood}

Strongest Sector: {top_sector}

Momentum stocks showing expansion may lead next market leg.
"""

    return text