"""排行榜数据更新脚本。

该脚本用于定期更新排行榜数据，可通过 cron job 或其他调度工具定期执行。
"""
import asyncio
import logging
from src.analysis.leaderboard_aggregator import LeaderboardAggregator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
LOGGER = logging.getLogger("silicon_river.update_leaderboards")


async def main():
    """更新所有排行榜数据。"""
    LOGGER.info("=== 开始更新排行榜数据 ===")

    agg = LeaderboardAggregator()

    try:
        # 更新缓存
        await agg.update_cache()

        # 获取统计信息
        stats = agg.get_cache_stats()
        LOGGER.info(f"缓存统计信息：{stats}")

        # 可选：同步到数据库（需要实现数据库集成）
        # await agg.sync_to_database(os.getenv("DATABASE_URL"))

        LOGGER.info("=== 排行榜数据更新完成 ===")

    except Exception as e:
        LOGGER.error(f"更新排行榜数据失败：{e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
