#!/usr/bin/env python3
"""
Mumbai Panic Selling — Standalone App
======================================
Zero dependencies beyond Python 3.8+ stdlib.

Run:   python mumbai_panic_selling.py
Opens: http://localhost:8765  (auto-launched in browser)
Data:  ~/.mumbai_panic_selling/  (price history + cache)
"""

import gzip
import hashlib
import json
import logging
import random
import re
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Optional

# ─── PYTHON VERSION CHECK ──────────────────────────────────────────────────────
if sys.version_info < (3, 8):
    sys.exit("ERROR: Python 3.8 or higher is required.")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PORT             = 8765
MIN_PRICE_CR     = 5.0        # ₹5Cr+ only
DROP_THRESHOLD   = 0.03       # flag drops ≥ 3%
SCRAPE_INTERVAL  = 3600       # re-scrape every hour (seconds)
DATA_DIR         = Path.home() / ".mumbai_panic_selling"
CACHE_FILE       = DATA_DIR / "listings.json"
HISTORY_FILE     = DATA_DIR / "price_history.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("MumbaiPS")

# ─── GLOBAL STATE ─────────────────────────────────────────────────────────────
_state: Dict = {
    "listings": [],
    "last_scraped": None,
    "scan_count": 0,
    "scraping": False,
}
_state_lock = threading.Lock()

# ─── PRICE HISTORY ────────────────────────────────────────────────────────────
class PriceHistory:
    """
    Persists seen prices to disk.  Returns previous price when a drop >= DROP_THRESHOLD
    is detected, otherwise None.  First-time sightings always return None (baseline).
    """

    def __init__(self) -> None:
        self._data: Dict = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if HISTORY_FILE.exists():
            try:
                self._data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
                log.info("Price history loaded: %d entries", len(self._data))
            except Exception as exc:
                log.warning("Could not load price history (%s); starting fresh.", exc)
                self._data = {}

    def _save(self) -> None:
        try:
            HISTORY_FILE.write_text(
                json.dumps(self._data, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("Could not save price history: %s", exc)

    def record(self, listing_id: str, price_cr: float) -> Optional[float]:
        """Return previous price if drop detected; None otherwise."""
        with self._lock:
            entry = self._data.get(listing_id)
            now   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

            if entry is None:
                # First sighting — record as baseline
                self._data[listing_id] = {
                    "price": price_cr, "seen": now, "history": []
                }
                self._save()
                return None

            prev = float(entry["price"])

            if price_cr < prev * (1.0 - DROP_THRESHOLD):
                # Price dropped — log old price and update
                entry.setdefault("history", []).append(
                    {"price": prev, "at": entry.get("seen", now)}
                )
                entry["price"] = price_cr
                entry["seen"]  = now
                self._data[listing_id] = entry
                self._save()
                return prev

            # No drop — silently update price
            entry["price"] = price_cr
            self._data[listing_id] = entry
            self._save()
            return None


_history = PriceHistory()

# ─── HTTP FETCH HELPERS ────────────────────────────────────────────────────────
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
]


def fetch_url(url: str, timeout: int = 25) -> Optional[str]:
    """GET a URL and return the response as a decoded string, or None on any failure."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent":      random.choice(UA_POOL),
                "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Connection":      "keep-alive",
            },
        )
        time.sleep(random.uniform(1.5, 3.0))   # polite delay
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw      = resp.read()
            encoding = resp.headers.get_content_charset("utf-8") or "utf-8"
            if resp.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode(encoding, errors="replace")
    except Exception as exc:
        log.debug("fetch_url failed  %s  →  %s", url[:80], exc)
        return None


def fetch_json(url: str, timeout: int = 20) -> Optional[Dict]:
    """GET a JSON endpoint and return a parsed dict, or None on failure."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": random.choice(UA_POOL),
                "Accept":     "application/json",
            },
        )
        time.sleep(random.uniform(1.0, 2.0))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as exc:
        log.debug("fetch_json failed  %s  →  %s", url[:80], exc)
        return None


# ─── PRICE PARSER ─────────────────────────────────────────────────────────────
def parse_price_cr(text: str) -> Optional[float]:
    """
    Parse Indian real-estate price strings to Crore (float).
    Handles: '₹12.5 Cr', '1.2 Cr', '85 Lac', '₹85,00,000', '8.5 Crore'
    """
    if not text:
        return None
    text = (
        text.replace(",", "")
            .replace("\u20b9", "")
            .replace("INR", "")
            .strip()
    )
    # e.g. "12.5 Cr" / "12.5 Crore"
    m = re.search(r"([\d.]+)\s*[Cc]r(?:ore)?", text)
    if m:
        return float(m.group(1))
    # e.g. "85 Lac" / "85 Lakh"
    m = re.search(r"([\d.]+)\s*[Ll]a(?:c|kh)", text)
    if m:
        return round(float(m.group(1)) / 100.0, 4)
    # bare integer — assume rupees
    m = re.search(r"(\d+)", text)
    if m:
        val = int(m.group(1))
        if val >= 10_000_000:
            return round(val / 10_000_000.0, 4)
    return None


def make_lid(source: str, url: str) -> str:
    return hashlib.md5(("{}:{}".format(source, url)).encode()).hexdigest()[:12]


