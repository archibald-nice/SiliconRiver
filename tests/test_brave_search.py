"""Brave Search 客户端单元测试。"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from src.analysis.brave_search import (
    BraveSearchClient,
    BraveSearchAPIError,
    BraveSearchAuthError,
    BraveSearchRateLimitError,
    BraveSearchTimeoutError,
    BraveSearchNetworkError,
)


class TestBraveSearchClientInitialization:
    """测试客户端初始化。"""

    def test_client_enabled_with_api_key(self):
        """测试有效 API 密钥时客户端启用。"""
        client = BraveSearchClient(api_key="test-key")
        assert client.enabled is True
        assert client.api_key == "test-key"

    def test_client_disabled_without_api_key(self):
        """测试没有 API 密钥时客户端禁用。"""
        client = BraveSearchClient(api_key=None)
        assert client.enabled is False
        assert client.api_key is None

    def test_token_bucket_initialization(self):
        """测试 Token Bucket 初始化。"""
        client = BraveSearchClient(api_key="test-key")
        assert client.tokens == client.RATE_LIMIT_REQUESTS
        assert client.last_refill is not None


class TestBraveSearchClientRateLimiting:
    """测试速率限制功能。"""

    @pytest.mark.asyncio
    async def test_rate_limit_single_request(self):
        """测试单个请求的速率限制。"""
        client = BraveSearchClient(api_key="test-key")
        initial_tokens = client.tokens

        await client._apply_rate_limit()

        assert client.tokens < initial_tokens

    @pytest.mark.asyncio
    async def test_rate_limit_token_consumption(self):
        """测试令牌消耗。"""
        client = BraveSearchClient(api_key="test-key")
        client.tokens = 2

        # 快速消耗令牌
        await client._apply_rate_limit()
        first_tokens = client.tokens

        await client._apply_rate_limit()
        second_tokens = client.tokens

        assert first_tokens < 2
        assert second_tokens < first_tokens

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_when_no_tokens(self):
        """测试在没有令牌时阻塞。"""
        client = BraveSearchClient(api_key="test-key")
        client.tokens = 0.1  # 不足 1 个令牌
        client.last_refill = asyncio.get_event_loop().time()

        # 应该等待直到有令牌可用
        await asyncio.wait_for(client._apply_rate_limit(), timeout=2)


class TestBraveSearchClientRetry:
    """测试重试机制。"""

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self):
        """测试超时时重试。"""
        client = BraveSearchClient(api_key="test-key")

        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise BraveSearchTimeoutError("Timeout")
            return "success"

        result = await client._with_retry(failing_func)

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self):
        """测试速率限制时重试。"""
        client = BraveSearchClient(api_key="test-key")

        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise BraveSearchRateLimitError("Rate limited")
            return "success"

        result = await client._with_retry(failing_func)

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(self):
        """测试身份验证错误时不重试。"""
        client = BraveSearchClient(api_key="test-key")

        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise BraveSearchAuthError("Invalid key")

        with pytest.raises(BraveSearchAuthError):
            await client._with_retry(failing_func)

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_api_error(self):
        """测试 API 错误时不重试。"""
        client = BraveSearchClient(api_key="test-key")

        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise BraveSearchAPIError("Server error")

        with pytest.raises(BraveSearchAPIError):
            await client._with_retry(failing_func)

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_max_attempts(self):
        """测试达到最大重试次数。"""
        client = BraveSearchClient(api_key="test-key")

        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise BraveSearchTimeoutError("Timeout")

        with pytest.raises(BraveSearchTimeoutError):
            await client._with_retry(failing_func)

        assert call_count == client.MAX_RETRIES


class TestBraveSearchClientSearchWeb:
    """测试网络搜索功能。"""

    @pytest.mark.asyncio
    async def test_search_disabled_client(self):
        """测试禁用的客户端返回空列表。"""
        client = BraveSearchClient(api_key=None)
        result = await client.search_web("test query")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_successful(self):
        """测试成功的搜索。"""
        client = BraveSearchClient(api_key="test-key")

        mock_results = [
            {
                "title": "Test Result 1",
                "description": "A test search result",
                "url": "http://test1.com",
            },
            {
                "title": "Test Result 2",
                "description": "Another test result",
                "url": "http://test2.com",
            },
        ]

        with patch.object(
            client, "_with_retry", new_callable=AsyncMock
        ) as mock_retry:
            mock_retry.return_value = mock_results
            result = await client.search_web("test query")

            assert result == mock_results
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_search_query_construction(self):
        """测试搜索查询构造。"""
        client = BraveSearchClient(api_key="test-key")

        with patch.object(
            client, "_apply_rate_limit", new_callable=AsyncMock
        ):
            with patch.object(
                client, "_with_retry", new_callable=AsyncMock
            ) as mock_retry:
                mock_retry.return_value = []
                await client.search_web("GPT-4", count=10, freshness="pm")

                # 验证调用参数
                mock_retry.assert_called_once()
                call_args = mock_retry.call_args
                assert call_args[0][1]["q"] == "GPT-4 (release OR announcement OR benchmark OR paper)"
                assert call_args[0][1]["count"] == 10
                assert call_args[0][1]["freshness"] == "pm"

    @pytest.mark.asyncio
    async def test_search_max_results_capped(self):
        """测试搜索结果数量被限制。"""
        client = BraveSearchClient(api_key="test-key")

        # 模拟返回超过限制的结果
        mock_results = [
            {"title": f"Result {i}", "description": f"Desc {i}", "url": f"http://test{i}.com"}
            for i in range(15)
        ]

        with patch.object(
            client, "_apply_rate_limit", new_callable=AsyncMock
        ):
            with patch.object(
                client, "_execute_search", new_callable=AsyncMock
            ) as mock_execute:
                mock_execute.return_value = mock_results
                result = await client.search_web("test")

                # 应该限制返回 10 条
                assert len(result) <= 10

    @pytest.mark.asyncio
    async def test_search_exception_handling(self):
        """测试搜索异常处理。"""
        client = BraveSearchClient(api_key="test-key")

        with patch.object(
            client, "_apply_rate_limit", new_callable=AsyncMock
        ):
            with patch.object(
                client, "_with_retry", new_callable=AsyncMock
            ) as mock_retry:
                mock_retry.side_effect = Exception("Unexpected error")
                result = await client.search_web("test query")

                # 异常被捕获，返回空列表
                assert result == []


class TestBraveSearchClientExecuteSearch:
    """测试执行搜索请求。"""

    @pytest.mark.asyncio
    async def test_execute_search_success(self):
        """测试成功的 API 请求。"""
        client = BraveSearchClient(api_key="test-key")

        mock_response = {
            "results": [
                {
                    "title": "Result 1",
                    "description": "Description 1",
                    "url": "http://test1.com",
                },
                {
                    "title": "Result 2",
                    "description": "Description 2",
                    "url": "http://test2.com",
                },
            ]
        }

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response_obj = AsyncMock()
            mock_response_obj.status = 200
            mock_response_obj.json = AsyncMock(return_value=mock_response)
            mock_response_obj.__aenter__.return_value = mock_response_obj
            mock_response_obj.__aexit__.return_value = None

            mock_get.return_value.__aenter__.return_value = mock_response_obj
            mock_get.return_value.__aexit__ = AsyncMock()

            result = await client._execute_search(
                {"q": "test", "count": 5},
                {"Accept": "application/json"}
            )

            assert len(result) == 2
            assert result[0]["title"] == "Result 1"

    @pytest.mark.asyncio
    async def test_execute_search_401_error(self):
        """测试 401 认证错误。"""
        client = BraveSearchClient(api_key="invalid-key")

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response_obj = AsyncMock()
            mock_response_obj.status = 401
            mock_response_obj.__aenter__.return_value = mock_response_obj
            mock_response_obj.__aexit__.return_value = None

            mock_get.return_value.__aenter__.return_value = mock_response_obj
            mock_get.return_value.__aexit__ = AsyncMock()

            with pytest.raises(BraveSearchAuthError):
                await client._execute_search(
                    {"q": "test", "count": 5},
                    {"Accept": "application/json"}
                )

    @pytest.mark.asyncio
    async def test_execute_search_429_error(self):
        """测试 429 速率限制错误。"""
        client = BraveSearchClient(api_key="test-key")

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response_obj = AsyncMock()
            mock_response_obj.status = 429
            mock_response_obj.__aenter__.return_value = mock_response_obj
            mock_response_obj.__aexit__.return_value = None

            mock_get.return_value.__aenter__.return_value = mock_response_obj
            mock_get.return_value.__aexit__ = AsyncMock()

            with pytest.raises(BraveSearchRateLimitError):
                await client._execute_search(
                    {"q": "test", "count": 5},
                    {"Accept": "application/json"}
                )

    @pytest.mark.asyncio
    async def test_execute_search_timeout(self):
        """测试请求超时。"""
        client = BraveSearchClient(api_key="test-key")

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.side_effect = asyncio.TimeoutError()

            with pytest.raises(BraveSearchTimeoutError):
                await client._execute_search(
                    {"q": "test", "count": 5},
                    {"Accept": "application/json"}
                )
