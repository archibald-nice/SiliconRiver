"""性能监控和分析工具。

用于监控异步分析流程的性能指标，包括：
- API 调用延迟
- 缓存命中率
- 并发效率
- 错误率和恢复时间
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from collections import defaultdict, deque

LOGGER = logging.getLogger("silicon_river.performance_monitor")


@dataclass(slots=True)
class LatencyMetric:
    """延迟指标。"""
    name: str
    value: float  # 毫秒
    timestamp: float = field(default_factory=time.time)
    success: bool = True
    error_msg: str | None = None


@dataclass(slots=True)
class CacheMetric:
    """缓存指标。"""
    component: str  # brave_search, swe_bench, lmsys_arena, hf_leaderboard
    hit: bool
    size: int = 0  # 缓存条目数
    ttl_remaining: int = 0  # 剩余 TTL（秒）


class PerformanceMonitor:
    """性能监控器。

    监控关键性能指标：
    - 分析总延迟
    - 各阶段延迟（数据收集、LLM 调用、处理）
    - API 调用成功率
    - 缓存命中率
    - 并发效率
    """

    # 保留最近 1000 条指标记录
    MAX_METRICS_WINDOW = 1000

    def __init__(self):
        """初始化性能监控器。"""
        self.latency_metrics: deque[LatencyMetric] = deque(maxlen=self.MAX_METRICS_WINDOW)
        self.cache_metrics: deque[CacheMetric] = deque(maxlen=self.MAX_METRICS_WINDOW)
        self.api_call_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failure": 0, "total_time_ms": 0}
        )
        self.concurrent_analyses: int = 0
        self.max_concurrent_reached: int = 0

    def record_latency(
        self,
        name: str,
        value: float,
        success: bool = True,
        error_msg: str | None = None
    ) -> None:
        """记录延迟指标。

        Args:
            name: 指标名称 (e.g., "search_news", "llm_call", "total_analysis")
            value: 延迟时间（毫秒）
            success: 是否成功
            error_msg: 错误信息（如果失败）
        """
        metric = LatencyMetric(
            name=name,
            value=value,
            success=success,
            error_msg=error_msg
        )
        self.latency_metrics.append(metric)

        # 记录 API 调用统计
        if name in ["brave_search", "swe_bench", "lmsys_arena", "hf_leaderboard"]:
            stats = self.api_call_stats[name]
            stats["total_time_ms"] += value
            if success:
                stats["success"] += 1
            else:
                stats["failure"] += 1

    def record_cache_hit(
        self,
        component: str,
        hit: bool,
        size: int = 0,
        ttl_remaining: int = 0
    ) -> None:
        """记录缓存指标。

        Args:
            component: 组件名称
            hit: 是否缓存命中
            size: 缓存大小
            ttl_remaining: 剩余 TTL（秒）
        """
        metric = CacheMetric(
            component=component,
            hit=hit,
            size=size,
            ttl_remaining=ttl_remaining
        )
        self.cache_metrics.append(metric)

    def record_concurrent_analysis(self, count: int) -> None:
        """记录并发分析数量。

        Args:
            count: 当前并发分析数量
        """
        self.concurrent_analyses = count
        if count > self.max_concurrent_reached:
            self.max_concurrent_reached = count

    def get_statistics(self) -> dict[str, Any]:
        """获取性能统计信息。

        Returns:
            包含各种性能指标的字典
        """
        stats = {
            "metrics_collected": len(self.latency_metrics),
            "cache_metrics_collected": len(self.cache_metrics),
            "current_concurrent": self.concurrent_analyses,
            "max_concurrent_reached": self.max_concurrent_reached,
            "api_call_statistics": {},
            "latency_summary": {},
            "cache_statistics": {},
        }

        # API 调用统计
        for api_name, api_stats in self.api_call_stats.items():
            total = api_stats["success"] + api_stats["failure"]
            if total > 0:
                avg_time = api_stats["total_time_ms"] / total
                success_rate = api_stats["success"] / total * 100
                stats["api_call_statistics"][api_name] = {
                    "total_calls": total,
                    "successful": api_stats["success"],
                    "failed": api_stats["failure"],
                    "success_rate": f"{success_rate:.2f}%",
                    "average_time_ms": f"{avg_time:.2f}",
                }

        # 延迟统计（按指标名称分组）
        latency_by_name: dict[str, list[float]] = defaultdict(list)
        for metric in self.latency_metrics:
            if metric.success:
                latency_by_name[metric.name].append(metric.value)

        for name, values in latency_by_name.items():
            if values:
                stats["latency_summary"][name] = {
                    "count": len(values),
                    "min_ms": f"{min(values):.2f}",
                    "max_ms": f"{max(values):.2f}",
                    "avg_ms": f"{sum(values) / len(values):.2f}",
                    "p95_ms": f"{self._percentile(values, 0.95):.2f}",
                    "p99_ms": f"{self._percentile(values, 0.99):.2f}",
                }

        # 缓存统计
        cache_by_component: dict[str, list[bool]] = defaultdict(list)
        for metric in self.cache_metrics:
            cache_by_component[metric.component].append(metric.hit)

        for component, hits in cache_by_component.items():
            if hits:
                hit_rate = sum(hits) / len(hits) * 100
                stats["cache_statistics"][component] = {
                    "total_accesses": len(hits),
                    "hits": sum(hits),
                    "misses": len(hits) - sum(hits),
                    "hit_rate": f"{hit_rate:.2f}%",
                }

        return stats

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        """计算百分位数。

        Args:
            values: 值列表
            percentile: 百分位（0-1）

        Returns:
            百分位数值
        """
        if not values:
            return 0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile)
        return sorted_values[min(index, len(sorted_values) - 1)]

    def get_total_analysis_time_stats(self) -> dict[str, Any]:
        """获取总分析时间统计。

        Returns:
            包含分析时间统计的字典
        """
        total_times = [
            m.value for m in self.latency_metrics
            if m.name == "total_analysis" and m.success
        ]

        if not total_times:
            return {
                "total_analyses": 0,
                "average_time_ms": 0,
                "min_time_ms": 0,
                "max_time_ms": 0,
                "p95_time_ms": 0,
                "p99_time_ms": 0,
                "meets_sla": False,
            }

        avg_time = sum(total_times) / len(total_times)

        return {
            "total_analyses": len(total_times),
            "average_time_ms": f"{avg_time:.2f}",
            "min_time_ms": f"{min(total_times):.2f}",
            "max_time_ms": f"{max(total_times):.2f}",
            "p95_time_ms": f"{self._percentile(total_times, 0.95):.2f}",
            "p99_time_ms": f"{self._percentile(total_times, 0.99):.2f}",
            "meets_sla": avg_time < 15000,  # SLA: < 15 秒
        }

    def get_failure_analysis(self) -> dict[str, Any]:
        """获取失败分析。

        Returns:
            包含失败信息的字典
        """
        failures_by_component: dict[str, list[str]] = defaultdict(list)
        for metric in self.latency_metrics:
            if not metric.success and metric.error_msg:
                failures_by_component[metric.name].append(metric.error_msg)

        failure_stats = {}
        for component, errors in failures_by_component.items():
            failure_stats[component] = {
                "failure_count": len(errors),
                "recent_errors": errors[-5:],  # 最后 5 条错误
                "error_rate": self._calculate_error_rate(component),
            }

        return failure_stats

    def _calculate_error_rate(self, component: str) -> str:
        """计算特定组件的错误率。

        Args:
            component: 组件名称

        Returns:
            错误率百分比字符串
        """
        if component not in self.api_call_stats:
            return "0.00%"

        stats = self.api_call_stats[component]
        total = stats["success"] + stats["failure"]
        if total == 0:
            return "0.00%"

        error_rate = stats["failure"] / total * 100
        return f"{error_rate:.2f}%"

    def reset(self) -> None:
        """重置所有指标。"""
        self.latency_metrics.clear()
        self.cache_metrics.clear()
        self.api_call_stats.clear()
        self.concurrent_analyses = 0
        self.max_concurrent_reached = 0
        LOGGER.info("性能监控指标已重置")

    def log_summary(self) -> None:
        """打印性能统计摘要。"""
        stats = self.get_statistics()
        total_stats = self.get_total_analysis_time_stats()
        failure_stats = self.get_failure_analysis()

        LOGGER.info("=" * 60)
        LOGGER.info("性能监控统计摘要")
        LOGGER.info("=" * 60)

        # 分析时间统计
        LOGGER.info("分析时间统计:")
        LOGGER.info(f"  总分析数: {total_stats['total_analyses']}")
        LOGGER.info(f"  平均时间: {total_stats['average_time_ms']} ms")
        LOGGER.info(f"  P95 时间: {total_stats['p95_time_ms']} ms")
        LOGGER.info(f"  P99 时间: {total_stats['p99_time_ms']} ms")
        LOGGER.info(f"  SLA 达成: {total_stats['meets_sla']}")

        # API 调用统计
        if stats["api_call_statistics"]:
            LOGGER.info("API 调用统计:")
            for api_name, api_stats in stats["api_call_statistics"].items():
                LOGGER.info(f"  {api_name}:")
                LOGGER.info(f"    调用数: {api_stats['total_calls']}")
                LOGGER.info(f"    成功率: {api_stats['success_rate']}")
                LOGGER.info(f"    平均延迟: {api_stats['average_time_ms']} ms")

        # 缓存统计
        if stats["cache_statistics"]:
            LOGGER.info("缓存统计:")
            for component, cache_stats in stats["cache_statistics"].items():
                LOGGER.info(f"  {component}: {cache_stats['hit_rate']}")

        # 失败分析
        if failure_stats:
            LOGGER.info("失败分析:")
            for component, failure_info in failure_stats.items():
                LOGGER.info(f"  {component}: {failure_info['failure_count']} 次失败 ({failure_info['error_rate']})")

        LOGGER.info("=" * 60)


# 全局监控器实例
_global_monitor: PerformanceMonitor | None = None


def get_monitor() -> PerformanceMonitor:
    """获取全局性能监控器实例。

    Returns:
        性能监控器实例
    """
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = PerformanceMonitor()
    return _global_monitor


def reset_monitor() -> None:
    """重置全局性能监控器。"""
    global _global_monitor
    if _global_monitor:
        _global_monitor.reset()
