"""LMArena 官方排行榜抓取。

数据源：Hugging Face 数据集 ``lmarena-ai/leaderboard-dataset`` 的
``text/latest`` split。用 datasets-server 的 ``/rows`` 接口翻页读取，
**不引入 pyarrow/pandas**（parquet 直链更快，但会把依赖装进来）。

实测（2026-10-18）：

* ``length`` 上限 **100**，传 500/1000 返回 422；
* ``text/latest`` 共 11,033 行、29 个 category、``overall`` 416 个模型；
* 9 个并发线程翻 111 页约 16 秒。

失败策略：任何一页重试耗尽就抛 :class:`ArenaFetchError`，**不返回部分数据**。
部分数据会让 category 内排名看起来“少了一些模型”，却没有任何信号。
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests

LOGGER = logging.getLogger("silicon_river.arena.lmarena")

ROWS_URL = "https://datasets-server.huggingface.co/rows"
DATASET = "lmarena-ai/leaderboard-dataset"
CONFIG = "text"
SPLIT = "latest"
PAGE_SIZE = 100
DEFAULT_WORKERS = 9
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.5
USER_AGENT = "SiliconRiver/1.0 (arena score sync)"


class ArenaFetchError(RuntimeError):
    """LMArena 上游拉取/解析失败（不回落任何本地假数据）。"""


@dataclass(frozen=True, slots=True)
class ArenaRow:
    """LMArena 的一行评分（一个模型在一个 category 下的排名）。"""

    model_name: str
    organization: str | None
    category: str
    rank: int | None
    score: float | None
    vote_count: float | None = None
    publish_date: str | None = None


_thread_local = threading.local()


def _session() -> requests.Session:
    """每个线程一个 Session：复用连接，又避免跨线程共享。

    注意：本机 shell 常带 ``all_proxy=socks5://``。``requests`` 不读
    ``all_proxy``（只读 HTTP(S)_PROXY），所以这里不需要特殊处理；
    httpx 才需要，本模块刻意不用 httpx。
    """
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        _thread_local.session = session
    return session


def _http_get(url: str, timeout: int = REQUEST_TIMEOUT) -> requests.Response:
    """独立成函数，测试里直接 monkeypatch 它，不碰真实网络。"""
    return _session().get(url, timeout=timeout)


def build_rows_url(offset: int, length: int = PAGE_SIZE) -> str:
    """拼 ``/rows`` 请求 URL。

    >>> build_rows_url(0, 2)
    'https://datasets-server.huggingface.co/rows?dataset=lmarena-ai%2Fleaderboard-dataset&config=text&split=latest&offset=0&length=2'
    """
    if offset < 0:
        raise ValueError(f"offset 不能为负：{offset}")
    if not 1 <= length <= PAGE_SIZE:
        raise ValueError(f"length 必须在 1..{PAGE_SIZE} 之间：{length}")
    query = urlencode(
        {
            "dataset": DATASET,
            "config": CONFIG,
            "split": SPLIT,
            "offset": offset,
            "length": length,
        }
    )
    return f"{ROWS_URL}?{query}"


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_rows_payload(payload: dict[str, Any]) -> list[ArenaRow]:
    """把 ``/rows`` 响应转成 :class:`ArenaRow` 列表（纯函数）。

    坏行（缺 ``model_name`` / ``category``）跳过并打 debug，不整页失败：
    排行榜快照里偶发脏行的概率不为 0，但整页重试也修不好它。
    """
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise ArenaFetchError("LMArena 响应缺少 rows 数组")

    parsed: list[ArenaRow] = []
    for entry in raw_rows:
        row = entry.get("row") if isinstance(entry, dict) else None
        if not isinstance(row, dict):
            continue
        model_name = _as_text(row.get("model_name"))
        category = _as_text(row.get("category"))
        if not model_name or not category:
            LOGGER.debug("跳过缺少 model_name/category 的 LMArena 行：%r", row)
            continue
        parsed.append(
            ArenaRow(
                model_name=model_name,
                organization=_as_text(row.get("organization")),
                category=category,
                rank=_as_int(row.get("rank")),
                score=_as_float(row.get("rating")),
                vote_count=_as_float(row.get("vote_count")),
                publish_date=_as_text(row.get("leaderboard_publish_date")),
            )
        )
    return parsed


def fetch_page(
    offset: int,
    length: int = PAGE_SIZE,
    *,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """拉一页，失败按线性退避重试；重试耗尽抛 :class:`ArenaFetchError`。"""
    url = build_rows_url(offset, length)
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = _http_get(url, timeout=timeout)
            if response.status_code != 200:
                raise ArenaFetchError(f"HTTP {response.status_code}：{url}")
            payload = response.json()
            if not isinstance(payload, dict) or "rows" not in payload:
                raise ArenaFetchError(f"响应缺少 rows 字段：{url}")
            return payload
        except (requests.RequestException, ValueError, ArenaFetchError) as exc:
            last_error = exc
            if attempt < max_retries:
                # 429 是数据集服务器的限流配额（按分钟），线性 1.5s 退避等不到配额恢复；
                # 拉到 5s 起步，别把重试次数白白烧光。
                delay = RETRY_BASE_DELAY * attempt
                if "HTTP 429" in str(exc):
                    delay = max(delay, 5.0 * attempt)
                LOGGER.warning(
                    "LMArena 第 %d 页拉取失败（尝试 %d/%d）：%s；%.1fs 后重试",
                    offset // PAGE_SIZE + 1,
                    attempt,
                    max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

    raise ArenaFetchError(
        f"LMArena 拉取失败（offset={offset}，重试 {max_retries} 次）：{last_error}"
    ) from last_error


def fetch_latest_rows(
    limit: int | None = None,
    *,
    workers: int = DEFAULT_WORKERS,
    page_size: int = PAGE_SIZE,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> list[ArenaRow]:
    """并发拉取 ``text/latest`` 的全部行。

    Args:
        limit: 最多取多少行（调试用）。排名/评分由上游给出，截断不会重算，
            但截断后的数据**不是完整快照**，只适合抽样检查。
        workers: 并发线程数，默认 9（实测 8–10 最优）。
    """
    if limit is not None and limit <= 0:
        raise ValueError(f"limit 必须为正数或 None：{limit}")
    if not 1 <= page_size <= PAGE_SIZE:
        raise ValueError(f"page_size 必须在 1..{PAGE_SIZE} 之间：{page_size}")

    first_payload = fetch_page(
        0, page_size, timeout=timeout, max_retries=max_retries
    )
    total = first_payload.get("num_rows_total")
    if not isinstance(total, int) or total < 0:
        raise ArenaFetchError(
            f"LMArena 响应缺少合法的 num_rows_total：{total!r}"
        )

    target = total if limit is None else min(total, limit)
    if target == 0:
        return []

    first_rows = parse_rows_payload(first_payload)
    rows: list[ArenaRow] = first_rows[:target]

    pages: list[tuple[int, int]] = []
    for offset in range(page_size, target, page_size):
        pages.append((offset, min(page_size, target - offset)))

    if pages:
        def _fetch(item: tuple[int, int]) -> list[ArenaRow]:
            offset, length = item
            return parse_rows_payload(
                fetch_page(
                    offset, length, timeout=timeout, max_retries=max_retries
                )
            )

        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(pages)))) as pool:
            for page_rows in pool.map(_fetch, pages):
                rows.extend(page_rows)

    # 防御：实际行数与 num_rows_total 对不上时明确告警（上游改版/limit 截断）。
    if limit is None and len(rows) != total:
        LOGGER.warning(
            "LMArena 行数不一致：num_rows_total=%d，实际解析=%d", total, len(rows)
        )
    LOGGER.info("LMArena 拉取完成：%d 行 / %d 页", len(rows), 1 + len(pages))
    return rows


def count_categories(rows: list[ArenaRow]) -> int:
    return len({row.category for row in rows})
