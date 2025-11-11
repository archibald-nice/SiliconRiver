"""增强分析集成测试 - 测试 Brave Search 集成。"""
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock

from src.analysis.async_analyzer import (
    AsyncModelAnalyzer,
    AnalysisContext,
    MCPDataSource,
)


class TestMCPDataSourceIntegration:
    """测试 MCP 数据源与 Brave Search 的集成。"""

    @pytest.mark.asyncio
    async def test_search_news_integration(self):
        """测试搜索新闻集成。"""
        with patch("src.analysis.async_analyzer.BRAVE_SEARCH_API_KEY", "test-key"):
            with patch("src.analysis.async_analyzer.ENABLE_BRAVE_SEARCH", True):
                mcp_source = MCPDataSource()

                # 模拟 Brave Search 结果
                mock_results = [
                    {
                        "title": "GPT-4 发布",
                        "description": "OpenAI 正式发布 GPT-4",
                        "url": "http://example.com",
                    },
                    {
                        "title": "GPT-4 性能测试",
                        "description": "GPT-4 性能评测结果",
                        "url": "http://example.com",
                    },
                ]

                with patch.object(
                    mcp_source.brave_client, "search_web", new_callable=AsyncMock
                ) as mock_search:
                    mock_search.return_value = mock_results

                    result = await mcp_source.search_news("GPT-4")

                    assert len(result) <= 3
                    assert all(isinstance(item, str) for item in result)
                    assert "GPT-4 发布" in result[0]

    @pytest.mark.asyncio
    async def test_search_news_disabled(self):
        """测试禁用搜索时返回空列表。"""
        with patch("src.analysis.async_analyzer.BRAVE_SEARCH_API_KEY", ""):
            with patch("src.analysis.async_analyzer.ENABLE_BRAVE_SEARCH", False):
                mcp_source = MCPDataSource()
                result = await mcp_source.search_news("GPT-4")
                assert result == []

    @pytest.mark.asyncio
    async def test_search_news_exception_handling(self):
        """测试异常处理。"""
        with patch("src.analysis.async_analyzer.BRAVE_SEARCH_API_KEY", "test-key"):
            with patch("src.analysis.async_analyzer.ENABLE_BRAVE_SEARCH", True):
                mcp_source = MCPDataSource()

                with patch.object(
                    mcp_source.brave_client, "search_web", new_callable=AsyncMock
                ) as mock_search:
                    mock_search.side_effect = Exception("Network error")

                    result = await mcp_source.search_news("GPT-4")

                    # 异常被捕获，返回空列表
                    assert result == []


class TestAnalysisContextEnhancement:
    """测试分析上下文增强。"""

    def test_analysis_context_with_news(self):
        """测试包含新闻的分析上下文。"""
        context = AnalysisContext(
            model_id="gpt-4",
            model_name="GPT-4",
            description="Advanced language model",
            news=[
                "GPT-4 发布：新的能力",
                "GPT-4 评测：性能提升",
            ],
        )

        assert context.model_id == "gpt-4"
        assert context.model_name == "GPT-4"
        assert len(context.news) == 2
        assert "新的能力" in context.news[0]

    def test_analysis_context_without_news(self):
        """测试不包含新闻的分析上下文。"""
        context = AnalysisContext(
            model_id="gpt-3",
            model_name="GPT-3",
        )

        assert context.news is None


class TestPromptEnhancement:
    """测试提示词增强。"""

    @pytest.mark.asyncio
    async def test_build_enhanced_prompt_with_news(self):
        """测试包含新闻的增强提示词构造。"""
        analyzer = AsyncModelAnalyzer(api_key="test-key")

        context = AnalysisContext(
            model_id="gpt-4",
            model_name="GPT-4",
            description="Advanced model",
            news=[
                "Title 1: Description 1",
                "Title 2: Description 2",
            ],
            tags=["large", "multimodal"],
        )

        prompt = analyzer._build_enhanced_prompt(context)

        # 验证提示词内容
        assert "GPT-4" in prompt
        assert "Advanced model" in prompt
        assert "最新新闻信息" in prompt
        assert "Title 1" in prompt
        assert "Title 2" in prompt
        assert "large" in prompt
        assert "multimodal" in prompt

    @pytest.mark.asyncio
    async def test_build_enhanced_prompt_without_news(self):
        """测试不包含新闻的增强提示词构造。"""
        analyzer = AsyncModelAnalyzer(api_key="test-key")

        context = AnalysisContext(
            model_id="gpt-3",
            model_name="GPT-3",
            description="Base model",
        )

        prompt = analyzer._build_enhanced_prompt(context)

        # 验证提示词内容
        assert "GPT-3" in prompt
        assert "Base model" in prompt
        # 新闻部分不应该出现
        assert prompt.count("最新新闻信息") == 0

    @pytest.mark.asyncio
    async def test_build_enhanced_prompt_json_format(self):
        """测试增强提示词中的 JSON 格式。"""
        analyzer = AsyncModelAnalyzer(api_key="test-key")

        context = AnalysisContext(
            model_id="test",
            model_name="Test Model",
        )

        prompt = analyzer._build_enhanced_prompt(context)

        # 验证 JSON 格式在提示词中
        assert "analysis_summary" in prompt
        assert "key_features" in prompt
        assert "use_cases" in prompt
        assert "performance_metrics" in prompt

    @pytest.mark.asyncio
    async def test_build_enhanced_prompt_instructions(self):
        """测试增强提示词中的指令。"""
        analyzer = AsyncModelAnalyzer(api_key="test-key")

        context = AnalysisContext(
            model_id="test",
            model_name="Test Model",
        )

        prompt = analyzer._build_enhanced_prompt(context)

        # 验证指令内容
        assert "只返回JSON" in prompt
        assert "客观、简洁" in prompt
        assert "综合分析" in prompt


