"""SWE-bench 官方排行榜抓取（swebench.com 页面内嵌 JSON）。

静态 JSON 路径（``/data/leaderboard*.json``）早已 404；真实数据在首页
``<script type="application/json" id="leaderboard-data">`` 里（约 2.4MB）。

已确认的事实（2026-10-18 实测）：

* 页面 200，一次请求约 0.7–1.1s；
* 五个分组：Verified 180 / Lite 84 / Multimodal 22 / Test 24 / Multilingual 13；
* 每条 entry 的关键字段：``name``、``model_display``、``model_org``、``agent``、
  ``date``、``folder``、``tags``（``"Model: claude-opus-4-5"``）、``resolved``（百分数）；
* **没有 rank，同一模型可能有多条**（不同 agent 提交），必须去重取最高 resolved；
* 有大量多模型系统（一个 agent 同时用 4 个模型）和 ``Undisclosed`` 条目，
  这些分数不能算到单个模型头上。

本模块的取舍：

* 只取 ``tags`` 里**恰好一个** ``Model:`` 的 entry；0 个（系统/未披露）或多个
  （多模型系统）都跳过。宁可少 60 条，也不把系统分数记到模型头上。
* Verified / Lite 两个分组各写一份（category 不同），因为它们题目集不同。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable

import requests

from .lmarena import ArenaRow
from .matcher import normalize_name

LOGGER = logging.getLogger("silicon_river.arena.swebench")

SWEBENCH_URL = "https://www.swebench.com/"
SCRIPT_ID = "leaderboard-data"
DEFAULT_GROUPS = ("Verified", "Lite")
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.5
USER_AGENT = "SiliconRiver/1.0 (arena score sync)"

_SCRIPT_RE = re.compile(
    r"<script\b[^>]*\bid=[\"']" + re.escape(SCRIPT_ID) + r"[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_MODEL_TAG_PREFIX = "model:"


class SweBenchFetchError(RuntimeError):
    """SWE-bench 页面拉取失败（不回落任何本地假数据）。"""


class SweBenchParseError(RuntimeError):
    """页面结构变了，抠不出 ``leaderboard-data`` JSON。"""


def _http_get(url: str, timeout: int = REQUEST_TIMEOUT) -> requests.Response:
    return requests.get(
        url, timeout=timeout, headers={"User-Agent": USER_AGENT}
    )


def extract_leaderboard_json(html: str) -> list[dict[str, Any]]:
    """从 HTML 里抠出 ``leaderboard-data`` 的 JSON 数组（纯函数）。"""
    match = _SCRIPT_RE.search(html)
    if match is None:
        raise SweBenchParseError(
            "页面里找不到 <script id=\"leaderboard-data\">；"
            "swebench.com 可能改版了，需要重新确认真实数据位置"
        )
    raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SweBenchParseError(f"leaderboard-data 不是合法 JSON：{exc}") from exc
    if not isinstance(data, list):
        raise SweBenchParseError(
            f"leaderboard-data 顶层应为数组，实际是 {type(data).__name__}"
        )
    return data


def _model_slugs(entry: dict[str, Any]) -> list[str]:
    tags = entry.get("tags")
    if not isinstance(tags, list):
        return []
    slugs: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        if tag.strip().lower().startswith(_MODEL_TAG_PREFIX):
            slug = tag.split(":", 1)[1].strip()
            if slug:
                slugs.append(slug)
    return slugs


def _as_percentage(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class _BestEntry:
    """一个归一化模型在某个分组下的最佳成绩。"""

    key: str
    slug: str
    display: str
    score: float
    organization: str | None
    date: str | None


def _rank_rows(best: dict[str, _BestEntry]) -> list[tuple[_BestEntry, int]]:
    """按 resolved 降序算名次；同分并列（1,2,2,4），同分内按归一化名排序。"""
    ordered = sorted(best.values(), key=lambda entry: (-entry.score, entry.key))
    ranked: list[tuple[_BestEntry, int]] = []
    previous_score: float | None = None
    current_rank = 0
    for position, entry in enumerate(ordered, 1):
        if previous_score is None or entry.score != previous_score:
            current_rank = position
            previous_score = entry.score
        ranked.append((entry, current_rank))
    return ranked


def parse_leaderboard_data(
    data: Iterable[dict[str, Any]], groups: Iterable[str] = DEFAULT_GROUPS
) -> list[ArenaRow]:
    """解析内嵌 JSON，返回 Verified / Lite 两组的 :class:`ArenaRow`（纯函数）。

    去重键是 :func:`normalize_name`（会剥掉日期后缀），所以
    ``claude-opus-4-5`` 与 ``claude-opus-4-5-20251101`` 会合并成一条。
    """
    wanted = {group.lower(): group for group in groups}
    payload = list(data)
    by_name: dict[str, dict[str, Any]] = {}
    for block in payload:
        if isinstance(block, dict):
            name = block.get("name")
            if isinstance(name, str):
                by_name[name.strip().lower()] = block

    missing = [group for key, group in wanted.items() if key not in by_name]
    if missing:
        raise SweBenchParseError(
            f"leaderboard-data 缺少分组：{', '.join(missing)}；"
            f"实际分组：{', '.join(sorted(by_name)) or '<空>'}"
        )

    rows: list[ArenaRow] = []
    for key, group_name in wanted.items():
        results = by_name[key].get("results")
        if not isinstance(results, list):
            raise SweBenchParseError(f"分组 {group_name} 的 results 不是数组")

        # 归一化名 → 该模型当前最佳条目
        best: dict[str, _BestEntry] = {}
        for entry in results:
            if not isinstance(entry, dict):
                continue
            slugs = _model_slugs(entry)
            if len(slugs) != 1:
                # 0 个 = 系统/未披露；>1 = 多模型系统。都不能归因到单个模型。
                continue
            score = _as_percentage(entry.get("resolved"))
            if score is None:
                continue

            slug = slugs[0]
            dedupe_key = normalize_name(slug) or slug.lower()
            display = str(entry.get("model_display") or entry.get("name") or slug).strip()
            organization = entry.get("model_org")
            organization = str(organization).strip() if organization else None
            date = entry.get("date")
            date = str(date).strip() if date else None

            previous = best.get(dedupe_key)
            if previous is None or score > previous.score:
                # 同分时保留先出现的那条（页面本身按分数排）。
                best[dedupe_key] = _BestEntry(
                    key=dedupe_key,
                    slug=slug,
                    display=display,
                    score=score,
                    organization=organization,
                    date=date,
                )

        for entry, rank in _rank_rows(best):
            rows.append(
                ArenaRow(
                    # 用原始 slug（``Qwen3-235B-A22B``）而不是归一化键：matcher 的尺寸守卫
                    # 依赖名字里的 ``235b``/``a22b``，压成 ``qwen3235ba22b`` 这类紧凑键后
                    # 正则匹配不到尺寸，守卫会失效。去重仍按归一化键做。
                    model_name=entry.slug,
                    organization=entry.organization,
                    category=group_name.lower(),
                    rank=rank,
                    score=entry.score,
                    vote_count=None,
                    publish_date=entry.date,
                )
            )
    return rows


def fetch_html(
    *, timeout: int = REQUEST_TIMEOUT, max_retries: int = MAX_RETRIES
) -> str:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = _http_get(SWEBENCH_URL, timeout=timeout)
            if response.status_code != 200:
                raise SweBenchFetchError(
                    f"HTTP {response.status_code}：{SWEBENCH_URL}"
                )
            return response.text
        except (requests.RequestException, SweBenchFetchError) as exc:
            last_error = exc
            if attempt < max_retries:
                delay = RETRY_BASE_DELAY * attempt
                LOGGER.warning(
                    "SWE-bench 页面拉取失败（尝试 %d/%d）：%s；%.1fs 后重试",
                    attempt,
                    max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
    raise SweBenchFetchError(
        f"SWE-bench 页面拉取失败（重试 {max_retries} 次）：{last_error}"
    ) from last_error


def fetch_swebench_rows(limit: int | None = None) -> list[ArenaRow]:
    """拉页面 → 抠 JSON → 解析 Verified/Lite → （可选）截断。

    ``limit`` 只截断**输出行**，排名仍在完整数据上计算，避免“先截断再排名”
    产生假的第 1 名。
    """
    if limit is not None and limit <= 0:
        raise ValueError(f"limit 必须为正数或 None：{limit}")
    data = extract_leaderboard_json(fetch_html())
    rows = parse_leaderboard_data(data)
    return rows[:limit] if limit is not None else rows
