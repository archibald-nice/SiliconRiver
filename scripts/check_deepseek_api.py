#!/usr/bin/env python
"""手动冒烟脚本：验证 DeepSeek OpenAI 兼容 API 调用是否可用。

用法（在项目根目录执行）：
    python scripts/check_deepseek_api.py

注意：文件名不要以 test_ 开头，否则会被 pytest 误当作测试用例收集。
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径（本文件位于 scripts/ 下，故需回退一级）
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from src.analysis.analyzer import ModelAnalyzer

# 加载环境变量（.env 位于项目根目录）
load_dotenv(dotenv_path=project_root / ".env")


def check_analyzer():
    """测试 ModelAnalyzer 的 OpenAI 兼容 API 调用。"""
    print("=" * 60)
    print("测试 DeepSeek OpenAI 兼容 API 调用")
    print("=" * 60)

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("错误: DEEPSEEK_API_KEY 未配置")
        print("请在 .env 文件中设置 DEEPSEEK_API_KEY")
        return False

    print(f"检测到 API Key (长度: {len(api_key)})")

    analyzer = ModelAnalyzer()

    if not analyzer.client:
        print("错误: OpenAI 客户端初始化失败")
        return False

    print("OpenAI 客户端初始化成功")
    print(f"  - API Base URL: {analyzer.api_url}")
    print(f"  - Model: {analyzer.model}")
    print(f"  - Timeout: {analyzer.timeout}s")

    print("\n开始测试 API 调用...")
    print("-" * 60)

    result = analyzer.analyze_model(
        model_name="Llama 2",
        description="Meta的7B开源大语言模型",
        tags=["开源", "LLaMA"],
    )

    if result:
        print("API 调用成功!")
        print("\n分析结果:")
        print(f"  模型: {result.model_id}")
        print(f"  总结: {result.analysis_summary[:100]}...")
        print(f"  特性: {result.key_features}")
        print(f"  场景: {result.use_cases}")
        print(f"  使用模型: {result.llm_model_used}")
        return True

    print("API 调用失败 - 未获得有效分析结果")
    return False


if __name__ == "__main__":
    success = check_analyzer()
    print("\n" + "=" * 60)
    print("所有检查通过!" if success else "检查失败")
    sys.exit(0 if success else 1)