class TestFullAnalysisFlowWithBraveSearch:
    """测试完整的分析流程集成。"""

    @pytest.mark.asyncio
    async def test_analyze_with_brave_search_news(self):
        """测试使用 Brave Search 新闻进行分析。"""
        analyzer = AsyncModelAnalyzer(api_key="test-key")

        context = AnalysisContext(
            model_id="gpt-4",
            model_name="GPT-4",
            description="Advanced model",
        )

        # 模拟新闻搜索结果
        mock_news = [
            "GPT-4 发布: OpenAI 发布新模型",
            "GPT-4 评测: 性能提升 50%",
        ]

        with patch.object(
            analyzer.mcp_source, "search_news", new_callable=AsyncMock
        ) as mock_search_news:
            mock_search_news.return_value = mock_news

            with patch.object(
                analyzer.mcp_source, "search_papers", new_callable=AsyncMock
            ) as mock_search_papers:
                mock_search_papers.return_value = []

                with patch.object(
                    analyzer.mcp_source, "get_timeline_context", new_callable=AsyncMock
                ) as mock_timeline:
                    mock_timeline.return_value = {}

                    # 构建提示词
                    context.news = await analyzer.mcp_source.search_news("GPT-4")
                    prompt = analyzer._build_enhanced_prompt(context)

                    # 验证新闻被包含
                    assert "GPT-4 发布" in prompt
                    assert "GPT-4 评测" in prompt

    @pytest.mark.asyncio
    async def test_analyze_with_empty_news(self):
        """测试空新闻结果的分析。"""
        analyzer = AsyncModelAnalyzer(api_key="test-key")

        context = AnalysisContext(
            model_id="unknown-model",
            model_name="Unknown Model",
        )

        with patch.object(
            analyzer.mcp_source, "search_news", new_callable=AsyncMock
        ) as mock_search_news:
            mock_search_news.return_value = []

            context.news = await analyzer.mcp_source.search_news("Unknown Model")
            prompt = analyzer._build_enhanced_prompt(context)

            # 不应该包含新闻部分
            assert "最新新闻信息" not in prompt or prompt.count("最新新闻信息") == 0


class TestBraveSearchConfiguration:
    """测试 Brave Search 配置。"""

    def test_mcp_data_source_initialization_with_key(self):
        """测试有 API 密钥时的初始化。"""
        with patch("src.analysis.async_analyzer.BRAVE_SEARCH_API_KEY", "test-key"):
            with patch("src.analysis.async_analyzer.ENABLE_BRAVE_SEARCH", True):
                mcp_source = MCPDataSource()
                assert mcp_source.brave_client is not None

    def test_mcp_data_source_initialization_without_key(self):
        """测试没有 API 密钥时的初始化。"""
        with patch("src.analysis.async_analyzer.BRAVE_SEARCH_API_KEY", ""):
            with patch("src.analysis.async_analyzer.ENABLE_BRAVE_SEARCH", True):
                mcp_source = MCPDataSource()
                assert mcp_source.brave_client is None

    def test_mcp_data_source_initialization_disabled(self):
        """测试禁用时的初始化。"""
        with patch("src.analysis.async_analyzer.BRAVE_SEARCH_API_KEY", "test-key"):
            with patch("src.analysis.async_analyzer.ENABLE_BRAVE_SEARCH", False):
                mcp_source = MCPDataSource()
                assert mcp_source.brave_client is None
