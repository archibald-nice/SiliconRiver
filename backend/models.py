"""Silicon River API Pydantic 模型定义。"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """基础模型信息。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    model_id: str
    provider: str
    model_name: str
    description: Optional[str]
    tags: List[str]
    created_at: datetime
    downloads: Optional[int]
    likes: Optional[int]
    model_card_url: str


class ModelAnalysis(BaseModel):
    """模型AI分析结果（包含里程碑信息）。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    model_id: str
    analysis_summary: Optional[str] = None
    key_features: List[str] = []
    use_cases: List[str] = []
    performance_metrics: Optional[Dict[str, object]] = None
    llm_model_used: Optional[str] = None
    analyzed_at: Optional[datetime] = None
    tags: List[str] = []
    # 里程碑字段（阶段一新增）
    is_milestone: bool = False
    milestone_features: Optional[str] = None
    updated_at: Optional[datetime] = None


class ArenaScoreInfo(BaseModel):
    """单个模型评分信息。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    model_id: str
    source: str
    rank: Optional[int] = None
    score: Optional[float] = None
    category: str = "overall"
    updated_at: Optional[datetime] = None


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
    created_at: datetime
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


class AnalysisStats(BaseModel):
    """AI分析统计信息。"""
    model_config = ConfigDict(protected_namespaces=(), ser_json_schema_extra=None)

    total_models: int
    analyzed_models: int
    unanalyzed_models: int
    analysis_rate: float


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
    start: datetime
    end: datetime
    preset: str
    label: str