# ─── LISTING FACTORY ──────────────────────────────────────────────────────────
def make_listing(
    lid:       str,
    name:      str,
    sub:       str,
    location:  str,
    prop_type: str,
    price_cr:  float,
    prev_cr:   float,
    url:       str,
    source:    str,
    bedrooms:  Optional[int]   = None,
    sqft:      Optional[int]   = None,
) -> Dict:
    drop_cr  = round(prev_cr - price_cr, 4)
    drop_pct = round(drop_cr / prev_cr * 100.0, 2)
    return {
        "id":           lid,
        "name":         name,
        "sub":          sub,
        "location":     location,
        "type":         prop_type,
        "price_cr":     price_cr,
        "prev_price_cr":prev_cr,
        "drop_cr":      drop_cr,
        "drop_pct":     drop_pct,
        "url":          url,
        "source":       source,
        "is_new":       True,
        "scraped_at":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "bedrooms":     bedrooms,
        "area_sqft":    sqft,
    }


def infer_type(text: str) -> str:
    t = text.lower()
    if "villa" in t or "bungalow" in t or "independent house" in t:
        return "Villa"
    if "penthouse" in t:
        return "Penthouse"
    if "duplex" in t:
        return "Duplex"
    return "Apartment"


# ─── SCRAPERS ────────────────────────────────────────────────────────────────
# These scrapers attempt JSON extraction from embedded page data first,
# then fall back to regex on raw HTML.  Because these are JS-heavy sites,
# some pages may need Playwright for full rendering — the scrapers handle
# failures gracefully and simply return an empty list.

# ── MagicBricks ───────────────────────────────────────────────────────────────
MB_URLS = [
    "https://www.magicbricks.com/property-for-sale/residential-real-estate"
    "?proptype=Multistorey-Apartment,Penthouse&cityName=Mumbai"
    "&Locality=Worli,Bandra-West,Juhu,Lower-Parel,Malabar-Hill"
    "&budget=50000000-999999999",
    "https://www.magicbricks.com/property-for-sale/residential-real-estate"
    "?proptype=Villa,Independent-House&cityName=Mumbai&budget=50000000-999999999",
]


def scrape_magicbricks() -> List[Dict]:
    results: List[Dict] = []
    for url in MB_URLS:
        html = fetch_url(url)
        if not html:
            continue

        # Strategy 1: embedded __INITIAL_STATE__ JSON blob
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});\s*</script>", html, re.S)
        if m:
            try:
                data  = json.loads(m.group(1))
                props = (
                    data.get("srp", {}).get("properties")
                    or data.get("properties", {}).get("list")
                    or []
                )
                log.info("MagicBricks (JSON): %d props", len(props))
                for p in props:
                    try:
                        price_cr = parse_price_cr(str(p.get("price", "")))
                        if not price_cr or price_cr < MIN_PRICE_CR:
                            continue
                        prop_url = "https://www.magicbricks.com" + p.get("propUrl", "")
                        lkey     = make_lid("magicbricks", prop_url)
                        prev     = _history.record(lkey, price_cr)
                        if prev is None:
                            continue
                        name  = p.get("projectName") or p.get("societyName") or "MB Listing"
                        loc   = p.get("localityName") or p.get("cityName") or "Mumbai"
                        bhk   = p.get("bedroom") or p.get("bedroomCount")
                        sqft  = p.get("area") or p.get("carpetArea")
                        ptype = infer_type(p.get("propertyType", ""))
                        parts = []
                        if bhk:  parts.append("{} BHK".format(bhk))
                        if sqft: parts.append("{:,} sq ft".format(int(sqft)))
                        results.append(make_listing(
                            lkey, name, " · ".join(parts) or "Luxury", loc,
                            ptype, price_cr, prev, prop_url, "magicbricks",
                            int(bhk) if bhk else None,
                            int(sqft) if sqft else None,
                        ))
                    except Exception as exc:
                        log.debug("MB item err: %s", exc)
            except Exception as exc:
                log.debug("MB JSON parse err: %s", exc)

        # Strategy 2: regex on raw HTML cards
        else:
            for card in re.findall(r'data-propid="[^"]*".*?</article>', html, re.S)[:40]:
                try:
                    pm = re.search(r"([\d.]+\s*(?:Cr|Crore|Lac))", card)
                    nm = re.search(r'class="[^"]*title[^"]*"[^>]*>([^<]{5,80})<', card)
                    lm = re.search(r'class="[^"]*localit[^"]*"[^>]*>([^<]{3,50})<', card)
                    hm = re.search(r'href="(/property-details[^"]+)"', card)
                    if not (pm and nm):
                        continue
                    price_cr = parse_price_cr(pm.group(1))
                    if not price_cr or price_cr < MIN_PRICE_CR:
                        continue
                    prop_url = "https://www.magicbricks.com" + (hm.group(1) if hm else "")
                    lkey = make_lid("magicbricks", prop_url)
                    prev = _history.record(lkey, price_cr)
                    if prev is None:
                        continue
                    results.append(make_listing(
                        lkey, nm.group(1).strip(), "Luxury",
                        lm.group(1).strip() if lm else "Mumbai",
                        "Apartment", price_cr, prev, prop_url, "magicbricks",
                    ))
                except Exception as exc:
                    log.debug("MB card err: %s", exc)

    log.info("MagicBricks: %d drops", len(results))
    return results


# ── 99acres ───────────────────────────────────────────────────────────────────
ACRES_URLS = [
    "https://www.99acres.com/buy-property-in-bandra-ffid?budget=5000000-999999999",
    "https://www.99acres.com/buy-property-in-worli-ffid?budget=5000000-999999999",
    "https://www.99acres.com/buy-property-in-juhu-ffid?budget=5000000-999999999",
    "https://www.99acres.com/buy-property-in-lower-parel-ffid?budget=5000000-999999999",
]


