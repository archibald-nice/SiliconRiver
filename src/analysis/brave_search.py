"""Brave Search API 异步客户端实现。

提供与 Brave Search API 的交互能力，包括：
- Web 搜索功能
- 速率限制控制
- 指数退避重试机制
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

LOGGER = logging.getLogger("silicon_river.brave_search")


class BraveSearchClient:
    """Brave Search API 异步客户端。

    特性：
    - 异步 HTTP 请求
    - Token Bucket 速率限制
    - 指数退避重试机制
    - 完整的错误处理
    """

    # API 配置
    API_URL = "https://api.search.brave.com/res/v1"
    REQUEST_TIMEOUT = 10  # 秒
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒（基础延迟）

    # 速率限制配置
    RATE_LIMIT_REQUESTS = 10  # 每时间窗口的最大请求数
    RATE_LIMIT_WINDOW = 60  # 时间窗口（秒）

    def __init__(self, api_key: str | None = None):
        """初始化 Brave Search 客户端。

        Args:
            api_key: Brave Search API 密钥。如果为 None，则禁用搜索功能。
        """
        self.api_key = api_key
        self.enabled = api_key is not None

        # Token Bucket 速率限制
        self.tokens = self.RATE_LIMIT_REQUESTS
        self.last_refill = time.time()

    async def search_web(
        self,
        query: str,
        count: int = 5,
        freshness: str = "pw"
    ) -> list[dict]:
        """执行网络搜索。

        Args:
            query: 搜索查询字符串
            count: 返回的结果数量（默认 5）
            freshness: 结果时效性过滤
                - "pd": 过去一天
                - "pw": 过去一周（默认）
                - "pm": 过去一个月
                - "py": 过去一年

        Returns:
            搜索结果列表，每条结果包含 title、description、url 等字段
            如果搜索失败或客户端未启用，返回空列表。
        """
        if not self.enabled:
            LOGGER.debug("Brave Search 未启用")
            return []

        try:
            # 应用速率限制
            await self._apply_rate_limit()

            # 构建请求参数
            params = {
                "q": query,
                "count": min(count, 20),  # API 最多支持 20 结果
                "freshness": freshness,
            }

            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            }

            # 使用重试机制执行请求
            result = await self._with_retry(
                self._execute_search, params, headers
            )
            return result

        except Exception as e:
            LOGGER.error(f"网络搜索异常：{e}")
            return []

    async def _execute_search(
        self,
        params: dict,
        headers: dict
    ) -> list[dict]:
        """执行实际的搜索请求。

        Args:
            params: 查询参数
            headers: HTTP 头

        Returns:
            搜索结果列表
        """
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.API_URL}/search",
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # 提取结果
                        results = []
                        for item in data.get("results", [])[:10]:  # 限制返回数量
                            result = {
                                "title": item.get("title", ""),
                                "description": item.get("description", ""),
                                "url": item.get("url", ""),
                            }
                            if result["title"] and result["description"]:
                                results.append(result)
                        return results
                    elif resp.status == 429:
                        # 速率限制
                        raise BraveSearchRateLimitError("超过速率限制")
                    elif resp.status == 401:
                        raise BraveSearchAuthError("API 密钥无效")
                    else:
                        raise BraveSearchAPIError(
                            f"API 返回错误：HTTP {resp.status}"
                        )
            except asyncio.TimeoutError:
                raise BraveSearchTimeoutError("请求超时")
            except aiohttp.ClientError as e:
                raise BraveSearchNetworkError(f"网络错误：{e}")

    async def _apply_rate_limit(self) -> None:
        """应用 Token Bucket 速率限制。

        基于 Token Bucket 算法实现速率限制。
        """
        now = time.time()
        elapsed = now - self.last_refill

        # 按经过时间补充令牌
        tokens_to_add = (elapsed / self.RATE_LIMIT_WINDOW) * self.RATE_LIMIT_REQUESTS
        self.tokens = min(
            self.RATE_LIMIT_REQUESTS,
            self.tokens + tokens_to_add
        )
        self.last_refill = now

        # 等待直到有可用令牌
        while self.tokens < 1:
            wait_time = (1 - self.tokens) / (
                self.RATE_LIMIT_REQUESTS / self.RATE_LIMIT_WINDOW
            )
            await asyncio.sleep(wait_time)
            now = time.time()
            elapsed = now - self.last_refill
            tokens_to_add = (elapsed / self.RATE_LIMIT_WINDOW) * self.RATE_LIMIT_REQUESTS
            self.tokens = min(
                self.RATE_LIMIT_REQUESTS,
                self.tokens + tokens_to_add
            )
            self.last_refill = now

        # 消费一个令牌
        self.tokens -= 1

    async def _with_retry(
        self,
        func,
        *args,
        **kwargs
    ) -> Any:
        """带指数退避重试的函数执行。

        Args:
            func: 异步函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数执行结果

        Raises:
            异常：最大重试次数后仍失败时抛出
        """
        last_exception = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return await func(*args, **kwargs)
            except (BraveSearchRateLimitError, BraveSearchTimeoutError) as e:
                # 可重试的错误
                last_exception = e
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_DELAY * (2 ** (attempt - 1))
                    LOGGER.warning(
                        f"搜索失败（尝试 {attempt}/{self.MAX_RETRIES}），"
                        f"将在 {wait_time}s 后重试：{e}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    LOGGER.error(f"搜索在 {self.MAX_RETRIES} 次重试后仍失败")
            except (BraveSearchAuthError, BraveSearchAPIError) as e:
                # 不可重试的错误
                LOGGER.error(f"搜索不可重试错误：{e}")
                raise
            except BraveSearchNetworkError as e:
                # 网络错误，可重试
                last_exception = e
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_DELAY * (2 ** (attempt - 1))
                    LOGGER.warning(
                        f"网络错误（尝试 {attempt}/{self.MAX_RETRIES}），"
                        f"将在 {wait_time}s 后重试：{e}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    LOGGER.error(f"网络错误在 {self.MAX_RETRIES} 次重试后仍失败")

        if last_exception:
            raise last_exception
        raise BraveSearchError("未知错误")


# 自定义异常类
class BraveSearchError(Exception):
    """Brave Search 基础异常。"""
    pass


class BraveSearchAPIError(BraveSearchError):
    """API 返回错误。"""
    pass


class BraveSearchAuthError(BraveSearchError):
    """身份验证失败。"""
    pass


class BraveSearchRateLimitError(BraveSearchError):
    """超过速率限制。"""
    pass


class BraveSearchTimeoutError(BraveSearchError):
    """请求超时。"""
    pass


class BraveSearchNetworkError(BraveSearchError):
    """网络连接错误。"""
    pass
