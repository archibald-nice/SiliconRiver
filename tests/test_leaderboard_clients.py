"""排行榜客户端单元测试。"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import json

from src.analysis.leaderboard_clients.base import LeaderboardClient
from src.analysis.leaderboard_clients.swe_bench import SWEBenchLeaderboardClient
from src.analysis.leaderboard_aggregator import LeaderboardAggregator


class TestLeaderboardClientBase:
    """测试排行榜客户端基类。"""

    def test_normalize_model_name_basic(self):
        """测试基础的名称规范化。"""
        client = SWEBenchLeaderboardClient()

        # 测试大小写转换
        assert client.normalize_model_name("GPT-4") == "gpt-4"

        # 测试移除版本号
        assert "v1" not in client.normalize_model_name("GPT-4-v1.0")

        # 测试移除空格
        assert client.normalize_model_name("  Claude  ") == "claude"

    def test_match_model_names_exact(self):
        """测试精确模型名称匹配。"""
        client = SWEBenchLeaderboardClient()

        assert client.match_model_names("GPT-4", "gpt-4") is True
        assert client.match_model_names("Claude", "claude") is True

    def test_match_model_names_substring(self):
        """测试子字符串匹配。"""
        client = SWEBenchLeaderboardClient()

        assert client.match_model_names("GPT-4", "OpenAI GPT-4") is True
        assert client.match_model_names("Claude", "Anthropic Claude") is True

    def test_match_model_names_similarity(self):
        """测试相似度匹配。"""
        client = SWEBenchLeaderboardClient()

        # 高度相似的名称应该匹配
        assert client.match_model_names("GPT-4", "GPT4") is True


class TestSWEBenchLeaderboardClient:
    """测试 SWE-bench 客户端。"""

    @pytest.mark.asyncio
    async def test_client_initialization(self):
        """测试客户端初始化。"""
        client = SWEBenchLeaderboardClient()

        assert client.name == "SWE-bench"
        assert client.enabled is True
        assert len(client.LEADERBOARD_URLS) == 3

    @pytest.mark.asyncio
    async def test_fetch_leaderboard_with_mock(self):
        """测试使用 Mock 的排行榜获取。"""
        client = SWEBenchLeaderboardClient()

        # Mock 返回数据
        mock_data = [
            {"model": "gpt-4", "name": "GPT-4", "solve_rate": 0.85},
            {"model": "claude-3", "name": "Claude-3", "solve_rate": 0.80},
        ]

        with patch.object(client, '_fetch_with_retry', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_data

            result = await client.fetch_leaderboard()

            assert "bash-only" in result
            assert "test" in result
            assert "verified" in result

    def test_find_model_rank_found(self):
        """测试查找存在的模型排名。"""
        client = SWEBenchLeaderboardClient()

        data = {
            "bash-only": [
                {"model": "gpt-4", "name": "GPT-4", "solve_rate": 85},
                {"model": "claude-3", "name": "Claude-3", "solve_rate": 80},
            ]
        }

        result = client.find_model_rank(data, "GPT-4")

        assert result is not None
        assert result["rank"] == 1
        assert result["score"] == 85
        assert result["category"] == "bash-only"
        assert result["source"] == "SWE-bench"

    def test_find_model_rank_not_found(self):
        """测试查找不存在的模型排名。"""
        client = SWEBenchLeaderboardClient()

        data = {
            "bash-only": [
                {"model": "gpt-4", "name": "GPT-4", "solve_rate": 85},
            ]
        }

        result = client.find_model_rank(data, "Unknown-Model")

        assert result is None

    def test_find_model_rank_decimal_score(self):
        """测试处理小数评分（0-1）。"""
        client = SWEBenchLeaderboardClient()

        data = {
            "test": [
                {"model": "claude", "name": "Claude", "accuracy": 0.75},
            ]
        }

        result = client.find_model_rank(data, "Claude")

        assert result is not None
        assert result["score"] == 75  # 应该转换为百分比

    def test_normalize_swe_bench_name(self):
        """测试 SWE-bench 特定的名称规范化。"""
        norm = SWEBenchLeaderboardClient._normalize_swe_bench_name

        # 测试移除组织前缀
        assert norm("openai/gpt-4") == "gpt-4"
        assert norm("anthropic/claude") == "claude"

        # 测试移除 URL 编码
        assert "20" not in norm("GPT%204")


class TestLeaderboardAggregator:
    """测试排行榜聚合器。"""

    def test_aggregator_initialization(self):
        """测试聚合器初始化。"""
        agg = LeaderboardAggregator()

        assert "swe_bench" in agg.clients
        assert len(agg.clients) >= 1

    @pytest.mark.asyncio
    async def test_get_model_ranks_single_rank(self):
        """测试获取单个排名。"""
        agg = LeaderboardAggregator()

        # Mock SWE-bench 客户端
        mock_rank = {
            "rank": 1,
            "score": 85,
            "category": "bash-only",
            "source": "SWE-bench"
        }

        with patch.object(
            agg.clients["swe_bench"], "fetch_leaderboard", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = {
                "bash-only": [
                    {"model": "gpt-4", "name": "GPT-4", "solve_rate": 85}
                ]
            }

            with patch.object(
                agg.clients["swe_bench"], "find_model_rank", return_value=mock_rank
            ):
                result = await agg.get_model_ranks("GPT-4")

                assert len(result) >= 1
                assert result[0]["rank"] == 1

    @pytest.mark.asyncio
    async def test_get_model_ranks_empty(self):
        """测试未找到排名时返回空列表。"""
        agg = LeaderboardAggregator()

        with patch.object(
            agg.clients["swe_bench"], "fetch_leaderboard", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = {"bash-only": []}

            with patch.object(
                agg.clients["swe_bench"], "find_model_rank", return_value=None
            ):
                result = await agg.get_model_ranks("Unknown-Model")

                assert result == []

    @pytest.mark.asyncio
    async def test_update_cache(self):
        """测试缓存更新。"""
        agg = LeaderboardAggregator()

        with patch.object(
            agg.clients["swe_bench"], "fetch_leaderboard", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = {"bash-only": []}

            await agg.update_cache()

            # 应该至少被调用一次
            mock_fetch.assert_called()

    def test_clear_cache_all(self):
        """测试清空所有缓存。"""
        agg = LeaderboardAggregator()

        # 添加一些缓存数据
        agg.clients["swe_bench"].cache = {"bash-only": [{"model": "test"}]}

        agg.clear_cache()

        # 缓存应该被清空
        assert agg.clients["swe_bench"].cache == {}

    def test_clear_cache_specific(self):
        """测试清空特定客户端的缓存。"""
        agg = LeaderboardAggregator()

        # 添加一些缓存数据
        agg.clients["swe_bench"].cache = {"bash-only": [{"model": "test"}]}

        agg.clear_cache("swe_bench")

        # 应该只清空指定的客户端
        assert agg.clients["swe_bench"].cache == {}

    def test_get_cache_stats(self):
        """测试获取缓存统计。"""
        agg = LeaderboardAggregator()

        # 添加一些缓存数据
        agg.clients["swe_bench"].cache = {
            "bash-only": [{"model": "test1"}, {"model": "test2"}],
            "test": [{"model": "test3"}]
        }

        stats = agg.get_cache_stats()

        assert "total_entries" in stats
        assert "clients" in stats
        assert stats["total_entries"] == 3


class TestLeaderboardIntegration:
    """集成测试。"""

    @pytest.mark.asyncio
    async def test_end_to_end_model_ranking(self):
        """测试端到端的模型排名获取。"""
        agg = LeaderboardAggregator()

        # Mock 完整的数据流
        mock_leaderboard_data = {
            "bash-only": [
                {"model": "gpt-4", "name": "GPT-4", "solve_rate": 85},
                {"model": "claude", "name": "Claude", "solve_rate": 80},
            ],
            "test": [
                {"model": "gpt-4", "name": "GPT-4", "solve_rate": 90},
            ],
            "verified": [
                {"model": "claude", "name": "Claude", "solve_rate": 75},
            ]
        }

        with patch.object(
            agg.clients["swe_bench"], "fetch_leaderboard", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = mock_leaderboard_data

            with patch.object(
                agg.clients["swe_bench"], "find_model_rank"
            ) as mock_find:
                def find_side_effect(data, model_name):
                    for category, entries in data.items():
                        for rank, entry in enumerate(entries, 1):
                            if entry["model"].lower() == model_name.lower():
                                return {
                                    "rank": rank,
                                    "score": entry["solve_rate"],
                                    "category": category,
                                    "source": "SWE-bench"
                                }
                    return None

                mock_find.side_effect = find_side_effect

                result = await agg.get_model_ranks("GPT-4")

                assert len(result) >= 1
                assert any(r["rank"] == 1 for r in result)
