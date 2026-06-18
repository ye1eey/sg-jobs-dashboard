# SG Jobs Dashboard — Analyst & Biz Dev
Real-time Singapore job scraper with auto-refresh. Pulls from **MyCareersFuture** (gov API) and **Indeed SG** every 30 minutes. One-click links to LinkedIn, Glassdoor, JobStreet, NodeFlair. AI-powered job match analysis.

---

## Deploy to Railway (recommended, free)

1. **Push to GitHub**
   ```bash
   git init
   git add .
   git commit -m "initial"
   gh repo create sg-jobs-dashboard --public --push
   ```

2. **Deploy on Railway**
   - Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
   - Select your repo — Railway auto-detects the Dockerfile
   - Click **Deploy**
   - Your live URL appears in ~2 minutes (e.g. `https://sg-jobs-dashboard-production.up.railway.app`)

3. Done — dashboard auto-scrapes on startup and every 30 minutes.

---

## Deploy to Render (alternative, free)

1. Push to GitHub (same as above)
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Render reads `render.yaml` automatically → click **Create Web Service**
5. Live in ~3 minutes

---

## Run locally (testing)

```bash
# Install deps
cd backend
pip install -r requirements.txt

# Run server
uvicorn main:app --reload --port 8000

# Open dashboard
open http://localhost:8000
```

---

## What it scrapes

| Source | Method | Frequency |
|--------|--------|-----------|
| MyCareersFuture | Official JSON API | Every 30 min |
| Indeed SG | HTML scrape | Every 30 min |
| LinkedIn | Deep link (opens browser) | Manual |
| Glassdoor | Deep link (opens browser) | Manual |
| JobStreet | Deep link (opens browser) | Manual |

LinkedIn and Glassdoor require login cookies — they cannot be scraped headlessly without a paid proxy service. The dashboard provides pre-filtered direct links that open in your browser where you're already logged in.

---

## Add LinkedIn scraping (optional, paid)

Sign up at [rapidapi.com](https://rapidapi.com) → search "LinkedIn Jobs API" → get an API key. Then add to `backend/main.py`:

```python
async def scrape_linkedin_api(client, api_key):
    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "linkedin-jobs-search.p.rapidapi.com"}
    r = await client.get("https://linkedin-jobs-search.p.rapidapi.com/", headers=headers,
                         params={"keywords": "analyst business development", "location": "Singapore", "dateSincePosted": "past24Hours"})
    ...
```

---

## Project structure

```
sg-jobs-dashboard/
├── backend/
│   ├── main.py          # FastAPI app + scraper + scheduler
│   ├── requirements.txt
│   └── jobs.json        # Persisted job store (auto-created)
├── frontend/
│   └── static/
│       └── index.html   # Dashboard UI
├── Dockerfile
├── railway.toml         # Railway config
└── render.yaml          # Render config
```
