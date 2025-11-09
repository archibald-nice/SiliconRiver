#!/usr/bin/env python
"""快速测试脚本：验证DeepSeek OpenAI兼容API调用。"""
import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from src.analysis.analyzer import ModelAnalyzer

# 加载环境变量
load_dotenv()

def test_analyzer():
    """测试ModelAnalyzer的OpenAI兼容API调用。"""
    print("=" * 60)
    print("测试 DeepSeek OpenAI 兼容API调用")
    print("=" * 60)

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ 错误: DEEPSEEK_API_KEY 未配置")
        print("请在 .env 文件中设置 DEEPSEEK_API_KEY")
        return False

    print(f"✓ 检测到 API Key (长度: {len(api_key)})")

    # 初始化分析器
    analyzer = ModelAnalyzer()

    if not analyzer.client:
        print("❌ 错误: OpenAI客户端初始化失败")
        return False

    print("✓ OpenAI客户端初始化成功")
    print(f"  - API Base URL: {analyzer.api_url}")
    print(f"  - Model: {analyzer.model}")
    print(f"  - Timeout: {analyzer.timeout}s")

    # 测试API调用
    print("\n开始测试API调用...")
    print("-" * 60)

    result = analyzer.analyze_model(
        model_name="Llama 2",
        description="Meta的7B开源大语言模型",
        tags=["开源", "LLaMA"]
    )

    if result:
        print("✓ API调用成功!")
        print(f"\n分析结果:")
        print(f"  模型: {result.model_id}")
        print(f"  总结: {result.analysis_summary[:100]}...")
        print(f"  特性: {result.key_features}")
        print(f"  场景: {result.use_cases}")
        print(f"  使用模型: {result.llm_model_used}")
        return True
    else:
        print("❌ API调用失败 - 未获得有效分析结果")
        return False

if __name__ == "__main__":
    success = test_analyzer()
    print("\n" + "=" * 60)
    if success:
        print("✓ 所有测试通过!")
        sys.exit(0)
    else:
        print("✗ 测试失败")
        sys.exit(1)
