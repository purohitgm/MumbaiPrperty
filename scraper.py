"""
Mumbai Luxury Real Estate Scraper
Scrapes: MagicBricks, 99acres, Housing.com, NoBroker

Run standalone:  python scraper.py
Via API:         imported by main.py
"""

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlencode

import httpx
from bs4 import BeautifulSoup

from models import Listing

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MIN_PRICE_CR  = 5.0          # only track ₹5Cr+ properties
DROP_THRESHOLD = 0.03        # flag if price dropped ≥ 3%
CACHE_FILE    = Path("cache/listings.json")
HISTORY_FILE  = Path("cache/price_history.json")
CACHE_TTL_SEC = 3600         # re-scrape every hour

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ─── HEADERS POOL (rotate to avoid detection) ────────────────────────────────
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
]

def get_headers(referer: str = "https://www.google.com") -> dict:
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

# ─── PRICE HISTORY (detect drops) ────────────────────────────────────────────

class PriceHistory:
    """Simple file-backed price history to detect drops between scrapes."""

    def __init__(self):
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._load()

    def _load(self):
        if HISTORY_FILE.exists():
            try:
                self._data = json.loads(HISTORY_FILE.read_text())
            except Exception:
                self._data = {}

    def _save(self):
        HISTORY_FILE.write_text(json.dumps(self._data, default=str))

    def record(self, listing_id: str, price_cr: float) -> Optional[float]:
        """
        Record current price. Returns previous price if a drop is detected,
        else None.
        """
        entry = self._data.get(listing_id)
        now_str = datetime.utcnow().isoformat()

        if entry is None:
            # First time seeing this listing
            self._data[listing_id] = {"price": price_cr, "seen_at": now_str, "history": []}
            self._save()
            return None

        prev_price = entry["price"]
        if price_cr < prev_price * (1 - DROP_THRESHOLD):
            # Price dropped!
            entry.setdefault("history", []).append(
                {"price": prev_price, "recorded_at": entry.get("seen_at", now_str)}
            )
            entry["price"] = price_cr
            entry["seen_at"] = now_str
            self._data[listing_id] = entry
            self._save()
            return prev_price

        # Price unchanged or increased — update silently
        entry["price"] = price_cr
        self._data[listing_id] = entry
        self._save()
        return None


price_history = PriceHistory()


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def parse_price_cr(text: str) -> Optional[float]:
    """
    Parse Indian real estate price strings to Crore (float).
    Handles: '₹ 12.5 Cr', '1.2 Cr', '85 Lac', '₹8500000', '8.5 Crore'
    """
    if not text:
        return None
    text = text.replace(",", "").replace("\u20b9", "").strip()

    # Match explicit Crore
    m = re.search(r"([\d.]+)\s*[Cc]r(?:ore)?", text)
    if m:
        return float(m.group(1))

    # Match Lacs / Lakhs
    m = re.search(r"([\d.]+)\s*[Ll]a[ck]", text)
    if m:
        return round(float(m.group(1)) / 100, 4)

    # Match bare number (assume rupees if > 500000)
    m = re.search(r"([\d]+)", text)
    if m:
        val = int(m.group(1))
        if val >= 10_000_000:     # ≥ 1Cr in paise
            return round(val / 10_000_000, 4)
        if val >= 100_000:        # ≥ 1 Lac
            return round(val / 10_000_000, 4)

    return None


def listing_id(source: str, url: str) -> str:
    return hashlib.md5(f"{source}:{url}".encode()).hexdigest()[:12]


async def safe_get(client: httpx.AsyncClient, url: str, **kwargs) -> Optional[httpx.Response]:
    """Fetch URL with retry + jitter. Returns None on failure."""
    for attempt in range(3):
        try:
            await asyncio.sleep(random.uniform(1.2, 3.0))
            resp = await client.get(url, timeout=20, **kwargs)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:
                log.warning("Rate-limited on %s, backing off…", url)
                await asyncio.sleep(10 + attempt * 5)
        except Exception as exc:
            log.warning("Attempt %d failed for %s: %s", attempt + 1, url, exc)
    return None


# ─── SCRAPER: MAGICBRICKS ────────────────────────────────────────────────────

