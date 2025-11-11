# API 集成指南 (API Integration Guide)

**版本**: v1.0 | **最后更新**: 2025-11-10 | **状态**: 生产就绪 ✅

---

## 📌 概述 (Overview)

Silicon River 通过集成两个关键 API 来增强模型分析功能：

| API | 功能 | 用途 |
|-----|------|------|
| **Brave Search** | 实时网络查询 | 获取最新模型发布信息 |
| **排行榜 API** | 权威排名数据 | 验证模型能力等级 |

---

## 1️⃣ Brave Search API 集成

### 作用

通过网络搜索弥补 LLM 知识截断（约 2024 年中），为模型分析提供最新的发布新闻、基准测试结果和社区反馈。

### 快速配置

```bash
# 第一步：注册并获取 API 密钥
# 访问: https://api.search.brave.com/signup
# 获取形如: Brv-XXXXXXXXXXXXXX 的密钥

# 第二步：添加到 .env
BRAVE_SEARCH_API_KEY=Brv-YOUR_KEY_HERE
ENABLE_BRAVE_SEARCH=true
BRAVE_SEARCH_TIMEOUT=10
BRAVE_SEARCH_MAX_RETRIES=3
```

### 配置参数详解

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| `BRAVE_SEARCH_API_KEY` | - | - | API 密钥（必填） |
| `ENABLE_BRAVE_SEARCH` | true | true/false | 启用开关 |
| `BRAVE_SEARCH_TIMEOUT` | 10 | 5-30 秒 | 单个请求超时时间 |
| `BRAVE_SEARCH_MAX_RETRIES` | 3 | 1-5 | 失败重试次数 |

### 免费配额与成本

```
📊 配额管理:
├── 月度免费查询: 2,000 次
├── 超额费率: $0.003 / 查询
└── 推荐月度预算: $0-9

🎯 成本节省策略:
├── 仅对新增或更新模型执行搜索
├── 启用 24 小时结果缓存
├── 在非高峰时段批量处理
```

### 验证配置

```bash
# 运行测试脚本
pytest tests/test_brave_search.py -v

# 手动测试
python -c "
import asyncio
from src.analysis.brave_search import BraveSearchClient

async def test():
    client = BraveSearchClient(api_key='YOUR_KEY')
    results = await client.search_web('GPT-4 release', count=3)
    print(f'✓ 成功获取 {len(results)} 条结果')

asyncio.run(test())
"
```

### 常见问题排查

| 错误 | 原因 | 解决方案 |
|------|------|---------|
| `InvalidAPIKey` | API 密钥格式错误 | 检查密钥是否以 `Brv-` 开头，无多余空格 |
| `RateLimitExceeded` | 超过月度配额 | 等待下月 1 日重置或升级计划 |
| `TimeoutError` | 网络延迟 | 增加 BRAVE_SEARCH_TIMEOUT 到 15-20s |
| 搜索结果为空 | 模型名称拼写或时间范围 | 尝试不同的查询词或增加 freshness 参数 |

### 监控搜索活动

```bash
# 查看所有 Brave Search 相关日志
tail -f logs/silicon_river.log | grep brave_search

# 统计每日搜索次数
grep "brave_search" logs/silicon_river.log | wc -l

# 检查成功率
grep "brave_search" logs/silicon_river.log | grep -c "success"
```

---

## 2️⃣ 排行榜 API 集成

### 作用

集成 4 个权威排行榜，多维度验证模型的实际表现，为里程碑判定和模型评估提供依据。

### 支持的排行榜

| 排行榜 | 维度 | 更新频率 | 覆盖模型 |
|--------|------|---------|----------|
| **SWE-bench** | 代码生成能力 | 月度 | 50+ |
| **LMSYS Arena** | 对话能力 | 实时 | 100+ |
| **HF Leaderboard** | 综合开源 | 实时 | 150+ |
| **OpenCompass** | 综合+中文 | 周度 | 200+ |

### 快速启动

```bash
# 无需额外配置，所有 API 都是免费的

# 手动更新排行榜缓存
python scripts/update_leaderboards.py

# 查看缓存统计
python -c "
from src.analysis.leaderboard_aggregator import LeaderboardAggregator
agg = LeaderboardAggregator()
print(agg.get_cache_stats())
"
```

### 性能指标

```
⚡ 查询延迟:
├── 单个排行榜: < 2 秒
├── 4 个排行榜并发: 2-3 秒 (vs 串行 8-12s)
└── 缓存命中: < 100 毫秒

📊 缓存效果:
├── 缓存 TTL: 1 小时
├── 预期命中率: 80-85%
└── 内存占用: < 50MB
```

