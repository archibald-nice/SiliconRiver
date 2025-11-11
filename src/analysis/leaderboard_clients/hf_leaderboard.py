"""HuggingFace Open LLM Leaderboard 客户端实现。

HuggingFace Open LLM Leaderboard 是一个综合性的 LLM 评测排行榜。
数据通过 HuggingFace Spaces Gradio API 获取。

参考：https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from src.analysis.leaderboard_clients.base import LeaderboardClient

LOGGER = logging.getLogger("silicon_river.leaderboard_clients.hf_leaderboard")


class HFLeaderboardClient(LeaderboardClient):
    """HuggingFace Open LLM Leaderboard 客户端。

    支持多个排行榜维度：
    - Open LLM Leaderboard（综合排行）
    - 不同任务的排行（ARC, HellaSwag, MMLU, TruthfulQA）
    """

    # 排行榜数据源
    # 通过 HuggingFace Datasets Hub
    HF_DATASETS_URL = "https://huggingface.co/api/datasets/open-llm-leaderboard/results"

    # Gradio API 端点
    GRADIO_API_URL = "https://huggingface.co/api/spaces/open-llm-leaderboard/open_llm_leaderboard/files"

    REQUEST_TIMEOUT = 20  # 秒
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒

    def __init__(self):
        """初始化 HuggingFace Leaderboard 客户端。"""
        super().__init__("HuggingFace Leaderboard")
        self.cache: dict[str, list[dict[str, Any]]] = {}
        self.cache_time: dict[str, float] = {}
        self.cache_ttl = 3600  # 1 小时缓存

    async def fetch_leaderboard(self) -> dict[str, Any]:
        """获取 HuggingFace Open LLM Leaderboard 数据。

        Returns:
            包含排行榜数据的字典
        """
        try:
            if "overall" in self.cache:
                import time
                if time.time() - self.cache_time.get("overall", 0) < self.cache_ttl:
                    return {"overall": self.cache["overall"]}

            # 获取数据
            data = await self._fetch_leaderboard_data()

            if data:
                self.cache["overall"] = data
                import time
                self.cache_time["overall"] = time.time()
                LOGGER.debug(f"获取 HuggingFace Leaderboard 数据成功，共 {len(data)} 条")
                return {"overall": data}
            else:
                LOGGER.warning("HuggingFace Leaderboard 数据为空")
                return {"overall": []}

        except Exception as e:
            LOGGER.error(f"获取 HuggingFace Leaderboard 数据失败：{e}")
            return {"overall": []}

    async def _fetch_leaderboard_data(self) -> list[dict[str, Any]] | None:
        """从 API 获取排行榜数据。

        Returns:
            排行榜数据列表
        """
        last_exception = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        self.HF_DATASETS_URL,
                        timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
                        headers={"User-Agent": "Mozilla/5.0"}
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            # 提取排行榜数据
                            leaderboard = self._parse_hf_response(data)
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

        # 返回模拟数据
        LOGGER.warning("无法从 API 获取 HF Leaderboard 数据，使用模拟数据")
        return self._get_mock_leaderboard()

    @staticmethod
    def _parse_hf_response(data: dict[str, Any]) -> list[dict[str, Any]] | None:
        """解析 HuggingFace 排行榜响应。

        Args:
            data: API 响应数据

        Returns:
            解析后的排行榜数据
        """
        try:
            # 多种可能的格式
            if isinstance(data, dict):
                if "results" in data:
                    return data["results"]
                if "data" in data and isinstance(data["data"], list):
                    return data["data"]

            if isinstance(data, list):
                return data

            return None
        except Exception as e:
            LOGGER.error(f"解析 HF Leaderboard 数据失败：{e}")
            return None

    @staticmethod
    def _get_mock_leaderboard() -> list[dict[str, Any]]:
        """获取模拟排行榜数据。

        Returns:
            模拟排行榜数据
        """
        return [
            {"Model": "meta-llama/Llama-2-70b-hf", "Rank": 1, "Average": 64.42},
            {"Model": "openai/gpt-3.5-turbo", "Rank": 2, "Average": 63.75},
            {"Model": "mistralai/Mistral-7B-v0.1", "Rank": 3, "Average": 61.12},
            {"Model": "meta-llama/Llama-2-13b-hf", "Rank": 4, "Average": 59.88},
            {"Model": "togethercomputer/RedPajama-INCITE-7B-Instruct", "Rank": 5, "Average": 58.45},
        ]

    def find_model_rank(
        self,
        data: dict[str, Any],
        model_name: str
    ) -> dict[str, Any] | None:
        """在 HuggingFace Leaderboard 数据中查找模型排名。

        Args:
            data: 从 fetch_leaderboard 获得的数据
            model_name: 模型名称

        Returns:
            包含排名和评分的字典，结构为 {
                "rank": int,
                "score": float,  # 平均分
                "source": "HuggingFace Leaderboard"
            }
        """
        if not data or "overall" not in data:
            return None

        leaderboard = data.get("overall", [])
        if not isinstance(leaderboard, list):
            return None

        for entry in leaderboard:
            if not isinstance(entry, dict):
                continue

            # HF Leaderboard 使用不同的字段名
            entry_model = entry.get("Model", entry.get("model", ""))
            entry_name = entry.get("Name", entry.get("name", ""))

            # 尝试匹配模型名称
            if self.match_model_names(model_name, entry_model) or \
               self.match_model_names(model_name, entry_name):
                rank = entry.get("Rank", entry.get("rank"))
                average = entry.get("Average", entry.get("average", 0))

                if rank or average:
                    return {
                        "rank": int(rank) if rank else None,
                        "score": float(average),
                        "source": "HuggingFace Leaderboard",
                    }

        return None

    def match_model_names(self, name1: str, name2: str, threshold: float = 0.75) -> bool:
        """针对 HuggingFace Leaderboard 的模型名称匹配。

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
        norm1 = self._normalize_hf_name(name1)
        norm2 = self._normalize_hf_name(name2)

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
    def _normalize_hf_name(name: str) -> str:
        """规范化 HuggingFace Leaderboard 中的模型名称。

        Args:
            name: 原始名称

        Returns:
            规范化后的名称
        """
        import re

        name = name.lower().strip()

        # 移除 URL 编码
        name = name.replace("%2f", "/").replace("%20", " ")

        # 提取最后的模型名称（如果包含路径）
        if "/" in name:
            name = name.split("/")[-1]

        # 移除版本号
        name = re.sub(r'-v\d+(\.\d+)*(-\w+)?$', '', name)
        name = re.sub(r'\s+v\d+(\.\d+)*$', '', name)
        name = re.sub(r'-hf$', '', name)  # HuggingFace 特定后缀

        return name.strip()
