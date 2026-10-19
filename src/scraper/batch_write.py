"""批量写的开关与切块（ISSUE-034）。

HF 与 OpenRouter 两个写入端共用这几行：`SCRAPER_BATCH_WRITE=0` 立刻退回逐行写
（出问题时的逃生门），`SCRAPER_BATCH_SIZE` 控制每批条数（默认 1000）。
"""

from __future__ import annotations

import os
from typing import Iterable, List, Sequence, TypeVar

T = TypeVar("T")


def enabled() -> bool:
    """是否走批量写。默认开启——逐行写在 Supabase 上是 1.3 秒/模型。"""
    raw = os.getenv("SCRAPER_BATCH_WRITE", "1").strip().lower()
    return raw not in ("", "0", "false", "off", "no")


def size() -> int:
    try:
        value = int(os.getenv("SCRAPER_BATCH_SIZE", "1000"))
    except ValueError:
        return 1000
    return value if value > 0 else 1000


def chunked(items: Sequence[T], batch: int) -> Iterable[List[T]]:
    for start in range(0, len(items), batch):
        yield list(items[start : start + batch])
