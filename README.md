# Silicon River

> An interactive stream of large-model releases powered by AI-enhanced analysis.

Silicon River ingests public LLM catalogues (Hugging Face, OpenRouter), optionally enriches them with Brave web search and three leaderboard clients, applies a keyword-and-rank **milestone heuristic**, and renders an interactive **3D spiral timeline** with filtering and tooltips.

**Latest enhancement (Phase 5, Oct 2026)**: real arena scores imported from **LMArena** (HF `lmarena-ai/leaderboard-dataset`) and **SWE-bench** by `scripts/sync_arena_scores.py`, UTC `timestamptz` storage end to end, HF ingestion filtered by `pipeline_tag`, and a test suite that never touches the network. The legacy in-process leaderboard clients stay **disabled by default** (see [Known gaps](#known-gaps)).

_中文文档请见 [README-zh.md](README-zh.md)._

## ✨ Highlights

- **Immersive 3D Timeline** – Spiral visualization with smooth camera control; click nodes to lock focus and inspect full model metadata with pricing details.

- **AI-Enhanced Analysis** – Optional Brave Search context plus DeepSeek LLM analysis. Leaderboard enrichment is opt-in and off by default.

- **Smart Milestone Detection** – Four-branch heuristic: strong keywords → weak-keyword pairs → timeline position → leaderboard rank (the last branch only fires once arena scores have been imported).

- **Filter-First UX** – Time ranges (30d/6m/1y/all), years, providers, text search, and license filters with instant results and model count display.

- **Data Pipeline** – Python scrapers, Hugging Face sync logs, PostgreSQL storage, incremental jobs, and a 456-case backend test suite (see [Testing](#testing)).

- **Operational Visibility** – In-process latency/success metrics with text and JSON reports; provider avatar blobs cached in PostgreSQL. No distributed cache or multi-instance metrics aggregation.

## Architecture

```mermaid
flowchart LR
    hf["Hugging Face"] --> scrapers["Python scrapers<br/>(HF jobs write sync_log)"]
    orx["OpenRouter"] --> scrapers
    scrapers --> db[("PostgreSQL")]
    db --> analysis["Optional AI analysis<br/>DeepSeek LLM + Brave Search<br/>+ 3 leaderboard clients (off by default)"]
    analysis --> db
    db --> api["FastAPI REST API"]
    api --> spa["React + Three.js SPA"]
```

**Key Components**:
- **Data Ingestion**: Python scrapers fetch models from Hugging Face and OpenRouter. Hugging Face jobs write a `sync_log` row per run; the OpenRouter jobs currently do not (known gap).
- **Real-time Web Search**: Optional Brave Search API context for recent announcements and benchmarks; disabled in `.env.example` until a key is configured.
- **Leaderboard Enrichment**: arena scores are synced from two real sources — LMArena (via the `lmarena-ai/leaderboard-dataset` HF dataset, read as parquet) and SWE-bench (the JSON embedded in `swebench.com`) — by `scripts/sync_arena_scores.py`, which matches leaderboard names onto catalogue `model_id`s and upserts `model_arena_info`. The three legacy in-process clients (SWE-bench / LMSYS Arena / HF Leaderboard) still exist but are disabled by default.
- **AI Analysis**: DeepSeek LLM generates model descriptions from catalogue data and, when enabled, web/leaderboard context.
- **Milestone Detection**: Four-branch heuristic (strong keywords → weak-keyword pairs → timeline rank → leaderboard rank) identifies pivotal models; the leaderboard branch is inert until arena data exists.
- **Observability**: `PerformanceMonitor` keeps a bounded in-process sample window; `performance_reporter` renders text/JSON reports. There is no distributed latency tracking or cache-hit metric.

## Known gaps

These are deliberate, documented limitations, not claims of completeness:

- **The legacy leaderboard lookup is off by default** (`ENABLE_LEADERBOARD_LOOKUP=false`). The three upstream clients can take ~70s combined, far beyond the 30s per-model analysis budget; when an upstream fails they now return empty results with a WARNING instead of hard-coded sample rankings (the mocks were removed in `c9327ec`).
- **Arena sync is a scheduled job, not a request-time lookup.** Scores only move when `scripts/sync_arena_scores.py` runs (weekly on the data-pipeline machine). About a quarter of leaderboard entries still have no catalogue match, so the arena UI is empty for those models.
- **Ingestion runs once a day, not hourly.** Each model currently costs ~1.3s of database round-trips on write, so a full pass takes about an hour; raising the frequency needs the batch-write change tracked in the local issue archive.
- **OpenRouter ingestion does not write `sync_log`.** Only the Hugging Face scrapers record runs.
- **Metrics are per-process.** There is no Redis, no distributed cache, and no aggregation across API instances. `LEADERBOARD_CACHE_TTL` is not read by any code.
- **The test suite used to hit the real network.** Three leaderboard tests mocked only one of three clients, so the other two attempted live requests, timed out, and fell back to sample data — 206s instead of 0.06s, with order-dependent failures. All clients are mocked now; tests must stay hermetic.

## Getting Started
### Prerequisites
- Python 3.11+ (CI uses 3.12) and Node.js 20+
- PostgreSQL 14+ with a database you can administer
- (Optional) Hugging Face access token for higher rate limits

**Secrets**: every credential (database URL, HF token, DeepSeek key) is read from the
environment / a local `.env` file that is git-ignored. The repository contains only
placeholder templates (`.env.example`, `backend/.env.example`, `frontend/.env.example`);
no key, token or connection string with real credentials is committed.

### 1. Backend
```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # macOS/Linux
pip install -r requirements.txt           # scrapers + AI analysis
pip install -r backend/requirements.txt   # FastAPI service (both are needed locally)
pip install -r requirements-dev.txt       # optional: test tools + local pgserver
python scripts/init_db.py           # create tables and indexes
```

> If `python -m venv` fails with an `ensurepip` error (common on macOS, where `python3`
> is a uv/pyenv-managed relocatable build), use `uv venv .venv --python 3.12` instead.
>
> No PostgreSQL at hand? `bash scripts/dev_db.sh start` brings up a local one from the
> `pgserver` wheel inside `.venv` — no Homebrew or Docker required.

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
| **Core** | |
| `DATABASE_URL` | PostgreSQL DSN shared by scrapers and the API (`postgresql://user:password@host:5432/silicon_river`). |
| `TEST_DATABASE_URL` | Disposable PostgreSQL database for running tests. |
| **Data Sources** | |
| `HF_TOKEN` | Optional Hugging Face token used by scraping jobs. |
| `PROVIDERS` | Comma-separated Hugging Face organisations to mirror. |
| `PROVIDERS_OPENROUTER` | Providers to keep when ingesting OpenRouter metadata. |
| `OPENROUTER_MODELS_URL` | Override endpoint for OpenRouter model listings. |
| `HF_DAILY_FETCH_LIMIT` / `OPENROUTER_DAILY_FETCH_LIMIT` | Safety limits for incremental jobs. |
| **AI Enhancement (Phase 4)** | |
| `DEEPSEEK_API_KEY` | Optional; analysis is skipped when unset. |
| `DEEPSEEK_API_URL` | DeepSeek base URL (`https://api.deepseek.com/v1`); must not include `/chat/completions`. |
| `DEEPSEEK_MODEL` | Analysis model (default: `deepseek-chat`). |
| `ENABLE_POST_SCRAPE_ANALYSIS` | Run analysis at the end of a scrape (default: `false`; prefer the separate analysis job). |
| `BRAVE_SEARCH_API_KEY` | Brave Search API key for real-time web queries (get from https://api.search.brave.com) |
| `ENABLE_BRAVE_SEARCH` | Enable/disable Brave Search integration (code default: `true`; `.env.example` ships `false` until a key is set) |
| `BRAVE_SEARCH_TIMEOUT` | Request timeout in seconds (default: 10) |
| `BRAVE_SEARCH_MAX_RETRIES` | Retry count on failure (default: 3) |
| `ENABLE_LEADERBOARD_LOOKUP` | Online leaderboard lookup during analysis (default: `false`; see [Known gaps](#known-gaps)) |
| **Frontend** | |
| `VITE_API_BASE` | Frontend API target (defaults to `http://localhost:8000`). |
| **Caching & Performance** | |
| `AVATAR_MAX_BYTES` | Provider avatar size limit in bytes (default: 524288 = 512KB) |
| `AVATAR_CACHE_TTL` | Browser cache duration for avatars in seconds (default: 86400 = 1 day) |

### Loading Data

Run these scripts whenever you need to refresh the catalogue. Hugging Face jobs record each run in `sync_log`; the OpenRouter jobs currently do not. Brave Search and leaderboard enrichment are off unless explicitly enabled.

```bash
# Hugging Face (full sync)
python -m src.scraper.fetch_models

# Hugging Face (daily/partial)
python -m src.scraper.fetch_models_incr_day

# OpenRouter (full sync)
python -m src.scraper.fetch_models_openrouter

# OpenRouter (daily/partial)
python -m src.scraper.fetch_models_openrouter_incr_day

# Legacy: warm the in-process leaderboard cache (no DB write; the real DB path is sync_arena_scores.py)
python scripts/update_leaderboards.py

# Sync arena scores from LMArena + SWE-bench into model_arena_info
python scripts/sync_arena_scores.py --source all

# Re-analyze and update existing models (periodically or on demand)
python -m src.scraper.reanalyze_models --older-than-days 7 --no-confirm
```

**Performance**: this repository ships no benchmark results. Per-model latency depends on the LLM and the optional upstream APIs; with leaderboard lookup disabled (the default) no leaderboard cache is involved. Provider avatars are cached inside PostgreSQL; subsequent API calls serve the binary directly or fall back to the upstream URL with size limits (`AVATAR_MAX_BYTES`).

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
- AI-powered milestone badges highlight pivotal models using the four-branch detection heuristic (keywords, timeline position, and leaderboard rank when available).

## Testing

Install the development requirements first (they are no longer part of the production requirements):

```bash
pip install -r requirements-dev.txt
export TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/silicon_river_test   # macOS/Linux
# set TEST_DATABASE_URL=...                                                        # Windows
.venv/bin/python -m pytest tests/ -q
```

The backend suite collects **456 cases and takes about 22 seconds** (`456 passed`).

Two history notes, because both caused real confusion:

- Before 2026-10-18 the baseline was `148 passed, 33 skipped`: the `async def` cases were skipped because `pytest-asyncio` was not installed, so they had **never actually run**. Installing it surfaced five stale mocks, now fixed.
- The suite must not touch the network. Three leaderboard tests used to mock one client out of three, so the rest hit live endpoints, timed out after ~70s each, and fell back to hard-coded sample data (order-dependent failures).

The suite provisions the schema, truncates between cases, and exercises ingestion helpers, API endpoints, and the milestone algorithm. Database-backed tests skip when `TEST_DATABASE_URL` is unset. CI (`.github/workflows/ci.yml`) runs the same suite against a `postgres:16` service plus a frontend `npm ci && npm run build`.

**Coverage includes**:
- Data scraper transformations (Hugging Face and OpenRouter format parsing)
- API endpoint validation (timeline filtering, avatar caching, arena score queries)
- Database schema integrity (indexes, constraints, join operations)
- Milestone detection algorithm (four-branch strategy validation)
- Search client behaviour (caching, retries, error paths)
- Graceful API degradation and error handling

## Project Layout

```text
backend/              FastAPI application (uvicorn entrypoint lives here)
frontend/             React + Vite single-page app (Timeline3D, filters)
scripts/              Database bootstrap and maintenance CLIs
src/scraper/          Hugging Face and OpenRouter ingestion jobs
src/analysis/         AI-enhanced analysis (Brave Search, leaderboards, milestone detection)
tests/                Pytest suite (456 backend cases)
.github/workflows/    CI (backend pytest + frontend build)
.env.example          Environment variable template
requirements.txt      Runtime Python dependencies
requirements-dev.txt  Test tools + local PostgreSQL (pgserver)
```

**Phase 4 Additions**:
- `src/analysis/brave_search.py` – Brave Search API client with caching and retry logic
- `src/analysis/async_analyzer.py` – Async model analyzer with real-time context
- `src/analysis/leaderboard_aggregator.py` – 3 leaderboard clients with in-memory caching and model name normalization (disabled unless `ENABLE_LEADERBOARD_LOOKUP=true`)
- `src/analysis/performance_monitor.py` – In-process latency tracking and statistics (bounded sample window)
- `src/analysis/performance_reporter.py` – Performance reporting in text and JSON formats
- `src/scraper/reanalyze_models.py` – Model re-analysis tool (three strategies)
- `scripts/update_leaderboards.py` – Warms the in-process leaderboard cache; does not persist to PostgreSQL

## License
MIT License – see [LICENSE](LICENSE).
