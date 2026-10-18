"""模型评分（arena）真实数据源。

两个上游：

* :mod:`src.scraper.arena.lmarena` —— LMArena 官方排行榜（HF datasets-server）；
* :mod:`src.scraper.arena.swebench` —— SWE-bench 官方排行榜（页面内嵌 JSON）。

配套 :mod:`src.scraper.arena.matcher` 把排行榜模型名映射到本仓库
``model_id``，:mod:`scripts.sync_arena_scores` 负责落库。

**不允许任何假数据兜底**：上游失败就抛异常/返回空，绝不编造排名
（ISSUE-001 事故，详见 docs/issues/001-arena-score-pipeline-broken.md）。
"""
from __future__ import annotations

from .lmarena import ArenaFetchError, ArenaRow, fetch_latest_rows
from .matcher import (
    ArenaMatch,
    load_aliases,
    match_arena_rows,
    normalize_name,
    sizes_compatible,
)
from .swebench import SweBenchFetchError, SweBenchParseError, fetch_swebench_rows

__all__ = [
    "ArenaFetchError",
    "ArenaMatch",
    "ArenaRow",
    "SweBenchFetchError",
    "SweBenchParseError",
    "fetch_latest_rows",
    "fetch_swebench_rows",
    "load_aliases",
    "match_arena_rows",
    "normalize_name",
    "sizes_compatible",
]
