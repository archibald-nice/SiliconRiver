"""Silicon River API Pydantic 模型定义。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Dict, List, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict


def _ensure_utc(value: datetime) -> datetime:
    """把时间字段统一成 UTC aware（ISSUE-006）。

    为什么要在序列化层做一次，而不是指望数据库：

    - 列已经是 `timestamptz`，psycopg 取出来是 **aware** datetime，但偏移量是
      *会话时区*，不是 UTC。本地库/某些部署的 TimeZone 是 `Asia/Shanghai` 时，
      `2025-06-03T12:00Z` 会读成 `2025-06-03T20:00:00+08:00`——时刻没错，但 API
      输出的偏移随部署环境变化，前端/缓存/日志的对比全得跟着变。
    - 靠 `SET TIME ZONE 'UTC'` 固定会话时区不可靠：Supabase 的 transaction pooler
      每个事务可能换物理连接，会话级设置不保证延续。
    - 所以 API 边界统一归一化：naive 一律按 UTC 解释（历史兼容），aware 一律转 UTC，
      响应固定输出 `+00:00`。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# 时间字段统一类型：校验后一定是 UTC aware datetime
UtcDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]


class Model(BaseModel):
    """基础模型信息。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    model_id: str
    provider: str
    model_name: str
    description: Optional[str]
    tags: List[str]
    created_at: UtcDatetime
    downloads: Optional[int]
    likes: Optional[int]
    model_card_url: str


class ModelAnalysis(BaseModel):
    """模型AI分析结果（包含里程碑信息）。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    model_id: str
    # 厂商名取自关联的 models.provider（ISSUE-016）：model_id 的斜杠前缀是仓库组织名
    # （`aion-labs`），不等于展示用的厂商名（`aionlabs`），前端不能再从 model_id 推导。
    provider: Optional[str] = None
    analysis_summary: Optional[str] = None
    key_features: List[str] = []
    use_cases: List[str] = []
    performance_metrics: Optional[Dict[str, object]] = None
    llm_model_used: Optional[str] = None
    analyzed_at: Optional[UtcDatetime] = None
    tags: List[str] = []
    # 里程碑字段（阶段一新增）
    is_milestone: bool = False
    milestone_features: Optional[str] = None
    updated_at: Optional[UtcDatetime] = None


class ArenaScoreInfo(BaseModel):
    """单个模型评分信息。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    model_id: str
    source: str
    rank: Optional[int] = None
    score: Optional[float] = None
    category: str = "overall"
    updated_at: Optional[UtcDatetime] = None


class ArenaScoreSummary(BaseModel):
    """模型评分信息汇总。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    model_id: Optional[str] = None
    has_score: bool = False
    sources: List[str] = []
    combined_score: Optional[float] = None
    details: List[ArenaScoreInfo] = []


class TimelineModel(BaseModel):
    """时间线视图的模型信息。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    model_id: str
    provider: str
    model_name: str
    description: Optional[str]
    created_at: UtcDatetime
    model_card_url: str
    tags: List[str]
    avatar_url: Optional[str] = None
    is_open_source: Optional[bool] = None
    price: Optional[Dict[str, object]] = None
    huggingface_rank: Optional[int] = None
    analysis_summary: Optional[str] = None


class TimelineModelWithAnalysis(TimelineModel):
    """包含完整分析和评分信息的时间线模型。"""
    is_milestone: bool = False
    milestone_features: Optional[str] = None
    arena_score: Optional[ArenaScoreSummary] = None


class ProviderStat(BaseModel):
    """提供商统计信息。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    provider: str
    model_count: int


class ModelList(BaseModel):
    """模型列表响应。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    items: List[Model]
    total: int
    page: int
    page_size: int


class AnalysisList(BaseModel):
    """分析结果列表响应。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    items: List[ModelAnalysis]
    total: int
    page: int
    page_size: int


class TimelineResponse(BaseModel):
    """时间线响应。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    items: List[TimelineModel]
    total: int
    page: int
    page_size: int
    start: UtcDatetime
    end: UtcDatetime
    preset: str
    label: str
