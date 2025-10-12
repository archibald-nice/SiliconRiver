"""Daily incremental fetcher for Hugging Face providers."""
from __future__ import annotations

import logging
import os

from src.scraper import fetch_models as hf_fetch

LOGGER = logging.getLogger("silicon_river.fetch.hf.daily")
LOGGING_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOGGING_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_LIMIT = 200


def main() -> None:
    limit = int(os.getenv("HF_DAILY_FETCH_LIMIT", str(DEFAULT_LIMIT)))
    LOGGER.info("Running Hugging Face daily fetch with limit=%s", limit)
    summary = hf_fetch.fetch_and_store(limit=limit)
    for provider, (processed, inserted) in summary.items():
        LOGGER.info("Provider %s: processed=%s inserted=%s", provider, processed, inserted)


if __name__ == "__main__":
    main()