MAGICBRICKS_URLS = [
    "https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Multistorey-Apartment,Builder-Floor-Apartment,Penthouse,Studio-Apartment&cityName=Mumbai&Locality=Worli,Bandra,Juhu,Lower-Parel,Malabar-Hill,Prabhadevi,BKC&budget=50000000-999999999",
    "https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Villa,Independent-House&cityName=Mumbai&budget=50000000-999999999",
]

async def scrape_magicbricks(client: httpx.AsyncClient) -> list[Listing]:
    listings = []
    for url in MAGICBRICKS_URLS:
        resp = await safe_get(client, url, headers=get_headers("https://www.magicbricks.com/"))
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "lxml")

        cards = soup.select("div.mb-srp__card") or soup.select("[data-propid]")
        log.info("MagicBricks: found %d cards at %s", len(cards), url[:80])

        for card in cards:
            try:
                name_el  = card.select_one(".mb-srp__card--title") or card.select_one("h2")
                price_el = card.select_one(".mb-srp__card__price--amount") or card.select_one("[data-price]")
                loc_el   = card.select_one(".mb-srp__card--locality") or card.select_one(".mb-srp__card--address")
                area_el  = card.select_one(".mb-srp__card--area") or card.select_one("[data-area]")
                link_el  = card.select_one("a[href]")
                type_el  = card.select_one(".mb-srp__card--badge") or card.select_one("[data-type]")
                bhk_el   = card.select_one(".mb-srp__card--bedroom") or card.select_one("[data-bedroom]")

                if not (name_el and price_el):
                    continue

                price_cr = parse_price_cr(price_el.get_text())
                if not price_cr or price_cr < MIN_PRICE_CR:
                    continue

                raw_url = link_el["href"] if link_el else url
                full_url = urljoin("https://www.magicbricks.com", raw_url)
                lid = listing_id("magicbricks", full_url)

                # Check price history for drop
                prev = price_history.record(lid, price_cr)
                if prev is None:
                    continue  # No drop detected

                drop_cr  = round(prev - price_cr, 4)
                drop_pct = round(drop_cr / prev * 100, 2)

                prop_type = "Apartment"
                if type_el:
                    t = type_el.get_text().lower()
                    if "villa" in t or "house" in t:  prop_type = "Villa"
                    elif "penthouse" in t:              prop_type = "Penthouse"
                    elif "duplex" in t:                 prop_type = "Duplex"

                bhk = None
                if bhk_el:
                    m = re.search(r"(\d)", bhk_el.get_text())
                    if m: bhk = int(m.group(1))

                sqft = None
                if area_el:
                    m = re.search(r"([\d,]+)", area_el.get_text().replace(",", ""))
                    if m: sqft = int(m.group(1))

                sub_parts = []
                if bhk:   sub_parts.append(f"{bhk} BHK")
                if sqft:  sub_parts.append(f"{sqft:,} sq ft")

                listings.append(Listing(
                    id=lid,
                    name=name_el.get_text(strip=True),
                    sub=" · ".join(sub_parts) if sub_parts else "Luxury Property",
                    location=loc_el.get_text(strip=True) if loc_el else "Mumbai",
                    city_area=loc_el.get_text(strip=True) if loc_el else "Mumbai",
                    type=prop_type,
                    price_cr=price_cr,
                    prev_price_cr=prev,
                    drop_cr=drop_cr,
                    drop_pct=drop_pct,
                    url=full_url,
                    source="magicbricks",
                    is_new=True,
                    scraped_at=datetime.utcnow(),
                    bedrooms=bhk,
                    area_sqft=sqft,
                ))
            except Exception as e:
                log.debug("MagicBricks card parse error: %s", e)

    return listings


# ─── SCRAPER: 99ACRES ────────────────────────────────────────────────────────

ACRES_URLS = [
    "https://www.99acres.com/buy-property-in-mumbai-ffid?budget=5000000-999999999&property_type=10,12,14,18",
    "https://www.99acres.com/buy-property-in-bandra-ffid?budget=5000000-999999999",
    "https://www.99acres.com/buy-property-in-worli-ffid?budget=5000000-999999999",
    "https://www.99acres.com/buy-property-in-juhu-ffid?budget=5000000-999999999",
]

