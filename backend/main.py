import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="SG Jobs Dashboard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory store (persisted to jobs.json on disk) ─────────────────────────
STORE_PATH = os.path.join(os.path.dirname(__file__), "jobs.json")
job_store: dict[str, dict] = {}
last_scraped: Optional[datetime] = None


def load_store():
    global job_store
    if os.path.exists(STORE_PATH):
        try:
            with open(STORE_PATH) as f:
                job_store = json.load(f)
        except Exception:
            job_store = {}


def save_store():
    with open(STORE_PATH, "w") as f:
        json.dump(job_store, f)


# ── Scrapers ─────────────────────────────────────────────────────────────────
MCF_QUERIES = ["analyst", "business development", "data analyst", "business analyst"]
INDEED_QUERIES = ["analyst singapore", "business development singapore"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


async def scrape_mycareersfuture(client: httpx.AsyncClient) -> list[dict]:
    jobs = []
    seen = set()
    for query in MCF_QUERIES:
        try:
            url = (
                f"https://api.mycareersfuture.gov.sg/v2/jobs"
                f"?search={query}&limit=30&sortBy=new_posting_date"
            )
            r = await client.get(url, headers=HEADERS, timeout=15)
            data = r.json()
            for j in data.get("results", []):
                uid = j.get("uuid", "")
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                salary = j.get("salary", {}) or {}
                cats = [c.get("category", "") for c in (j.get("categories") or [])]
                jobs.append({
                    "id": uid,
                    "source": "MyCareersFuture",
                    "source_color": "#c0392b",
                    "title": j.get("title", ""),
                    "company": (j.get("postedCompany") or {}).get("name", ""),
                    "salary_min": salary.get("minimum"),
                    "salary_max": salary.get("maximum"),
                    "employment_type": (j.get("employmentTypes") or [""])[0],
                    "categories": cats,
                    "url": (j.get("metadata") or {}).get("jobDetailsUrl", ""),
                    "posted_at": (j.get("metadata") or {}).get("createdAt", ""),
                    "scraped_at": datetime.utcnow().isoformat(),
                    "saved": job_store.get(uid, {}).get("saved", False),
                    "applied": job_store.get(uid, {}).get("applied", False),
                })
        except Exception as e:
            print(f"[MCF] Error for '{query}': {e}")
    return jobs


async def scrape_indeed(client: httpx.AsyncClient) -> list[dict]:
    """Scrape Indeed SG via their public search HTML (no API key needed)."""
    jobs = []
    seen = set()
    for query in INDEED_QUERIES:
        try:
            url = f"https://sg.indeed.com/jobs?q={query.replace(' ', '+')}&sort=date&fromage=7"
            r = await client.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=20)
            html = r.text
            # Extract job cards from Indeed HTML using regex on structured data
            # Indeed embeds JSON data in a script tag
            pattern = r'"jobkey":"([^"]+)".*?"title":"([^"]+)".*?"company":"([^"]+)"'
            matches = re.findall(pattern, html)
            # Also try the newer mosaic data format
            mosaic = re.findall(
                r'"jobKey":"([^"]+)"[^}]*"title":"([^"]+)"[^}]*"company":\{"name":"([^"]+)"',
                html
            )
            all_matches = [(m[0], m[1], m[2]) for m in matches + mosaic]
            for jobkey, title, company in all_matches[:15]:
                if jobkey in seen:
                    continue
                seen.add(jobkey)
                jobs.append({
                    "id": f"indeed-{jobkey}",
                    "source": "Indeed SG",
                    "source_color": "#003A9B",
                    "title": title,
                    "company": company,
                    "salary_min": None,
                    "salary_max": None,
                    "employment_type": "Full Time",
                    "categories": _infer_categories(title),
                    "url": f"https://sg.indeed.com/viewjob?jk={jobkey}",
                    "posted_at": datetime.utcnow().isoformat(),
                    "scraped_at": datetime.utcnow().isoformat(),
                    "saved": job_store.get(f"indeed-{jobkey}", {}).get("saved", False),
                    "applied": job_store.get(f"indeed-{jobkey}", {}).get("applied", False),
                })
        except Exception as e:
            print(f"[Indeed] Error for '{query}': {e}")
    return jobs


