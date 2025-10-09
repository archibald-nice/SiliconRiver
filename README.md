# Silicon River

> Unified pipeline that mirrors Hugging Face model metadata into PostgreSQL and serves it through a FastAPI + React stack.

Need a Chinese version? See [README-zh.md](README-zh.md).

## Project Overview
- Scrape Hugging Face organisations listed in `PROVIDERS`, normalise records, and persist them to PostgreSQL.
- Serve a REST API for catalogue browsing, timeline exploration, and provider statistics.
- Deliver an interactive React + Three.js dashboard that visualises the catalogue and timeline.
- Package the scraper, API, and frontend so they can be deployed independently or as a single stack.

## Architecture at a Glance
```text
Hugging Face Hub
       |
       v
Scraper (Python) --> PostgreSQL <-- FastAPI REST API --> React + Three.js Dashboard
                       |
                       v
                Sync Log & Tests
```

## Repository Layout
```text
SiliconRiver/
|- backend/              FastAPI application entry point and dependencies
|  |- main.py
|  |- requirements.txt
|- scripts/
|  |- init_db.py         PostgreSQL schema bootstrap script
|- src/
|  |- scraper/
|     |- fetch_models.py Hugging Face ingestion script
|- frontend/             React + Tailwind single page app (Vite build)
|- tests/                pytest suite covering the ingestion workflow
|- data/                 Local sample database (SQLite) for exploration
|- requirements.txt      Shared Python dependencies for scraper/tests
|- .env.example          Root environment template (HF token, providers, DB)
```

## Core Components
### Scraper (`src/scraper/fetch_models.py`)
- Uses the Hugging Face Hub SDK to list models per provider, maps them to `ModelRecord`, and writes to `models` and `sync_log` tables.
- Normalises timestamps to UTC strings, truncates long descriptions, and stores tags as JSON.
- Reuses `scripts.init_db.create_schema` to guarantee tables and indexes exist before inserting.

### Database Schema (`scripts/init_db.py`)
- Defines `models` (unique `model_id`, metadata fields, audit timestamps) and `sync_log` (per-run metrics).
- Adds indexes on provider, creation date, and sync activity for efficient filtering.

### FastAPI Backend (`backend/main.py`)
- Exposes `/api/models`, `/api/models/{model_id}`, `/api/timeline`, `/api/stats/providers`, and `/health`.
- Implements filtering by provider, tag, search term, pagination, and timeline presets (30d, 6m, 1y) or custom year.
- Uses Pydantic response models and psycopg 3 with `dict_row` cursors for typed responses.
- Enables permissive CORS and reads `DATABASE_URL` from the project `.env` file.

### React Frontend (`frontend/`)
- Vite + React 18 + TypeScript + Tailwind UI, backed by React Query for data fetching and caching.
- `Home.tsx` provides a tabbed timeline and list view, filter panel, and paginated model cards.
- `Timeline3D.tsx` renders an interactive Three.js curve with hover tooltips and scroll navigation.
- Environment variable `VITE_API_BASE` controls which backend instance the SPA targets.

### Test Suite (`tests/test_fetch_models.py`)
- Spins up the ingestion pipeline against `TEST_DATABASE_URL`, mocking the Hugging Face client.
- Verifies deduplication, sync log entries, and exercises the FastAPI timeline endpoint via `TestClient`.
- Requires psycopg and `fastapi[testclient]`; skips automatically if prerequisites are missing.

## Environment Configuration
Environment values can be supplied via the root `.env`, service-specific `.env` files, or runtime variables.

| Variable | Purpose | Notes |
|----------|---------|-------|
| `HF_TOKEN` | Optional Hugging Face token for higher rate limits | Stored in root `.env` |
| `PROVIDERS` | Comma-separated organisation IDs to mirror (for example `meta-llama,google`) | Required for scraper |
| `DATABASE_URL` | PostgreSQL DSN used by scraper and API | Example `postgresql://user:pass@host:5432/silicon_river` |
| `TEST_DATABASE_URL` | PostgreSQL DSN for pytest runs | Point to a disposable database |
| `VITE_API_BASE` | Backend base URL consumed by the frontend SPA | Defaults to `http://localhost:8000` |

Sample dataset: `data/silicon_river.db` is a pre-filled SQLite snapshot for quick exploration or offline debugging.

## Quick Start
1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd SiliconRiver
   ```
2. **Create a virtual environment and install Python dependencies**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   # source .venv/bin/activate  # macOS/Linux
   pip install -r requirements.txt
   pip install -r backend/requirements.txt
   ```
3. **Create environment files**
   ```bash
   cp .env.example .env
   cp backend/.env.example backend/.env
   cp frontend/.env.example frontend/.env
   ```
   Then update:
   - `HF_TOKEN` (optional): Hugging Face token for higher rate limits.
   - `PROVIDERS` (required): Comma-separated list of provider IDs to mirror.
   - `DATABASE_URL`: PostgreSQL connection string, e.g. `postgresql://user:password@host:5432/silicon_river`.
   - `VITE_API_BASE`: FastAPI base URL, defaults to `http://localhost:8000`.
4. **Initialise the schema**
   ```bash
   python scripts/init_db.py
   ```
5. **Run the scraper** (repeat to refresh data)
   ```bash
   python src/scraper/fetch_models.py
   ```
6. **Start the API**
   ```bash
   cd backend
   uvicorn main:app --reload --port 8080
   ```
7. **Launch the frontend** (new terminal)
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   Visit `http://localhost:5173/`; the dev server proxies API calls to `VITE_API_BASE`.

## API Surface
| Endpoint | Description | Query Parameters |
|----------|-------------|------------------|
| `GET /api/models` | Paginated catalogue of models | `page`, `page_size`, `provider`, `tag`, `search` |
| `GET /api/models/{model_id}` | Single model details | None |
| `GET /api/timeline` | Timeline slice by preset or custom year | `preset`, `year`, `page`, `page_size`, `sort` |
| `GET /api/stats/providers` | Provider-level model counts | None |
| `GET /health` | Health probe | None |

## Data Refresh Workflow
- Schedule `python src/scraper/fetch_models.py` with cron, GitHub Actions, or another job runner.
- Monitor `sync_log` for processed versus inserted totals, run status, and errors.
- Consider pruning or archiving historical records if the catalogue grows quickly.

## Testing & Quality
- Set `TEST_DATABASE_URL` to a disposable PostgreSQL instance and run `pytest`.
- Tests reset `models` and `sync_log` between runs to keep expectations deterministic.
- Manually check `/health` and `/api/stats/providers` after seeding to confirm API connectivity.

## Deployment Notes
- **Backend**: `uvicorn main:app --host 0.0.0.0 --port 8000` with `DATABASE_URL` configured and outbound access to Hugging Face if scraping in the same environment.
- **Frontend**: `npm run build` to produce `frontend/dist/`, then host the static bundle (Vercel, Netlify, Cloudflare Pages, etc.).
- **Database**: PostgreSQL required; run `python scripts/init_db.py` during provisioning to ensure the schema exists.
- **Secrets management**: Store tokens and DSNs in your platform secret store instead of committing `.env` files.

## Known Limitations & Future Improvements
- Timestamps are stored as text; migrating to `TIMESTAMP WITH TIME ZONE` would unlock richer SQL analytics.
- Ensure static assets and docs are served as UTF-8 to keep international text readable.
- Frontend currently focuses on browsing; consider adding search suggestions, sorting options, or richer model detail pages.
- Large provider catalogues may require pagination tuning (for example a smaller timeline `page_size`) to keep responses fast.

## License
MIT License - see [LICENSE](LICENSE).