async def scrape_99acres(client: httpx.AsyncClient) -> list[Listing]:
    listings = []
    for url in ACRES_URLS:
        resp = await safe_get(client, url, headers=get_headers("https://www.99acres.com/"))
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "lxml")

        # 99acres uses different class names depending on version
        cards = (
            soup.select("div[data-gtm='property_card']") or
            soup.select("div.propertyCard__container") or
            soup.select("article.srpTuple__wrapper") or
            soup.select("[class*='propertyCard']")
        )
        log.info("99acres: found %d cards at %s", len(cards), url[:80])

        for card in cards:
            try:
                name_el  = card.select_one("a[data-label='PROP_TITLE']") or card.select_one(".srpTuple__propertyName")
                price_el = card.select_one("[data-label='PRICE']") or card.select_one(".srpTuple__priceValWrap")
                loc_el   = card.select_one("[data-label='LOCALITY']") or card.select_one(".srpTuple__locationInfo")
                link_el  = card.select_one("a[href*='/property-']") or card.select_one("a[href]")
                area_el  = card.select_one("[data-label='AREA']") or card.select_one(".srpTuple__sizeInfo")

                if not (name_el and price_el):
                    continue

                price_cr = parse_price_cr(price_el.get_text())
                if not price_cr or price_cr < MIN_PRICE_CR:
                    continue

                raw_url = link_el["href"] if link_el else url
                full_url = urljoin("https://www.99acres.com", raw_url)
                lid = listing_id("99acres", full_url)

                prev = price_history.record(lid, price_cr)
                if prev is None:
                    continue

                drop_cr  = round(prev - price_cr, 4)
                drop_pct = round(drop_cr / prev * 100, 2)

                title = name_el.get_text(strip=True)
                prop_type = "Apartment"
                tl = title.lower()
                if "villa" in tl or "bungalow" in tl:  prop_type = "Villa"
                elif "penthouse" in tl:                  prop_type = "Penthouse"
                elif "duplex" in tl:                     prop_type = "Duplex"

                bhk = None
                m = re.search(r"(\d)\s*BHK", title, re.I)
                if m: bhk = int(m.group(1))

                sqft = None
                if area_el:
                    m = re.search(r"([\d,]+)", area_el.get_text().replace(",", ""))
                    if m: sqft = int(m.group(1))

                sub_parts = []
                if bhk:   sub_parts.append(f"{bhk} BHK")
                if sqft:  sub_parts.append(f"{sqft:,} sq ft")

                listings.append(Listing(
                    id=lid,
                    name=title,
                    sub=" · ".join(sub_parts) if sub_parts else "Luxury Property",
                    location=loc_el.get_text(strip=True) if loc_el else "Mumbai",
                    city_area=loc_el.get_text(strip=True) if loc_el else "Mumbai",
                    type=prop_type,
                    price_cr=price_cr,
                    prev_price_cr=prev,
                    drop_cr=drop_cr,
                    drop_pct=drop_pct,
                    url=full_url,
                    source="99acres",
                    is_new=True,
                    scraped_at=datetime.utcnow(),
                    bedrooms=bhk,
                    area_sqft=sqft,
                ))
            except Exception as e:
                log.debug("99acres card parse error: %s", e)

    return listings


# ─── SCRAPER: HOUSING.COM ────────────────────────────────────────────────────

HOUSING_URLS = [
    "https://housing.com/in/buy/mumbai/residential-real-estate?budget=50L-above&area=Bandra,Worli,Juhu,Prabhadevi,Lower+Parel",
    "https://housing.com/in/buy/mumbai/villa?budget=50L-above",
]

