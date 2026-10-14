"""AI分析与数据爬取的集成模块。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg

from src.analysis.async_analyzer import AsyncModelAnalyzer, AnalysisResult
from src.analysis.tag_generator import TagGenerator

LOGGER = logging.getLogger("silicon_river.integration")


class AnalysisIntegration:
    """管理AI分析与数据库的集成。"""

    def __init__(
        self,
        db_url: str,
        analyzer: AsyncModelAnalyzer | None = None,
        tag_generator: TagGenerator | None = None,
    ):
        """初始化集成管理器。

        Args:
            db_url: 数据库连接URL
            analyzer: 异步模型分析器实例（可选）
            tag_generator: 标签生成器实例（可选）
        """
        self.db_url = db_url
        self.analyzer = analyzer or AsyncModelAnalyzer()
        self.tag_generator = tag_generator or TagGenerator()

    async def analyze_and_save_model(
        self,
        model_id: str,
        model_name: str,
        description: str | None = None,
        tags: list[str] | None = None,
        provider: str | None = None,
    ) -> bool:
        """分析并保存**单个**模型。

        这是 `analyze_batch` 的单元素便捷入口。刻意让它委托过去，而不是复刻一份
        独立逻辑 —— 之前正是这个函数每次只传 `model_ids=[model_id]` 一个模型，
        把 `AsyncModelAnalyzer` 里的 semaphore 废成了并发度 1。

        Args:
            model_id: 模型ID
            model_name: 模型名称
            description: 模型描述
            tags: 现有标签列表
            provider: 提供商名称（可选）

        Returns:
            是否成功保存
        """
        result = await self.analyze_batch(
            [
                {
                    "model_id": model_id,
                    "model_name": model_name,
                    "description": description,
                    "tags": tags or [],
                    "provider": provider,
                }
            ],
            batch_size=1,
            delay_between_batches=0.0,
        )
        return result["succeeded"] == 1

    def _save_analysis_to_db(
        self,
        model_id: str,
        model_name: str | None,
        provider: str | None,
        analysis_result: AnalysisResult,
        generated_tags: list[str],
    ) -> bool:
        """将分析结果保存到数据库。

        Args:
            model_id: 模型ID
            model_name: 模型名称（可选）
            provider: 提供商名称（可选）
            analysis_result: 分析结果对象
            generated_tags: 生成的标签列表

        Returns:
            是否成功保存
        """
        try:
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cursor:
                    # 处理不同类型的字段
                    # key_features 和 use_cases 是 TEXT[] 数组，直接传递列表
                    # performance_metrics 是 JSONB，需要 json.dumps()
                    performance_metrics_json = json.dumps(analysis_result.performance_metrics)

                    # 保存分析结果到model_analysis表
                    cursor.execute(
                        """
                        INSERT INTO model_analysis (
                            model_id,
                            provider,
                            model_name,
                            analysis_summary,
                            key_features,
                            use_cases,
                            performance_metrics,
                            llm_model_used,
                            analyzed_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                        ON CONFLICT (model_id) DO UPDATE SET
                            provider = EXCLUDED.provider,
                            model_name = EXCLUDED.model_name,
                            analysis_summary = EXCLUDED.analysis_summary,
                            key_features = EXCLUDED.key_features,
                            use_cases = EXCLUDED.use_cases,
                            performance_metrics = EXCLUDED.performance_metrics,
                            llm_model_used = EXCLUDED.llm_model_used,
                            analyzed_at = EXCLUDED.analyzed_at
                        """,
                        (
                            model_id,
                            provider,
                            model_name,
                            analysis_result.analysis_summary,
                            analysis_result.key_features,  # 直接传递列表（psycopg3会处理）
                            analysis_result.use_cases,     # 直接传递列表（psycopg3会处理）
                            performance_metrics_json,      # JSON字符串
                            analysis_result.llm_model_used,
                            datetime.now(timezone.utc),
                        ),
                    )

                    # 保存生成的标签到model_tags表
                    self._save_tags_to_db(cursor, model_id, generated_tags)

                    conn.commit()
                    LOGGER.info(
                        f"成功保存模型分析：{model_id}（{len(generated_tags)}个标签）"
                    )
                    return True

        except psycopg.Error as e:
            LOGGER.error(f"数据库保存失败 {model_id}: {e}")
            return False

    def _save_tags_to_db(
        self, cursor: psycopg.cursor, model_id: str, tags: list[str]
    ) -> None:
        """保存标签到数据库。

        Args:
            cursor: 数据库游标
            model_id: 模型ID
            tags: 标签列表
        """
        # 先删除该模型的现有标签
        cursor.execute("DELETE FROM model_tags WHERE model_id = %s", (model_id,))

        # 插入新标签
        for tag in tags:
            cursor.execute(
                """
                INSERT INTO model_tags (model_id, tag, inserted_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (model_id, tag) DO NOTHING
                """,
                (model_id, tag),
            )

        LOGGER.debug(f"已保存 {len(tags)} 个标签到数据库")

    async def analyze_batch(
        self,
        models: list[dict],
        batch_size: int = 10,
        delay_between_batches: float = 1.0,
    ) -> dict:
        """并发分析一批模型，然后串行写库。

        两个阶段刻意分开，因为它们的瓶颈完全不同：

        - **分析阶段（并发）**：整批一次性交给 `AsyncModelAnalyzer.analyze_batch`，
          由它内部的 semaphore 把在途请求数限在 `MAX_CONCURRENT_ANALYSIS`。
          这一步全是网络等待，并发度直接决定总耗时。
        - **保存阶段（串行）**：`_save_analysis_to_db` 用的是同步 psycopg，并发写会
          阻塞事件循环，也会把数据库连接数打上去，所以一个一个写。

        历史坑：这个函数以前是 `for` 循环逐个调 `analyze_and_save_model`，而后者
        每次只传一个模型给 `analyze_batch`，于是 semaphore 每次只保护 1 个任务 ——
        `MAX_CONCURRENT_ANALYSIS` 配了等于没配，500 个模型要串行跑一小时。
        现在改成一次性把整批交过去，那个配置才真正生效。

        Args:
            models: 模型列表，每个元素是 dict，含
                model_id / model_name / description / tags / provider
            batch_size: 每写库多少个模型打印一次进度（会自动下限到 1）
            delay_between_batches: 连续失败后的退避秒数。
                注意：限流现在由 semaphore 负责，这里不再用作"批次间固定间隔"，
                否则只会在写库阶段白白插进几百秒空转

        Returns:
            包含成功/失败统计的结果字典
        """
        import asyncio

        results = {
            "total": len(models),
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "errors": {},  # 按错误类型统计
        }

        if not models:
            return results

        batch_size = max(1, int(batch_size))
        concurrency = getattr(self.analyzer, "max_concurrent", 1) or 1
        LOGGER.info(
            f"开始批量分析 {len(models)} 个模型"
            f"（并发上限 {concurrency}；分两阶段：并发分析 → 串行写库）"
        )

        # ── 阶段 1：并发分析 ─────────────────────────────────────────────
        async with self.analyzer as analyzer:
            analysis_results = await analyzer.analyze_batch(
                model_ids=[model.get("model_id") for model in models],
                model_names=[model.get("model_name") for model in models],
                descriptions=[model.get("description") for model in models],
                tags_list=[model.get("tags") or [] for model in models],
            )

        # analyze_batch 内部用 gather(return_exceptions=True)，所以失败项可能是
        # 异常对象；整批超时时它返回 [None] * n。两种情况都要能落到失败计数里。
        if len(analysis_results) != len(models):
            LOGGER.error(
                f"分析结果数量与模型数量不一致（{len(analysis_results)} != {len(models)}），"
                "缺失的按失败处理"
            )

        # ── 阶段 2：串行写库 ─────────────────────────────────────────────
        consecutive_failures = 0
        max_consecutive_failures = 5  # 连续失败5次后暂停

        for i, model in enumerate(models, start=1):
            model_id = model.get("model_id")
            model_name = model.get("model_name")
            analysis_result = analysis_results[i - 1] if i - 1 < len(analysis_results) else None

            try:
                if isinstance(analysis_result, BaseException):
                    # 把 gather 捕获到的异常重新抛出来，走下面的统一异常处理
                    raise analysis_result

                if analysis_result is None:
                    LOGGER.warning(f"模型分析未返回结果，跳过数据库保存：{model_id}")
                    results["failed"] += 1
                    consecutive_failures += 1
                else:
                    # 生成标签
                    generated_tags = self.tag_generator.generate_tags(
                        model_name=model_name,
                        description=model.get("description"),
                        existing_tags=model.get("tags") or [],
                    )

                    if self._save_analysis_to_db(
                        model_id=model_id,
                        model_name=model_name,
                        provider=model.get("provider"),
                        analysis_result=analysis_result,
                        generated_tags=generated_tags or [],
                    ):
                        results["succeeded"] += 1
                        consecutive_failures = 0  # 重置连续失败计数
                    else:
                        results["failed"] += 1
                        consecutive_failures += 1

            except Exception as e:
                error_type = type(e).__name__
                results["errors"][error_type] = results["errors"].get(error_type, 0) + 1
                LOGGER.error(f"模型分析异常 {model_id}: {error_type}: {e}")
                results["failed"] += 1
                consecutive_failures += 1

            # 如果连续失败过多，暂停一段时间
            if consecutive_failures >= max_consecutive_failures:
                LOGGER.warning(
                    f"连续失败 {consecutive_failures} 次，暂停 {delay_between_batches * 2} 秒后继续"
                )
                await asyncio.sleep(delay_between_batches * 2)
                consecutive_failures = 0

            # 每处理 batch_size 个模型打印一次进度
            if i % batch_size == 0 or i == len(models):
                success_rate = round(results["succeeded"] / i * 100, 1)
                LOGGER.info(
                    f"已处理 {i}/{len(models)} 个模型，"
                    f"成功: {results['succeeded']}, 失败: {results['failed']}，"
                    f"成功率: {success_rate}%"
                )

        LOGGER.info(
            f"批量分析完成 - 总计: {results['total']}, "
            f"成功: {results['succeeded']}, 失败: {results['failed']}"
        )
        if results['errors']:
            LOGGER.info(f"错误分布: {results['errors']}")

        return results

    def fetch_analyzed_models(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """从数据库获取已分析的模型。

        Args:
            limit: 获取数量
            offset: 偏移量

        Returns:
            已分析模型列表
        """
        try:
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            m.model_id,
                            m.model_name,
                            m.provider,
                            ma.analysis_summary,
                            ma.key_features,
                            ma.use_cases,
                            ma.performance_metrics,
                            array_agg(mt.tag) as tags
                        FROM models m
                        LEFT JOIN model_analysis ma ON m.model_id = ma.model_id
                        LEFT JOIN model_tags mt ON m.model_id = mt.model_id
                        WHERE ma.id IS NOT NULL
                        GROUP BY m.model_id, m.model_name, m.provider,
                                 ma.analysis_summary, ma.key_features,
                                 ma.use_cases, ma.performance_metrics
                        ORDER BY ma.analyzed_at DESC
                        LIMIT %s OFFSET %s
                        """,
                        (limit, offset),
                    )

                    columns = [desc[0] for desc in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]

        except psycopg.Error as e:
            LOGGER.error(f"获取已分析模型失败: {e}")
            return []