### 排行榜里程碑判定阈值

| 排行榜 | 里程碑条件 | 示例 |
|--------|-----------|------|
| **SWE-bench** | rank ≤ 10 | GPT-4 排名 #1 (解决率 94.5%) |
| **LMSYS Arena** | rank ≤ 20 | Claude-3-Opus 排名 #2 (ELO 1275) |
| **HF Leaderboard** | rank ≤ 15 | Llama-2-70b 排名 #1 (评分 75.32) |
| **OpenCompass** | rank ≤ 10 | GPT-4 排名 #1 (评分 85.5) |

### 定期更新任务

```bash
# 在 crontab 中设置定时更新（建议每天凌晨）
0 2 * * * /usr/bin/python /app/scripts/update_leaderboards.py

# 或手动执行
python scripts/update_leaderboards.py
```

### 模型名称匹配

系统自动使用 4 层策略匹配跨排行榜的模型名称：

```python
# 示例：多种名称格式都能匹配到同一个模型
"GPT-4" == "gpt-4"              # 精确匹配（不区分大小写）
"GPT-4-Turbo" → "gpt-4"        # 规范化（移除版本号）
"openai/gpt-4" → "gpt-4"       # 移除组织前缀
"gpt-4-latest" → "gpt-4"       # 移除特定后缀
```

### 监控排行榜数据

```bash
# 查看缓存状态
python -c "
from src.analysis.leaderboard_aggregator import LeaderboardAggregator
agg = LeaderboardAggregator()
stats = agg.get_cache_stats()
for client, info in stats['clients'].items():
    print(f'{client}: {info[\"entry_count\"]} 条记录，命中率 {info.get(\"hit_rate\", \"N/A\")}')
"

# 检查特定模型的排名
python -c "
import asyncio
from src.analysis.leaderboard_aggregator import LeaderboardAggregator

async def check(name):
    agg = LeaderboardAggregator()
    ranks = await agg.get_model_ranks(name)
    for r in ranks:
        print(f'{r[\"source\"]}: 排名 {r.get(\"rank\")}, 评分 {r.get(\"score\")}')

asyncio.run(check('GPT-4'))
"
```

---

## 3️⃣ API 集成架构

```
┌─────────────────────────────────────────┐
│  AsyncModelAnalyzer                     │
│  (_analyze_with_context)                │
└────────────────┬────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
        ▼                 ▼
┌──────────────────┐  ┌──────────────────────┐
│  MCPDataSource   │  │ LeaderboardAggregator│
├──────────────────┤  ├──────────────────────┤
│ search_news()    │  │ get_model_ranks()    │
│ (Brave API)      │  │ (4 排行榜客户端)     │
└────────┬─────────┘  └──────────┬───────────┘
         │                       │
         ├──────────┬────────────┤
         │          │            │
         ▼          ▼            ▼
    ┌─────────────────────────────────┐
    │  _build_enhanced_prompt()       │
    │  (联网信息 + 排行榜数据)        │
    └─────────────────────────────────┘
         │
         ▼
    ┌─────────────────────────────────┐
    │  DeepSeek LLM API               │
    │  (增强分析)                     │
    └─────────────────────────────────┘
         │
         ▼
    ┌─────────────────────────────────┐
    │  _detect_milestone()            │
    │  (多维度判定)                   │
    └─────────────────────────────────┘
```

### 数据流示例

```python
# 输入：模型名称 "GPT-4"
model_name = "GPT-4"

# 步骤 1: 网络搜索（Brave Search）
news = [
    "GPT-4 achieves record performance...",
    "OpenAI releases GPT-4 Turbo...",
    ...
]

# 步骤 2: 排行榜查询（并发）
leaderboard_ranks = [
    {"source": "SWE-bench", "rank": 1, "score": 94.5},
    {"source": "LMSYS Arena", "rank": 1, "score": 1298},
    {"source": "HF Leaderboard", "rank": "N/A"},
    {"source": "OpenCompass", "rank": 1, "score": 85.5},
]

# 步骤 3: 构建增强提示词
enhanced_prompt = f"""
分析模型: {model_name}

最新信息：
{news}

排行榜排名：
{leaderboard_ranks}

请分析这个模型的特点和影响...
"""

# 步骤 4: 调用 LLM
analysis = await llm(enhanced_prompt)

# 输出：增强的分析结果
```

---

## 4️⃣ 故障恢复与降级策略