async def scrape_housing(client: httpx.AsyncClient) -> list[Listing]:
    listings = []
    for url in HOUSING_URLS:
        resp = await safe_get(client, url, headers=get_headers("https://housing.com/"))
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "lxml")

        cards = (
            soup.select("[data-testid='listing-card']") or
            soup.select("div[class*='propertyCard']") or
            soup.select("li[class*='listingCard']")
        )
        log.info("Housing.com: found %d cards at %s", len(cards), url[:80])

        for card in cards:
            try:
                name_el  = card.select_one("h2, h3, [class*='title']")
                price_el = card.select_one("[class*='price']")
                loc_el   = card.select_one("[class*='locality'], [class*='location']")
                link_el  = card.select_one("a[href]")

                if not (name_el and price_el):
                    continue

                price_cr = parse_price_cr(price_el.get_text())
                if not price_cr or price_cr < MIN_PRICE_CR:
                    continue

                raw_url = link_el["href"] if link_el else url
                full_url = urljoin("https://housing.com", raw_url)
                lid = listing_id("housing", full_url)

                prev = price_history.record(lid, price_cr)
                if prev is None:
                    continue

                drop_cr  = round(prev - price_cr, 4)
                drop_pct = round(drop_cr / prev * 100, 2)

                title = name_el.get_text(strip=True)
                prop_type = "Apartment"
                tl = title.lower()
                if "villa" in tl:          prop_type = "Villa"
                elif "penthouse" in tl:    prop_type = "Penthouse"
                elif "duplex" in tl:       prop_type = "Duplex"

                bhk = None
                m = re.search(r"(\d)\s*BHK", title, re.I)
                if m: bhk = int(m.group(1))

                sub_parts = []
                if bhk: sub_parts.append(f"{bhk} BHK")

                listings.append(Listing(
                    id=lid,
                    name=title,
                    sub=" · ".join(sub_parts) if sub_parts else "Luxury Property",
                    location=loc_el.get_text(strip=True) if loc_el else "Mumbai",
                    city_area=loc_el.get_text(strip=True) if loc_el else "Mumbai",
                    type=prop_type,
                    price_cr=price_cr,
                    prev_price_cr=prev,
                    drop_cr=drop_cr,
                    drop_pct=drop_pct,
                    url=full_url,
                    source="housing",
                    is_new=True,
                    scraped_at=datetime.utcnow(),
                    bedrooms=bhk,
                ))
            except Exception as e:
                log.debug("Housing.com card parse error: %s", e)

    return listings


# ─── SCRAPER: NOBROKER ───────────────────────────────────────────────────────

NOBROKER_URLS = [
    "https://www.nobroker.in/property/buy/flat-in-Mumbai?budget=5000000,999999999&amenities=sea_view",
    "https://www.nobroker.in/property/buy/villa-in-Mumbai?budget=5000000,999999999",
]

async def scrape_nobroker(client: httpx.AsyncClient) -> list[Listing]:
    """
    NoBroker loads content via JS. We hit their internal JSON API directly.
    Endpoint discovered via DevTools network panel.
    """
    listings = []
    api_base = "https://www.nobroker.in/api/v2/public/property/listing/search"

    searches = [
        {"city": "mumbai", "propertySubTypes": ["flat"], "budgetMin": 5000000, "budgetMax": 999999999, "localities": ["Bandra", "Worli", "Juhu", "Lower Parel", "Malabar Hill"]},
        {"city": "mumbai", "propertySubTypes": ["penthouse", "villa"], "budgetMin": 5000000, "budgetMax": 999999999},
    ]

    for params in searches:
        try:
            resp = await safe_get(
                client,
                api_base,
                headers={**get_headers("https://www.nobroker.in/"), "Accept": "application/json"},
            )
            if not resp:
                continue

            data = resp.json()
            props = data.get("data", {}).get("propertyList", []) or data.get("properties", [])
            log.info("NoBroker: found %d properties", len(props))

            for prop in props:
                try:
                    price_raw = prop.get("price") or prop.get("expectedPrice") or 0
                    price_cr  = round(int(price_raw) / 10_000_000, 4) if price_raw else None
                    if not price_cr or price_cr < MIN_PRICE_CR:
                        continue

                    lid = listing_id("nobroker", str(prop.get("id", prop.get("propertyId", ""))))

                    prev = price_history.record(lid, price_cr)
                    if prev is None:
                        continue

                    drop_cr  = round(prev - price_cr, 4)
                    drop_pct = round(drop_cr / prev * 100, 2)

                    bhk   = prop.get("bedroom") or prop.get("bedroomCount")
                    sqft  = prop.get("carpetArea") or prop.get("builtUpArea")
                    name  = prop.get("societyName") or prop.get("projectName") or "NoBroker Listing"
                    loc   = prop.get("localityName") or prop.get("locality") or "Mumbai"
                    ptype = (prop.get("propertySubType") or "flat").lower()

                    prop_type = "Apartment"
                    if "villa" in ptype:        prop_type = "Villa"
                    elif "penthouse" in ptype:  prop_type = "Penthouse"
                    elif "duplex" in ptype:     prop_type = "Duplex"

                    sub_parts = []
                    if bhk:   sub_parts.append(f"{bhk} BHK")
                    if sqft:  sub_parts.append(f"{sqft:,} sq ft")

                    url = f"https://www.nobroker.in/property/details/{prop.get('id', '')}"

                    listings.append(Listing(
                        id=lid,
                        name=name,
                        sub=" · ".join(sub_parts) if sub_parts else "Luxury Property",
                        location=loc,
                        city_area=loc,
                        type=prop_type,
                        price_cr=price_cr,
                        prev_price_cr=prev,
                        drop_cr=drop_cr,
                        drop_pct=drop_pct,
                        url=url,
                        source="nobroker",
                        is_new=True,
                        scraped_at=datetime.utcnow(),
                        bedrooms=bhk,
                        area_sqft=sqft,
                        image_url=prop.get("coverPhotoUrl"),
                    ))
                except Exception as e:
                    log.debug("NoBroker item parse error: %s", e)

        except Exception as e:
            log.warning("NoBroker scrape error: %s", e)

    return listings


