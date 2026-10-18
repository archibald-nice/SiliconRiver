"""Daily incremental fetcher for OpenRouter providers."""
from __future__ import annotations

import logging
import os

from src.scraper import fetch_models_openrouter as openrouter_fetch

LOGGER = logging.getLogger("silicon_river.fetch.openrouter.daily")
LOGGING_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOGGING_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")

# ISSUE-030：这是**白名单过滤之后**的安全阀，不是丢弃源数据的窗口。
# 0 = 不截断（推荐）：limit 只在「已命中白名单的模型太多、需要限流」时才有意义，
# 截断会打 WARNING 而不是静默丢数据。旧值 300 小于上游总数，曾整段吃掉尾部厂商。
DEFAULT_LIMIT = 0


def main() -> None:
    limit = int(os.getenv("OPENROUTER_DAILY_FETCH_LIMIT", str(DEFAULT_LIMIT)))
    LOGGER.info("Running OpenRouter daily fetch with limit=%s", limit)
    summary = openrouter_fetch.fetch_and_store(limit=limit)
    for provider, (processed, inserted) in summary.items():
        LOGGER.info("Provider %s: processed=%s inserted=%s", provider, processed, inserted)

    # 爬虫完成后，运行AI分析
    try:
        from src.scraper.analysis_orchestrator import run_post_scrape_analysis

        LOGGER.info("OpenRouter爬虫完成，开始运行AI分析...")
        analysis_result = run_post_scrape_analysis()
        LOGGER.info(f"AI分析完成: {analysis_result}")
    except Exception as e:
        LOGGER.warning(f"AI分析运行失败: {e}")


if __name__ == "__main__":
    main()