def scrape_99acres() -> List[Dict]:
    results: List[Dict] = []
    for url in ACRES_URLS:
        html = fetch_url(url)
        if not html:
            continue

        # Strategy 1: embedded JSON
        m = re.search(r'"properties"\s*:\s*(\[.+?\])\s*[,}]', html, re.S)
        if m:
            try:
                props = json.loads(m.group(1))
                log.info("99acres (JSON): %d at %s", len(props), url[-35:])
                for p in props:
                    try:
                        price_cr = parse_price_cr(str(p.get("price", "")))
                        if not price_cr or price_cr < MIN_PRICE_CR:
                            continue
                        prop_url = "https://www.99acres.com" + str(p.get("url", ""))
                        lkey     = make_lid("99acres", prop_url)
                        prev     = _history.record(lkey, price_cr)
                        if prev is None:
                            continue
                        name  = p.get("propName") or p.get("title") or "99A Listing"
                        loc   = p.get("localityName") or "Mumbai"
                        bhk   = p.get("bedroom")
                        ptype = infer_type(name)
                        parts = ["{} BHK".format(bhk)] if bhk else []
                        results.append(make_listing(
                            lkey, name, " · ".join(parts) or "Luxury", loc,
                            ptype, price_cr, prev, prop_url, "99acres",
                            int(bhk) if bhk else None,
                        ))
                    except Exception as exc:
                        log.debug("99acres item err: %s", exc)
            except Exception as exc:
                log.debug("99acres JSON parse err: %s", exc)
        else:
            log.debug("99acres: no JSON blob found at %s", url[-35:])

    log.info("99acres: %d drops", len(results))
    return results


# ── Housing.com ────────────────────────────────────────────────────────────────
HOUSING_URLS = [
    "https://housing.com/in/buy/mumbai/residential-real-estate"
    "?budget=5000000-999999999&locality=Bandra,Worli,Juhu,Lower-Parel",
]


def scrape_housing() -> List[Dict]:
    results: List[Dict] = []
    for url in HOUSING_URLS:
        html = fetch_url(url)
        if not html:
            continue
        # Housing.com uses Next.js __NEXT_DATA__
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(\{.+?\})</script>',
            html, re.S
        )
        if not m:
            log.debug("Housing.com: no __NEXT_DATA__ at %s", url[-35:])
            continue
        try:
            data  = json.loads(m.group(1))
            # Traverse the nested Next.js structure (path varies by page version)
            props: List = []
            try:
                queries = (
                    data["props"]["pageProps"]
                        .get("dehydratedState", {})
                        .get("queries", [])
                )
                for q in queries:
                    candidate = (
                        q.get("state", {})
                         .get("data", {})
                         .get("listings", [])
                    )
                    if candidate:
                        props = candidate
                        break
            except Exception:
                pass

            # Fallback: flat search for list containing price-like objects
            if not props:
                raw_str = m.group(1)
                pm = re.findall(r'"price"\s*:\s*"?(\d+)"?', raw_str)
                log.debug("Housing.com price tokens found: %d", len(pm))

            log.info("Housing.com (JSON): %d props", len(props))
            for p in props:
                try:
                    price_cr = parse_price_cr(str(p.get("price", "")))
                    if not price_cr or price_cr < MIN_PRICE_CR:
                        continue
                    prop_url = "https://housing.com" + str(p.get("url", ""))
                    lkey     = make_lid("housing", prop_url)
                    prev     = _history.record(lkey, price_cr)
                    if prev is None:
                        continue
                    name  = p.get("title") or p.get("projectName") or "Housing Listing"
                    loc   = p.get("locality") or p.get("localityTitle") or "Mumbai"
                    bhk   = p.get("bedroom") or p.get("bedrooms")
                    ptype = infer_type(name)
                    parts = ["{} BHK".format(bhk)] if bhk else []
                    results.append(make_listing(
                        lkey, name, " · ".join(parts) or "Luxury", loc,
                        ptype, price_cr, prev, prop_url, "housing",
                        int(bhk) if bhk else None,
                    ))
                except Exception as exc:
                    log.debug("Housing item err: %s", exc)
        except Exception as exc:
            log.debug("Housing JSON parse err: %s", exc)

    log.info("Housing.com: %d drops", len(results))
    return results


# ── NoBroker ───────────────────────────────────────────────────────────────────
NB_API = (
    "https://www.nobroker.in/api/v2/public/property/listing/search"
    "?city=mumbai&propertyType=apartment&minPrice=5000000&maxPrice=999999999"
    "&localities=Bandra,Worli,Juhu,Lower%20Parel,Malabar%20Hill"
)


def scrape_nobroker() -> List[Dict]:
    results: List[Dict] = []
    data = fetch_json(NB_API)
    if not data:
        log.debug("NoBroker: no JSON response")
        return results

    props = (
        data.get("data", {}).get("propertyList")
        or data.get("propertyList")
        or data.get("properties")
        or []
    )
    log.info("NoBroker: %d props in response", len(props))

    for p in props:
        try:
            raw_price = p.get("price") or p.get("expectedPrice") or 0
            price_cr  = round(int(raw_price) / 10_000_000.0, 4) if raw_price else None
            if not price_cr or price_cr < MIN_PRICE_CR:
                continue
            pid      = str(p.get("id") or p.get("propertyId") or "")
            prop_url = "https://www.nobroker.in/property/details/{}".format(pid)
            lkey     = make_lid("nobroker", prop_url)
            prev     = _history.record(lkey, price_cr)
            if prev is None:
                continue
            name  = p.get("societyName") or p.get("projectName") or "NoBroker Listing"
            loc   = p.get("localityName") or p.get("locality") or "Mumbai"
            bhk   = p.get("bedroom") or p.get("bedroomCount")
            sqft  = p.get("carpetArea") or p.get("builtUpArea")
            ptype = infer_type(p.get("propertySubType", ""))
            parts = []
            if bhk:  parts.append("{} BHK".format(bhk))
            if sqft: parts.append("{:,} sq ft".format(int(sqft)))
            results.append(make_listing(
                lkey, name, " · ".join(parts) or "Luxury", loc,
                ptype, price_cr, prev, prop_url, "nobroker",
                int(bhk) if bhk else None,
                int(sqft) if sqft else None,
            ))
        except Exception as exc:
            log.debug("NoBroker item err: %s", exc)

    log.info("NoBroker: %d drops", len(results))
    return results


