"""排行榜数据聚合器 - 管理多个排行榜客户端。"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from src.analysis.leaderboard_clients.base import LeaderboardClient
from src.analysis.leaderboard_clients.swe_bench import SWEBenchLeaderboardClient
from src.analysis.leaderboard_clients.lmsys_arena import LMSYSArenaLeaderboardClient
from src.analysis.leaderboard_clients.hf_leaderboard import HFLeaderboardClient

LOGGER = logging.getLogger("silicon_river.leaderboard_aggregator")

# 默认**关闭**在线排行榜查询，原因两条，都是实测出来的：
#   1. 慢到吃掉整个分析预算 —— 三个客户端串起来约 70s（SWE-bench 的三个 URL 全
#      404 还要各重试 2 次，HF / LMSYS 走 20s 超时），而单个模型的分析预算是
#      ANALYSIS_TIMEOUT_SECONDS=30s。结果是 LLM 调用还没开始就被 asyncio.wait_for
#      掐掉，模型一个都分析不出来。
#   2. 上游挂了会**兜底到写死的假数据**（HF / LMSYS 客户端的 _get_mock_leaderboard），
#      于是每个模型都被塞进"Llama-2 排名第 1、64.42 分"这类编造的排名，
#      等于拿假事实污染 LLM 的分析结论。
# 真排行榜数据由 scripts/update_arena_scores.py 单独写进 model_arena_info 表，
# 不必在逐个模型的分析流程里现抓。需要时把 ENABLE_LEADERBOARD_LOOKUP 设为 true。
ENABLE_LEADERBOARD_LOOKUP = (
    os.getenv("ENABLE_LEADERBOARD_LOOKUP", "false").lower() == "true"
)


class LeaderboardAggregator:
    """排行榜数据聚合器。

    管理多个排行榜客户端，协调并发请求，实现缓存机制。
    """

    # 缓存 TTL（24 小时）
    CACHE_TTL = 86400

    def __init__(self, enabled: bool | None = None):
        """初始化排行榜聚合器。

        Args:
            enabled: 是否启用在线排行榜查询。None（默认）时读环境变量
                ENABLE_LEADERBOARD_LOOKUP（默认 false）。显式传 True 可强制
                建出客户端，供测试注入 mock 用。
        """
        if enabled is None:
            enabled = ENABLE_LEADERBOARD_LOOKUP

        self.clients: dict[str, LeaderboardClient] = {}
        self.cache: dict[str, dict[str, Any]] = {}
        self.cache_time: dict[str, float] = {}
        self.enabled = enabled

        # 关掉在线查询时不建客户端：既省掉初始化的开销，也让
        # get_model_ranks 立刻返回空列表，不占用分析预算。
        if not enabled:
            LOGGER.info(
                "排行榜在线查询未启用（ENABLE_LEADERBOARD_LOOKUP=false）；"
                "分析提示词将不含排行榜排名"
            )
            return

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
        # 开关关闭时 clients 为空，这里直接短路返回，语义等同"所有排行榜都没查到"
        if not self.clients:
            return []

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
