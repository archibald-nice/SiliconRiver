"""性能监控装饰器。

用于自动记录异步函数的性能指标。
"""
from __future__ import annotations

import asyncio
import functools
import logging
import time
from typing import Any, Callable, TypeVar, cast

from src.analysis.performance_monitor import get_monitor

LOGGER = logging.getLogger("silicon_river.performance_decorator")

T = TypeVar("T")


def monitor_latency(metric_name: str | None = None) -> Callable:
    """监控异步函数的延迟。

    Args:
        metric_name: 指标名称，如果未提供则使用函数名

    Returns:
        装饰器函数
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            name = metric_name or f"{func.__module__}.{func.__name__}"
            start_time = time.time()

            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.time() - start_time) * 1000
                get_monitor().record_latency(name, elapsed_ms, success=True)
                return result
            except Exception as e:
                elapsed_ms = (time.time() - start_time) * 1000
                error_msg = f"{type(e).__name__}: {str(e)[:100]}"
                get_monitor().record_latency(
                    name, elapsed_ms, success=False, error_msg=error_msg
                )
                raise

        return wrapper

    return decorator


def monitor_cache(component_name: str) -> Callable:
    """监控缓存命中情况。

    Args:
        component_name: 组件名称

    Returns:
        装饰器函数
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # 假设 self.cache 存在
            cache = None
            cache_size = 0
            ttl_remaining = 0

            if args and hasattr(args[0], "cache"):
                cache = args[0].cache
                cache_size = len(cache) if isinstance(cache, dict) else 0

            if args and hasattr(args[0], "cache_ttl"):
                ttl_remaining = args[0].cache_ttl

            result = await func(*args, **kwargs)

            # 记录是否命中缓存（简单判断：如果返回数据且缓存不为空则视为可能命中）
            hit = cache_size > 0 if cache else False
            get_monitor().record_cache_hit(
                component_name, hit, cache_size, ttl_remaining
            )

            return result

        return wrapper

    return decorator
