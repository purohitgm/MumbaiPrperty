# Mumbai Panic Selling — Real Estate Price Drop Tracker

Track luxury real estate price drops (₹5Cr+) across Mumbai in real time.
Scrapes: **MagicBricks · 99acres · Housing.com · NoBroker**

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium   # optional, for JS-heavy pages
```

### 2. First run — record baseline prices
```bash
python scraper.py
```
> The first run records current prices. Price drops are detected on the **second run** (and every run after).

### 3. Start the API server
```bash
uvicorn main:app --reload --port 8000
```

### 4. Open the frontend
Open `index.html` in your browser. It calls `http://localhost:8000` automatically.

---

## How It Works

1. **Scraper** (`scraper.py`) fetches listings from four platforms every hour
2. Prices are stored in `cache/price_history.json`
3. When a listing's price drops ≥ 3%, it's flagged and served via the API
4. The **frontend** (`index.html`) polls the API and displays live drops

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/listings` | All price drops |
| GET | `/api/listings?refresh=1` | Force re-scrape |
| GET | `/api/listings?type=Penthouse` | Filter by type |
| GET | `/api/listings?min_drop_pct=10` | Only 10%+ drops |
| GET | `/api/listings?location=Bandra` | Filter by area |
| GET | `/api/listings?sort=drop_cr` | Sort by ₹ drop |
| GET | `/api/stats` | Aggregate stats |
| GET | `/api/listing/{id}` | Single listing |
| POST | `/api/refresh` | Background re-scrape |

---

## Configuration

Edit `scraper.py` top section:

```python
MIN_PRICE_CR   = 5.0    # minimum listing price in Crore
DROP_THRESHOLD = 0.03   # flag drops ≥ 3%
CACHE_TTL_SEC  = 3600   # cache duration (seconds)
```

---

## Tips

- **First run shows no drops** — that's normal. Prices are recorded as baseline. Drops appear from run #2 onwards.
- Run `python scraper.py` daily via cron for continuous tracking
- If sites block scraping, set `USE_PLAYWRIGHT = True` in `scraper.py` for browser-based scraping
- To track rentals, add rental URL endpoints in `MAGICBRICKS_URLS` / `ACRES_URLS`

---

## Cron Setup (auto-scrape every hour)
```bash
crontab -e
# Add:
0 * * * * cd /path/to/mumbai-realestate && python scraper.py
```

---

## File Structure
```
mumbai-realestate/
├── main.py           ← FastAPI server
├── scraper.py        ← Multi-site scraper
├── models.py         ← Pydantic data models
├── requirements.txt
├── index.html        ← Frontend (open in browser)
└── cache/
    ├── listings.json      ← Current drop listings (auto-created)
    └── price_history.json ← Price history DB (auto-created)
```
