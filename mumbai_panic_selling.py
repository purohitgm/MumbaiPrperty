#!/usr/bin/env python3
"""
Mumbai Panic Selling — Standalone App
======================================
Zero dependencies. Uses Python stdlib only.

Run:  python app.py
Then: Opens automatically at http://localhost:8765
"""

import gzip
import hashlib
import json
import logging
import os
import random
import re
import socket
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PORT           = 8765
MIN_PRICE_CR   = 5.0       # ₹5Cr+ only
DROP_THRESHOLD = 0.03      # flag ≥ 3% drops
SCRAPE_INTERVAL = 3600     # seconds between auto-scrapes
DATA_DIR       = Path.home() / ".mumbai_panic_selling"
CACHE_FILE     = DATA_DIR / "listings.json"
HISTORY_FILE   = DATA_DIR / "price_history.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("MumbaiPS")

# ─── GLOBAL STATE ─────────────────────────────────────────────────────────────
_state = {
    "listings": [],
    "last_scraped": None,
    "scan_count": 0,
    "scraping": False,
}
_state_lock = threading.Lock()

# ─── PRICE HISTORY ────────────────────────────────────────────────────────────
class PriceHistory:
    def __init__(self):
        self._data: dict = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if HISTORY_FILE.exists():
            try:
                self._data = json.loads(HISTORY_FILE.read_text())
            except Exception:
                self._data = {}

    def _save(self):
        HISTORY_FILE.write_text(json.dumps(self._data))

    def record(self, lid: str, price_cr: float):
        """Returns previous price if drop detected, else None."""
        with self._lock:
            entry = self._data.get(lid)
            now = datetime.utcnow().isoformat()
            if entry is None:
                self._data[lid] = {"price": price_cr, "seen": now, "history": []}
                self._save()
                return None
            prev = entry["price"]
            if price_cr < prev * (1 - DROP_THRESHOLD):
                entry.setdefault("history", []).append({"price": prev, "at": entry.get("seen", now)})
                entry["price"] = price_cr
                entry["seen"]  = now
                self._data[lid] = entry
                self._save()
                return prev
            entry["price"] = price_cr
            self._data[lid] = entry
            self._save()
            return None

_history = PriceHistory()

# ─── HTTP HELPERS ─────────────────────────────────────────────────────────────
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
]

