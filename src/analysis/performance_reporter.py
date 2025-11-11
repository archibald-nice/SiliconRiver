"""性能报告生成工具。

用于生成详细的性能分析报告，支持多种格式（文本、JSON、HTML）。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from io import StringIO

from src.analysis.performance_monitor import get_monitor


class PerformanceReporter:
    """性能报告生成器。"""

    @staticmethod
    def generate_text_report() -> str:
        """生成文本格式的性能报告。

        Returns:
            格式化的文本报告
        """
        monitor = get_monitor()
        stats = monitor.get_statistics()
        total_stats = monitor.get_total_analysis_time_stats()
        failure_stats = monitor.get_failure_analysis()

        report = StringIO()
        report.write("=" * 80 + "\n")
        report.write(f"性能监控报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        report.write("=" * 80 + "\n\n")

        # 1. 执行概览
        report.write("【执行概览】\n")
        report.write(f"总分析数: {total_stats['total_analyses']}\n")
        report.write(f"当前并发: {stats['current_concurrent']}\n")
        report.write(f"最大并发: {stats['max_concurrent_reached']}\n")
        report.write(f"收集指标数: {stats['metrics_collected']}\n\n")

        # 2. 分析时间统计
        report.write("【分析时间统计】\n")
        report.write(f"平均时间: {total_stats['average_time_ms']} ms\n")
        report.write(f"最小时间: {total_stats['min_time_ms']} ms\n")
        report.write(f"最大时间: {total_stats['max_time_ms']} ms\n")
        report.write(f"P95 时间: {total_stats['p95_time_ms']} ms\n")
        report.write(f"P99 时间: {total_stats['p99_time_ms']} ms\n")
        report.write(f"SLA 达成 (< 15s): {'✓' if total_stats['meets_sla'] else '✗'}\n\n")

        # 3. 各阶段性能
        if stats["latency_summary"]:
            report.write("【各阶段性能】\n")
            for stage_name, stage_stats in stats["latency_summary"].items():
                report.write(f"\n{stage_name}:\n")
                report.write(f"  执行次数: {stage_stats['count']}\n")
                report.write(f"  平均延迟: {stage_stats['avg_ms']} ms\n")
                report.write(f"  P95 延迟: {stage_stats['p95_ms']} ms\n")
                report.write(f"  P99 延迟: {stage_stats['p99_ms']} ms\n")
            report.write("\n")

        # 4. API 调用统计
        if stats["api_call_statistics"]:
            report.write("【API 调用统计】\n")
            for api_name, api_stats in stats["api_call_statistics"].items():
                report.write(f"\n{api_name}:\n")
                report.write(f"  总调用数: {api_stats['total_calls']}\n")
                report.write(f"  成功调用: {api_stats['successful']}\n")
                report.write(f"  失败调用: {api_stats['failed']}\n")
                report.write(f"  成功率: {api_stats['success_rate']}\n")
                report.write(f"  平均延迟: {api_stats['average_time_ms']} ms\n")
            report.write("\n")

        # 5. 缓存统计
        if stats["cache_statistics"]:
            report.write("【缓存统计】\n")
            for component, cache_stats in stats["cache_statistics"].items():
                report.write(f"\n{component}:\n")
                report.write(f"  总访问数: {cache_stats['total_accesses']}\n")
                report.write(f"  缓存命中: {cache_stats['hits']}\n")
                report.write(f"  缓存未中: {cache_stats['misses']}\n")
                report.write(f"  命中率: {cache_stats['hit_rate']}\n")
            report.write("\n")

        # 6. 失败分析
        if failure_stats:
            report.write("【失败分析】\n")
            for component, failure_info in failure_stats.items():
                if failure_info['failure_count'] > 0:
                    report.write(f"\n{component}:\n")
                    report.write(f"  失败次数: {failure_info['failure_count']}\n")
                    report.write(f"  错误率: {failure_info['error_rate']}\n")
                    if failure_info['recent_errors']:
                        report.write(f"  最近错误:\n")
                        for error in failure_info['recent_errors'][-3:]:
                            report.write(f"    - {error}\n")
            report.write("\n")

        # 7. 建议
        report.write("【性能建议】\n")
        report.write(PerformanceReporter._generate_recommendations(stats, total_stats))

        report.write("\n" + "=" * 80 + "\n")
        return report.getvalue()

    @staticmethod
    def generate_json_report() -> str:
        """生成 JSON 格式的性能报告。

        Returns:
            JSON 格式的报告
        """
        monitor = get_monitor()
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "statistics": monitor.get_statistics(),
            "total_analysis_time": monitor.get_total_analysis_time_stats(),
            "failure_analysis": monitor.get_failure_analysis(),
        }
        return json.dumps(report_data, indent=2, ensure_ascii=False)

    @staticmethod
    def _generate_recommendations(
        stats: dict[str, Any],
        total_stats: dict[str, Any]
    ) -> str:
        """生成性能改进建议。

        Args:
            stats: 性能统计数据
            total_stats: 总分析时间统计

        Returns:
            建议文本
        """
        recommendations = []

        # 1. 分析时间建议
        if not total_stats['meets_sla']:
            avg_time = float(total_stats['average_time_ms'].replace(',', ''))
            if avg_time > 20000:
                recommendations.append(
                    "⚠️  分析平均耗时过长 (> 20s)，建议：\n"
                    "   - 增加并发度（MAX_CONCURRENT_ANALYSIS）\n"
                    "   - 优化 LLM 提示词长度\n"
                    "   - 考虑缓存热预热"
                )
            else:
                recommendations.append(
                    "⚠️  分析耗时接近 SLA 上限 (15s)，建议：\n"
                    "   - 监控 API 延迟\n"
                    "   - 考虑提高排行榜缓存 TTL"
                )

        # 2. API 成功率建议
        for api_name, api_stats in stats.get("api_call_statistics", {}).items():
            success_rate_str = api_stats['success_rate'].rstrip('%')
            try:
                success_rate = float(success_rate_str)
                if success_rate < 90:
                    recommendations.append(
                        f"⚠️  {api_name} 成功率低 ({api_stats['success_rate']})，建议：\n"
                        f"   - 检查 API 配置和网络连接\n"
                        f"   - 增加重试次数或超时时间"
                    )
                elif success_rate < 95:
                    recommendations.append(
                        f"ℹ️  {api_name} 成功率一般 ({api_stats['success_rate']})，可继续优化"
                    )
            except ValueError:
                pass

        # 3. 缓存命中率建议
        for component, cache_stats in stats.get("cache_statistics", {}).items():
            hit_rate_str = cache_stats['hit_rate'].rstrip('%')
            try:
                hit_rate = float(hit_rate_str)
                if hit_rate < 50:
                    recommendations.append(
                        f"ℹ️  {component} 缓存命中率低 ({cache_stats['hit_rate']})，可优化：\n"
                        f"   - 增加缓存 TTL\n"
                        f"   - 实现缓存预热策略"
                    )
            except ValueError:
                pass

        if not recommendations:
            recommendations.append("✓ 系统性能良好，无需改进")

        return "\n".join(recommendations)


def print_performance_report() -> None:
    """打印完整的性能报告。"""
    reporter = PerformanceReporter()
    report = reporter.generate_text_report()
    print(report)


def get_performance_report_json() -> str:
    """获取 JSON 格式的性能报告。

    Returns:
        JSON 字符串
    """
    reporter = PerformanceReporter()
    return reporter.generate_json_report()
