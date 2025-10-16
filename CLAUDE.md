# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Silicon River is an interactive 3D timeline visualization of large language model releases. It scrapes model metadata from Hugging Face and OpenRouter, stores it in PostgreSQL, and presents it through a Three.js-powered spiral timeline interface.

## Architecture

```
                 ┌────────────────────┐
  Hugging Face   │  Data Scrapers     │
  OpenRouter ──▶ │  (Python, Sync Log)│
                 └─────────┬──────────┘
                           │
                     PostgreSQL
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
 FastAPI REST API                    React + Three.js Frontend
```

### Key Components

- **Backend (FastAPI)**: [`backend/main.py`](backend/main.py) - Core API server with typed responses using Pydantic
- **Frontend (React)**: [`frontend/src/`](frontend/src/) - SPA with Vite, Tailwind CSS, and Three.js
- **Data Ingestion**: [`src/scraper/`](src/scraper/) - Python scripts for fetching model data
- **Database**: PostgreSQL with schema initialized via [`scripts/init_db.py`](scripts/init_db.py)

## Common Development Commands

### Backend Development
```bash
# Start development server
uvicorn backend.main:app --reload --port 8000

# Initialize database
python scripts/init_db.py

# Run tests
pytest

# Data ingestion (choose based on needs)
python src/scraper/fetch_models.py                    # Hugging Face full sync
python src/scraper/fetch_models_incr_day.py --limit 200  # Hugging Face daily
python src/scraper/fetch_models_openrouter.py        # OpenRouter full sync
python src/scraper/fetch_models_openrouter_incr_day.py --limit 300  # OpenRouter daily
```

### Frontend Development
```bash
cd frontend
npm install
npm run dev        # Development server on http://localhost:5173
npm run build      # Production build
```

## Core API Endpoints

- **`GET /api/timeline`** - Primary endpoint for 3D timeline data with filtering and pagination
- **`GET /api/models`** - Paginated model catalogue with search/filtering
- **`GET /api/stats/providers`** - Provider statistics
- **`GET /api/providers/{id}/avatar`** - Cached provider avatar serving
- **`GET /health`** - Health check endpoint

## Frontend Architecture

- **Timeline3D Component**: [`frontend/src/components/Timeline3D.tsx`](frontend/src/components/Timeline3D.tsx) - Main 3D visualization using Three.js
- **Data Fetching**: React Query for server state management
- **Styling**: Tailwind CSS with custom theme via [`frontend/src/theme/`](frontend/src/theme/)
- **Timeline Logic**: Core algorithms in [`frontend/src/timeline/`](frontend/src/timeline/)

## Environment Configuration

Copy `.env.example` to `.env` and configure:

- **`DATABASE_URL`** - PostgreSQL connection string (shared by scrapers and API)
- **`HF_TOKEN`** - Optional Hugging Face token for higher rate limits
- **`PROVIDERS`** - Comma-separated Hugging Face organizations to mirror
- **`PROVIDERS_OPENROUTER`** - OpenRouter providers to keep
- **`VITE_API_BASE`** - Frontend API target (default: `http://localhost:8000`)
- **`TEST_DATABASE_URL`** - Separate database for running tests

## Database Schema

Key tables:
- **`models`** - Model metadata with tags, pricing, and rankings
- **`providers`** - Provider information with cached avatars
- **`sync_log`** - Audit trail for data ingestion runs

## Testing

```bash
# Set test database URL first (Windows)
set TEST_DATABASE_URL=postgresql://user:pass@localhost:5433/silicon_river_test

# Run all tests
pytest
```

Tests cover scraper functionality and API endpoints. They automatically provision and clean up database schema.

## Key Features Implementation

- **3D Spiral Timeline**: Models positioned chronologically along a 3D curve with interactive navigation
- **Avatar Caching**: Provider avatars fetched and cached in PostgreSQL with fallback to upstream
- **Price Tooltips**: For closed-source models, pricing information displayed on hover
- **Filter-First Workflow**: Real-time filtering by time range, provider, name, and open-source status
- **Responsive Design**: Mobile-friendly with touch support for timeline interaction

## Development Notes

- Timeline data is optimized for rendering with hundreds/thousands of models
- Avatar fetching includes size limits and timeout handling
- Frontend uses TypeScript with strict typing for API responses
- Database queries use proper indexing for performance on large datasets
- All timestamps handled in UTC for consistency