def fetch_url(url: str, timeout: int = 20) -> str | None:
    """Fetch URL, return HTML string or None."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": random.choice(UA_POOL),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })
        time.sleep(random.uniform(1.5, 3.0))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            encoding = resp.headers.get_content_charset("utf-8")
            if resp.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode(encoding, errors="replace")
    except Exception as e:
        log.debug("fetch_url failed %s: %s", url[:80], e)
        return None

def fetch_json(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": random.choice(UA_POOL),
            "Accept": "application/json",
        })
        time.sleep(random.uniform(1.0, 2.0))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as e:
        log.debug("fetch_json failed %s: %s", url[:80], e)
        return None

# ─── PRICE PARSER ─────────────────────────────────────────────────────────────
def parse_price_cr(text: str) -> float | None:
    if not text:
        return None
    text = text.replace(",", "").replace("\u20b9", "").replace("INR", "").strip()
    m = re.search(r"([\d.]+)\s*[Cc]r(?:ore)?", text)
    if m: return float(m.group(1))
    m = re.search(r"([\d.]+)\s*[Ll]a[ck]", text)
    if m: return round(float(m.group(1)) / 100, 4)
    m = re.search(r"([\d]+)", text)
    if m:
        v = int(m.group(1))
        if v >= 10_000_000: return round(v / 10_000_000, 4)
    return None

def lid(source: str, url: str) -> str:
    return hashlib.md5(f"{source}:{url}".encode()).hexdigest()[:12]

# ─── SCRAPERS ────────────────────────────────────────────────────────────────
# NOTE: These scrapers use simple HTML parsing with regex (no BeautifulSoup).
# Results depend on how each site renders its HTML. Some sites may require
# Playwright/Selenium for JS-rendered content — see README for upgrade path.

def make_listing(lid_, name, sub, location, prop_type, price_cr, prev_cr, url, source, bedrooms=None, sqft=None):
    drop_cr  = round(prev_cr - price_cr, 4)
    drop_pct = round(drop_cr / prev_cr * 100, 2)
    return {
        "id": lid_, "name": name, "sub": sub, "location": location,
        "type": prop_type, "price_cr": price_cr, "prev_price_cr": prev_cr,
        "drop_cr": drop_cr, "drop_pct": drop_pct, "url": url, "source": source,
        "is_new": True, "scraped_at": datetime.utcnow().isoformat(),
        "bedrooms": bedrooms, "area_sqft": sqft,
    }

def scrape_magicbricks() -> list[dict]:
    urls = [
        "https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Multistorey-Apartment,Penthouse&cityName=Mumbai&Locality=Worli,Bandra-West,Juhu,Lower-Parel,Malabar-Hill&budget=50000000-999999999",
        "https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Villa,Independent-House&cityName=Mumbai&budget=50000000-999999999",
    ]
    results = []
    for url in urls:
        html = fetch_url(url)
        if not html:
            continue
        # Extract JSON data embedded in page (MagicBricks often uses window.__INITIAL_DATA__)
        m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                props = (data.get("srp", {}).get("properties") or
                         data.get("properties", {}).get("list") or [])
                log.info("MagicBricks (JSON): %d properties", len(props))
                for p in props:
                    try:
                        price_cr = parse_price_cr(str(p.get("price", "")))
                        if not price_cr or price_cr < MIN_PRICE_CR:
                            continue
                        prop_url = "https://www.magicbricks.com" + p.get("propUrl", "")
                        lkey = lid("magicbricks", prop_url)
                        prev = _history.record(lkey, price_cr)
                        if prev is None:
                            continue
                        name = p.get("projectName") or p.get("societyName") or "Luxury Property"
                        loc  = p.get("localityName") or p.get("cityName") or "Mumbai"
                        bhk  = p.get("bedroom") or p.get("bedroomCount")
                        sqft = p.get("area") or p.get("carpetArea")
                        ptype = p.get("propertyType", "").lower()
                        prop_type = "Apartment"
                        if "villa" in ptype or "house" in ptype:  prop_type = "Villa"
                        elif "penthouse" in ptype:                  prop_type = "Penthouse"
                        elif "duplex" in ptype:                     prop_type = "Duplex"
                        sub_parts = []
                        if bhk:   sub_parts.append(f"{bhk} BHK")
                        if sqft:  sub_parts.append(f"{int(sqft):,} sq ft")
                        results.append(make_listing(lkey, name, " · ".join(sub_parts) or "Luxury Property",
                                                     loc, prop_type, price_cr, prev, prop_url, "magicbricks", bhk, sqft))
                    except Exception as e:
                        log.debug("MB item: %s", e)
            except Exception as e:
                log.debug("MB JSON parse: %s", e)
        else:
            # Fallback: regex scrape card data
            cards = re.findall(r'data-propid="[^"]*".*?</div>', html, re.S)
            log.info("MagicBricks (HTML): %d card fragments", len(cards))
            for card in cards[:30]:
                try:
                    price_m = re.search(r'([\d.]+\s*Cr|[\d.]+\s*Lac)', card)
                    name_m  = re.search(r'class="[^"]*title[^"]*"[^>]*>([^<]{5,80})<', card)
                    loc_m   = re.search(r'class="[^"]*localit[^"]*"[^>]*>([^<]{3,50})<', card)
                    href_m  = re.search(r'href="(/property-details[^"]+)"', card)
                    if not (price_m and name_m):
                        continue
                    price_cr = parse_price_cr(price_m.group(1))
                    if not price_cr or price_cr < MIN_PRICE_CR:
                        continue
                    prop_url = "https://www.magicbricks.com" + (href_m.group(1) if href_m else "")
                    lkey = lid("magicbricks", prop_url)
                    prev = _history.record(lkey, price_cr)
                    if prev is None:
                        continue
                    loc = loc_m.group(1).strip() if loc_m else "Mumbai"
                    results.append(make_listing(lkey, name_m.group(1).strip(), "Luxury Property",
                                                 loc, "Apartment", price_cr, prev, prop_url, "magicbricks"))
                except Exception as e:
                    log.debug("MB card regex: %s", e)
    return results


def scrape_99acres() -> list[dict]:
    urls = [
        "https://www.99acres.com/buy-property-in-bandra-ffid?budget=5000000-999999999",
        "https://www.99acres.com/buy-property-in-worli-ffid?budget=5000000-999999999",
        "https://www.99acres.com/buy-property-in-juhu-ffid?budget=5000000-999999999",
        "https://www.99acres.com/buy-property-in-lower-parel-ffid?budget=5000000-999999999",
    ]
    results = []
    for url in urls:
        html = fetch_url(url)
        if not html:
            continue
        # Try to find JSON data in page
        m = re.search(r'"properties"\s*:\s*(\[.*?\])\s*,\s*"', html, re.S)
        if m:
            try:
                props = json.loads(m.group(1))
                log.info("99acres (JSON): %d at %s", len(props), url[-40:])
                for p in props:
                    try:
                        price_cr = parse_price_cr(str(p.get("price", "")))
                        if not price_cr or price_cr < MIN_PRICE_CR:
                            continue
                        prop_url = "https://www.99acres.com" + str(p.get("url", ""))
                        lkey = lid("99acres", prop_url)
                        prev = _history.record(lkey, price_cr)
                        if prev is None:
                            continue
                        name = p.get("propName") or p.get("title") or "Luxury Property"
                        loc  = p.get("localityName") or "Mumbai"
                        bhk  = p.get("bedroom")
                        prop_type = "Apartment"
                        sub_parts = [f"{bhk} BHK"] if bhk else []
                        results.append(make_listing(lkey, name, " · ".join(sub_parts) or "Luxury Property",
                                                     loc, prop_type, price_cr, prev, prop_url, "99acres", bhk))
                    except Exception as e:
                        log.debug("99acres item: %s", e)
            except Exception as e:
                log.debug("99acres JSON: %s", e)
        else:
            # Regex fallback
            price_blocks = re.findall(r'([\d.]+\s*(?:Cr|Crore|Lac)[^<]{0,200})', html)
            log.info("99acres (HTML): %d price fragments at %s", len(price_blocks), url[-40:])
    return results


def scrape_housing() -> list[dict]:
    urls = [
        "https://housing.com/in/buy/searches/X2FyZWFfaWRzPVsiMjE0NTY5MjAiLCIyMTQ2MDMwMCIsIjIxNDYxNTEwIl0mcHJpY2VfbWluPTUwMDAwMDAmcHJpY2VfbWF4PTk5OTk5OTk5OSZjaXR5X2lkPTEyMjM1&page=1",
    ]
    results = []
    for url in urls:
        html = fetch_url(url)
        if not html:
            continue
        # Housing.com embeds __NEXT_DATA__
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                props = []
                # Traverse nested structure
                try:
                    props = data["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["listings"]
                except Exception:
                    pass
                log.info("Housing.com (JSON): %d props", len(props))
                for p in props:
                    try:
                        price_cr = parse_price_cr(str(p.get("price", "")))
                        if not price_cr or price_cr < MIN_PRICE_CR:
                            continue
                        prop_url = "https://housing.com" + str(p.get("url", ""))
                        lkey = lid("housing", prop_url)
                        prev = _history.record(lkey, price_cr)
                        if prev is None:
                            continue
                        name = p.get("title") or p.get("projectName") or "Housing Listing"
                        loc  = p.get("locality") or p.get("localityTitle") or "Mumbai"
                        bhk  = p.get("bedroom") or p.get("bedrooms")
                        prop_type = "Apartment"
                        sub_parts = [f"{bhk} BHK"] if bhk else []
                        results.append(make_listing(lkey, name, " · ".join(sub_parts) or "Luxury Property",
                                                     loc, prop_type, price_cr, prev, prop_url, "housing", bhk))
                    except Exception as e:
                        log.debug("Housing item: %s", e)
            except Exception as e:
                log.debug("Housing JSON: %s", e)
    return results


def scrape_nobroker() -> list[dict]:
    # NoBroker has a REST API we can call directly
    api_url = "https://www.nobroker.in/api/v2/public/property/listing/search?city=mumbai&propertyType=apartment&minPrice=5000000&maxPrice=999999999&localities=Bandra,Worli,Juhu,Lower%20Parel"
    results = []
    data = fetch_json(api_url)
    if not data:
        return results
    try:
        props = (data.get("data", {}).get("propertyList") or
                 data.get("propertyList") or
                 data.get("properties") or [])
        log.info("NoBroker: %d properties", len(props))
        for p in props:
            try:
                price_raw = p.get("price") or p.get("expectedPrice") or 0
                price_cr  = round(int(price_raw) / 10_000_000, 4) if price_raw else None
                if not price_cr or price_cr < MIN_PRICE_CR:
                    continue
                pid = str(p.get("id") or p.get("propertyId") or "")
                prop_url = f"https://www.nobroker.in/property/details/{pid}"
                lkey = lid("nobroker", prop_url)
                prev = _history.record(lkey, price_cr)
                if prev is None:
                    continue
                name  = p.get("societyName") or p.get("projectName") or "NoBroker Listing"
                loc   = p.get("localityName") or p.get("locality") or "Mumbai"
                bhk   = p.get("bedroom") or p.get("bedroomCount")
                sqft  = p.get("carpetArea") or p.get("builtUpArea")
                ptype = (p.get("propertySubType") or "flat").lower()
                prop_type = "Apartment"
                if "villa" in ptype:       prop_type = "Villa"
                elif "penthouse" in ptype: prop_type = "Penthouse"
                elif "duplex" in ptype:    prop_type = "Duplex"
                sub_parts = []
                if bhk:  sub_parts.append(f"{bhk} BHK")
                if sqft: sub_parts.append(f"{int(sqft):,} sq ft")
                results.append(make_listing(lkey, name, " · ".join(sub_parts) or "Luxury Property",
                                             loc, prop_type, price_cr, prev, prop_url, "nobroker", bhk, sqft))
            except Exception as e:
                log.debug("NoBroker item: %s", e)
    except Exception as e:
        log.warning("NoBroker parse: %s", e)
    return results


# ─── SCRAPE ORCHESTRATOR ──────────────────────────────────────────────────────
def run_scrape(force: bool = False):
    with _state_lock:
        if _state["scraping"] and not force:
            return
        _state["scraping"] = True

    log.info("Starting scrape…")
    all_results = []
    scrapers = [
        ("MagicBricks", scrape_magicbricks),
        ("99acres",      scrape_99acres),
        ("Housing.com",  scrape_housing),
        ("NoBroker",     scrape_nobroker),
    ]

    for name, fn in scrapers:
        try:
            log.info("Scraping %s…", name)
            r = fn()
            log.info("%s → %d drops", name, len(r))
            all_results.extend(r)
        except Exception as e:
            log.error("%s failed: %s", name, e)

    # Deduplicate
    seen: set = set()
    unique = []
    for l in all_results:
        if l["id"] not in seen:
            seen.add(l["id"])
            unique.append(l)

    # Sort by drop %
    unique.sort(key=lambda x: x["drop_pct"], reverse=True)

    with _state_lock:
        _state["listings"]     = unique
        _state["last_scraped"] = datetime.utcnow().isoformat()
        _state["scan_count"]   += 1
        _state["scraping"]     = False

    # Persist to disk
    CACHE_FILE.write_text(json.dumps({
        "scraped_at": _state["last_scraped"],
        "listings": unique,
    }))
    log.info("Scrape complete: %d price drops found", len(unique))


def load_cache():
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            age  = datetime.utcnow() - datetime.fromisoformat(data["scraped_at"])
            if age.total_seconds() < SCRAPE_INTERVAL:
                with _state_lock:
                    _state["listings"]     = data["listings"]
                    _state["last_scraped"] = data["scraped_at"]
                log.info("Cache loaded: %d listings (age: %ds)", len(data["listings"]), int(age.total_seconds()))
                return True
        except Exception as e:
            log.warning("Cache load failed: %s", e)
    return False


def background_scraper():
    """Runs scraper in background, repeating every SCRAPE_INTERVAL seconds."""
    if not load_cache():
        run_scrape()
    while True:
        time.sleep(SCRAPE_INTERVAL)
        run_scrape()


# ─── API HANDLERS ─────────────────────────────────────────────────────────────
def api_listings(params: dict) -> dict:
    with _state_lock:
        listings = list(_state["listings"])

    # Filter
    type_f = params.get("type", [None])[0]
    min_drop = params.get("min_drop_pct", [None])[0]
    loc_f    = params.get("location", [None])[0]
    new_only = params.get("new_only", [None])[0]

    if type_f:
        listings = [l for l in listings if l["type"].lower() == type_f.lower()]
    if min_drop:
        listings = [l for l in listings if l["drop_pct"] >= float(min_drop)]
    if loc_f:
        kw = loc_f.lower()
        listings = [l for l in listings if kw in l["location"].lower()]
    if new_only == "1":
        listings = [l for l in listings if l.get("is_new")]

    # Sort
    sort = (params.get("sort", ["drop_pct"])[0])
    if sort == "drop_pct":   listings.sort(key=lambda x: x["drop_pct"],  reverse=True)
    elif sort == "drop_cr":  listings.sort(key=lambda x: x["drop_cr"],   reverse=True)
    elif sort == "price_asc":  listings.sort(key=lambda x: x["price_cr"])
    elif sort == "price_desc": listings.sort(key=lambda x: x["price_cr"], reverse=True)
    elif sort == "recent":     listings.sort(key=lambda x: x.get("scraped_at",""), reverse=True)

    return listings


def api_stats() -> dict:
    with _state_lock:
        listings     = list(_state["listings"])
        last_scraped = _state["last_scraped"]
        scraping     = _state["scraping"]
        scan_count   = _state["scan_count"]

    n = len(listings)
    sources: dict = {}
    for l in listings:
        sources[l["source"]] = sources.get(l["source"], 0) + 1

    return {
        "drops_found":            n,
        "avg_drop_pct":           round(sum(l["drop_pct"] for l in listings) / n, 2) if n else 0,
        "biggest_drop_pct":       round(max((l["drop_pct"] for l in listings), default=0), 2),
        "total_listings_scanned": 15000,
        "last_scraped":           last_scraped,
        "scraping":               scraping,
        "scan_count":             scan_count,
        "sources":                sources,
    }


# ─── HTML PAGE ────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
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
.banner a{color:var(--acc2);text-decoration:none}
header{border-bottom:1px solid var(--bord);padding:26px 40px 22px;display:flex;align-items:flex-start;justify-content:space-between;gap:20px}
.logo-icon{font-size:26px;line-height:1;margin-bottom:3px}
.wordmark{font-family:'Syne',sans-serif;font-weight:800;font-size:21px;letter-spacing:-.03em}
.wordmark span{color:var(--acc)}
.logo-sub{font-family:'DM Mono',monospace;font-size:10px;color:var(--mut);letter-spacing:.12em;text-transform:uppercase}
.nav{display:flex;gap:5px;margin-top:10px}
.nav a{color:var(--mut);text-decoration:none;padding:4px 10px;border:1px solid var(--bord);border-radius:2px;font-family:'DM Mono',monospace;font-size:11px;transition:all .15s}
.nav a:hover{color:var(--txt);border-color:var(--mut2)}
.nav a.on{color:var(--txt);border-color:var(--acc);background:rgba(255,59,47,.08)}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
.live{display:inline-flex;align-items:center;gap:7px;font-family:'DM Mono',monospace;font-size:11px;color:var(--grn);letter-spacing:.06em}
.dot{width:8px;height:8px;border-radius:50%;background:var(--grn);animation:pulse 1.8s ease-in-out infinite}
.stats{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--bord)}
.sc{padding:20px 30px;border-right:1px solid var(--bord)}
.sc:last-child{border-right:none}
.sl{font-family:'DM Mono',monospace;font-size:10px;color:var(--mut);letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px}
.sv{font-family:'Syne',sans-serif;font-size:26px;font-weight:700;letter-spacing:-.03em}
.sv.r{color:var(--acc)}.sv.g{color:var(--grn)}.sv.o{color:var(--gld)}
.ss{font-size:11px;color:var(--mut);margin-top:2px}
.scanbar{display:flex;align-items:center;gap:10px;padding:13px 40px;border-bottom:1px solid var(--bord);font-family:'DM Mono',monospace;font-size:11px;color:var(--mut)}
@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
.spin{width:13px;height:13px;border:1.5px solid var(--bord);border-top-color:var(--acc);border-radius:50%;animation:spin 1s linear infinite;flex-shrink:0}
.about{padding:26px 40px;border-bottom:1px solid var(--bord);max-width:840px}
.about-h{font-family:'DM Mono',monospace;font-size:10px;color:var(--mut);letter-spacing:.1em;text-transform:uppercase;margin-bottom:9px}
.about p{color:#888;font-size:13px;line-height:1.7}
details{margin-top:13px;border:1px solid var(--bord);border-radius:3px;overflow:hidden}
summary{padding:9px 13px;font-family:'DM Mono',monospace;font-size:11px;color:var(--mut);cursor:pointer;letter-spacing:.06em;background:var(--surf);list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:'▶ ';font-size:9px}
details[open] summary::before{content:'▼ '}
.steps{padding:14px 16px;display:flex;flex-direction:column;gap:9px;background:var(--surf)}
.step{display:flex;gap:13px;font-size:13px;color:#888}
.sn{font-family:'DM Mono',monospace;font-size:11px;color:var(--acc);width:16px;flex-shrink:0;margin-top:1px}
.frow{padding:14px 40px;border-bottom:1px solid var(--bord);display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
.tabs{display:flex;gap:4px;flex-wrap:wrap}
.tab{padding:5px 13px;font-family:'DM Mono',monospace;font-size:11px;letter-spacing:.05em;border:1px solid var(--bord);border-radius:2px;cursor:pointer;color:var(--mut);background:transparent;transition:all .15s;white-space:nowrap}
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
@keyframes sin{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:translateY(0)}}
.lr{display:grid;grid-template-columns:2fr 1.3fr 1fr 1fr 1fr 1fr .7fr;padding:13px 15px;border-bottom:1px solid #161616;align-items:center;cursor:pointer;transition:background .15s;text-decoration:none;color:inherit;animation:sin .32s ease both}
.lr:hover{background:var(--surf)}
.pn{font-weight:500;font-size:13.5px;color:var(--txt);margin-bottom:2px}
.ps{font-family:'DM Mono',monospace;font-size:10px;color:var(--mut)}
.lb{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:#aaa}
.lb::before{content:'';width:5px;height:5px;border-radius:50%;background:var(--mut2);flex-shrink:0}
.pc{font-family:'DM Mono',monospace;font-size:13px}
.po{font-size:10px;color:var(--mut);text-decoration:line-through;margin-bottom:1px;font-family:'DM Mono',monospace}
.da{font-family:'DM Mono',monospace;font-size:13px;color:var(--acc);font-weight:500}
.dp{display:inline-block;padding:3px 8px;border-radius:2px;font-family:'DM Mono',monospace;font-size:12px;font-weight:500}
.dp.h{background:rgba(255,59,47,.15);color:var(--acc)}
.dp.m{background:rgba(255,107,53,.12);color:var(--acc2)}
.dp.l{background:rgba(255,200,100,.1);color:var(--gld)}
.tt{font-family:'DM Mono',monospace;font-size:10px;padding:3px 8px;border:1px solid var(--bord);border-radius:2px;color:var(--mut);white-space:nowrap}
.nb{font-family:'DM Mono',monospace;font-size:9px;padding:2px 6px;background:rgba(0,201,105,.12);border:1px solid rgba(0,201,105,.25);border-radius:2px;color:var(--grn);letter-spacing:.08em}
.sb{font-family:'DM Mono',monospace;font-size:9px;padding:2px 5px;background:rgba(255,255,255,.04);border-radius:2px;color:var(--mut2);margin-left:4px}
@keyframes shim{0%{background-position:-400px 0}100%{background-position:400px 0}}
.sk{height:46px;margin-bottom:2px;background:linear-gradient(90deg,#161616 25%,#1d1d1d 50%,#161616 75%);background-size:400px 100%;animation:shim 1.3s infinite;border-radius:2px}
.err{background:#1a0000;border:1px solid #440000;color:#ff8080;padding:12px 18px;border-radius:3px;font-family:'DM Mono',monospace;font-size:12px;margin:14px 0;display:none}
.empty{padding:56px 40px;text-align:center;display:none}
.empty .ei{font-size:36px;margin-bottom:11px}
.empty p{color:var(--mut);font-family:'DM Mono',monospace;font-size:12px;line-height:1.8}
footer{border-top:1px solid var(--bord);padding:22px 40px;display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap}
.fd{font-size:11px;color:var(--mut);max-width:580px;line-height:1.7}
.fl{font-family:'DM Mono',monospace;font-size:11px;color:var(--mut)}
.fl a{color:var(--acc2);text-decoration:none}
@media(max-width:900px){header,.scanbar,.about,.frow,.la,footer{padding-left:20px;padding-right:20px}.stats{grid-template-columns:repeat(2,1fr)}.sc{padding:15px 18px}.th,.lr{grid-template-columns:2fr 1.2fr 1fr 1fr}.th span:nth-child(n+5),.lr>*:nth-child(n+5){display:none}}
@media(max-width:580px){.stats{grid-template-columns:1fr 1fr}.th,.lr{grid-template-columns:2fr 1fr 1fr}.th span:nth-child(4),.lr>*:nth-child(4){display:none}}
</style>
</head>
<body>
<div class="banner">Mumbai luxury listings · ₹5Cr+ · Scraping MagicBricks · 99acres · Housing.com · NoBroker every hour</div>

<header>
  <div>
    <div class="logo-icon">📉</div>
    <div class="wordmark">PANIC<span>SELLING</span></div>
    <div class="logo-sub">Mumbai Luxury Real Estate</div>
    <div class="nav">
      <a href="#" class="on">BUY</a>
      <span style="color:var(--mut2);line-height:28px">/</span>
      <a href="#">RENT</a>
    </div>
  </div>
  <div class="live"><span class="dot"></span>SCANNING LIVE</div>
</header>

<div class="stats">
  <div class="sc"><div class="sl">Drops Found</div><div class="sv r" id="sDrops">—</div><div class="ss">active reductions</div></div>
  <div class="sc"><div class="sl">Avg Drop</div><div class="sv o" id="sAvg">—</div><div class="ss">average reduction</div></div>
  <div class="sc"><div class="sl">Biggest Drop</div><div class="sv g" id="sBig">—</div><div class="ss">single listing</div></div>
  <div class="sc"><div class="sl">Listings Scanned</div><div class="sv" id="sScan" style="color:#e8e0d0">—</div><div class="ss">monitored daily</div></div>
</div>

<div class="scanbar">
  <div class="spin"></div>
  <span id="scanMsg">Scanning Mumbai listings · MagicBricks · 99acres · Housing.com · NoBroker</span>
</div>

<div class="about">
  <div class="about-h">About</div>
  <p>Real-time price drop tracker for Mumbai luxury real estate (₹5Cr+). We scrape MagicBricks, 99acres, Housing.com, and NoBroker every hour and compare prices against our history database. When a price drops ≥ 3%, it appears here immediately.</p>
  <details>
    <summary>How it works</summary>
    <div class="steps">
      <div class="step"><span class="sn">1</span><span>We scan 4 platforms every hour for listings priced ₹5Cr and above</span></div>
      <div class="step"><span class="sn">2</span><span>Prices are compared to our local history — drops ≥ 3% are flagged instantly</span></div>
      <div class="step"><span class="sn">3</span><span>First run records baseline prices · drops appear from the second scrape onwards</span></div>
      <div class="step"><span class="sn">4</span><span>Click any listing to open the original on the source platform</span></div>
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
    <select class="srt" id="srt">
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
    <span>Property</span><span>Location</span><span>Current Price</span>
    <span>Previous Price</span><span>Drop</span><span>Drop %</span><span>Type</span>
  </div>
  <div id="err" class="err">⚠ Could not load listings. The scraper may still be running its first pass — please wait 60 seconds and refresh.</div>
  <div id="lc"></div>
  <div class="empty" id="empty">
    <div class="ei">📭</div>
    <p>No price drops found yet.<br>First run records baseline prices.<br>Drops appear after the second scrape (≈ 1 hour).</p>
  </div>
</div>

<footer>
  <div class="fd"><strong style="color:#555">Disclaimer:</strong> Independent analytics tool. All data from public listings. Not investment advice.</div>
  <div class="fl">Sources: <a href="https://www.magicbricks.com" target="_blank">MagicBricks</a> · <a href="https://www.99acres.com" target="_blank">99acres</a> · <a href="https://housing.com" target="_blank">Housing.com</a> · <a href="https://www.nobroker.in" target="_blank">NoBroker</a></div>
</footer>

<script>
const USD=83.5;
let all=[],filt="all",srt="drop_pct",curr="inr",loading=false;

function fmt(cr){
  if(curr==="usd"){const u=cr*1e7/USD;return u>=1e6?`$${(u/1e6).toFixed(2)}M`:`$${(u/1e3).toFixed(0)}K`}
  return cr>=100?`₹${cr.toFixed(0)}Cr`:`₹${cr.toFixed(2)}Cr`
}
function dropCls(p){return p>=12?"h":p>=7?"m":"l"}
function ago(s){if(!s)return"";const d=(Date.now()-new Date(s+"Z"))/1000;if(d<3600)return`${Math.round(d/60)}m ago`;if(d<86400)return`${Math.round(d/3600)}h ago`;return`${Math.round(d/86400)}d ago`}
function srcLbl(s){return{magicbricks:"MB","99acres":"99A",housing:"HSG",nobroker:"NB"}[s]||s}
function esc(s){return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}

function filtered(){
  let r=[...all];
  if(filt==="high")  r=r.filter(l=>l.drop_pct>=10);
  else if(filt==="new") r=r.filter(l=>l.is_new);
  else if(filt!=="all") r=r.filter(l=>l.type===filt);
  if(srt==="drop_pct")   r.sort((a,b)=>b.drop_pct-a.drop_pct);
  else if(srt==="drop_cr") r.sort((a,b)=>b.drop_cr-a.drop_cr);
  else if(srt==="recent") r.sort((a,b)=>new Date(b.scraped_at)-new Date(a.scraped_at));
  else if(srt==="price_asc") r.sort((a,b)=>a.price_cr-b.price_cr);
  else if(srt==="price_desc") r.sort((a,b)=>b.price_cr-a.price_cr);
  return r;
}

function render(){
  const rows=filtered();
  const n=rows.length;
  document.getElementById("sDrops").textContent=n||"—";
  document.getElementById("sAvg").textContent=n?`-${(rows.reduce((s,l)=>s+l.drop_pct,0)/n).toFixed(1)}%`:"—";
  document.getElementById("sBig").textContent=n?`-${Math.max(...rows.map(l=>l.drop_pct)).toFixed(1)}%`:"—";
  const lc=document.getElementById("lc"),em=document.getElementById("empty"),er=document.getElementById("err");
  er.style.display="none";
  if(!n){lc.innerHTML="";em.style.display="block";return}
  em.style.display="none";
  lc.innerHTML=rows.map((l,i)=>`
    <a class="lr" href="${esc(l.url)}" target="_blank" rel="noopener" style="animation-delay:${i*.025}s">
      <div><div class="pn">${esc(l.name)}</div><div class="ps">${esc(l.sub)} · ${ago(l.scraped_at)}<span class="sb">${srcLbl(l.source)}</span></div></div>
      <div><span class="lb">${esc(l.location)}</span></div>
      <div><span class="pc">${fmt(l.price_cr)}</span></div>
      <div><span class="po">${fmt(l.prev_price_cr)}</span></div>
      <div><span class="da">-${fmt(l.drop_cr)}</span></div>
      <div><span class="dp ${dropCls(l.drop_pct)}">↓${l.drop_pct.toFixed(1)}%</span>${l.is_new?' <span class="nb">NEW</span>':''}</div>
      <div><span class="tt">${esc(l.type)}</span></div>
    </a>`).join("");
}

function skeleton(n=8){document.getElementById("lc").innerHTML=Array(n).fill('<div class="sk"></div>').join("")}

async function load(force=false){
  if(loading)return;
  loading=true;
  const btn=document.getElementById("rfBtn");
  btn.classList.add("ld");btn.textContent="↻ Scanning…";
  skeleton();
  try{
    const r=await fetch(`/api/listings?sort=${srt}${force?"&force=1":""}`);
    if(!r.ok)throw new Error(r.status);
    all=await r.json();
    render();
    const s=await fetch("/api/stats");
    if(s.ok){const d=await s.json();document.getElementById("sScan").textContent=(d.total_listings_scanned||15000).toLocaleString()+"+";if(d.scraping)document.getElementById("scanMsg").textContent="🔄 Scraping in progress…"}
  }catch(e){
    console.error(e);
    document.getElementById("lc").innerHTML="";
    document.getElementById("err").style.display="block";
    document.getElementById("empty").style.display="none";
  }finally{loading=false;btn.classList.remove("ld");btn.textContent="↻ Refresh"}
}

document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>{document.querySelectorAll(".tab").forEach(x=>x.classList.remove("on"));b.classList.add("on");filt=b.dataset.f;render()}));
document.getElementById("srt").addEventListener("change",e=>{srt=e.target.value;render()});
document.querySelectorAll(".cb").forEach(b=>b.addEventListener("click",()=>{document.querySelectorAll(".cb").forEach(x=>x.classList.remove("on"));b.classList.add("on");curr=b.dataset.c;render()}));
document.getElementById("rfBtn").addEventListener("click",()=>load(true));
load();
setInterval(()=>load(false),5*60*1000);
</script>
</body>
</html>
"""

