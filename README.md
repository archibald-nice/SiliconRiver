# Silicon River

> An interactive stream of large-model releases powered by AI-enhanced analysis.

Silicon River ingests public LLM catalogues (Hugging Face, OpenRouter), augments them with **real-time web search** and **multi-leaderboard cross-validation**, applies sophisticated **milestone detection**, and renders an immersive **3D spiral timeline** with rich filtering and tooltips.

**🌟 Latest Enhancement (Phase 4, Nov 2025)**: Production-grade performance monitoring, multi-leaderboard integration (SWE-bench, LMSYS Arena, HF Leaderboard), and 4-tier milestone detection strategy.

_中文文档请见 [README-zh.md](README-zh.md)。_

## ✨ Highlights

- **Immersive 3D Timeline** – Spiral visualization with smooth camera control; click nodes to lock focus and inspect full model metadata with pricing details.

- **AI-Enhanced Analysis** – Real-time web search (Brave API) + LLM analysis + multi-leaderboard validation for accurate model profiling.

- **Smart Milestone Detection** – 4-tier strategy combining keyword analysis, timeline position, and authoritative leaderboard rankings (SWE-bench, LMSYS, HF).

- **Filter-First UX** – Time ranges (30d/6m/1y/all), years, providers, text search, and license filters with instant results and model count display.

- **Reliable Data Pipeline** – Python scrapers with sync logs, PostgreSQL caching, incremental updates, and comprehensive test coverage (75+ test cases).

- **Production-Ready** – Complete performance monitoring, distributed caching, graceful API degradation, and comprehensive runbooks.

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

            ┌─────────────────────────────┐
            │  AI-Enhanced Analysis       │
            ├─────────────────────────────┤
            │ • Brave Search API          │
            │ • 4 Leaderboard APIs        │
            │ • DeepSeek LLM Analysis     │
            │ • 4-Tier Milestone Detection│
            │ • Performance Monitoring    │
            └─────────────────────────────┘
```

**Key Components**:
- **Data Ingestion**: Python scrapers fetch models from Hugging Face and OpenRouter with sync logs for audit trails
- **Real-time Web Search**: Brave Search API provides latest model announcements and benchmarks
- **Multi-Leaderboard Validation**: 3 authoritative sources (SWE-bench, LMSYS Arena, HF Leaderboard) verify model capabilities
- **AI Analysis**: DeepSeek LLM generates rich model descriptions using web context and leaderboard data
- **Milestone Detection**: 4-tier algorithm (strong keywords → weak keywords → timeline rank → leaderboard rank) identifies pivotal models
- **Performance Monitoring**: Distributed latency tracking, cache hit metrics, and API success rates ensure production reliability

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
| `BRAVE_SEARCH_API_KEY` | Brave Search API key for real-time web queries (get from https://api.search.brave.com) |
| `ENABLE_BRAVE_SEARCH` | Enable/disable Brave Search integration (default: true) |
| `BRAVE_SEARCH_TIMEOUT` | Request timeout in seconds (default: 10) |
| `BRAVE_SEARCH_MAX_RETRIES` | Retry count on failure (default: 3) |
| `LEADERBOARD_CACHE_TTL` | Cache duration for leaderboard data in seconds (default: 3600) |
| **Frontend** | |
| `VITE_API_BASE` | Frontend API target (defaults to `http://localhost:8000`). |
| **Caching & Performance** | |
| `AVATAR_MAX_BYTES` | Provider avatar size limit in bytes (default: 524288 = 512KB) |
| `AVATAR_CACHE_TTL` | Browser cache duration for avatars in seconds (default: 86400 = 1 day) |

**For detailed API configuration and cost analysis, see [docs/core-info-v1/1-API-INTEGRATION-GUIDE.md](docs/core-info-v1/1-API-INTEGRATION-GUIDE.md)**.

### Loading Data

Run these scripts whenever you need to refresh the catalogue. Each command respects the configured provider lists and records the run inside `sync_log`. With Brave Search and leaderboard APIs enabled, new models are enriched with real-time context and multi-dimensional validation.

```bash
# Hugging Face (full sync)
python src/scraper/fetch_models.py

# Hugging Face (daily/partial)
python src/scraper/fetch_models_incr_day.py --limit 200

# OpenRouter (full sync)
python src/scraper/fetch_models_openrouter.py

# OpenRouter (daily/partial)
python src/scraper/fetch_models_openrouter_incr_day.py --limit 300

# Update leaderboard cache (recommended daily)
python scripts/update_leaderboards.py

# Re-analyze and update existing models (periodically or on demand)
python -m src.scraper.reanalyze_models --older-than-days 7 --no-confirm
```

**Performance**: Single model analysis completes in 10-12 seconds on average (target <15s), with 80-85% leaderboard cache hit rates. Provider avatars are cached inside PostgreSQL; subsequent API calls serve the binary directly or fall back to the upstream URL with size limits (`AVATAR_MAX_BYTES`).

**For detailed monitoring and optimization, see [docs/core-info-v1/3-PERFORMANCE-MONITORING.md](docs/core-info-v1/3-PERFORMANCE-MONITORING.md)**.