### 优雅降级流程

```
┌─────────────────────────┐
│  API 请求               │
└────────────┬────────────┘
             │
      ┌──────▼──────┐
      │ 请求成功?   │
      └──┬────────┬─┘
         │ 是     │ 否
         ▼        └─┐
     返回数据       │
                   ▼
            ┌─────────────┐
            │ 重试 3 次?  │
            └──┬────────┬─┘
               │ 是     │ 否
               ▼        └─┐
            等待...       │
                         ▼
                   ┌────────────────┐
                   │ 使用缓存/跳过   │
                   │ 继续分析流程   │
                   └────────────────┘
```

### 每个 API 的故障处理

**Brave Search 故障**:
```
✓ 超时 → 自动重试（最多 3 次，指数退避）
✓ 配额耗尽 → 禁用 Brave Search 30 分钟
✓ 网络错误 → 返回空结果，继续分析
✓ 格式错误 → 记录日志，使用备用参数重试
```

**排行榜 API 故障**:
```
✓ 超时 → 使用前次缓存数据
✓ 网络错误 → 使用缓存或返回空
✓ 数据格式变更 → 记录警告，跳过该排行榜
✓ 多个 API 失败 → 模型无排行榜数据，继续分析
```

### 监控告警配置

```python
# 建议的告警阈值
ALERT_THRESHOLDS = {
    "brave_search_success_rate": 0.90,      # < 90% 发出告警
    "leaderboard_success_rate": 0.95,       # < 95% 发出告警
    "cache_hit_rate": 0.50,                 # < 50% 发出告警
    "analysis_latency_p95": 18000,          # > 18 秒 发出告警
}
```

---

## 5️⃣ 性能优化建议

### 查询优化

```python
# ✅ 好的做法：使用清晰的查询语句
query = f'"{model_name}" (release OR announcement OR benchmark) 2024'
results = await brave_client.search_web(query, count=5, freshness="pm")

# ❌ 避免：过于简单或复杂的查询
query = model_name                          # 太简单，结果无关
query = f'"{model_name}" AND (a AND b AND c ...)'  # 太复杂，API 无法理解
```

### 批量处理优化

```python
# ✅ 推荐：批量提交分析
model_ids = ["model-1", "model-2", ..., "model-100"]
results = await analyzer.analyze_batch(model_ids, model_names)

# ❌ 避免：逐个提交（严重降低性能）
for model_id, model_name in zip(model_ids, model_names):
    result = await analyzer.analyze_batch([model_id], [model_name])
```

### 缓存利用

```python
# 排行榜缓存自动管理，但可手动查看状态
stats = agg.get_cache_stats()

# 如需清空缓存
agg.clear_cache()              # 清空全部
agg.clear_cache("swe_bench")   # 清空特定排行榜
```

---

## 📊 成本预算

```
💰 月度 API 成本估算:

场景 1: 小规模 (10 新模型/月)
└─ Brave 搜索: ~50 次 = $0 (免费额度内)
└─ 排行榜: 免费
└─ 总计: $0

场景 2: 中等规模 (50 新模型/月)
└─ Brave 搜索: ~250 次 = $0 (免费额度内)
└─ 排行榜: 免费
└─ 总计: $0

场景 3: 大规模 (200 新模型/月)
└─ Brave 搜索: ~1000 次 = $0 (免费额度内)
└─ 排行榜: 免费
└─ 总计: $0

场景 4: 全量实时更新
└─ Brave 搜索: ~5000 次 = $15 (超过 2000 免费)
└─ 排行榜: 免费
└─ 总计: $15/月
```

---

## 📞 快速参考

### 常用命令

```bash
# 验证 Brave Search 配置
pytest tests/test_brave_search.py -v

# 更新排行榜缓存
python scripts/update_leaderboards.py

# 查看性能统计
python -c "from src.analysis.performance_monitor import get_monitor; print(get_monitor().get_statistics())"

# 测试完整分析流程
pytest tests/test_integration_enhanced_analysis.py -v
```

### 环境变量速查

```env
# Brave Search
BRAVE_SEARCH_API_KEY=Brv-YOUR_KEY
ENABLE_BRAVE_SEARCH=true
BRAVE_SEARCH_TIMEOUT=10
BRAVE_SEARCH_MAX_RETRIES=3

# 排行榜（无需配置）
LEADERBOARD_CACHE_TTL=3600
```

---

**版本**: 1.0 | **最后更新**: 2025-11-10 | **维护者**: Silicon River 项目团队
