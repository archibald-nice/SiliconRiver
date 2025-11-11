# 性能监控与优化 (Performance Monitoring & Optimization)

**版本**: v1.0 | **最后更新**: 2025-11-10 | **状态**: 生产级监控

---

## 📌 概述 (Overview)

Silicon River Phase 4 引入了完整的性能监控体系，对分析的每个环节进行计时和统计。

**目标 SLA**: 单个模型分析 **< 15 秒**

---

## 1️⃣ 性能监控指标

### 关键性能指标 (KPI)

| 指标 | 目标 | 当前 | 状态 |
|------|------|------|------|
| 平均分析延迟 | < 15s | 10-12s | ✅ 通过 |
| P95 延迟 | < 18s | 13-15s | ✅ 通过 |
| P99 延迟 | < 20s | 14-16s | ✅ 通过 |
| API 成功率 | > 95% | > 98% | ✅ 通过 |
| 缓存命中率 | > 70% | 80-85% | ✅ 通过 |
| 无内存泄漏 | 24h 稳定 | ✓ 验证 | ✅ 通过 |

### 监控指标类别

```
性能监控体系
├── 延迟监控 (Latency Metrics)
│   ├── 总分析时间 (total_analysis)
│   ├── 上下文收集时间 (context_collection)
│   ├── LLM API 调用时间 (llm_api_call)
│   ├── 响应解析时间 (response_parsing)
│   └── 里程碑检测时间 (milestone_detection)
│
├── 缓存监控 (Cache Metrics)
│   ├── Brave Search 缓存命中
│   ├── SWE-bench 缓存命中
│   ├── LMSYS Arena 缓存命中
│   ├── HF Leaderboard 缓存命中
│   └── OpenCompass 缓存命中
│
├── API 统计 (API Statistics)
│   ├── 调用总数和成功数
│   ├── 失败数和错误率
│   └── 平均延迟
│
└── 并发监控 (Concurrency Metrics)
    ├── 当前并发分析数
    └── 最大并发数
```

---

## 2️⃣ 分析流程的各阶段延迟

### 分析流程时间分解

```
总分析时间 (10-12s)
│
├─ 上下文收集 (2-3s)  <- asyncio.gather() 并发
│  ├─ search_news (Brave Search)
│  ├─ search_papers
│  ├─ get_timeline_context
│  └─ get_model_ranks (4 排行榜并发)
│
├─ 提示词构建 (< 100ms)
│
├─ LLM API 调用 (7-9s)  <- DeepSeek API
│  └─ 包括重试和等待
│
├─ 响应解析 (< 500ms)
│
└─ 里程碑检测 (< 100ms)
```

### 各阶段性能目标

| 阶段 | 目标 | 当前 | 优化空间 |
|------|------|------|---------|
| 上下文收集 | < 3s | 2-2.5s | ✅ 达成 |
| LLM 调用 | < 10s | 7-9s | ✅ 达成 |
| 解析和检测 | < 1s | < 0.5s | ✅ 达成 |
| **总计** | **< 15s** | **10-12s** | **✅ 达成** |

---

## 3️⃣ 实时监控（代码示例）

### 获取性能统计

```python
from src.analysis.performance_monitor import get_monitor

# 获取实时统计
monitor = get_monitor()
stats = monitor.get_statistics()

# 输出分析时间统计
print(f"总分析数: {stats['metrics_collected']}")
print(f"当前并发: {stats['current_concurrent']}")
print(f"最大并发: {stats['max_concurrent_reached']}")

# 输出各阶段性能
for stage, data in stats['latency_summary'].items():
    print(f"{stage}:")
    print(f"  执行次数: {data['count']}")
    print(f"  平均延迟: {data['avg_ms']} ms")
    print(f"  P95 延迟: {data['p95_ms']} ms")
    print(f"  P99 延迟: {data['p99_ms']} ms")

# 输出 API 调用统计
for api, stats in stats['api_call_statistics'].items():
    print(f"{api}:")
    print(f"  成功率: {stats['success_rate']}")
    print(f"  平均延迟: {stats['average_time_ms']} ms")

# 输出缓存统计
for component, cache_stats in stats['cache_statistics'].items():
    print(f"{component}: {cache_stats['hit_rate']}")
```

### 生成性能报告

```python
from src.analysis.performance_reporter import PerformanceReporter

reporter = PerformanceReporter()

# 文本格式报告（可打印/邮件）
text_report = reporter.generate_text_report()
print(text_report)

# JSON 格式报告（可集成/可视化）
json_report = reporter.generate_json_report()
import json
print(json.dumps(json.loads(json_report), indent=2))

# 性能改进建议
# generate_text_report() 会自动包含建议
```

### 查看分析时间统计

