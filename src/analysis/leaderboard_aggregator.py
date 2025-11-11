"""排行榜数据聚合器 - 管理多个排行榜客户端。"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.analysis.leaderboard_clients.base import LeaderboardClient
from src.analysis.leaderboard_clients.swe_bench import SWEBenchLeaderboardClient
from src.analysis.leaderboard_clients.lmsys_arena import LMSYSArenaLeaderboardClient
from src.analysis.leaderboard_clients.hf_leaderboard import HFLeaderboardClient

LOGGER = logging.getLogger("silicon_river.leaderboard_aggregator")


class LeaderboardAggregator:
    """排行榜数据聚合器。

    管理多个排行榜客户端，协调并发请求，实现缓存机制。
    """

    # 缓存 TTL（24 小时）
    CACHE_TTL = 86400

    def __init__(self):
        """初始化排行榜聚合器。"""
        self.clients: dict[str, LeaderboardClient] = {}
        self.cache: dict[str, dict[str, Any]] = {}
        self.cache_time: dict[str, float] = {}

        # 初始化排行榜客户端
        self._init_clients()

    def _init_clients(self):
        """初始化所有排行榜客户端。"""
        # SWE-bench 客户端（阶段 2）
        swe_bench = SWEBenchLeaderboardClient()
        self.clients["swe_bench"] = swe_bench

        # LMSYS Arena 客户端（阶段 3）
        lmsys_arena = LMSYSArenaLeaderboardClient()
        self.clients["lmsys_arena"] = lmsys_arena

        # HuggingFace Leaderboard 客户端（阶段 3）
        hf_leaderboard = HFLeaderboardClient()
        self.clients["hf_leaderboard"] = hf_leaderboard

        LOGGER.debug(f"已初始化 {len(self.clients)} 个排行榜客户端")

    async def get_model_ranks(self, model_name: str) -> list[dict[str, Any]]:
        """获取模型在所有排行榜中的排名。

        Args:
            model_name: 模型名称

        Returns:
            包含排名信息的列表，每个元素为 {
                "source": "排行榜名称",
                "rank": int,
                "score": float,
                "category": str (可选)
            }
        """
        results = []

        # 并发获取所有排行榜数据
        tasks = [
            self._get_rank_from_client(client, model_name)
            for client in self.clients.values()
        ]

        try:
            ranks = await asyncio.gather(*tasks, return_exceptions=True)
            for rank_info in ranks:
                if rank_info and not isinstance(rank_info, Exception):
                    results.append(rank_info)
        except Exception as e:
            LOGGER.error(f"获取排名数据失败：{e}")

        return results

    async def _get_rank_from_client(
        self,
        client: LeaderboardClient,
        model_name: str
    ) -> dict[str, Any] | None:
        """从单个排行榜客户端获取模型排名。

        Args:
            client: 排行榜客户端
            model_name: 模型名称

        Returns:
            排名信息或 None
        """
        try:
            # 获取排行榜数据
            data = await client.fetch_leaderboard()

            # 查找模型
            rank_info = client.find_model_rank(data, model_name)

            if rank_info:
                LOGGER.debug(
                    f"在 {client.name} 中找到 {model_name} 的排名："
                    f"第 {rank_info.get('rank')} 名"
                )
                return rank_info
            else:
                LOGGER.debug(f"在 {client.name} 中未找到 {model_name}")
                return None

        except Exception as e:
            LOGGER.error(f"从 {client.name} 获取排名失败（{model_name}）：{e}")
            return None

    async def update_cache(self) -> None:
        """更新所有排行榜的缓存。

        可通过定时任务调用以保持数据最新。
        """
        LOGGER.info("开始更新排行榜缓存...")

        tasks = [
            self._update_client_cache(client)
            for client in self.clients.values()
        ]

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            LOGGER.info(f"排行榜缓存更新完成：{success_count}/{len(self.clients)} 个客户端成功")
        except Exception as e:
            LOGGER.error(f"更新排行榜缓存失败：{e}")

    async def _update_client_cache(self, client: LeaderboardClient) -> bool:
        """更新单个客户端的缓存。

        Args:
            client: 排行榜客户端

        Returns:
            是否成功
        """
        try:
            await client.fetch_leaderboard()
            LOGGER.debug(f"{client.name} 缓存更新成功")
            return True
        except Exception as e:
            LOGGER.error(f"{client.name} 缓存更新失败：{e}")
            return False

    def get_cache_stats(self) -> dict[str, Any]:
        """获取缓存统计信息。

        Returns:
            包含缓存统计的字典
        """
        stats = {
            "total_entries": 0,
            "clients": {}
        }

        for client_name, client in self.clients.items():
            if hasattr(client, 'cache'):
                entry_count = sum(
                    len(v) if isinstance(v, list) else 1
                    for v in client.cache.values()
                )
                stats["total_entries"] += entry_count
                stats["clients"][client_name] = {
                    "cached_categories": len(client.cache),
                    "entry_count": entry_count,
                }

        return stats

    async def sync_to_database(self, db_url: str) -> None:
        """将排行榜数据同步到数据库。

        注意：这是一个示意方法，实现取决于具体的数据库架构。

        Args:
            db_url: 数据库连接 URL
        """
        LOGGER.info(f"开始将排行榜数据同步到数据库：{db_url}")

        # TODO: 实现数据库同步逻辑
        # 1. 获取所有排行榜数据
        # 2. 连接数据库
        # 3. 为每个模型插入或更新 model_arena_info 记录
        # 4. 记录同步结果

        LOGGER.warning("排行榜数据同步功能暂未实现")

    def clear_cache(self, client_name: str | None = None) -> None:
        """清空缓存。

        Args:
            client_name: 特定客户端名称，None 表示清空所有
        """
        if client_name:
            if client_name in self.clients:
                if hasattr(self.clients[client_name], 'cache'):
                    self.clients[client_name].cache.clear()
                    if client_name in self.cache_time:
                        del self.cache_time[client_name]
                LOGGER.info(f"已清空 {client_name} 的缓存")
            else:
                LOGGER.warning(f"客户端 {client_name} 不存在")
        else:
            for client in self.clients.values():
                if hasattr(client, 'cache'):
                    client.cache.clear()
            self.cache.clear()
            self.cache_time.clear()
            LOGGER.info("已清空所有缓存")
