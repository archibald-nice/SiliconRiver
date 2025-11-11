"""模型重新分析工具 - 支持三种重新分析策略。"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import click

# 添加项目根目录到Python路径
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from src.scraper.analysis_orchestrator import AnalysisOrchestrator

LOGGER = logging.getLogger("silicon_river.reanalyze")

# 配置日志
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(message)s"
)


@click.command()
@click.option(
    "--force",
    is_flag=True,
    help="强制重新分析所有模型（忽略已有记录）"
)
@click.option(
    "--older-than-days",
    type=int,
    help="重新分析N天前分析过的模型"
)
@click.option(
    "--missing-fields",
    help="重新分析缺少指定字段的模型（逗号分隔，如 is_milestone,milestone_features）"
)
@click.option(
    "--provider",
    help="限制特定提供商（如 openai,anthropic）"
)
@click.option(
    "--limit",
    type=int,
    default=50,
    help="本次处理的最大模型数量（默认50）"
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="仅查询待分析模型，不执行分析"
)
@click.option(
    "--no-confirm",
    is_flag=True,
    help="跳过交互式确认（用于自动化脚本）"
)
def main(
    force: bool,
    older_than_days: int | None,
    missing_fields: str | None,
    provider: str | None,
    limit: int,
    dry_run: bool,
    no_confirm: bool,
) -> None:
    """模型重新分析工具。

    支持三种重新分析策略：
    1. --force: 强制重新分析所有模型
    2. --older-than-days N: 重新分析N天前的记录
    3. --missing-fields: 补充缺失的字段

    示例:
        # 强制重新分析所有模型（限制50个）
        python -m src.scraper.reanalyze_models --force --limit 50

        # 重新分析30天前的记录
        python -m src.scraper.reanalyze_models --older-than-days 30

        # 补充缺失的里程碑字段
        python -m src.scraper.reanalyze_models --missing-fields is_milestone,milestone_features

        # 仅预览openai提供商需要更新的模型
        python -m src.scraper.reanalyze_models --older-than-days 7 --provider openai --dry-run
    """
    # 异步主函数包装
    asyncio.run(_async_main(
        force=force,
        older_than_days=older_than_days,
        missing_fields=missing_fields,
        provider=provider,
        limit=limit,
        dry_run=dry_run,
        no_confirm=no_confirm,
    ))


async def _async_main(
    force: bool,
    older_than_days: int | None,
    missing_fields: str | None,
    provider: str | None,
    limit: int,
    dry_run: bool,
    no_confirm: bool,
) -> None:
    """异步主函数实现。"""

    # 参数验证：三种策略互斥
    strategies = sum([force, older_than_days is not None, missing_fields is not None])
    if strategies > 1:
        raise click.UsageError(
            "❌ --force, --older-than-days, --missing-fields 三个选项只能选择一个"
        )

    if strategies == 0:
        click.secho(
            "ℹ️  未指定重新分析策略，将使用默认行为：只分析未分析的模型",
            fg="cyan"
        )

    # 初始化协调器
    orchestrator = AnalysisOrchestrator()

    # 根据策略获取模型列表
    try:
        if force:
            click.secho("🔄 强制重新分析模式：所有模型", fg="yellow")
            models = orchestrator._fetch_models_for_reanalysis(
                strategy="force",
                provider=provider,
                limit=limit
            )
        elif older_than_days is not None:
            click.secho(
                f"📅 时间过滤模式：重新分析 {older_than_days} 天前的记录",
                fg="yellow"
            )
            models = orchestrator._fetch_models_for_reanalysis(
                strategy="older_than",
                provider=provider,
                limit=limit,
                days=older_than_days
            )
        elif missing_fields is not None:
            click.secho(
                f"📝 字段补充模式：补充缺失字段 {missing_fields}",
                fg="yellow"
            )
            fields = [f.strip() for f in missing_fields.split(",")]
            models = orchestrator._fetch_models_for_reanalysis(
                strategy="missing_fields",
                provider=provider,
                limit=limit,
                fields=fields
            )
        else:
            # 默认行为：仅分析未分析的模型
            click.secho("✨ 默认模式：只分析未分析的模型", fg="yellow")
            models = orchestrator._fetch_unanalyzed_models(provider=provider)

    except ValueError as e:
        raise click.ClickException(f"参数错误: {e}")
    except Exception as e:
        raise click.ClickException(f"获取模型列表失败: {e}")

    # 显示查询结果
    click.secho(f"\n找到 {len(models)} 个待分析的模型", fg="green", bold=True)

    if not models:
        click.secho("✓ 没有待分析的模型，任务完成", fg="cyan")
        return

    # 如果是干运行模式，只显示前10个
    if dry_run:
        click.secho("\n📋 待分析模型列表（预览，仅显示前10个）：", fg="blue")
        for i, model in enumerate(models[:10], 1):
            click.echo(
                f"  {i:2d}. {model['model_id']:40s} ({model['provider']})"
            )
        if len(models) > 10:
            click.secho(f"  ... 还有 {len(models) - 10} 个模型", fg="white")
        click.secho("\n✓ 干运行模式：未执行分析", fg="cyan")
        return

    # 显示详细信息
    click.echo()
    click.secho("待分析的模型：", fg="blue")
    for i, model in enumerate(models[:5], 1):
        click.echo(
            f"  {i}. {model['model_id']:40s} | {model['provider']}"
        )
    if len(models) > 5:
        click.secho(f"  ... 还有 {len(models) - 5} 个模型", fg="white")

    # 交互式确认
    if not no_confirm:
        click.echo()
        if not click.confirm(
            f"确认重新分析这 {len(models)} 个模型？",
            default=False
        ):
            click.secho("已取消操作", fg="yellow")
            return

    # 执行分析
    click.echo()
    click.secho("🚀 开始分析...", fg="cyan", bold=True)

    try:
        results = await orchestrator.integration.analyze_batch(
            models=models,
            batch_size=10,
            delay_between_batches=2.0,
        )

        # 显示统计结果
        click.echo()
        click.secho("分析完成！", fg="green", bold=True)
        click.secho(
            f"  ✓ 成功: {results['succeeded']}",
            fg="green"
        )
        click.secho(
            f"  ✗ 失败: {results['failed']}",
            fg="red" if results['failed'] > 0 else "green"
        )
        if results.get('skipped', 0) > 0:
            click.secho(
                f"  ⊘ 跳过: {results['skipped']}",
                fg="yellow"
            )

        # 显示整体统计
        stats = orchestrator.get_analysis_stats(provider=provider)
        if stats:
            click.echo()
            click.secho("分析统计：", fg="blue")
            click.echo(f"  总模型数: {stats['total_models']}")
            click.echo(f"  已分析: {stats['analyzed_models']}")
            click.echo(f"  未分析: {stats['unanalyzed_models']}")
            click.echo(f"  分析率: {stats['analysis_rate']:.1f}%")

    except Exception as e:
        click.secho(f"❌ 分析执行失败: {e}", fg="red")
        sys.exit(1)


if __name__ == "__main__":
    main()