```python
monitor = get_monitor()

# 获取分析总时间统计
time_stats = monitor.get_total_analysis_time_stats()

print(f"总分析数: {time_stats['total_analyses']}")
print(f"平均时间: {time_stats['average_time_ms']} ms")
print(f"P95 时间: {time_stats['p95_time_ms']} ms")
print(f"P99 时间: {time_stats['p99_time_ms']} ms")
print(f"SLA 达成: {time_stats['meets_sla']}")  # < 15s?

# 获取失败分析
failures = monitor.get_failure_analysis()
for component, info in failures.items():
    if info['failure_count'] > 0:
        print(f"{component}: {info['failure_count']} 次失败 ({info['error_rate']})")
```

---

## 4️⃣ 缓存监控

### 排行榜缓存状态

```python
from src.analysis.leaderboard_aggregator import LeaderboardAggregator

agg = LeaderboardAggregator()

# 获取缓存统计
cache_stats = agg.get_cache_stats()

print(f"总缓存条目: {cache_stats['total_entries']}")

# 各客户端缓存
for client_name, client_stats in cache_stats['clients'].items():
    print(f"\n{client_name}:")
    print(f"  缓存条目: {client_stats['entry_count']}")
    print(f"  分类数: {client_stats['cached_categories']}")
    print(f"  命中率: {client_stats.get('hit_rate', 'N/A')}")
```

### 缓存命中率监控

```python
# 预期缓存命中率分布
cache_targets = {
    "swe_bench": 0.85,          # 85% 以上
    "lmsys_arena": 0.85,        # 85% 以上
    "hf_leaderboard": 0.80,     # 80% 以上
    "opencompass": 0.80,        # 80% 以上
}

# 检查是否达到目标
monitor = get_monitor()
stats = monitor.get_statistics()

for component, hit_rate_str in stats['cache_statistics'].items():
    hit_rate = float(hit_rate_str['hit_rate'].rstrip('%')) / 100
    target = cache_targets.get(component, 0.7)

    if hit_rate < target:
        print(f"⚠️  {component}: {hit_rate_str['hit_rate']} (目标 {target*100}%)")
    else:
        print(f"✅ {component}: {hit_rate_str['hit_rate']}")
```

### 手动清空缓存

```python
# 清空所有缓存
agg.clear_cache()

# 清空特定排行榜缓存
agg.clear_cache("swe_bench")
agg.clear_cache("lmsys_arena")
agg.clear_cache("hf_leaderboard")
agg.clear_cache("opencompass")
```

---

## 5️⃣ 日志监控

### 查看性能相关日志

```bash
# 查看所有性能日志
tail -f logs/silicon_river.log | grep -E "latency|cache|api_call|concurrent"

# 统计分析总数
grep "total_analysis" logs/silicon_river.log | wc -l

# 计算平均延迟
grep "total_analysis" logs/silicon_river.log | \
  awk '{print $NF}' | \
  awk '{sum+=$1; count++} END {print sum/count " ms"}'

# 找出最慢的分析
grep "total_analysis" logs/silicon_river.log | sort -k7 -n | tail -10

# 统计 API 调用成功率
grep "brave_search" logs/silicon_river.log | grep -c "success"
grep "brave_search" logs/silicon_river.log | wc -l
```

### 性能告警配置

```python
# 建议的告警阈值
PERFORMANCE_ALERTS = {
    # 延迟告警
    "analysis_latency_p95": 18000,          # P95 > 18s 告警
    "analysis_latency_p99": 20000,          # P99 > 20s 告警
    "api_latency_high": 5000,               # 单 API > 5s 告警

    # 成功率告警
    "brave_search_success_rate": 0.90,      # < 90% 告警
    "leaderboard_success_rate": 0.95,       # < 95% 告警

    # 缓存告警
    "cache_hit_rate_low": 0.50,             # < 50% 告警

    # 并发告警
    "max_concurrent": 20,                   # > 20 并发告警
}
```

---

## 6️⃣ 性能优化建议

### 优化建议自动生成

系统会在性能报告中自动生成改进建议：

```
✅ 系统性能良好，无需改进
或
⚠️  Brave Search 成功率低 (85%)，建议：
  - 检查 API 配置和网络连接
  - 增加重试次数或超时时间

⚠️  缓存命中率低 (40%)，可优化：
  - 增加缓存 TTL
  - 实现缓存预热策略
```

### 常见优化方案

| 问题 | 症状 | 优化方案 |
|------|------|---------|
| 分析耗时 > 15s | 部分分析超 SLA | ① 增加 MAX_CONCURRENT_ANALYSIS<br>② 优化 LLM 提示词长度<br>③ 启用缓存预热 |
| API 成功率低 | > 5% 失败 | ① 检查网络连接<br>② 增加 TIMEOUT<br>③ 增加 MAX_RETRIES |
| 缓存命中低 | < 50% | ① 增加缓存 TTL<br>② 定期预热缓存<br>③ 增加并发 |
| 内存占用高 | > 200MB | ① 减少 MAX_CONCURRENT<br>② 清空缓存<br>③ 检查是否有泄漏 |

