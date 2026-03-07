"""
Mumbai Panic Selling — FastAPI Backend
--------------------------------------
Start:  uvicorn main:app --reload --port 8000

Endpoints:
  GET  /api/listings          → list of price drops (cached)
  GET  /api/listings?refresh=1 → force re-scrape
  GET  /api/stats             → aggregate statistics
  GET  /api/listing/{id}      → single listing detail
  GET  /health                → health check
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from models import Listing, ScrapeStats
from scraper import get_listings, load_cache, save_cache

log = logging.getLogger(__name__)

# ─── SCHEDULER ───────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler()

async def scheduled_scrape():
    log.info("Scheduled scrape starting…")
    listings = await get_listings(force_refresh=True)
    log.info("Scheduled scrape complete: %d drops", len(listings))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run once on startup
    await get_listings()

    # Schedule every hour
    scheduler.add_job(scheduled_scrape, "interval", hours=1, id="hourly_scrape")
    scheduler.start()
    yield
    scheduler.shutdown()

# ─── APP ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Mumbai Panic Selling API",
    description="Track luxury real estate price drops across Mumbai",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # lock this down in production
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def compute_stats(listings: list[Listing]) -> ScrapeStats:
    n = len(listings)
    sources: dict[str, int] = {}
    for l in listings:
        sources[l.source] = sources.get(l.source, 0) + 1

    return ScrapeStats(
        total_listings_scanned=15000,   # replace with real counter if you track it
        drops_found=n,
        avg_drop_pct=round(sum(l.drop_pct for l in listings) / n, 2) if n else 0.0,
        biggest_drop_pct=round(max((l.drop_pct for l in listings), default=0.0), 2),
        last_updated=datetime.utcnow(),
        sources=sources,
    )


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/api/listings", response_model=list[Listing])
async def get_all_listings(
    refresh: bool = Query(False, description="Force re-scrape (slow)"),
    type: Optional[str] = Query(None, description="Filter by type: Apartment/Villa/Penthouse/Duplex"),
    min_drop_pct: Optional[float] = Query(None, description="Minimum drop percentage"),
    location: Optional[str] = Query(None, description="Filter by location keyword"),
    sort: str = Query("drop_pct", description="Sort by: drop_pct | drop_cr | price_asc | price_desc | recent"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    listings = await get_listings(force_refresh=refresh)

    # Filter
    if type:
        listings = [l for l in listings if l.type.lower() == type.lower()]
    if min_drop_pct:
        listings = [l for l in listings if l.drop_pct >= min_drop_pct]
    if location:
        kw = location.lower()
        listings = [l for l in listings if kw in l.location.lower() or kw in l.city_area.lower()]

    # Sort
    if sort == "drop_pct":
        listings.sort(key=lambda x: x.drop_pct, reverse=True)
    elif sort == "drop_cr":
        listings.sort(key=lambda x: x.drop_cr, reverse=True)
    elif sort == "price_asc":
        listings.sort(key=lambda x: x.price_cr)
    elif sort == "price_desc":
        listings.sort(key=lambda x: x.price_cr, reverse=True)
    elif sort == "recent":
        listings.sort(key=lambda x: x.scraped_at, reverse=True)

    return listings[offset : offset + limit]


@app.get("/api/stats", response_model=ScrapeStats)
async def get_stats():
    listings = await get_listings()
    return compute_stats(listings)


@app.get("/api/listing/{listing_id}", response_model=Listing)
async def get_listing(listing_id: str):
    listings = await get_listings()
    for l in listings:
        if l.id == listing_id:
            return l
    raise HTTPException(status_code=404, detail="Listing not found")


@app.post("/api/refresh", response_model=dict)
async def trigger_refresh(background_tasks: BackgroundTasks):
    """Trigger a background re-scrape without waiting for it."""
    async def _refresh():
        await get_listings(force_refresh=True)
    background_tasks.add_task(_refresh)
    return {"status": "refresh triggered", "message": "Results will be available in ~30–60 seconds"}