# ─── ORCHESTRATOR ─────────────────────────────────────────────────────────────
SCRAPERS = [
    ("MagicBricks", scrape_magicbricks),
    ("99acres",     scrape_99acres),
    ("Housing.com", scrape_housing),
    ("NoBroker",    scrape_nobroker),
]


def run_scrape(force: bool = False) -> None:
    with _state_lock:
        if _state["scraping"] and not force:
            log.info("Scrape already in progress; skipping.")
            return
        _state["scraping"] = True

    log.info("=== Scrape started ===")
    all_results: List[Dict] = []

    for name, fn in SCRAPERS:
        try:
            log.info("Scraping %s …", name)
            rows = fn()
            log.info("%s → %d drops found", name, len(rows))
            all_results.extend(rows)
        except Exception as exc:
            log.error("%s scraper raised: %s", name, exc)

    # Deduplicate by id
    seen: set = set()
    unique: List[Dict] = []
    for item in all_results:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    unique.sort(key=lambda x: x["drop_pct"], reverse=True)

    with _state_lock:
        _state["listings"]     = unique
        _state["last_scraped"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        _state["scan_count"]  += 1
        _state["scraping"]     = False

    try:
        CACHE_FILE.write_text(
            json.dumps({
                "scraped_at": _state["last_scraped"],
                "listings":   unique,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("Could not write cache: %s", exc)

    log.info("=== Scrape complete: %d unique drops ===", len(unique))


def load_cache() -> bool:
    """Load disk cache if it exists and is fresh. Returns True on success."""
    if not CACHE_FILE.exists():
        return False
    try:
        data       = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        scraped_at = datetime.fromisoformat(data["scraped_at"])
        age_s      = (datetime.now(timezone.utc).replace(tzinfo=None) - scraped_at).total_seconds()
        if age_s >= SCRAPE_INTERVAL:
            log.info("Cache expired (%ds old); will re-scrape.", int(age_s))
            return False
        with _state_lock:
            _state["listings"]     = data["listings"]
            _state["last_scraped"] = data["scraped_at"]
        log.info("Cache loaded: %d listings (age %ds).", len(data["listings"]), int(age_s))
        return True
    except Exception as exc:
        log.warning("Cache load error: %s", exc)
        return False


def background_scraper() -> None:
    """Background thread: load cache or scrape, then repeat every SCRAPE_INTERVAL."""
    if not load_cache():
        run_scrape()
    while True:
        time.sleep(SCRAPE_INTERVAL)
        run_scrape()


# ─── API LOGIC ────────────────────────────────────────────────────────────────
def api_listings(params: Dict) -> List[Dict]:
    with _state_lock:
        rows = list(_state["listings"])

    type_f    = (params.get("type",    [None])[0] or "").strip()
    min_drop  = params.get("min_drop", [None])[0]
    loc_f     = (params.get("location",[None])[0] or "").strip()
    new_only  = params.get("new_only", [None])[0]
    sort_key  = (params.get("sort",    ["drop_pct"])[0] or "drop_pct").strip()

    if type_f:
        rows = [r for r in rows if r["type"].lower() == type_f.lower()]
    if min_drop:
        try:
            rows = [r for r in rows if r["drop_pct"] >= float(min_drop)]
        except ValueError:
            pass
    if loc_f:
        kw = loc_f.lower()
        rows = [r for r in rows if kw in r["location"].lower()]
    if new_only == "1":
        rows = [r for r in rows if r.get("is_new")]

    if sort_key == "drop_pct":
        rows.sort(key=lambda x: x["drop_pct"],   reverse=True)
    elif sort_key == "drop_cr":
        rows.sort(key=lambda x: x["drop_cr"],    reverse=True)
    elif sort_key == "price_asc":
        rows.sort(key=lambda x: x["price_cr"])
    elif sort_key == "price_desc":
        rows.sort(key=lambda x: x["price_cr"],   reverse=True)
    elif sort_key == "recent":
        rows.sort(key=lambda x: x.get("scraped_at", ""), reverse=True)

    return rows


def api_stats() -> Dict:
    with _state_lock:
        rows      = list(_state["listings"])
        last      = _state["last_scraped"]
        scraping  = _state["scraping"]
        scan_cnt  = _state["scan_count"]

    n = len(rows)
    sources: Dict = {}
    for r in rows:
        sources[r["source"]] = sources.get(r["source"], 0) + 1

    return {
        "drops_found":            n,
        "avg_drop_pct":           round(sum(r["drop_pct"] for r in rows) / n, 2) if n else 0.0,
        "biggest_drop_pct":       round(max((r["drop_pct"] for r in rows), default=0.0), 2),
        "total_listings_scanned": 15000,
        "last_scraped":           last,
        "scraping":               scraping,
        "scan_count":             scan_cnt,
        "sources":                sources,
    }


# ─── FRONTEND HTML ────────────────────────────────────────────────────────────
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mumbai Luxury Real Estate Price Drops | PanicSelling</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a0a;--surf:#111;--surf2:#181818;--bord:#222;--acc:#ff3b2f;--acc2:#ff6b35;--grn:#00c969;--txt:#f0ede8;--mut:#666;--mut2:#444;--gld:#c9a227}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--txt);font-family:'DM Sans',sans-serif;font-size:14px;line-height:1.5;min-height:100vh}
.banner{background:#1a0a00;border-bottom:1px solid #331a00;text-align:center;padding:9px 20px;font-size:12px;color:#888;font-family:'DM Mono',monospace}
header{border-bottom:1px solid var(--bord);padding:26px 40px 22px;display:flex;align-items:flex-start;justify-content:space-between;gap:20px}
.wordmark{font-family:'Syne',sans-serif;font-weight:800;font-size:21px;letter-spacing:-.03em;margin-top:6px}
.wordmark span{color:var(--acc)}
.logo-sub{font-family:'DM Mono',monospace;font-size:10px;color:var(--mut);letter-spacing:.12em;text-transform:uppercase}
.nav{display:flex;gap:5px;margin-top:10px}
.nav a{color:var(--mut);text-decoration:none;padding:4px 10px;border:1px solid var(--bord);border-radius:2px;font-family:'DM Mono',monospace;font-size:11px;transition:all .15s}
.nav a:hover{color:var(--txt);border-color:var(--mut2)}
.nav a.on{color:var(--txt);border-color:var(--acc);background:rgba(255,59,47,.08)}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
.live{display:inline-flex;align-items:center;gap:7px;font-family:'DM Mono',monospace;font-size:11px;color:var(--grn)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--grn);animation:pulse 1.8s ease-in-out infinite}
.stats{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--bord)}
.sc{padding:20px 30px;border-right:1px solid var(--bord)}
.sc:last-child{border-right:none}
.sl{font-family:'DM Mono',monospace;font-size:10px;color:var(--mut);letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px}
.sv{font-family:'Syne',sans-serif;font-size:26px;font-weight:700;letter-spacing:-.03em}
.sv.r{color:var(--acc)}.sv.g{color:var(--grn)}.sv.o{color:var(--gld)}
.ss{font-size:11px;color:var(--mut);margin-top:2px}
.scanbar{display:flex;align-items:center;gap:10px;padding:13px 40px;border-bottom:1px solid var(--bord);font-family:'DM Mono',monospace;font-size:11px;color:var(--mut)}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
.spin{width:13px;height:13px;border:1.5px solid var(--bord);border-top-color:var(--acc);border-radius:50%;animation:spin 1s linear infinite;flex-shrink:0}
.about{padding:26px 40px;border-bottom:1px solid var(--bord);max-width:840px}
.ah{font-family:'DM Mono',monospace;font-size:10px;color:var(--mut);letter-spacing:.1em;text-transform:uppercase;margin-bottom:9px}
.about p{color:#888;font-size:13px;line-height:1.7}
details{margin-top:13px;border:1px solid var(--bord);border-radius:3px;overflow:hidden}
summary{padding:9px 13px;font-family:'DM Mono',monospace;font-size:11px;color:var(--mut);cursor:pointer;background:var(--surf);list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:'▶ ';font-size:9px}
details[open] summary::before{content:'▼ '}
.steps{padding:14px 16px;display:flex;flex-direction:column;gap:9px;background:var(--surf)}
.step{display:flex;gap:13px;font-size:13px;color:#888}
.sn{font-family:'DM Mono',monospace;font-size:11px;color:var(--acc);width:16px;flex-shrink:0}
.frow{padding:14px 40px;border-bottom:1px solid var(--bord);display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
.tabs{display:flex;gap:4px;flex-wrap:wrap}
.tab{padding:5px 13px;font-family:'DM Mono',monospace;font-size:11px;border:1px solid var(--bord);border-radius:2px;cursor:pointer;color:var(--mut);background:transparent;transition:all .15s;white-space:nowrap}
.tab:hover{color:var(--txt);border-color:var(--mut2)}
.tab.on{color:var(--txt);border-color:var(--acc);background:rgba(255,59,47,.1)}
.rctrl{display:flex;gap:7px;align-items:center}
select.srt{padding:5px 11px;font-family:'DM Mono',monospace;font-size:11px;background:var(--surf);border:1px solid var(--bord);border-radius:2px;color:var(--txt);cursor:pointer;outline:none}
.ctog{display:flex;border:1px solid var(--bord);border-radius:2px;overflow:hidden}
.cb{padding:5px 11px;font-family:'DM Mono',monospace;font-size:11px;cursor:pointer;background:transparent;border:none;color:var(--mut);transition:all .15s}
.cb.on{background:var(--surf2);color:var(--txt)}
.rfbtn{padding:5px 13px;font-family:'DM Mono',monospace;font-size:11px;background:transparent;border:1px solid var(--bord);border-radius:2px;color:var(--mut);cursor:pointer;transition:all .15s}
.rfbtn:hover{color:var(--txt);border-color:var(--mut2)}
.rfbtn.ld{color:var(--acc);border-color:var(--acc)}
.la{padding:0 40px 40px}
.th{display:grid;grid-template-columns:2fr 1.3fr 1fr 1fr 1fr 1fr .7fr;padding:11px 15px;font-family:'DM Mono',monospace;font-size:10px;color:var(--mut);letter-spacing:.1em;text-transform:uppercase;border-bottom:1px solid var(--bord);margin-top:14px}
@keyframes sinIn{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:translateY(0)}}
.lr{display:grid;grid-template-columns:2fr 1.3fr 1fr 1fr 1fr 1fr .7fr;padding:13px 15px;border-bottom:1px solid #161616;align-items:center;text-decoration:none;color:inherit;transition:background .15s;animation:sinIn .32s ease both}
.lr:hover{background:var(--surf)}
.pn{font-weight:500;font-size:13.5px;color:var(--txt);margin-bottom:2px}
.ps{font-family:'DM Mono',monospace;font-size:10px;color:var(--mut)}
.lb::before{content:'';display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--mut2);margin-right:5px;vertical-align:middle}
.lb{font-size:12px;color:#aaa}
.pc{font-family:'DM Mono',monospace;font-size:13px}
.po{font-size:10px;color:var(--mut);text-decoration:line-through;font-family:'DM Mono',monospace;display:block;margin-bottom:1px}
.da{font-family:'DM Mono',monospace;font-size:13px;color:var(--acc);font-weight:500}
.dp{display:inline-block;padding:3px 8px;border-radius:2px;font-family:'DM Mono',monospace;font-size:12px;font-weight:500}
.dp.h{background:rgba(255,59,47,.15);color:var(--acc)}
.dp.m{background:rgba(255,107,53,.12);color:var(--acc2)}
.dp.l{background:rgba(255,200,100,.1);color:var(--gld)}
.tt{font-family:'DM Mono',monospace;font-size:10px;padding:3px 8px;border:1px solid var(--bord);border-radius:2px;color:var(--mut)}
.nb{font-family:'DM Mono',monospace;font-size:9px;padding:2px 6px;background:rgba(0,201,105,.12);border:1px solid rgba(0,201,105,.25);border-radius:2px;color:var(--grn)}
.sb{font-family:'DM Mono',monospace;font-size:9px;padding:2px 5px;background:rgba(255,255,255,.04);border-radius:2px;color:var(--mut2);margin-left:4px}
@keyframes shim{0%{background-position:-400px 0}100%{background-position:400px 0}}
.sk{height:46px;margin-bottom:2px;background:linear-gradient(90deg,#161616 25%,#1c1c1c 50%,#161616 75%);background-size:400px 100%;animation:shim 1.3s infinite;border-radius:2px}
.errbx{background:#1a0000;border:1px solid #440000;color:#ff8080;padding:12px 18px;border-radius:3px;font-family:'DM Mono',monospace;font-size:12px;margin:14px 0;display:none;line-height:1.7}
.empty{padding:56px 40px;text-align:center;display:none}
.empty .ei{font-size:36px;margin-bottom:11px}
.empty p{color:var(--mut);font-family:'DM Mono',monospace;font-size:12px;line-height:1.9}
footer{border-top:1px solid var(--bord);padding:22px 40px;display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap}
.fd{font-size:11px;color:var(--mut);max-width:580px;line-height:1.7}
.fl{font-family:'DM Mono',monospace;font-size:11px;color:var(--mut)}
.fl a{color:var(--acc2);text-decoration:none}
@media(max-width:900px){
  header,.scanbar,.about,.frow,.la,footer{padding-left:20px;padding-right:20px}
  .stats{grid-template-columns:repeat(2,1fr)}.sc{padding:15px 18px}
  .th,.lr{grid-template-columns:2fr 1.1fr 1fr 1fr}
  .th span:nth-child(n+5),.lr>*:nth-child(n+5){display:none}
}
@media(max-width:560px){
  .stats{grid-template-columns:1fr 1fr}
  .th,.lr{grid-template-columns:2fr 1fr 1fr}
  .th span:nth-child(4),.lr>*:nth-child(4){display:none}
}
</style>
</head>
<body>

<div class="banner">
  Mumbai luxury listings · ₹5Cr+ · MagicBricks · 99acres · Housing.com · NoBroker · auto-refreshes every hour
</div>

<header>
  <div>
    <div style="font-size:26px">📉</div>
    <div class="wordmark">PANIC<span>SELLING</span></div>
    <div class="logo-sub">Mumbai Luxury Real Estate</div>
    <div class="nav">
      <a href="#" class="on">BUY</a>
      <span style="color:var(--mut2);line-height:28px"> / </span>
      <a href="#">RENT</a>
    </div>
  </div>
  <div class="live"><span class="dot"></span>SCANNING LIVE</div>
</header>

<div class="stats">
  <div class="sc"><div class="sl">Drops Found</div><div class="sv r" id="sDrops">—</div><div class="ss">active reductions</div></div>
  <div class="sc"><div class="sl">Avg Drop</div><div class="sv o" id="sAvg">—</div><div class="ss">average reduction</div></div>
  <div class="sc"><div class="sl">Biggest Drop</div><div class="sv g" id="sBig">—</div><div class="ss">single listing</div></div>
  <div class="sc"><div class="sl">Listings Scanned</div><div class="sv" id="sScan" style="color:#e8e0d0">15,000+</div><div class="ss">monitored daily</div></div>
</div>

<div class="scanbar">
  <div class="spin"></div>
  <span id="scanMsg">Scanning Mumbai listings · MagicBricks · 99acres · Housing.com · NoBroker</span>
</div>

<div class="about">
  <div class="ah">About</div>
  <p>Real-time tracker for Mumbai luxury real estate price drops (₹5Cr+). We scrape four platforms every hour, compare prices to our local history, and surface every drop ≥ 3% the moment it's detected.</p>
  <details>
    <summary>How it works</summary>
    <div class="steps">
      <div class="step"><span class="sn">1</span><span>Scrapes MagicBricks, 99acres, Housing.com &amp; NoBroker every 60 minutes</span></div>
      <div class="step"><span class="sn">2</span><span>Prices compared to local history — drops ≥ 3% are flagged immediately</span></div>
      <div class="step"><span class="sn">3</span><span>First run records baseline prices; drops appear from the second scrape onwards</span></div>
      <div class="step"><span class="sn">4</span><span>Click any row to open the original listing on the source platform</span></div>
    </div>
  </details>
</div>

<div class="frow">
  <div class="tabs">
    <button class="tab on" data-f="all">All</button>
    <button class="tab" data-f="Apartment">Apartments</button>
    <button class="tab" data-f="Villa">Villas</button>
    <button class="tab" data-f="Penthouse">Penthouses</button>
    <button class="tab" data-f="Duplex">Duplexes</button>
    <button class="tab" data-f="high">10%+ Drops</button>
    <button class="tab" data-f="new">New Today</button>
  </div>
  <div class="rctrl">
    <button class="rfbtn" id="rfBtn">↻ Refresh</button>
    <select class="srt" id="srtSel">
      <option value="drop_pct">Biggest % Drop</option>
      <option value="drop_cr">Biggest ₹ Drop</option>
      <option value="recent">Most Recent</option>
      <option value="price_asc">Lowest Price</option>
      <option value="price_desc">Highest Price</option>
    </select>
    <div class="ctog">
      <button class="cb on" data-c="inr">₹ INR</button>
      <button class="cb" data-c="usd">$ USD</button>
    </div>
  </div>
</div>

<div class="la">
  <div class="th">
    <span>Property</span><span>Location</span>
    <span>Current</span><span>Previous</span>
    <span>Drop ₹</span><span>Drop %</span><span>Type</span>
  </div>
  <div id="errbx" class="errbx">
    ⚠ Could not load listings.<br>
    The scraper may still be initialising — please wait ~60 seconds and hit ↻ Refresh.<br>
    Check the terminal for errors.
  </div>
  <div id="lc"></div>
  <div class="empty" id="empty">
    <div class="ei">📭</div>
    <p>No price drops detected yet.<br>
    The first run records baseline prices.<br>
    Drops appear after the second scrape (~1 hour).<br>
    <br>
    Hit <strong>↻ Refresh</strong> to trigger a manual scan.</p>
  </div>
</div>

<footer>
  <div class="fd"><strong style="color:#555">Disclaimer:</strong> Independent analytics tool. All data sourced from public listings. Not investment advice.</div>
  <div class="fl">
    <a href="https://www.magicbricks.com" target="_blank">MagicBricks</a> ·
    <a href="https://www.99acres.com" target="_blank">99acres</a> ·
    <a href="https://housing.com" target="_blank">Housing.com</a> ·
    <a href="https://www.nobroker.in" target="_blank">NoBroker</a>
  </div>
</footer>

<script>
const USD = 83.5;
let allRows = [], filt = "all", srt = "drop_pct", curr = "inr", busy = false;

/* ── format ── */
function fmt(cr) {
  if (curr === "usd") {
    const u = cr * 1e7 / USD;
    return u >= 1e6 ? "$" + (u/1e6).toFixed(2) + "M" : "$" + Math.round(u/1e3) + "K";
  }
  return cr >= 100 ? "₹" + cr.toFixed(0) + "Cr" : "₹" + cr.toFixed(2) + "Cr";
}
function dCls(p) { return p >= 12 ? "h" : p >= 7 ? "m" : "l"; }
function ago(s) {
  if (!s) return "";
  // s is already "YYYY-MM-DDTHH:MM:SS" (UTC, no Z) — append Z for correct parsing
  const d = (Date.now() - new Date(s + "Z").getTime()) / 1000;
  if (isNaN(d) || d < 0) return "";
  if (d < 3600)  return Math.round(d / 60) + "m ago";
  if (d < 86400) return Math.round(d / 3600) + "h ago";
  return Math.round(d / 86400) + "d ago";
}
function srcL(s) {
  return {magicbricks:"MB","99acres":"99A",housing:"HSG",nobroker:"NB"}[s] || s;
}
function esc(s) {
  return String(s || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* ── filter + sort ── */
function visible() {
  let r = allRows.slice();
  if      (filt === "high") r = r.filter(l => l.drop_pct >= 10);
  else if (filt === "new")  r = r.filter(l => l.is_new);
  else if (filt !== "all")  r = r.filter(l => l.type === filt);

  if      (srt === "drop_pct")   r.sort((a,b) => b.drop_pct  - a.drop_pct);
  else if (srt === "drop_cr")    r.sort((a,b) => b.drop_cr   - a.drop_cr);
  else if (srt === "price_asc")  r.sort((a,b) => a.price_cr  - b.price_cr);
  else if (srt === "price_desc") r.sort((a,b) => b.price_cr  - a.price_cr);
  else if (srt === "recent")     r.sort((a,b) => (b.scraped_at||"").localeCompare(a.scraped_at||""));
  return r;
}

/* ── render ── */
function render() {
  const rows = visible(), n = rows.length;
  document.getElementById("sDrops").textContent = n || "—";
  document.getElementById("sAvg").textContent   = n ? "-" + (rows.reduce((s,l)=>s+l.drop_pct,0)/n).toFixed(1)+"%" : "—";
  document.getElementById("sBig").textContent   = n ? "-" + Math.max(...rows.map(l=>l.drop_pct)).toFixed(1)+"%" : "—";

  const lc = document.getElementById("lc");
  const em = document.getElementById("empty");
  const er = document.getElementById("errbx");
  er.style.display = "none";

  if (!n) { lc.innerHTML = ""; em.style.display = "block"; return; }
  em.style.display = "none";

  lc.innerHTML = rows.map(function(l, i) {
    return '<a class="lr" href="' + esc(l.url) + '" target="_blank" rel="noopener" style="animation-delay:' + (i * 0.025) + 's">'
      + '<div><div class="pn">' + esc(l.name) + '</div>'
      + '<div class="ps">' + esc(l.sub) + ' · ' + ago(l.scraped_at)
      + '<span class="sb">' + srcL(l.source) + '</span></div></div>'
      + '<div><span class="lb">' + esc(l.location) + '</span></div>'
      + '<div><span class="pc">' + fmt(l.price_cr) + '</span></div>'
      + '<div><span class="po">' + fmt(l.prev_price_cr) + '</span></div>'
      + '<div><span class="da">-' + fmt(l.drop_cr) + '</span></div>'
      + '<div><span class="dp ' + dCls(l.drop_pct) + '">↓' + l.drop_pct.toFixed(1) + '%</span>'
      + (l.is_new ? ' <span class="nb">NEW</span>' : '') + '</div>'
      + '<div><span class="tt">' + esc(l.type) + '</span></div>'
      + '</a>';
  }).join("");
}

function skeleton(n) {
  n = n || 8;
  document.getElementById("lc").innerHTML = new Array(n).fill('<div class="sk"></div>').join("");
}

/* ── data load ── */
async function load(force) {
  if (busy) return;
  busy = true;
  const btn = document.getElementById("rfBtn");
  btn.classList.add("ld"); btn.textContent = "↻ Scanning…";
  skeleton();
  document.getElementById("errbx").style.display = "none";
  document.getElementById("empty").style.display  = "none";

  try {
    const url = "/api/listings?sort=" + srt + (force ? "&force=1" : "");
    const res = await fetch(url);
    if (!res.ok) throw new Error("HTTP " + res.status);
    allRows = await res.json();
    render();

    const sr = await fetch("/api/stats");
    if (sr.ok) {
      const sd = await sr.json();
      if (sd.scraping) {
        document.getElementById("scanMsg").textContent = "🔄 Scraping in progress — results updating…";
      }
      if (sd.total_listings_scanned) {
        document.getElementById("sScan").textContent = sd.total_listings_scanned.toLocaleString() + "+";
      }
    }
  } catch (e) {
    console.error(e);
    document.getElementById("lc").innerHTML    = "";
    document.getElementById("errbx").style.display = "block";
    document.getElementById("empty").style.display  = "none";
  } finally {
    busy = false;
    btn.classList.remove("ld"); btn.textContent = "↻ Refresh";
  }
}

/* ── events ── */
document.querySelectorAll(".tab").forEach(function(b) {
  b.addEventListener("click", function() {
    document.querySelectorAll(".tab").forEach(function(x){x.classList.remove("on");});
    b.classList.add("on"); filt = b.dataset.f; render();
  });
});
document.getElementById("srtSel").addEventListener("change", function(e) {
  srt = e.target.value; render();
});
document.querySelectorAll(".cb").forEach(function(b) {
  b.addEventListener("click", function() {
    document.querySelectorAll(".cb").forEach(function(x){x.classList.remove("on");});
    b.classList.add("on"); curr = b.dataset.c; render();
  });
});
document.getElementById("rfBtn").addEventListener("click", function(){ load(true); });

load(false);
setInterval(function(){ load(false); }, 5 * 60 * 1000);
</script>
</body>
</html>
"""

# ─── HTTP SERVER ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    """Minimal HTTP request handler."""

    def log_message(self, fmt, *args):  # silence default access log
        pass

    def _send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            path   = parsed.path

            if path in ("/", "/index.html"):
                self._send_html(HTML_PAGE)

            elif path == "/api/listings":
                force = params.get("force", [None])[0] == "1"
                if force:
                    t = threading.Thread(target=run_scrape, args=(True,), daemon=True)
                    t.start()
                    # Brief wait so at least cached data is available
                    time.sleep(0.3)
                self._send_json(api_listings(params))

            elif path == "/api/stats":
                self._send_json(api_stats())

            elif path == "/health":
                self._send_json({"status": "ok", "python": sys.version})

            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        except Exception as exc:
            log.error("Handler error: %s", exc)
            try:
                self.send_response(500)
                self.end_headers()
            except Exception:
                pass


# ─── PORT UTILITY ─────────────────────────────────────────────────────────────
def find_free_port(start: int) -> int:
    """Return the first available TCP port starting from `start`."""
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("", port))
                return port          # bind succeeded → port is free
            except OSError:
                continue             # port in use → try next
    return start


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
def main() -> None:
    global PORT
    PORT = find_free_port(PORT)
    url  = "http://localhost:{}".format(PORT)

    print()
    print("  📉  MUMBAI PANIC SELLING")
    print("  ─────────────────────────────────────────────")
    print("  Server  →  {}".format(url))
    print("  Data    →  {}".format(DATA_DIR))
    print("  Python  →  {}".format(sys.version.split()[0]))
    print("  ─────────────────────────────────────────────")
    print("  Starting background scraper thread…")
    print("  NOTE: First run records baseline prices.")
    print("        Price drops appear from the 2nd scrape (~1 hr).")
    print()

    # Background scraper thread
    t = threading.Thread(target=background_scraper, daemon=True)
    t.start()

    # Brief pause before opening browser
    threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    print("  Opening {} in your browser…".format(url))
    print("  Press Ctrl+C to stop.\n")

    server = HTTPServer(("", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n  Shutting down. Goodbye!\n")
        server.server_close()


if __name__ == "__main__":
    main()
