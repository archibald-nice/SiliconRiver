"""SWE-bench 排行榜客户端实现。

SWE-bench 是一个用于评测代码生成模型在真实世界软件工程任务中表现的基准。
数据来自 GitHub 上的官方 SWE-bench 排行榜仓库。

参考：https://github.com/swe-bench/swe-bench.github.io
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from src.analysis.leaderboard_clients.base import LeaderboardClient

LOGGER = logging.getLogger("silicon_river.leaderboard_clients.swe_bench")


class SWEBenchLeaderboardClient(LeaderboardClient):
    """SWE-bench 排行榜客户端。

    支持三个榜单：
    - bash-only: 仅使用 bash 命令的模型
    - Test: 需要运行测试的模型
    - Verified: 已验证的模型
    """

    # 官方排行榜 JSON 数据源
    LEADERBOARD_URLS = {
        "bash-only": "https://raw.githubusercontent.com/swe-bench/swe-bench.github.io/main/assets/data/leaderboard_bash_only.json",
        "test": "https://raw.githubusercontent.com/swe-bench/swe-bench.github.io/main/assets/data/leaderboard_test.json",
        "verified": "https://raw.githubusercontent.com/swe-bench/swe-bench.github.io/main/assets/data/leaderboard_verified.json",
    }

    REQUEST_TIMEOUT = 15  # 秒
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒

    def __init__(self):
        """初始化 SWE-bench 客户端。"""
        super().__init__("SWE-bench")
        self.cache: dict[str, dict[str, Any]] = {}
        self.cache_time: dict[str, float] = {}
        self.cache_ttl = 3600  # 1 小时缓存

    async def fetch_leaderboard(self) -> dict[str, Any]:
        """获取 SWE-bench 排行榜数据。

        Returns:
            包含所有榜单数据的字典
        """
        result = {}

        for category, url in self.LEADERBOARD_URLS.items():
            try:
                # 检查缓存
                if category in self.cache:
                    import time
                    if time.time() - self.cache_time[category] < self.cache_ttl:
                        result[category] = self.cache[category]
                        LOGGER.debug(f"使用缓存的 {category} 数据")
                        continue

                # 获取数据
                data = await self._fetch_with_retry(url)
                self.cache[category] = data
                import time
                self.cache_time[category] = time.time()
                result[category] = data

                LOGGER.debug(f"获取 {category} 排行榜数据成功")
            except Exception as e:
                LOGGER.error(f"获取 {category} 排行榜数据失败：{e}")
                continue

        return result

    async def _fetch_with_retry(self, url: str) -> dict[str, Any]:
        """带重试机制的 HTTP 请求。

        Args:
            url: 数据源 URL

        Returns:
            JSON 数据
        """
        last_exception = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
                    ) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        else:
                            raise Exception(f"HTTP {resp.status}")
            except asyncio.TimeoutError:
                last_exception = asyncio.TimeoutError("请求超时")
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_DELAY * (2 ** (attempt - 1))
                    LOGGER.warning(
                        f"请求超时（尝试 {attempt}/{self.MAX_RETRIES}），"
                        f"将在 {wait_time}s 后重试"
                    )
                    await asyncio.sleep(wait_time)
            except Exception as e:
                last_exception = e
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_DELAY * (2 ** (attempt - 1))
                    LOGGER.warning(
                        f"请求失败（尝试 {attempt}/{self.MAX_RETRIES}）：{e}，"
                        f"将在 {wait_time}s 后重试"
                    )
                    await asyncio.sleep(wait_time)

        raise last_exception or Exception("未知错误")

    def find_model_rank(
        self,
        data: dict[str, Any],
        model_name: str
    ) -> dict[str, Any] | None:
        """在 SWE-bench 数据中查找模型排名。

        Args:
            data: 从 fetch_leaderboard 获得的数据
            model_name: 模型名称

        Returns:
            包含排名和评分的字典，结构为 {
                "rank": int,
                "score": float,  # 解决率（百分比）
                "category": str,  # bash-only/test/verified
                "source": "SWE-bench"
            }
        """
        if not data:
            return None

        # 遍历所有榜单类别
        for category, entries in data.items():
            if not isinstance(entries, list):
                continue

            # 在该类别中查找模型
            for rank, entry in enumerate(entries, 1):
                if isinstance(entry, dict):
                    entry_model = entry.get("model", "")
                    entry_name = entry.get("name", "")

                    # 尝试匹配
                    if self.match_model_names(model_name, entry_model) or \
                       self.match_model_names(model_name, entry_name):
                        # 提取解决率（作为百分比）
                        solve_rate = entry.get("solve_rate", entry.get("accuracy", 0))
                        if isinstance(solve_rate, float) and solve_rate <= 1:
                            solve_rate = solve_rate * 100

                        return {
                            "rank": rank,
                            "score": float(solve_rate),
                            "category": category,
                            "source": "SWE-bench",
                        }

        return None

    def match_model_names(self, name1: str, name2: str, threshold: float = 0.75) -> bool:
        """针对 SWE-bench 的模型名称匹配。

        Args:
            name1: 第一个名称
            name2: 第二个名称
            threshold: 匹配阈值

        Returns:
            是否匹配
        """
        # 首先尝试精确匹配
        if name1.lower() == name2.lower():
            return True

        # 移除常见的模型标记
        norm1 = self._normalize_swe_bench_name(name1)
        norm2 = self._normalize_swe_bench_name(name2)

        if norm1 == norm2:
            return True

        # 子字符串匹配
        if norm1 in norm2 or norm2 in norm1:
            return True

        # 相似度匹配
        try:
            from difflib import SequenceMatcher
            ratio = SequenceMatcher(None, norm1, norm2).ratio()
            return ratio >= threshold
        except Exception:
            return False

    @staticmethod
    def _normalize_swe_bench_name(name: str) -> str:
        """规范化 SWE-bench 中的模型名称。

        Args:
            name: 原始名称

        Returns:
            规范化后的名称
        """
        import re

        name = name.lower().strip()

        # 移除 URL 编码和特殊字符
        name = name.replace("%2F", "/").replace("%20", " ")

        # 移除组织前缀（如 openai/, anthropic/ 等）
        if "/" in name:
            name = name.split("/")[-1]

        # 移除版本号和后缀
        name = re.sub(r'-v\d+(\.\d+)*$', '', name)
        name = re.sub(r'\s+v\d+(\.\d+)*$', '', name)
        name = re.sub(r'-latest$', '', name)
        name = re.sub(r'\(.*?\)', '', name)  # 移除括号内容

        return name.strip()