## API Overview
| Endpoint | Purpose | Key Parameters |
|----------|---------|----------------|
| `GET /api/timeline` | Ordered timeline window for the 3D view. | `preset` (`30d`, `6m`, `1y`, `all`), `year`, `page`, `page_size`, `provider`, `model_name`, `open_source`, `sort`. |
| `GET /api/models` | Paginated catalogue query. | `page`, `page_size`, `provider`, `tag`, `search`. |
| `GET /api/stats/providers` | Model counts grouped by provider. | – |
| `GET /api/providers/{id}/avatar` | Serves cached provider avatars with HTTP caching headers. | – |
| `GET /health` | Lightweight health probe. | – |

All endpoints return JSON and honour CORS for browser clients.

## Core Documentation

For in-depth guides tailored to specific roles, see [docs/core-info-v1/INDEX.md](docs/core-info-v1/INDEX.md):

| Document | Purpose | Audience | Time |
|----------|---------|----------|------|
| **1-API-INTEGRATION-GUIDE** | Configure Brave Search and 3 leaderboards | Developers, DevOps | 30 min |
| **2-MILESTONE-DETECTION-RULES** | Understand 4-tier milestone algorithm and tuning | Data Scientists, Product | 45 min |
| **3-PERFORMANCE-MONITORING** | Monitor, diagnose, and optimize system | DevOps, SRE | 45 min |
| **4-DEPLOYMENT-OPERATIONS** | Production deployment, maintenance, troubleshooting | DevOps, Ops | 1.5 hours |
| **5-QUICK-REFERENCE-CARD** | Fast command and parameter lookup | All roles | 5-10 min |
| **6-MODEL-REANALYSIS-GUIDE** | Flexibly update existing model data | DevOps, Data Admin | 15-20 min |

**Quick start paths**:
- 🚀 **New Developer**: 5-min Quick Ref → 1-API-INTEGRATION → Core Code
- 🔧 **DevOps/SRE**: 5-min Quick Ref → 3-PERFORMANCE → 4-DEPLOYMENT → 6-REANALYSIS
- 📊 **Data Scientist**: 2-MILESTONE-DETECTION → 3-PERFORMANCE
- 📋 **Product Manager**: README highlights + 2-MILESTONE-DETECTION

## Frontend Features

- Scroll the canvas or use the mouse wheel to move along the spiral timeline; click a node to lock the focus.
- Focus bubbles show provider name, release time (localised), open/closed badge, and description; hovering the badge reveals pricing when available.
- Filter chips and search input update the query immediately without page reloads; the total node count is shown underneath the filters.
- Provider avatars are prefetched once per session to minimise pop-in when focusing nodes.
- AI-powered milestone badges highlight pivotal models based on 4-tier detection algorithm combining keyword analysis, timeline position, and authoritative rankings.

## Testing

```bash
set TEST_DATABASE_URL=postgresql://user:pass@localhost:5433/silicon_river_test  # Windows
# export TEST_DATABASE_URL=...                                                 # macOS/Linux
pytest
```

The test suite (75+ test cases) provisions the schema, truncates it between cases, and exercises ingestion helpers, API endpoints, and the milestone detection algorithm. Tests skip automatically if PostgreSQL or the FastAPI test client is unavailable.

**Coverage includes**:
- Data scraper transformations (Hugging Face and OpenRouter format parsing)
- API endpoint validation (timeline filtering, avatar caching, leaderboard queries)
- Database schema integrity (indexes, constraints, join operations)
- Milestone detection algorithm (4-tier strategy validation)
- Performance monitoring and cache behavior
- Graceful API degradation and error handling

For performance benchmarking, see [docs/core-info-v1/3-PERFORMANCE-MONITORING.md](docs/core-info-v1/3-PERFORMANCE-MONITORING.md).

## Project Layout

```text
backend/              FastAPI application (uvicorn entrypoint lives here)
frontend/             React + Vite single-page app (Timeline3D, filters)
scripts/              Database bootstrap utilities
src/scraper/          Hugging Face and OpenRouter ingestion jobs
src/analysis/         AI-enhanced analysis (Brave Search, leaderboards, milestone detection)
tests/                Pytest coverage for scraper + API integration (75+ cases)
docs/core-info-v1/    Core project documentation (Phase 4)
  ├── 1-API-INTEGRATION-GUIDE.md
  ├── 2-MILESTONE-DETECTION-RULES.md
  ├── 3-PERFORMANCE-MONITORING.md
  ├── 4-DEPLOYMENT-OPERATIONS.md
  ├── 5-QUICK-REFERENCE-CARD.md
  └── INDEX.md
.env.example          Environment variable template
requirements.txt      Shared Python dependencies
```

**Phase 4 Additions**:
- `src/analysis/brave_search.py` – Brave Search API client with caching and retry logic
- `src/analysis/async_analyzer.py` – Async model analyzer with real-time context
- `src/analysis/leaderboard_aggregator.py` – 3 leaderboard APIs with caching and model name normalization
- `src/analysis/performance_monitor.py` – Distributed latency tracking and statistics
- `src/analysis/performance_reporter.py` – Performance reporting in text and JSON formats
- `src/scraper/reanalyze_models.py` – Model re-analysis tool (three strategies)
- `scripts/update_leaderboards.py` – Leaderboard cache maintenance script

See [docs/core-info-v1/INDEX.md](docs/core-info-v1/INDEX.md) for complete documentation navigation.

## License
MIT License – see [LICENSE](LICENSE).
