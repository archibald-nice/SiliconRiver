"""智能标签生成服务。"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from openai import OpenAI, APIError, APIConnectionError, APITimeoutError
from dotenv import load_dotenv

LOGGER = logging.getLogger("silicon_river.tag_generator")

# 从环境加载配置
load_dotenv()

# API配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com")
DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))


class TagGenerator:
    """使用LLM生成模型标签的服务。"""

    # 预定义的标签类别
    PREDEFINED_TAGS = {
        "能力": [
            "文本生成",
            "代码生成",
            "问答",
            "翻译",
            "摘要",
            "推理",
            "多模态",
            "视觉",
            "语音",
        ],
        "特性": [
            "开源",
            "闭源",
            "微调友好",
            "可量化",
            "长上下文",
            "实时推理",
            "知识库",
            "RAG",
        ],
        "规模": [
            "超大模型",
            "大模型",
            "中等模型",
            "小模型",
            "轻量化",
        ],
        "应用": [
            "生产级",
            "研究级",
            "演示",
            "企业应用",
            "教育",
            "开发工具",
        ],
    }

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        model: str | None = None,
        timeout: int = HTTP_TIMEOUT,
    ):
        """初始化标签生成器。

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
            LOGGER.warning("DEEPSEEK_API_KEY未设置，标签生成功能将被禁用")

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

    def generate_tags(
        self,
        model_name: str,
        description: str | None = None,
        existing_tags: list[str] | None = None,
    ) -> list[str] | None:
        """为模型生成标签。

        Args:
            model_name: 模型名称
            description: 模型描述
            existing_tags: 现有标签列表

        Returns:
            标签列表或None（如果生成失败）
        """
        if not self.api_key:
            LOGGER.warning(f"跳过标签生成：{model_name}（API密钥未配置）")
            # 返回基本的标签
            return self._extract_basic_tags(model_name, description)

        prompt = self._build_tag_prompt(model_name, description, existing_tags)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._call_api(prompt)
                if response:
                    tags = self._parse_tags(response)
                    if tags:
                        return tags
            except Exception as e:
                LOGGER.warning(
                    f"标签生成失败 {model_name}（尝试 {attempt}/{MAX_RETRIES}）: {e}"
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)  # 指数退避
                continue

        LOGGER.warning(f"标签生成最终失败：{model_name}，返回基本标签")
        return self._extract_basic_tags(model_name, description)

    def _build_tag_prompt(
        self,
        model_name: str,
        description: str | None = None,
        existing_tags: list[str] | None = None,
    ) -> str:
        """构建标签生成提示词。

        Args:
            model_name: 模型名称
            description: 模型描述
            existing_tags: 现有标签

        Returns:
            提示词文本
        """
        context = f"模型名称：{model_name}"
        if description:
            context += f"\n官方描述：{description}"
        if existing_tags:
            context += f"\n现有标签：{', '.join(existing_tags)}"

        predefined_list = []
        for category, tags in self.PREDEFINED_TAGS.items():
            predefined_list.append(f"{category}：{', '.join(tags)}")

        prompt = f"""请根据以下AI模型信息，从预定义标签列表中选择最相关的标签。

{context}

预定义标签（请从这些标签中选择）：
{chr(10).join(predefined_list)}

要求：
1. 只返回JSON格式：{{"tags": ["标签1", "标签2", ...]}}
2. 选择3-6个最相关的标签
3. 只使用预定义标签列表中的标签
4. 返回有效的JSON格式
5. 不要包含任何其他文字"""

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
                temperature=0.5,
                max_tokens=256,
            )

            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content

        except APITimeoutError:
            LOGGER.error(f"标签生成API请求超时（{self.timeout}秒）")
        except APIConnectionError as e:
            LOGGER.error(f"标签生成API连接失败: {e}")
        except APIError as e:
            LOGGER.error(f"标签生成API请求失败: {e}")
        except Exception as e:
            LOGGER.error(f"标签生成API调用异常: {e}")

        return None

    def _parse_tags(self, response_text: str) -> list[str] | None:
        """解析API响应提取标签。

        Args:
            response_text: API响应文本

        Returns:
            标签列表或None
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

            tags = data.get("tags", [])
            if isinstance(tags, list):
                # 验证标签是否在预定义列表中
                valid_tags = []
                all_predefined = []
                for tag_list in self.PREDEFINED_TAGS.values():
                    all_predefined.extend(tag_list)

                for tag in tags:
                    if tag in all_predefined:
                        valid_tags.append(tag)
                    else:
                        LOGGER.debug(f"跳过非预定义标签：{tag}")

                return valid_tags if valid_tags else None
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            LOGGER.debug(f"标签解析失败: {e}")

        return None

    def _extract_basic_tags(
        self, model_name: str, description: str | None = None
    ) -> list[str]:
        """从模型名称和描述中提取基本标签。

        Args:
            model_name: 模型名称
            description: 模型描述

        Returns:
            基本标签列表
        """
        tags = []
        text = (model_name + " " + (description or "")).lower()

        # 基于关键词匹配的简单标签提取
        keyword_mapping = {
            "code": "代码生成",
            "gpt": "文本生成",
            "llama": "文本生成",
            "vision": "视觉",
            "multimodal": "多模态",
            "qwen": "文本生成",
            "chinese": "中文",
            "open": "开源",
            "chat": "问答",
        }

        for keyword, tag in keyword_mapping.items():
            if keyword in text and tag not in tags:
                tags.append(tag)

        # 如果没有提取到标签，添加默认标签
        if not tags:
            tags.append("文本生成")

        return tags[:6]  # 最多返回6个标签
