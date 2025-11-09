"""AI分析服务使用示例。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from src.analysis.analyzer import ModelAnalyzer
from src.analysis.integration import AnalysisIntegration
from src.analysis.tag_generator import TagGenerator

# 加载环境配置
BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)

DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://USER:PASSWORD@HOST:5432/silicon_river"
)


def example_single_model_analysis():
    """示例：分析单个模型。"""
    print("=" * 50)
    print("示例 1: 分析单个模型")
    print("=" * 50)

    analyzer = ModelAnalyzer()
    result = analyzer.analyze_model(
        model_name="meta-llama/Llama-2-7b",
        description="开源的7B参数大语言模型，由Meta公司发布。",
        tags=["开源", "文本生成"],
    )

    if result:
        print(f"模型ID: {result.model_id}")
        print(f"分析总结: {result.analysis_summary}")
        print(f"主要特性: {result.key_features}")
        print(f"应用场景: {result.use_cases}")
        print(f"性能指标: {result.performance_metrics}")
    else:
        print("分析失败")


def example_tag_generation():
    """示例：生成模型标签。"""
    print("\n" + "=" * 50)
    print("示例 2: 生成模型标签")
    print("=" * 50)

    tag_generator = TagGenerator()
    tags = tag_generator.generate_tags(
        model_name="GPT-4",
        description="由OpenAI发布的多模态大语言模型，支持文本和图像理解。",
    )

    if tags:
        print(f"生成的标签: {tags}")
    else:
        print("标签生成失败")


def example_batch_analysis():
    """示例：批量分析模型。"""
    print("\n" + "=" * 50)
    print("示例 3: 批量分析模型")
    print("=" * 50)

    integration = AnalysisIntegration(db_url=DEFAULT_DB_URL)

    # 模拟数据
    models = [
        {
            "model_id": "qwen-max",
            "model_name": "Qwen Max",
            "description": "阿里巴巴通义千问最大版本",
            "tags": ["中文", "多模态"],
        },
        {
            "model_id": "claude-3",
            "model_name": "Claude 3",
            "description": "由Anthropic发布的最新大语言模型",
            "tags": [],
        },
    ]

    results = integration.analyze_batch(models, batch_size=1, delay_between_batches=2)
    print(f"批量分析结果:")
    print(f"  总数: {results['total']}")
    print(f"  成功: {results['succeeded']}")
    print(f"  失败: {results['failed']}")


def example_fetch_analyzed():
    """示例：获取已分析的模型。"""
    print("\n" + "=" * 50)
    print("示例 4: 获取已分析的模型")
    print("=" * 50)

    integration = AnalysisIntegration(db_url=DEFAULT_DB_URL)
    analyzed_models = integration.fetch_analyzed_models(limit=5)

    if analyzed_models:
        print(f"找到 {len(analyzed_models)} 个已分析的模型:")
        for model in analyzed_models:
            print(f"  - {model['model_name']} ({model['model_id']})")
            print(f"    标签: {model['tags']}")
    else:
        print("没有找到已分析的模型")


if __name__ == "__main__":
    print("AI分析服务使用示例\n")

    # 注意：这些示例需要配置DEEPSEEK_API_KEY环境变量
    # 如果未配置，某些功能可能不可用

    # 运行示例（根据需要取消注释）
    # example_single_model_analysis()
    # example_tag_generation()
    # example_batch_analysis()
    # example_fetch_analyzed()

    print("\n提示：")
    print("1. 将这些示例集成到您的爬虫脚本中")
    print("2. 在.env中配置DEEPSEEK_API_KEY")
    print("3. 根据需要调整批处理参数和延迟")
