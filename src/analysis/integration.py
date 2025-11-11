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
        """异步分析模型并保存分析结果到数据库。

        Args:
            model_id: 模型ID
            model_name: 模型名称
            description: 模型描述
            tags: 现有标签列表
            provider: 提供商名称（可选）

        Returns:
            是否成功保存
        """
        # 异步分析模型（使用异步上下文管理器）
        async with self.analyzer as analyzer:
            # 构建模型列表
            analysis_results = await analyzer.analyze_batch(
                model_ids=[model_id],
                model_names=[model_name],
                descriptions=[description],
                tags_list=[tags or []],
            )

        if not analysis_results or not analysis_results[0]:
            LOGGER.warning(f"模型分析失败，跳过数据库保存：{model_id}")
            return False

        analysis_result = analysis_results[0]

        # 生成标签
        generated_tags = self.tag_generator.generate_tags(
            model_name=model_name,
            description=description,
            existing_tags=tags,
        )

        # 保存到数据库
        return self._save_analysis_to_db(
            model_id=model_id,
            model_name=model_name,
            provider=provider,
            analysis_result=analysis_result,
            generated_tags=generated_tags or [],
        )

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
        """异步批量分析模型。

        Args:
            models: 模型列表，每个元素为dict包含model_id, model_name, description, tags
            batch_size: 批处理大小
            delay_between_batches: 批次之间的延迟（秒）

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

        LOGGER.info(f"开始异步批量分析 {len(models)} 个模型（批大小: {batch_size}，批间延迟: {delay_between_batches}秒）")

        consecutive_failures = 0
        max_consecutive_failures = 5  # 连续失败5次后暂停

        for i, model in enumerate(models):
            try:
                success = await self.analyze_and_save_model(
                    model_id=model.get("model_id"),
                    model_name=model.get("model_name"),
                    description=model.get("description"),
                    tags=model.get("tags", []),
                    provider=model.get("provider"),
                )

                if success:
                    results["succeeded"] += 1
                    consecutive_failures = 0  # 重置连续失败计数
                else:
                    results["failed"] += 1
                    consecutive_failures += 1

            except Exception as e:
                error_type = type(e).__name__
                results["errors"][error_type] = results["errors"].get(error_type, 0) + 1
                LOGGER.error(f"模型分析异常 {model.get('model_id')}: {error_type}: {e}")
                results["failed"] += 1
                consecutive_failures += 1

            # 如果连续失败过多，暂停一段时间
            if consecutive_failures >= max_consecutive_failures:
                LOGGER.warning(
                    f"连续失败 {consecutive_failures} 次，暂停 {delay_between_batches * 2} 秒后继续"
                )
                await asyncio.sleep(delay_between_batches * 2)
                consecutive_failures = 0

            # 每处理batch_size个模型后，等待一段时间
            if (i + 1) % batch_size == 0:
                progress = f"{i + 1}/{len(models)}"
                success_rate = round(results['succeeded'] / (i + 1) * 100, 1) if i + 1 > 0 else 0
                LOGGER.info(
                    f"已处理 {progress} 个模型，"
                    f"成功: {results['succeeded']}, 失败: {results['failed']}，"
                    f"成功率: {success_rate}%"
                )
                if i + 1 < len(models):
                    await asyncio.sleep(delay_between_batches)

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
