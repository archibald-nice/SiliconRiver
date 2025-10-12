"""Daily incremental fetcher for OpenRouter providers."""
from __future__ import annotations

import logging
import os

from src.scraper import fetch_models_openrouter as openrouter_fetch

LOGGER = logging.getLogger("silicon_river.fetch.openrouter.daily")
LOGGING_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOGGING_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_LIMIT = 300


def main() -> None:
    limit = int(os.getenv("OPENROUTER_DAILY_FETCH_LIMIT", str(DEFAULT_LIMIT)))
    LOGGER.info("Running OpenRouter daily fetch with limit=%s", limit)
    summary = openrouter_fetch.fetch_and_store(limit=limit)
    for provider, (processed, inserted) in summary.items():
        LOGGER.info("Provider %s: processed=%s inserted=%s", provider, processed, inserted)


if __name__ == "__main__":
    main()
