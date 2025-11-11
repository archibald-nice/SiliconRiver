"""AI分析协调器 - 统一管理爬虫完成后的AI分析流程。"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg
from dotenv import load_dotenv

from src.analysis.integration import AnalysisIntegration

LOGGER = logging.getLogger("silicon_river.analysis_orchestrator")

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)

DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://USER:PASSWORD@HOST:5432/silicon_river"
)

# 分析配置
ANALYSIS_ENABLED = os.getenv("ENABLE_POST_SCRAPE_ANALYSIS", "true").lower() == "true"
ANALYSIS_BATCH_SIZE = int(os.getenv("ANALYSIS_BATCH_SIZE", "10"))
ANALYSIS_DELAY = float(os.getenv("ANALYSIS_DELAY_BETWEEN_BATCHES", "2.0"))
ANALYSIS_LIMIT = int(os.getenv("ANALYSIS_LIMIT_PER_PROVIDER", "50"))


class AnalysisOrchestrator:
    """协调爬虫和AI分析的整合。"""

    def __init__(self, db_url: str | None = None):
        """初始化分析协调器。

        Args:
            db_url: 数据库连接URL
        """
        self.db_url = db_url or DEFAULT_DB_URL
        self.integration = AnalysisIntegration(db_url=self.db_url)

    def run_post_scrape_analysis(self, provider: str | None = None) -> dict:
        """在爬虫完成后运行AI分析。

        Args:
            provider: 特定提供商（可选），如果为None则分析所有待分析的模型

        Returns:
            包含分析统计的结果字典
        """
        if not ANALYSIS_ENABLED:
            LOGGER.info("AI分析功能已禁用")
            return {"enabled": False, "message": "AI分析功能已禁用"}

        LOGGER.info("开始爬虫后分析流程 (provider=%s)", provider or "all")

        # 获取待分析的模型
        models = self._fetch_unanalyzed_models(provider=provider)

        if not models:
            LOGGER.info("没有待分析的模型")
            return {
                "enabled": True,
                "provider": provider,
                "total": 0,
                "analyzed": 0,
                "failed": 0,
            }

        LOGGER.info(f"找到 {len(models)} 个待分析的模型")

        # 运行批量分析
        results = self.integration.analyze_batch(
            models=models,
            batch_size=ANALYSIS_BATCH_SIZE,
            delay_between_batches=ANALYSIS_DELAY,
        )

        return {
            "enabled": True,
            "provider": provider,
            "total": results["total"],
            "analyzed": results["succeeded"],
            "failed": results["failed"],
        }

    def _fetch_unanalyzed_models(self, provider: str | None = None) -> list[dict]:
        """从数据库获取待分析的模型。

        Args:
            provider: 特定提供商（可选）

        Returns:
            待分析的模型列表
        """
        try:
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cursor:
                    # 构建查询
                    query = """
                        SELECT m.model_id, m.model_name, m.description, m.tags, m.provider
                        FROM models m
                        LEFT JOIN model_analysis ma ON m.model_id = ma.model_id
                        WHERE ma.id IS NULL
                    """

                    params = []

                    # 如果指定了提供商，只获取该提供商的模型
                    if provider:
                        query += " AND m.provider = %s"
                        params.append(provider)

                    # 按插入时间倒序排列，获取最新的模型
                    query += " ORDER BY m.inserted_at DESC LIMIT %s"
                    params.append(ANALYSIS_LIMIT)

                    cursor.execute(query, params)

                    models = []
                    for row in cursor.fetchall():
                        models.append({
                            "model_id": row[0],
                            "model_name": row[1],
                            "description": row[2],
                            "tags": self._parse_tags(row[3]),
                            "provider": row[4],
                        })

                    return models

        except psycopg.Error as e:
            LOGGER.error(f"获取待分析模型失败: {e}")
            return []

    @staticmethod
    def _parse_tags(tags_str: str | None) -> list[str]:
        """解析标签字符串。

        Args:
            tags_str: 标签JSON字符串

        Returns:
            标签列表
        """
        if not tags_str:
            return []

        try:
            import json
            return json.loads(tags_str) if isinstance(tags_str, str) else []
        except (json.JSONDecodeError, TypeError):
            # 如果解析失败，尝试按逗号分割
            return [tag.strip() for tag in str(tags_str).split(",") if tag.strip()]

    def _fetch_models_for_reanalysis(
        self,
        strategy: str,
        provider: str | None = None,
        limit: int | None = None,
        **kwargs
    ) -> list[dict]:
        """根据不同策略获取需要重新分析的模型。

        Args:
            strategy: 策略类型 ('force', 'older_than', 'missing_fields')
            provider: 提供商过滤（可选）
            limit: 数量限制
            **kwargs: 策略特定参数
                - days: 用于 'older_than' 策略
                - fields: 用于 'missing_fields' 策略

        Returns:
            待分析模型列表
        """
        limit = limit or ANALYSIS_LIMIT

        try:
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cursor:
                    # 基础查询
                    base_query = """
                        SELECT m.model_id, m.model_name, m.description, m.tags, m.provider
                        FROM models m
                    """

                    params = []

                    # 根据策略构建WHERE子句
                    if strategy == "force":
                        query = base_query + " WHERE 1=1"

                    elif strategy == "older_than":
                        days = kwargs.get("days")
                        if days is None:
                            raise ValueError("'older_than' 策略需要指定 days 参数")
                        query = base_query + """
                            INNER JOIN model_analysis ma ON m.model_id = ma.model_id
                            WHERE ma.analyzed_at < NOW() - INTERVAL '%s days'
                        """
                        params.append(days)

                    elif strategy == "missing_fields":
                        fields = kwargs.get("fields", [])
                        if not fields:
                            raise ValueError("'missing_fields' 策略需要指定 fields 参数")

                        conditions = []
                        if "is_milestone" in fields:
                            conditions.append("(ma.is_milestone IS NULL OR ma.is_milestone = FALSE)")
                        if "milestone_features" in fields:
                            conditions.append("ma.milestone_features IS NULL")

                        if not conditions:
                            raise ValueError(f"无法识别的字段: {fields}")

                        query = base_query + f"""
                            INNER JOIN model_analysis ma ON m.model_id = ma.model_id
                            WHERE ({' OR '.join(conditions)})
                        """

                    else:
                        raise ValueError(f"未知策略: {strategy}")

                    # 添加提供商过滤
                    if provider:
                        query += " AND m.provider = %s"
                        params.append(provider)

                    # 排序和限制
                    query += " ORDER BY m.inserted_at DESC LIMIT %s"
                    params.append(limit)

                    cursor.execute(query, params)

                    # 转换结果
                    models = []
                    for row in cursor.fetchall():
                        models.append({
                            "model_id": row[0],
                            "model_name": row[1],
                            "description": row[2],
                            "tags": self._parse_tags(row[3]),
                            "provider": row[4],
                        })

                    return models

        except psycopg.Error as e:
            LOGGER.error(f"获取待重新分析模型失败: {e}")
            return []

    def get_analysis_stats(self, provider: str | None = None) -> dict:
        """获取模型分析统计信息。

        Args:
            provider: 特定提供商（可选）

        Returns:
            统计信息字典
        """
        try:
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cursor:
                    # 统计已分析的模型
                    query = "SELECT COUNT(*) FROM model_analysis WHERE 1=1"
                    params = []

                    if provider:
                        query += """
                            AND model_id IN (
                                SELECT model_id FROM models WHERE provider = %s
                            )
                        """
                        params.append(provider)

                    cursor.execute(query, params)
                    analyzed_count = cursor.fetchone()[0]

                    # 统计总模型数
                    query = "SELECT COUNT(*) FROM models WHERE 1=1"
                    params = []

                    if provider:
                        query += " AND provider = %s"
                        params.append(provider)

                    cursor.execute(query, params)
                    total_count = cursor.fetchone()[0]

                    return {
                        "total_models": total_count,
                        "analyzed_models": analyzed_count,
                        "unanalyzed_models": total_count - analyzed_count,
                        "analysis_rate": round(
                            (analyzed_count / total_count * 100) if total_count > 0 else 0, 2
                        ),
                    }

        except psycopg.Error as e:
            LOGGER.error(f"获取分析统计失败: {e}")
            return {}


def run_post_scrape_analysis(provider: str | None = None) -> dict:
    """便捷函数：在爬虫完成后运行分析。

    Args:
        provider: 特定提供商（可选）

    Returns:
        分析结果
    """
    orchestrator = AnalysisOrchestrator()
    return orchestrator.run_post_scrape_analysis(provider=provider)


if __name__ == "__main__":
    # 示例：运行分析
    result = run_post_scrape_analysis()
    print(f"分析完成: {result}")
