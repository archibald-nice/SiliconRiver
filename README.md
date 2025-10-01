# Silicon River

> Unified pipeline that mirrors Hugging Face model metadata into PostgreSQL and serves it through a FastAPI + React stack.

Silicon River fetches model cards from Hugging Face providers, persists them to PostgreSQL, exposes a read API, and renders an interactive dashboard. Everything is packaged so the scraper, API, and UI can be deployed separately or together.

## Features
- `src/scraper/fetch_models.py` ingests metadata for the providers listed in `PROVIDERS` and stores the records in PostgreSQL.
- `backend/main.py` exposes REST endpoints for listing models, querying details, and summarising provider stats.
- `frontend/` hosts a Vite + React 18 + Tailwind UI that consumes the API and visualises the catalogue.
- `tests/` includes pytest coverage for the ingestion workflow (mocked Hugging Face client, conflict handling, sync log recording).

## Tech Stack
- **Backend**: FastAPI, Pydantic, PostgreSQL, python-dotenv, psycopg 3.
- **Data ingestion**: Hugging Face Hub SDK, tqdm.
- **Frontend**: React 18, Vite, @tanstack/react-query, Tailwind CSS, Headless UI, Hero Icons.
- **Tooling**: pytest, TypeScript, Vite build toolchain.

## Project Layout
```text
SiliconRiver/
|- backend/              FastAPI application entry point and deps
|  |- main.py
|  |- requirements.txt
|- scripts/
|  |- init_db.py         PostgreSQL schema bootstrap script
|- src/
|  |- scraper/
|     |- fetch_models.py Hugging Face ingestion script
|- frontend/             React + Tailwind single page app
|- tests/                pytest suite for data ingestion
|- requirements.txt      Shared Python dependencies (scraper/tests)
|- .env.example          Root env template (HF token, providers, DB)
```

## Prerequisites
- Python 3.11+
- Node.js 20+
- npm (or another Node package manager)
- PostgreSQL database reachable from the scraper and API
- Hugging Face access token (optional but recommended to avoid rate limits)

## Getting Started
1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd SiliconRiver
   ```
2. **Install Python dependencies**
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
   Fill in:
   - `HF_TOKEN` – optional Hugging Face token for higher rate limits.
   - `PROVIDERS` – comma-separated list of organisation IDs to mirror.
   - `DATABASE_URL` – e.g. `postgresql://user:password@host:5432/silicon_river`.
   - `VITE_API_BASE` – URL of the FastAPI service (default `http://localhost:8000`).
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
   uvicorn main:app --reload --port 8000
   ```
7. **Launch the frontend** (separate terminal)
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   Visit `http://localhost:5173/` – the app proxies API requests to `VITE_API_BASE`.

## API Overview
- `GET /api/models` – paginated catalogue (`page`, `page_size`, `provider`, `tag`, `search`).
- `GET /api/models/{model_id}` – single model details.
- `GET /api/stats/providers` – model counts grouped by provider.
- `GET /health` – simple health probe.

## Testing
```bash
pytest
```
The ingestion tests require a PostgreSQL database. Set `TEST_DATABASE_URL` before running the suite to point to a disposable database; the test module truncates `models` and `sync_log` between runs.

## Deployment Notes
- **Scheduled refresh**: run `python src/scraper/fetch_models.py` from GitHub Actions, Render Cron, or another scheduler to keep the catalogue current.
- **Database**: the application expects a PostgreSQL DSN (only `postgresql://` URIs are supported by the default helpers).
- **Backend hosting**: e.g. Render web service (`uvicorn main:app --host 0.0.0.0 --port 8000`). Ensure the DB is reachable and seeded.
- **Frontend hosting**: build with `npm run build` and deploy the static `frontend/dist/` directory (Vercel, Netlify, etc.).

## License
MIT License – see [LICENSE](LICENSE).