def _infer_categories(title: str) -> list[str]:
    t = title.lower()
    cats = []
    if "data" in t:
        cats.append("Data")
    if "finance" in t or "financial" in t:
        cats.append("Finance")
    if "business" in t:
        cats.append("Business Development")
    if "analyst" in t:
        cats.append("Analyst")
    if "operations" in t or "ops" in t:
        cats.append("Operations")
    return cats or ["Analyst"]


# ── Main scrape job ───────────────────────────────────────────────────────────
async def run_scrape():
    global last_scraped
    print(f"[Scraper] Starting at {datetime.utcnow().isoformat()}")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        mcf_jobs, indeed_jobs = await asyncio.gather(
            scrape_mycareersfuture(client),
            scrape_indeed(client),
        )
    all_jobs = mcf_jobs + indeed_jobs
    for j in all_jobs:
        jid = j["id"]
        prev = job_store.get(jid, {})
        job_store[jid] = {**j, "saved": prev.get("saved", False), "applied": prev.get("applied", False)}
    save_store()
    last_scraped = datetime.utcnow()
    print(f"[Scraper] Done — {len(all_jobs)} jobs ({len(mcf_jobs)} MCF, {len(indeed_jobs)} Indeed)")


# ── Scheduler ─────────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup():
    load_store()
    scheduler.add_job(run_scrape, "interval", minutes=30, id="scrape")
    scheduler.start()
    # Run immediately on startup
    asyncio.create_task(run_scrape())


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


# ── API routes ────────────────────────────────────────────────────────────────
@app.get("/api/jobs")
async def get_jobs(
    q: str = Query("", description="Search query"),
    source: str = Query("", description="Filter by source"),
    category: str = Query("", description="Filter by category"),
    sort: str = Query("new", description="new | salary"),
    saved: bool = Query(False),
    applied: bool = Query(False),
):
    jobs = list(job_store.values())
    if saved:
        jobs = [j for j in jobs if j.get("saved")]
    if applied:
        jobs = [j for j in jobs if j.get("applied")]
    if q:
        ql = q.lower()
        jobs = [j for j in jobs if ql in j["title"].lower() or ql in j["company"].lower()]
    if source:
        jobs = [j for j in jobs if j["source"] == source]
    if category:
        cl = category.lower()
        jobs = [j for j in jobs if any(cl in c.lower() for c in j.get("categories", []))]

    if sort == "salary":
        jobs.sort(key=lambda j: j.get("salary_max") or 0, reverse=True)
    else:
        jobs.sort(key=lambda j: j.get("posted_at") or "", reverse=True)

    return {
        "jobs": jobs,
        "total": len(jobs),
        "last_scraped": last_scraped.isoformat() if last_scraped else None,
    }


@app.get("/api/stats")
async def get_stats():
    jobs = list(job_store.values())
    today = datetime.utcnow().date()
    new_today = sum(
        1 for j in jobs
        if j.get("posted_at", "")[:10] == str(today)
    )
    return {
        "total": len(jobs),
        "new_today": new_today,
        "saved": sum(1 for j in jobs if j.get("saved")),
        "applied": sum(1 for j in jobs if j.get("applied")),
        "sources": list({j["source"] for j in jobs}),
        "last_scraped": last_scraped.isoformat() if last_scraped else None,
    }


@app.post("/api/jobs/{job_id}/save")
async def toggle_save(job_id: str):
    if job_id in job_store:
        job_store[job_id]["saved"] = not job_store[job_id].get("saved", False)
        save_store()
        return {"saved": job_store[job_id]["saved"]}
    return JSONResponse({"error": "not found"}, status_code=404)


@app.post("/api/jobs/{job_id}/apply")
async def mark_applied(job_id: str):
    if job_id in job_store:
        job_store[job_id]["applied"] = True
        save_store()
        return {"applied": True}
    return JSONResponse({"error": "not found"}, status_code=404)


@app.post("/api/scrape")
async def trigger_scrape():
    asyncio.create_task(run_scrape())
    return {"message": "Scrape triggered"}


@app.get("/api/health")
async def health():
    return {"status": "ok", "jobs": len(job_store), "last_scraped": last_scraped.isoformat() if last_scraped else None}


# ── Serve frontend ────────────────────────────────────────────────────────────
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "static")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="static")
