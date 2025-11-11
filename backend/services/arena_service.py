"""评分数据聚合服务 - 从多个来源获取和验证模型评分。"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional, List

import psycopg
from dotenv import load_dotenv

LOGGER = logging.getLogger("silicon_river.arena_service")

# 从环境加载配置
load_dotenv()

# 评分数据源配置
FETCH_HUGGINGFACE_SCORES = os.getenv("FETCH_HUGGINGFACE_SCORES", "true").lower() == "true"
ARENA_SCORE_UPDATE_INTERVAL_HOURS = int(os.getenv("ARENA_SCORE_UPDATE_INTERVAL_HOURS", "24"))


@dataclass(slots=True)
class ArenaScore:
    """单个评分数据。"""
    model_id: str
    source: str
    rank: int | None = None
    score: float | None = None
    category: str = "overall"


@dataclass(slots=True)
class ArenaScoreSummary:
    """评分汇总数据。"""
    model_id: str
    has_score: bool = False
    sources: list[str] = None
    combined_score: float | None = None
    scores: list[ArenaScore] = None

    def __post_init__(self):
        if self.sources is None:
            self.sources = []
        if self.scores is None:
            self.scores = []


class ArenaScoreService:
    """模型评分数据聚合服务。"""

    def __init__(self, db_url: str | None = None):
        """初始化评分服务。

        Args:
            db_url: 数据库连接URL
        """
        self.db_url = db_url
        self.enable_huggingface = FETCH_HUGGINGFACE_SCORES

    def get_model_scores(self, model_id: str) -> ArenaScoreSummary:
        """获取单个模型的评分汇总。

        Args:
            model_id: 模型ID

        Returns:
            评分汇总信息
        """
        summary = ArenaScoreSummary(model_id=model_id)

        # 从数据库查询评分数据
        if self.db_url:
            scores = self._query_from_database(model_id)
            if scores:
                summary.scores = scores
                summary.has_score = True
                summary.sources = list(set(s.source for s in scores))
                summary.combined_score = self._normalize_and_combine(scores)
            else:
                summary.has_score = False

        return summary

    def get_batch_scores(self, model_ids: list[str]) -> dict[str, ArenaScoreSummary]:
        """批量获取多个模型的评分。

        Args:
            model_ids: 模型ID列表

        Returns:
            模型ID到评分汇总的映射字典
        """
        results = {}
        for model_id in model_ids:
            results[model_id] = self.get_model_scores(model_id)
        return results

    def _query_from_database(self, model_id: str) -> list[ArenaScore]:
        """从数据库查询模型评分。

        Args:
            model_id: 模型ID

        Returns:
            评分列表
        """
        if not self.db_url:
            return []

        try:
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT model_id, source, rank, score, category
                        FROM model_arena_info
                        WHERE model_id = %s
                        ORDER BY source, category
                        """,
                        (model_id,)
                    )
                    rows = cursor.fetchall()

            scores = []
            for row in rows:
                scores.append(ArenaScore(
                    model_id=row[0],
                    source=row[1],
                    rank=row[2],
                    score=row[3],
                    category=row[4]
                ))
            return scores

        except Exception as e:
            LOGGER.error(f"查询评分数据失败 {model_id}: {e}")
            return []

    def _normalize_and_combine(self, scores: list[ArenaScore]) -> float | None:
        """归一化并聚合多来源评分。

        Args:
            scores: 评分列表

        Returns:
            聚合后的评分值（0-100）
        """
        if not scores:
            return None

        # 仅考虑 overall 类别的评分
        overall_scores = [s.score for s in scores if s.category == "overall" and s.score is not None]

        if not overall_scores:
            return None

        # 计算平均值
        combined = sum(overall_scores) / len(overall_scores)
        return round(combined, 2)

    def update_huggingface_scores(self, scores_data: list[dict]) -> bool:
        """更新 HuggingFace 评分数据。

        Args:
            scores_data: 评分数据列表

        Returns:
            是否更新成功
        """
        if not self.enable_huggingface or not self.db_url:
            return False

        try:
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cursor:
                    for data in scores_data:
                        cursor.execute(
                            """
                            INSERT INTO model_arena_info
                            (model_id, source, rank, score, category)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (model_id, source, category)
                            DO UPDATE SET
                                rank = EXCLUDED.rank,
                                score = EXCLUDED.score,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            (
                                data.get("model_id"),
                                "huggingface",
                                data.get("rank"),
                                data.get("score"),
                                data.get("category", "overall")
                            )
                        )
                conn.commit()
            LOGGER.info(f"更新了 {len(scores_data)} 条 HuggingFace 评分数据")
            return True

        except Exception as e:
            LOGGER.error(f"更新 HuggingFace 评分失败: {e}")
            return False
