"""异步模型分析服务 - 支持并发分析和MCP数据源集成。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional, Any

import aiohttp
from dotenv import load_dotenv
from openai import AsyncOpenAI, APIError, APIConnectionError, APITimeoutError

from src.analysis.brave_search import BraveSearchClient, BraveSearchError
from src.analysis.leaderboard_aggregator import LeaderboardAggregator
from src.analysis.performance_monitor import get_monitor, PerformanceMonitor
from src.analysis.performance_decorator import monitor_latency

LOGGER = logging.getLogger("silicon_river.async_analyzer")

# 从环境加载配置
load_dotenv()

# API配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com")
DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))

# 异步分析配置
MAX_CONCURRENT_ANALYSIS = int(os.getenv("MAX_CONCURRENT_ANALYSIS", "5"))
ANALYSIS_TIMEOUT_SECONDS = int(os.getenv("ANALYSIS_TIMEOUT_SECONDS", "30"))

# MCP配置
ENABLE_MCP_SEARCH = os.getenv("ENABLE_MCP_SEARCH", "true").lower() == "true"
ENABLE_MCP_ARXIV = os.getenv("ENABLE_MCP_ARXIV", "false").lower() == "true"

# Brave Search API 配置
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
ENABLE_BRAVE_SEARCH = os.getenv("ENABLE_BRAVE_SEARCH", "true").lower() == "true"

# 定义不应重试的HTTP错误码
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 405, 406, 409, 410, 422}


@dataclass(slots=True)
class AnalysisContext:
    """模型分析上下文。"""
    model_id: str
    model_name: str
    description: str | None = None
    tags: list[str] | None = None
    news: list[str] | None = None
    papers: list[str] | None = None
    timeline_context: dict[str, Any] | None = None
    leaderboard_ranks: list[dict[str, Any]] | None = None  # 排行榜排名信息


@dataclass(slots=True)
class AnalysisResult:
    """模型分析结果。"""
    model_id: str
    analysis_summary: str
    key_features: list[str]
    use_cases: list[str]
    performance_metrics: dict
    llm_model_used: str
    is_milestone: bool = False
    milestone_features: str | None = None


@dataclass(slots=True)
class ArenaScoreInfo:
    """模型评分信息。"""
    model_id: str
    source: str
    rank: int | None = None
    score: float | None = None
    category: str = "overall"


class MCPDataSource:
    """MCP数据源集成。"""

    def __init__(self):
        """初始化MCP数据源。"""
        self.enabled_search = ENABLE_MCP_SEARCH
        self.enabled_arxiv = ENABLE_MCP_ARXIV
        # 初始化 Brave Search 客户端
        self.brave_client = (
            BraveSearchClient(api_key=BRAVE_SEARCH_API_KEY)
            if ENABLE_BRAVE_SEARCH and BRAVE_SEARCH_API_KEY
            else None
        )

    async def search_news(self, model_name: str) -> list[str]:
        """查询模型相关新闻（通过 Brave Search API）。

        Args:
            model_name: 模型名称

        Returns:
            新闻内容列表
        """
        if not self.brave_client:
            LOGGER.debug(f"Brave Search 客户端未配置，跳过查询：{model_name}")
            return []

        try:
            # 构建搜索查询
            query = f'"{model_name}" (release OR announcement OR benchmark OR paper)'

            # 执行搜索（获取过去一个月的结果）
            results = await self.brave_client.search_web(
                query=query,
                count=5,
                freshness="pm"  # 过去一个月
            )

            if not results:
                LOGGER.debug(f"未找到 {model_name} 的新闻信息")
                return []

            # 格式化结果为字符串列表
            news_items = []
            for result in results[:3]:  # 限制最多 3 条
                title = result.get("title", "")
                description = result.get("description", "")
                if title and description:
                    news_items.append(f"{title}: {description}")

            LOGGER.debug(f"获取 {model_name} 的新闻信息：{len(news_items)} 条")
            return news_items

        except Exception as e:
            LOGGER.warning(f"Brave Search 查询失败 {model_name}: {e}")
            return []

    async def search_papers(self, model_name: str) -> list[str]:
        """查询模型相关论文（ArXiv MCP）。

        Args:
            model_name: 模型名称

        Returns:
            论文内容列表
        """
        if not self.enabled_arxiv:
            return []

        try:
            # TODO: 实现实际的MCP ArXiv搜索调用
            # 当前返回空列表，后续由MCP服务集成
            LOGGER.debug(f"查询论文：{model_name}")
            return []
        except Exception as e:
            LOGGER.warning(f"论文查询失败 {model_name}: {e}")
            return []

    async def get_timeline_context(self, model_id: str) -> dict[str, Any]:
        """获取模型时间线上下文。

        Args:
            model_id: 模型ID

        Returns:
            时间线上下文字典
        """
        try:
            # TODO: 实现实际的数据库查询
            # 当前返回空字典，后续由数据库服务集成
            LOGGER.debug(f"查询时间线上下文：{model_id}")
            return {}
        except Exception as e:
            LOGGER.warning(f"时间线查询失败 {model_id}: {e}")
            return {}


class AsyncModelAnalyzer:
    """异步模型分析服务，支持并发分析。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        model: str | None = None,
        timeout: int = HTTP_TIMEOUT,
        max_concurrent: int = MAX_CONCURRENT_ANALYSIS,
    ):
        """初始化异步分析器。

        Args:
            api_key: LLM API密钥
            api_url: LLM API端点URL
            model: 使用的模型名称
            timeout: 请求超时时间（秒）
            max_concurrent: 最大并发分析数
        """
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.api_url = api_url or DEEPSEEK_API_URL
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.client: AsyncOpenAI | None = None
        self.mcp_source = MCPDataSource()
        self.leaderboard_agg = LeaderboardAggregator()  # 初始化排行榜聚合器

        if not self.api_key:
            LOGGER.warning("DEEPSEEK_API_KEY未设置，分析功能将被禁用")

    async def __aenter__(self):
        """异步上下文管理器进入。"""
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_url,
            timeout=self.timeout,
        ) if self.api_key else None
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出。"""
        if self.client:
            await self.client.close()

    async def analyze_batch(
        self,
        model_ids: list[str],
        model_names: list[str],
        descriptions: list[str | None] | None = None,
        tags_list: list[list[str]] | None = None,
    ) -> list[AnalysisResult | None]:
        """并发分析多个模型。

        Args:
            model_ids: 模型ID列表
            model_names: 模型名称列表
            descriptions: 模型描述列表
            tags_list: 模型标签列表

        Returns:
            分析结果列表
        """
        if not self.api_key or not self.client:
            LOGGER.warning("API密钥未配置，跳过批量分析")
            return [None] * len(model_ids)

        # 创建上下文列表
        contexts = []
        for i, model_id in enumerate(model_ids):
            context = AnalysisContext(
                model_id=model_id,
                model_name=model_names[i],
                description=descriptions[i] if descriptions else None,
                tags=tags_list[i] if tags_list else None,
            )
            contexts.append(context)

        # 使用信号量控制并发
        tasks = [
            self._analyze_with_context(context)
            for context in contexts
        ]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=ANALYSIS_TIMEOUT_SECONDS * len(model_ids)
            )
            return results
        except asyncio.TimeoutError:
            LOGGER.error(f"批量分析超时（{ANALYSIS_TIMEOUT_SECONDS * len(model_ids)}秒）")
            return [None] * len(model_ids)

    async def _analyze_with_context(self, context: AnalysisContext) -> AnalysisResult | None:
        """使用增强上下文分析单个模型。

        Args:
            context: 模型分析上下文

        Returns:
            分析结果或None
        """
        total_start = time.time()
        monitor = get_monitor()

        async with self.semaphore:
            monitor.record_concurrent_analysis(self.max_concurrent - self.semaphore._value)

            try:
                # 步骤1: 并发收集背景信息（新增排行榜数据）
                context_start = time.time()
                news_task = self.mcp_source.search_news(context.model_name)
                papers_task = self.mcp_source.search_papers(context.model_name)
                timeline_task = self.mcp_source.get_timeline_context(context.model_id)
                ranks_task = self.leaderboard_agg.get_model_ranks(context.model_name)

                context.news, context.papers, context.timeline_context, context.leaderboard_ranks = await asyncio.gather(
                    news_task, papers_task, timeline_task, ranks_task,
                    return_exceptions=True
                )

                context_time_ms = (time.time() - context_start) * 1000
                monitor.record_latency("context_collection", context_time_ms, success=True)

                # 处理异常返回
                if isinstance(context.news, Exception):
                    context.news = None
                if isinstance(context.papers, Exception):
                    context.papers = None
                if isinstance(context.timeline_context, Exception):
                    context.timeline_context = None
                if isinstance(context.leaderboard_ranks, Exception):
                    context.leaderboard_ranks = None

                # 步骤2: 构建增强提示词
                prompt = self._build_enhanced_prompt(context)

                # 步骤3: 调用分析API
                api_start = time.time()
                response = await self._call_api_async(prompt)
                api_time_ms = (time.time() - api_start) * 1000
                monitor.record_latency("llm_api_call", api_time_ms, success=response is not None)

                if not response:
                    return None

                # 步骤4: 解析响应
                parse_start = time.time()
                analysis = self._parse_response(context.model_id, response)
                parse_time_ms = (time.time() - parse_start) * 1000
                monitor.record_latency("response_parsing", parse_time_ms, success=analysis is not None)

                if not analysis:
                    return None

                # 步骤5: 里程碑识别
                milestone_start = time.time()
                analysis.is_milestone, analysis.milestone_features = self._detect_milestone(
                    analysis, context
                )
                milestone_time_ms = (time.time() - milestone_start) * 1000
                monitor.record_latency("milestone_detection", milestone_time_ms, success=True)

                # 记录总分析时间
                total_time_ms = (time.time() - total_start) * 1000
                monitor.record_latency("total_analysis", total_time_ms, success=True)

                if total_time_ms > 15000:
                    LOGGER.warning(f"模型分析耗时 {total_time_ms:.0f}ms，超过 SLA 15s 目标")

                return analysis

            except asyncio.TimeoutError:
                total_time_ms = (time.time() - total_start) * 1000
                monitor.record_latency(
                    "total_analysis", total_time_ms, success=False,
                    error_msg="TimeoutError"
                )
                LOGGER.error(f"模型分析超时：{context.model_id}")
                return None
            except Exception as e:
                total_time_ms = (time.time() - total_start) * 1000
                monitor.record_latency(
                    "total_analysis", total_time_ms, success=False,
                    error_msg=f"{type(e).__name__}"
                )
                LOGGER.error(f"模型分析异常 {context.model_id}: {e}")
                return None

    async def _call_api_async(self, prompt: str) -> str | None:
        """异步调用DeepSeek API。

        Args:
            prompt: 提示词

        Returns:
            API响应内容或None
        """
        if not self.client:
            LOGGER.error("OpenAI客户端未初始化")
            return None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=1024,
                )

                if response.choices and len(response.choices) > 0:
                    return response.choices[0].message.content

            except APITimeoutError as e:
                LOGGER.warning(f"API请求超时（尝试 {attempt}/{MAX_RETRIES}）: {e}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY * attempt)
                continue
            except APIConnectionError as e:
                LOGGER.warning(f"API连接失败（尝试 {attempt}/{MAX_RETRIES}）: {e}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY * attempt)
                continue
            except APIError as e:
                status_code = getattr(e, 'status_code', None)
                if status_code in NON_RETRYABLE_STATUS_CODES:
                    LOGGER.error(f"API不可重试错误（HTTP {status_code}）: {e}")
                    return None
                LOGGER.warning(f"API错误（尝试 {attempt}/{MAX_RETRIES}，HTTP {status_code}）: {e}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY * attempt)
                continue
            except Exception as e:
                LOGGER.warning(f"API调用异常（尝试 {attempt}/{MAX_RETRIES}）: {e}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY * attempt)
                continue

        LOGGER.error("API调用最终失败")
        return None

    def _build_enhanced_prompt(self, context: AnalysisContext) -> str:
        """构建增强的分析提示词（包含MCP数据）。

        Args:
            context: 分析上下文

        Returns:
            增强的提示词
        """
        prompt_parts = [
            f"请分析以下AI大语言模型，并以JSON格式返回分析结果。\n",
            f"模型名称：{context.model_name}"
        ]

        if context.description:
            prompt_parts.append(f"官方描述：{context.description}")

        if context.tags:
            prompt_parts.append(f"现有标签：{', '.join(context.tags)}")

        if context.news:
            prompt_parts.append(f"\n最新新闻信息（来自网络搜索）：")
            for i, news in enumerate(context.news[:3], 1):  # 限制新闻数量
                prompt_parts.append(f"{i}. {news}")

        if context.papers:
            prompt_parts.append(f"\n学术论文引用：")
            for i, paper in enumerate(context.papers[:3], 1):  # 限制论文数量
                prompt_parts.append(f"{i}. {paper}")

        # 新增：行业排行榜排名信息
        if context.leaderboard_ranks:
            prompt_parts.append(f"\n行业排行榜排名信息：")
            for rank_info in context.leaderboard_ranks:
                source = rank_info.get("source", "")
                rank = rank_info.get("rank")
                score = rank_info.get("score")
                category = rank_info.get("category", "")

                if rank and score is not None:
                    category_str = f"（{category}）" if category else ""
                    prompt_parts.append(
                        f"- {source}{category_str}：排名第 {rank}，评分 {score}%"
                    )

        prompt_parts.append("""
