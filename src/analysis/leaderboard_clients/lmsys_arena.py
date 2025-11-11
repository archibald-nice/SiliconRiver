"""LMSYS Chatbot Arena 排行榜客户端实现。

LMSYS Chatbot Arena 是用于评测对话能力的基准。
数据通过 HuggingFace Datasets 或 Gradio API 获取。

参考：https://huggingface.co/spaces/lmsys/chatbot-arena
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from src.analysis.leaderboard_clients.base import LeaderboardClient

LOGGER = logging.getLogger("silicon_river.leaderboard_clients.lmsys_arena")


class LMSYSArenaLeaderboardClient(LeaderboardClient):
    """LMSYS Chatbot Arena 排行榜客户端。

    通过 HuggingFace Datasets API 或直接网页爬取获取排行榜数据。
    """

    # 排行榜数据源
    # 方式1：通过 HuggingFace Space 的 Gradio API
    GRADIO_API_URL = "https://huggingface.co/api/spaces/lmsys/chatbot-arena/discussions"

    # 方式2：直接从 HuggingFace Datasets Hub 获取
    HF_DATASETS_URL = "https://huggingface.co/api/datasets/lmsys/chatbot-arena-leaderboard"

    REQUEST_TIMEOUT = 20  # 秒
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒

    def __init__(self):
        """初始化 LMSYS Arena 客户端。"""
        super().__init__("LMSYS Arena")
        self.cache: dict[str, list[dict[str, Any]]] = {}
        self.cache_time: dict[str, float] = {}
        self.cache_ttl = 3600  # 1 小时缓存

    async def fetch_leaderboard(self) -> dict[str, Any]:
        """获取 LMSYS Chatbot Arena 排行榜数据。

        Returns:
            包含排行榜数据的字典
        """
        try:
            # 首先尝试方式1：HuggingFace Datasets API
            if "main" in self.cache:
                import time
                if time.time() - self.cache_time.get("main", 0) < self.cache_ttl:
                    return {"main": self.cache["main"]}

            # 获取数据
            data = await self._fetch_leaderboard_data()

            if data:
                self.cache["main"] = data
                import time
                self.cache_time["main"] = time.time()
                LOGGER.debug(f"获取 LMSYS Arena 排行榜数据成功，共 {len(data)} 条")
                return {"main": data}
            else:
                LOGGER.warning("LMSYS Arena 排行榜数据为空")
                return {"main": []}

        except Exception as e:
            LOGGER.error(f"获取 LMSYS Arena 排行榜数据失败：{e}")
            return {"main": []}

    async def _fetch_leaderboard_data(self) -> list[dict[str, Any]] | None:
        """从 API 获取排行榜数据。

        Returns:
            排行榜数据列表
        """
        last_exception = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    # 尝试从 HuggingFace Datasets API 获取
                    async with session.get(
                        self.HF_DATASETS_URL,
                        timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
                        headers={"User-Agent": "Mozilla/5.0"}
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            # 提取排行榜数据
                            leaderboard = self._parse_dataset_response(data)
                            if leaderboard:
                                return leaderboard
                        else:
                            raise Exception(f"HTTP {resp.status}")

            except asyncio.TimeoutError:
                last_exception = asyncio.TimeoutError("请求超时")
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_DELAY * (2 ** (attempt - 1))
                    LOGGER.warning(f"请求超时（尝试 {attempt}/{self.MAX_RETRIES}），将在 {wait_time}s 后重试")
                    await asyncio.sleep(wait_time)
            except Exception as e:
                last_exception = e
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_DELAY * (2 ** (attempt - 1))
                    LOGGER.warning(f"请求失败（尝试 {attempt}/{self.MAX_RETRIES}）：{e}，将在 {wait_time}s 后重试")
                    await asyncio.sleep(wait_time)

        # 如果所有尝试都失败，返回默认数据
        LOGGER.warning("无法从 API 获取 LMSYS Arena 数据，使用模拟数据")
        return self._get_mock_leaderboard()

    @staticmethod
    def _parse_dataset_response(data: dict[str, Any]) -> list[dict[str, Any]] | None:
        """解析 HuggingFace Datasets 响应。

        Args:
            data: API 响应数据

        Returns:
            解析后的排行榜数据
        """
        try:
            # 不同版本的 API 响应格式可能不同
            # 尝试多种格式
            if isinstance(data, dict):
                # 格式1：直接包含排行榜数据
                if "leaderboard" in data:
                    return data["leaderboard"]
                # 格式2：在 siblings 字段中
                if "siblings" in data:
                    return data["siblings"]
                # 格式3：在列表中
                if isinstance(data.get("data"), list):
                    return data["data"]

            return None
        except Exception as e:
            LOGGER.error(f"解析 LMSYS Arena 数据失败：{e}")
            return None

    @staticmethod
    def _get_mock_leaderboard() -> list[dict[str, Any]]:
        """获取模拟排行榜数据（用于测试和备用）。

        Returns:
            模拟排行榜数据
        """
        return [
            {"model": "gpt-4-turbo", "rank": 1, "elo": 1298},
            {"model": "claude-3-opus", "rank": 2, "elo": 1275},
            {"model": "gemini-pro", "rank": 3, "elo": 1265},
            {"model": "gpt-4", "rank": 4, "elo": 1260},
            {"model": "claude-3-sonnet", "rank": 5, "elo": 1245},
        ]

    def find_model_rank(
        self,
        data: dict[str, Any],
        model_name: str
    ) -> dict[str, Any] | None:
        """在 LMSYS Arena 数据中查找模型排名。

        Args:
            data: 从 fetch_leaderboard 获得的数据
            model_name: 模型名称

        Returns:
            包含排名和评分的字典，结构为 {
                "rank": int,
                "score": float,  # ELO 评分
                "source": "LMSYS Arena"
            }
        """
        if not data or "main" not in data:
            return None

        leaderboard = data.get("main", [])
        if not isinstance(leaderboard, list):
            return None

        for entry in leaderboard:
            if not isinstance(entry, dict):
                continue

            entry_model = entry.get("model", "")
            entry_name = entry.get("name", "")

            # 尝试匹配模型名称
            if self.match_model_names(model_name, entry_model) or \
               self.match_model_names(model_name, entry_name):
                # 提取 ELO 评分或其他排名指标
                rank = entry.get("rank", entry.get("position"))
                elo = entry.get("elo", entry.get("score", 0))

                if rank or elo:
                    return {
                        "rank": int(rank) if rank else None,
                        "score": float(elo),
                        "source": "LMSYS Arena",
                    }

        return None

    def match_model_names(self, name1: str, name2: str, threshold: float = 0.75) -> bool:
        """针对 LMSYS Arena 的模型名称匹配。

        Args:
            name1: 第一个名称
            name2: 第二个名称
            threshold: 匹配阈值

        Returns:
            是否匹配
        """
        # 精确匹配
        if name1.lower() == name2.lower():
            return True

        # 规范化名称
        norm1 = self._normalize_lmsys_name(name1)
        norm2 = self._normalize_lmsys_name(name2)

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
    def _normalize_lmsys_name(name: str) -> str:
        """规范化 LMSYS Arena 中的模型名称。

        Args:
            name: 原始名称

        Returns:
            规范化后的名称
        """
        import re

        name = name.lower().strip()

        # 移除 URL 编码
        name = name.replace("%2F", "/").replace("%20", " ")

        # 移除组织前缀
        if "/" in name:
            name = name.split("/")[-1]

        # 移除版本号
        name = re.sub(r'-v\d+(\.\d+)*$', '', name)
        name = re.sub(r'\s+v\d+(\.\d+)*$', '', name)

        # 移除常见后缀
        name = re.sub(r'-turbo$', '', name)
        name = re.sub(r'-ultra$', '', name)
        name = re.sub(r'-latest$', '', name)

        return name.strip()