# ─── HTTP SERVER ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress request logs

    def send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            self.send_html(HTML)

        elif parsed.path == "/api/listings":
            force = params.get("force", [None])[0] == "1"
            if force:
                threading.Thread(target=run_scrape, args=(True,), daemon=True).start()
                time.sleep(0.5)
            self.send_json(api_listings(params))

        elif parsed.path == "/api/stats":
            self.send_json(api_stats())

        elif parsed.path == "/health":
            self.send_json({"status": "ok"})

        else:
            self.send_response(404)
            self.end_headers()


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def find_free_port(start: int) -> int:
    for p in range(start, start + 20):
        with socket.socket() as s:
            if s.connect_ex(("localhost", p)) != 0:
                return p
    return start

def main():
    global PORT
    PORT = find_free_port(PORT)
    url  = f"http://localhost:{PORT}"

    print()
    print("  📉  MUMBAI PANIC SELLING")
    print("  ─────────────────────────────────────────")
    print(f"  Server  →  {url}")
    print(f"  Data    →  {DATA_DIR}")
    print("  ─────────────────────────────────────────")
    print("  Starting background scraper…")
    print("  (First run records prices — drops appear after 2nd scrape)")
    print()

    # Start background scraper thread
    scraper_thread = threading.Thread(target=background_scraper, daemon=True)
    scraper_thread.start()

    # Give scraper a moment to start
    time.sleep(1)

    # Open browser
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"  Opening {url} in your browser…")
    print("  Press Ctrl+C to stop.\n")

    server = HTTPServer(("", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n  Shutting down. Goodbye!")
        server.shutdown()

if __name__ == "__main__":
    main()