请返回以下JSON格式的分析结果（确保返回有效的JSON）：
{
    "analysis_summary": "模型的简要分析总结（200字以内）",
    "key_features": ["特性1", "特性2", "特性3"],
    "use_cases": ["应用场景1", "应用场景2", "应用场景3"],
    "performance_metrics": {
        "estimated_quality": "高/中/低",
        "training_data_scope": "预计的训练数据范围描述",
        "inference_speed": "推理速度评估"
    }
}

要求：
1. 只返回JSON，不要有其他文字
2. analysis_summary应该客观、简洁
3. key_features应列举该模型的核心特性
4. use_cases应列举现实应用场景
5. performance_metrics应包含对模型性能的评估
6. 如果有新闻、论文或排行榜信息，请在分析中结合考虑，但不要仅仅复述信息
7. 基于所有可用信息提供综合分析
""")

        return "\n".join(prompt_parts)

    def _parse_response(self, model_id: str, response_text: str) -> AnalysisResult | None:
        """解析API响应。

        Args:
            model_id: 模型ID
            response_text: API响应文本

        Returns:
            解析后的分析结果或None
        """
        try:
            json_str = response_text.strip()

            if json_str.startswith("```json"):
                json_str = json_str[7:]
            if json_str.startswith("```"):
                json_str = json_str[3:]
            if json_str.endswith("```"):
                json_str = json_str[:-3]

            json_str = json_str.strip()
            data = json.loads(json_str)

            return AnalysisResult(
                model_id=model_id,
                analysis_summary=data.get("analysis_summary", ""),
                key_features=data.get("key_features", []),
                use_cases=data.get("use_cases", []),
                performance_metrics=data.get("performance_metrics", {}),
                llm_model_used=self.model,
            )
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            LOGGER.error(f"模型分析结果解析失败 {model_id}: {e}")
            LOGGER.debug(f"响应内容: {response_text}")
            return None

    def _detect_milestone(
        self,
        analysis: AnalysisResult,
        context: AnalysisContext
    ) -> tuple[bool, str | None]:
        """检测模型是否为里程碑模型。

        支持三种判定策略：
        1. 强指标：任意一个强关键词即可标记为里程碑
        2. 弱指标：2个或以上弱关键词即可标记为里程碑
        3. 排名指标：行业排名前20的模型视为里程碑

        Args:
            analysis: 分析结果
            context: 分析上下文

        Returns:
            (是否为里程碑, 里程碑特性说明)
        """
        # 里程碑关键词（分为强/弱指标）
        strong_keywords = {
            "首创", "首个", "业界第一", "革命性",
            "划时代", "突破性", "重大创新"
        }
        weak_keywords = {
            "突破", "创新", "改进", "增强",
            "重大进展", "性能提升", "开源贡献"
        }

        summary = analysis.analysis_summary.lower()
        features = [f.lower() for f in analysis.key_features]

        # 检测强关键词
        strong_found = []
        for keyword in strong_keywords:
            if keyword in summary or any(keyword in f for f in features):
                strong_found.append(keyword)

        # 检测弱关键词
        weak_found = []
        for keyword in weak_keywords:
            if keyword in summary or any(keyword in f for f in features):
                weak_found.append(keyword)

        # 策略1：强关键词任意一个就算里程碑
        if strong_found:
            milestone_features = f"包含里程碑特性：{', '.join(set(strong_found))}"
            return True, milestone_features

        # 策略2：弱关键词达到2个就算里程碑
        if len(weak_found) >= 2:
            milestone_features = f"包含多项关键特性：{', '.join(set(weak_found))}"
            return True, milestone_features

        # 策略3：检查排名（前20名视为里程碑）
        if context.timeline_context:
            model_rank = context.timeline_context.get("rank")
            if model_rank and model_rank <= 20:
                return True, f"行业排名第{model_rank}的关键模型"

        # 策略4：检查排行榜排名（新增）
        if context.leaderboard_ranks:
            for rank_info in context.leaderboard_ranks:
                source = rank_info.get("source", "")
                rank = rank_info.get("rank")
                score = rank_info.get("score")
                category = rank_info.get("category", "")

                # SWE-bench 前 10 名被视为里程碑
                if "swe-bench" in source.lower() and rank and rank <= 10:
                    category_desc = f"（{category}）" if category else ""
                    return True, f"SWE-bench{category_desc}排名第{rank}的突破性编程模型（解决率{score}%）"

                # LMSYS Arena 前 20 名被视为里程碑
                if "lmsys" in source.lower() and rank and rank <= 20:
                    return True, f"LMSYS Chatbot Arena排名第{rank}的顶尖对话模型（ELO {score}）"

                # HuggingFace Leaderboard 前 15 名被视为里程碑
                if "huggingface" in source.lower() and rank and rank <= 15:
                    return True, f"HuggingFace Open LLM排行榜第{rank}名模型（综合评分 {score}）"

        return False, None
