# Silicon River

An interactive stream of large-model releases. Silicon River ingests public catalogues, stores clean metadata in PostgreSQL, and renders a Three.js timeline that can be explored with filters and rich tooltips.

_中文文档请见 [README-zh.md](README-zh.md)。_

## Highlights
- **Immersive 3D timeline** – Scroll or drag to move between nodes, click to lock focus, and inspect release metadata in a lightweight bubble. Price details surface on hover for closed-source entries.
- **Filter-first workflow** – Compact chips toggle time ranges (including an unlimited view), specific years, providers, text search, and open/closed licensing states without reloading the page.
- **Reliable ingestion** – Python scrapers mirror Hugging Face and OpenRouter catalogues, normalise provider avatars, and keep a sync log for audits.
- **FastAPI + PostgreSQL core** – Typed responses, avatar caching, and pagination-ready endpoints power the SPA and external consumers alike.
- **React + React Query frontend** – Vite build, Tailwind styling, and granular caching keep the interface fast even with thousands of nodes.

## Architecture
```text
                 ┌────────────────────┐
   Hugging Face  │  Scrapers (Python) │
   OpenRouter ──▶│  + Sync Log        │
                 └─────────┬──────────┘
                           │
                     PostgreSQL
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
 FastAPI REST API                  React + Three.js SPA
  (/api/timeline, etc.)           (Timeline3D, filters)
```

## Getting Started
### Prerequisites
- Python 3.11+ and Node.js 18+
- PostgreSQL 14+ with a database you can administer
- (Optional) Hugging Face access token for higher rate limits

### 1. Backend
```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # macOS/Linux
pip install -r requirements.txt
python scripts/init_db.py           # create tables and indexes
```

Copy `.env.example` to `.env` and adjust the values described below. Start the API with:
```bash
uvicorn backend.main:app --reload --port 8000
```
The server listens on `http://localhost:8000` and exposes `/health` for quick readiness checks.

### 2. Frontend
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```
Set `VITE_API_BASE` in `frontend/.env` (defaults to `http://localhost:8000`).

### Environment Variables
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL DSN shared by scrapers and the API (`postgresql://user:password@host:5432/silicon_river`). |
| `HF_TOKEN` | Optional Hugging Face token used by scraping jobs. |
| `PROVIDERS` | Comma-separated Hugging Face organisations to mirror. |
| `PROVIDERS_OPENROUTER` | Providers to keep when ingesting OpenRouter metadata. |
| `OPENROUTER_MODELS_URL` | Override endpoint for OpenRouter model listings. |
| `HF_DAILY_FETCH_LIMIT` / `OPENROUTER_DAILY_FETCH_LIMIT` | Safety limits for incremental jobs. |
| `VITE_API_BASE` | Frontend API target. |
| `TEST_DATABASE_URL` | Disposable PostgreSQL database for running tests. |

### Loading Data
Run these scripts whenever you need to refresh the catalogue. Each command respects the configured provider lists and records the run inside `sync_log`.

```bash
# Hugging Face (full sync)
python src/scraper/fetch_models.py

# Hugging Face (daily/partial)
python src/scraper/fetch_models_incr_day.py --limit 200

# OpenRouter (full sync)
python src/scraper/fetch_models_openrouter.py

# OpenRouter (daily/partial)
python src/scraper/fetch_models_openrouter_incr_day.py --limit 300
```

Provider avatars are cached inside PostgreSQL; subsequent API calls serve the binary directly or fall back to the upstream URL with size limits (`AVATAR_MAX_BYTES`).

## API Overview
| Endpoint | Purpose | Key Parameters |
|----------|---------|----------------|
| `GET /api/timeline` | Ordered timeline window for the 3D view. | `preset` (`30d`, `6m`, `1y`, `all`), `year`, `page`, `page_size`, `provider`, `model_name`, `open_source`, `sort`. |
| `GET /api/models` | Paginated catalogue query. | `page`, `page_size`, `provider`, `tag`, `search`. |
| `GET /api/stats/providers` | Model counts grouped by provider. | – |
| `GET /api/providers/{id}/avatar` | Serves cached provider avatars with HTTP caching headers. | – |
| `GET /health` | Lightweight health probe. | – |

All endpoints return JSON and honour CORS for browser clients.

## Frontend Features
- Scroll the canvas or use the mouse wheel to move along the spiral timeline; click a node to lock the focus.
- Focus bubbles show provider name, release time (localised), open/closed badge, and description; hovering the badge reveals pricing when available.
- Filter chips and search input update the query immediately without page reloads; the total node count is shown underneath the filters.
- Provider avatars are prefetched once per session to minimise pop-in when focusing nodes.

## Testing
```bash
set TEST_DATABASE_URL=postgresql://user:pass@localhost:5433/silicon_river_test  # Windows
# export TEST_DATABASE_URL=...                                                 # macOS/Linux
pytest
```
The suite provisions the schema, truncates it between cases, and exercises both the ingestion helpers and `/api/timeline`. Tests skip automatically if PostgreSQL or the FastAPI test client is unavailable.

## Project Layout
```text
backend/           FastAPI application (uvicorn entrypoint lives here)
frontend/          React + Vite single-page app (Timeline3D, filters)
scripts/           Database bootstrap utilities
src/scraper/       Hugging Face and OpenRouter ingestion jobs
tests/             Pytest coverage for scraper + API integration
.env.example       Environment variable template
requirements.txt   Shared Python dependencies
```

## License
MIT License – see [LICENSE](LICENSE).