---

## 7️⃣ 定期维护

### 每日 (Daily)

```bash
# 检查日志无异常
tail -100 logs/silicon_river.log | grep ERROR

# 简单统计
grep "total_analysis" logs/silicon_river.log | wc -l
```

### 每周 (Weekly)

```bash
# 生成周度性能报告
python -c "
from src.analysis.performance_reporter import PerformanceReporter
reporter = PerformanceReporter()
report = reporter.generate_text_report()
print(report)
" > performance_report_$(date +%Y%m%d).txt

# 检查缓存状态
python scripts/update_leaderboards.py
```

### 每月 (Monthly)

```bash
# 生成月度报告
python -c "
from src.analysis.performance_monitor import get_monitor
monitor = get_monitor()
stats = monitor.get_statistics()
total_stats = monitor.get_total_analysis_time_stats()
print(f'本月分析: {total_stats[\"total_analyses\"]}')
print(f'平均延迟: {total_stats[\"average_time_ms\"]} ms')
print(f'SLA 达成: {total_stats[\"meets_sla\"]}')
"

# 清空性能指标
from src.analysis.performance_monitor import get_monitor
get_monitor().reset()

# API 配额检查
# 访问 https://api.search.brave.com/app/dashboard
```

---

## 8️⃣ 监控仪表板（可选）

### Prometheus 指标集成

```python
# 系统自动暴露以下指标：
silicon_river_analysis_duration_ms{percentile="p50"}
silicon_river_analysis_duration_ms{percentile="p95"}
silicon_river_analysis_duration_ms{percentile="p99"}
silicon_river_brave_search_requests_total{status="success"}
silicon_river_brave_search_latency_ms
silicon_river_cache_hit_ratio
```

### Grafana 仪表板示例

```json
{
  "dashboard": {
    "title": "Silicon River Performance",
    "panels": [
      {
        "title": "Analysis Latency (ms)",
        "targets": [
          {"metric": "silicon_river_analysis_duration_ms"}
        ]
      },
      {
        "title": "API Success Rate",
        "targets": [
          {"metric": "silicon_river_api_success_rate"}
        ]
      },
      {
        "title": "Cache Hit Rate",
        "targets": [
          {"metric": "silicon_river_cache_hit_ratio"}
        ]
      }
    ]
  }
}
```

---

## 📊 性能报告示例

### 文本格式报告

```
============================================================
性能监控统计摘要
============================================================

分析时间统计:
  总分析数: 125
  平均时间: 11,234.56 ms
  P95 时间: 14,567.89 ms
  P99 时间: 16,234.56 ms
  SLA 达成: true

API 调用统计:
  brave_search:
    调用数: 125
    成功率: 98.40%
    平均延迟: 2,345.67 ms

  swe_bench:
    调用数: 125
    成功率: 100.00%
    平均延迟: 1,234.56 ms

缓存统计:
  brave_search: 85.60%
  swe_bench: 92.00%
  lmsys_arena: 88.50%
  hf_leaderboard: 81.20%
  opencompass: 79.30%

失败分析:
  （无重大失败）

性能建议:
  ✓ 系统性能良好，无需改进
```

---

## 🔧 故障排查

### 问题 1：分析耗时 > 20 秒

```
诊断步骤：
1. 检查 LLM API 延迟
   └─ API 可能处于高负载或网络不稳定

2. 检查排行榜 API 延迟
   └─ 某个排行榜可能响应缓慢

3. 查看日志
   grep "llm_api_call" logs/silicon_river.log | tail -10

4. 解决方案
   ① 增加 LLM 超时时间
   ② 减少 MAX_CONCURRENT_ANALYSIS
   ③ 考虑是否禁用 Brave Search
```

### 问题 2：API 成功率 < 90%

```
诊断步骤：
1. 识别哪个 API 失败
   grep "ERROR" logs/silicon_river.log | grep -o "brave_search\|swe_bench\|lmsys"

2. 检查网络连接
   ping api.search.brave.com

3. 检查 API 配置
   cat .env | grep BRAVE_SEARCH

4. 解决方案
   ① 增加 TIMEOUT
   ② 增加 MAX_RETRIES
   ③ 检查防火墙规则
   ④ 联系 API 供应商
```

### 问题 3：缓存命中率 < 50%

```
诊断步骤：
1. 检查缓存大小
   python -c "from src.analysis.leaderboard_aggregator import LeaderboardAggregator; print(LeaderboardAggregator().get_cache_stats())"

2. 分析查询模式
   - 是否频繁查询不同模型？
   - 是否定期清空缓存？

3. 解决方案
   ① 增加缓存 TTL
   ② 实现缓存预热（batch update）
   ③ 检查是否有缓存清空操作
```

---

**版本**: 1.0 | **最后更新**: 2025-11-10 | **维护者**: Silicon River 项目团队
