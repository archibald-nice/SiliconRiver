"""AI模型分析服务 - 使用DeepSeek R1等LLM进行分析。"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI, APIError, APIConnectionError, APITimeoutError
from dotenv import load_dotenv

LOGGER = logging.getLogger("silicon_river.analyzer")

# 从环境加载配置
load_dotenv()

# API配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com")
DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))


@dataclass(slots=True)
class AnalysisResult:
    """模型分析结果。"""
    model_id: str
    analysis_summary: str
    key_features: list[str]
    use_cases: list[str]
    performance_metrics: dict
    llm_model_used: str


class ModelAnalyzer:
    """使用LLM进行模型分析的服务。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        model: str | None = None,
        timeout: int = HTTP_TIMEOUT,
    ):
        """初始化分析器。

        Args:
            api_key: LLM API密钥
            api_url: LLM API端点URL (base_url)
            model: 使用的模型名称
            timeout: 请求超时时间（秒）
        """
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.api_url = api_url or DEEPSEEK_API_URL
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout

        if not self.api_key:
            LOGGER.warning("DEEPSEEK_API_KEY未设置，分析功能将被禁用")

        # 初始化OpenAI兼容客户端
        self.client = self._initialize_client() if self.api_key else None

    def _initialize_client(self) -> OpenAI | None:
        """初始化OpenAI兼容的DeepSeek客户端。

        Returns:
            OpenAI客户端实例或None
        """
        try:
            return OpenAI(
                api_key=self.api_key,
                base_url=self.api_url,
                timeout=self.timeout,
            )
        except Exception as e:
            LOGGER.error(f"初始化OpenAI客户端失败: {e}")
            return None

    def analyze_model(
        self,
        model_name: str,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> AnalysisResult | None:
        """分析单个模型。

        Args:
            model_name: 模型名称
            description: 模型描述
            tags: 模型标签列表

        Returns:
            分析结果或None（如果分析失败）
        """
        if not self.api_key or not self.client:
            LOGGER.warning(f"跳过模型分析：{model_name}（API密钥未配置）")
            return None

        prompt = self._build_analysis_prompt(model_name, description, tags)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._call_api(prompt)
                if response:
                    return self._parse_response(model_name, response)
            except Exception as e:
                LOGGER.warning(
                    f"模型分析失败 {model_name}（尝试 {attempt}/{MAX_RETRIES}）: {e}"
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)  # 指数退避
                continue

        LOGGER.error(f"模型分析最终失败：{model_name}")
        return None

    def _build_analysis_prompt(
        self,
        model_name: str,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """构建分析提示词。

        Args:
            model_name: 模型名称
            description: 模型描述
            tags: 模型标签

        Returns:
            提示词文本
        """
        context = f"模型名称：{model_name}"
        if description:
            context += f"\n官方描述：{description}"
        if tags:
            context += f"\n现有标签：{', '.join(tags)}"

        prompt = f"""请分析以下AI大语言模型，并以JSON格式返回分析结果。

{context}

请返回以下JSON格式的分析结果（确保返回有效的JSON）：
{{
    "analysis_summary": "模型的简要分析总结（200字以内）",
    "key_features": ["特性1", "特性2", "特性3"],
    "use_cases": ["应用场景1", "应用场景2", "应用场景3"],
    "performance_metrics": {{
        "estimated_quality": "高/中/低",
        "training_data_scope": "预计的训练数据范围描述",
        "inference_speed": "推理速度评估"
    }}
}}

要求：
1. 只返回JSON，不要有其他文字
2. analysis_summary应该客观、简洁
3. key_features应列举该模型的核心特性
4. use_cases应列举现实应用场景
5. performance_metrics应包含对模型性能的评估"""

        return prompt

    def _call_api(self, prompt: str) -> str | None:
        """调用DeepSeek API（通过OpenAI兼容SDK）。

        Args:
            prompt: 提示词

        Returns:
            API响应内容或None
        """
        if not self.client:
            LOGGER.error("OpenAI客户端未初始化")
            return None

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # 降低温度以获得更一致的结果
                max_tokens=1024,
            )

            # 从OpenAI SDK响应中提取内容
            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content

        except APITimeoutError:
            LOGGER.error(f"API请求超时（{self.timeout}秒）")
        except APIConnectionError as e:
            LOGGER.error(f"API连接失败: {e}")
        except APIError as e:
            LOGGER.error(f"API请求失败: {e}")
        except Exception as e:
            LOGGER.error(f"API调用异常: {e}")

        return None

    def _parse_response(self, model_id: str, response_text: str) -> AnalysisResult | None:
        """解析API响应。

        Args:
            model_id: 模型ID
            response_text: API响应文本

        Returns:
            解析后的分析结果或None
        """
        try:
            # 尝试提取JSON
            json_str = response_text.strip()

            # 如果响应被代码块包裹，去除它们
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
