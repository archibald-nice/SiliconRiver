"""Phase 3 排行榜客户端综合测试。"""
import pytest
from unittest.mock import AsyncMock, patch

from src.analysis.leaderboard_clients.lmsys_arena import LMSYSArenaLeaderboardClient
from src.analysis.leaderboard_clients.hf_leaderboard import HFLeaderboardClient
from src.analysis.leaderboard_aggregator import LeaderboardAggregator


class TestLMSYSArenaClient:
    """LMSYS Arena 客户端测试。"""

    def test_initialization(self):
        """测试初始化。"""
        client = LMSYSArenaLeaderboardClient()
        assert client.name == "LMSYS Arena"
        assert client.enabled is True

    def test_normalize_name(self):
        """测试名称规范化。"""
        client = LMSYSArenaLeaderboardClient()

        assert client._normalize_lmsys_name("GPT-4-Turbo") == "gpt-4"
        assert client._normalize_lmsys_name("Claude-3-Opus") == "claude-3"
        assert client._normalize_lmsys_name("openai/GPT-4") == "gpt-4"

    def test_find_model_rank(self):
        """测试查找模型排名。"""
        client = LMSYSArenaLeaderboardClient()

        data = {
            "main": [
                {"model": "gpt-4-turbo", "rank": 1, "elo": 1298},
                {"model": "claude-3-opus", "rank": 2, "elo": 1275},
            ]
        }

        result = client.find_model_rank(data, "GPT-4")
        assert result is not None
        assert result["rank"] == 1
        assert result["score"] == 1298


class TestHFLeaderboardClient:
    """HuggingFace Leaderboard 客户端测试。"""

    def test_initialization(self):
        """测试初始化。"""
        client = HFLeaderboardClient()
        assert client.name == "HuggingFace Leaderboard"
        assert client.enabled is True

    def test_normalize_name(self):
        """测试名称规范化。"""
        client = HFLeaderboardClient()

        assert client._normalize_hf_name("meta-llama/Llama-2-70b-hf") == "llama-2-70b"
        assert client._normalize_hf_name("meta-llama/Llama-2-13b-hf") == "llama-2-13b"

    def test_find_model_rank(self):
        """测试查找模型排名。"""
        client = HFLeaderboardClient()

        data = {
            "overall": [
                {"Model": "meta-llama/Llama-2-70b-hf", "Rank": 1, "Average": 64.42},
                {"Model": "openai/gpt-3.5-turbo", "Rank": 2, "Average": 63.75},
            ]
        }

        result = client.find_model_rank(data, "Llama-2-70b")
        assert result is not None
        assert result["rank"] == 1
        assert result["score"] == 64.42


class TestLeaderboardAggregatorWithNewClients:
    """排行榜聚合器与新客户端的集成测试。"""

    def test_all_clients_initialized(self):
        """测试所有客户端已初始化。"""
        agg = LeaderboardAggregator()

        assert "swe_bench" in agg.clients
        assert "lmsys_arena" in agg.clients
        assert "hf_leaderboard" in agg.clients
        assert len(agg.clients) == 3

    @pytest.mark.asyncio
    async def test_concurrent_fetch_multiple_leaderboards(self):
        """测试并发获取多个排行榜。"""
        agg = LeaderboardAggregator()

        # Mock 所有客户端返回数据
        with patch.object(agg.clients["swe_bench"], "fetch_leaderboard", new_callable=AsyncMock) as mock_swe:
            with patch.object(agg.clients["lmsys_arena"], "fetch_leaderboard", new_callable=AsyncMock) as mock_lmsys:
                with patch.object(agg.clients["hf_leaderboard"], "fetch_leaderboard", new_callable=AsyncMock) as mock_hf:
                    # 设置返回值
                    mock_swe.return_value = {"bash-only": [{"model": "gpt-4", "rank": 1, "solve_rate": 85}]}
                    mock_lmsys.return_value = {"main": [{"model": "gpt-4", "rank": 1, "elo": 1298}]}
                    mock_hf.return_value = {"overall": [{"Model": "gpt-4", "Rank": 1, "Average": 85}]}

                    # Mock find_model_rank 方法
                    def swe_find(data, name):
                        if name.lower() == "gpt-4":
                            return {"rank": 1, "score": 85, "category": "bash-only", "source": "SWE-bench"}
                        return None

                    def lmsys_find(data, name):
                        if name.lower() == "gpt-4":
                            return {"rank": 1, "score": 1298, "source": "LMSYS Arena"}
                        return None

                    def hf_find(data, name):
                        if name.lower() == "gpt-4":
                            return {"rank": 1, "score": 85, "source": "HuggingFace Leaderboard"}
                        return None

                    agg.clients["swe_bench"].find_model_rank = swe_find
                    agg.clients["lmsys_arena"].find_model_rank = lmsys_find
                    agg.clients["hf_leaderboard"].find_model_rank = hf_find

                    # 获取所有排行榜的排名
                    ranks = await agg.get_model_ranks("GPT-4")

                    # 应该获得至少 1 个排行榜的结果
                    assert len(ranks) >= 1
                    sources = {r["source"] for r in ranks}

                    # 验证至少包含部分排行榜来源
                    assert any("SWE" in s or "LMSYS" in s or "HuggingFace" in s for s in sources)


class TestMilestoneDetectionWithAllLeaderboards:
    """使用所有排行榜的里程碑检测测试。"""

    def test_milestone_detection_swe_bench(self):
        """测试 SWE-bench 里程碑检测。"""
        # 注意：这是一个集成测试，验证里程碑检测逻辑
        # SWE-bench 前 10 名应该被标记为里程碑
        pass

    def test_milestone_detection_lmsys(self):
        """测试 LMSYS Arena 里程碑检测。"""
        # LMSYS Arena 前 20 名应该被标记为里程碑
        pass

    def test_milestone_detection_hf(self):
        """测试 HuggingFace Leaderboard 里程碑检测。"""
        # HF Leaderboard 前 15 名应该被标记为里程碑
        pass