# ─── MAIN SCRAPE ORCHESTRATOR ─────────────────────────────────────────────────

async def run_all_scrapers() -> list[Listing]:
    """Run all scrapers concurrently and return de-duped drop listings."""
    limits  = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    timeout = httpx.Timeout(30)

    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True) as client:
        results = await asyncio.gather(
            scrape_magicbricks(client),
            scrape_99acres(client),
            scrape_housing(client),
            scrape_nobroker(client),
            return_exceptions=True,
        )

    all_listings: list[Listing] = []
    for res in results:
        if isinstance(res, Exception):
            log.error("Scraper failed: %s", res)
        else:
            all_listings.extend(res)

    # Deduplicate by listing id
    seen: set[str] = set()
    unique = []
    for l in all_listings:
        if l.id not in seen:
            seen.add(l.id)
            unique.append(l)

    log.info("Scraped %d unique drop listings total", len(unique))
    return unique


# ─── CACHE HELPERS ────────────────────────────────────────────────────────────

def save_cache(listings: list[Listing]):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scraped_at": datetime.utcnow().isoformat(),
        "listings": [l.model_dump(mode="json") for l in listings],
    }
    CACHE_FILE.write_text(json.dumps(payload, default=str))
    log.info("Cache saved: %d listings", len(listings))


def load_cache() -> tuple[list[Listing], datetime | None]:
    """Returns (listings, scraped_at). scraped_at is None if cache is missing/expired."""
    if not CACHE_FILE.exists():
        return [], None
    try:
        data = json.loads(CACHE_FILE.read_text())
        scraped_at = datetime.fromisoformat(data["scraped_at"])
        if datetime.utcnow() - scraped_at > timedelta(seconds=CACHE_TTL_SEC):
            return [], None   # expired
        listings = [Listing(**l) for l in data["listings"]]
        log.info("Cache hit: %d listings (age: %ds)", len(listings),
                 (datetime.utcnow() - scraped_at).seconds)
        return listings, scraped_at
    except Exception as e:
        log.warning("Cache load error: %s", e)
        return [], None


async def get_listings(force_refresh: bool = False) -> list[Listing]:
    """Public entry point: return cached or freshly scraped listings."""
    if not force_refresh:
        cached, _ = load_cache()
        if cached:
            return cached

    listings = await run_all_scrapers()
    save_cache(listings)
    return listings


# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def main():
        print("Starting Mumbai luxury real estate scrape…")
        drops = await get_listings(force_refresh=True)
        if not drops:
            print("No drops found yet (may be first run — prices are being recorded for future comparison).")
        else:
            print(f"\nFound {len(drops)} price drops:\n")
            for l in sorted(drops, key=lambda x: x.drop_pct, reverse=True):
                print(f"  ↓{l.drop_pct:.1f}%  {l.name[:50]:<50}  ₹{l.price_cr}Cr  ({l.location})  [{l.source}]")

    asyncio.run(main())
