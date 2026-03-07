from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class Listing(BaseModel):
    id: str
    name: str
    sub: str                   # e.g. "3 BHK · 2,400 sq ft"
    location: str              # neighbourhood
    city_area: str             # broader area
    type: str                  # Apartment / Villa / Penthouse / Duplex
    price_cr: float            # current price in Crore INR
    prev_price_cr: float       # original / previous price in Crore INR
    drop_cr: float             # absolute drop in Crore
    drop_pct: float            # percentage drop
    url: str                   # listing URL
    source: str                # magicbricks / 99acres / housing / nobroker
    is_new: bool               # listed/dropped today
    scraped_at: datetime
    bedrooms: Optional[int] = None
    area_sqft: Optional[int] = None
    image_url: Optional[str] = None


class ScrapeStats(BaseModel):
    total_listings_scanned: int
    drops_found: int
    avg_drop_pct: float
    biggest_drop_pct: float
    last_updated: datetime
    sources: dict[str, int]    # source → count
