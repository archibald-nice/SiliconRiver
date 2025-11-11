# 快速参考卡 (Quick Reference Card)

**版本**: v1.0 | **最后更新**: 2025-11-10 | **用途**: 常用命令和参数速查

---

## 🚀 快速启动（5 分钟）

```bash
# 1. 复制配置文件
cp .env.example .env

# 2. 编辑 .env 填入 API 密钥
# 最少需要：BRAVE_SEARCH_API_KEY, DEEPSEEK_API_KEY, DATABASE_URL

# 3. 初始化数据库
python scripts/init_db.py

# 4. 启动后端（终端 1）
uvicorn backend.main:app --reload --port 8000

# 5. 启动前端（终端 2）
cd frontend && npm run dev

# 6. 打开浏览器
# http://localhost:5173
```

---

## 📋 常用命令

### 环境管理

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# 安装依赖
pip install -r requirements.txt

# 检查安装
python -c "import aiohttp, openai, psycopg; print('✓')"
```

### 数据库操作

```bash
# 初始化数据库
python scripts/init_db.py

# 连接数据库
psql -d silicon_river

# 查看表
psql -d silicon_river -c "\dt"

# 统计模型数
psql -d silicon_river -c "SELECT COUNT(*) FROM models;"

# 备份数据库
pg_dump silicon_river > backup_$(date +%Y%m%d).sql

# 恢复数据库
psql silicon_river < backup_20251110.sql
```

### 数据加载

```bash
# Hugging Face 全量同步
python src/scraper/fetch_models.py

# Hugging Face 增量同步（每日）
python src/scraper/fetch_models_incr_day.py --limit 200

# OpenRouter 全量同步
python src/scraper/fetch_models_openrouter.py

# OpenRouter 增量同步（每日）
python src/scraper/fetch_models_openrouter_incr_day.py --limit 300

# 更新排行榜缓存
python scripts/update_leaderboards.py
```

### 测试运行

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_brave_search.py -v
pytest tests/test_leaderboard_clients.py -v
pytest tests/test_integration_enhanced_analysis.py -v

# 运行并生成覆盖率报告
pytest tests/ --cov=src/analysis --cov-report=html

# 性能基准测试
python scripts/benchmark_analysis.py --models 10
```

### 监控和调试

```bash
# 查看实时日志
tail -f logs/silicon_river.log

# 搜索特定日志
grep "ERROR" logs/silicon_river.log
grep "brave_search" logs/silicon_river.log

# 性能统计
python -c "from src.analysis.performance_monitor import get_monitor; print(get_monitor().get_statistics())"

# 生成性能报告
python -c "from src.analysis.performance_reporter import print_performance_report; print_performance_report()"

# 查看缓存状态
python -c "from src.analysis.leaderboard_aggregator import LeaderboardAggregator; print(LeaderboardAggregator().get_cache_stats())"
```

---

## 🔧 环境变量速查

### 必填变量

| 变量 | 示例 | 说明 |
|------|------|------|
| `DATABASE_URL` | `postgresql://user:pass@localhost/silicon_river` | 数据库连接字符串 |
| `DEEPSEEK_API_KEY` | `sk-xxxx` | LLM API 密钥 |
| `BRAVE_SEARCH_API_KEY` | `Brv-xxxx` | 网络搜索 API 密钥 |

### 可选但推荐

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_BRAVE_SEARCH` | true | 启用网络搜索 |
| `BRAVE_SEARCH_TIMEOUT` | 10 | 搜索超时（秒） |
| `BRAVE_SEARCH_MAX_RETRIES` | 3 | 搜索重试次数 |
| `LEADERBOARD_CACHE_TTL` | 3600 | 缓存过期时间（秒） |
| `VITE_API_BASE` | `http://localhost:8000` | 前端 API 地址 |

### 完整配置模板

```env
# 数据库
DATABASE_URL=postgresql://user:password@localhost:5432/silicon_river
TEST_DATABASE_URL=postgresql://user:password@localhost:5433/silicon_river_test

# LLM API
DEEPSEEK_API_KEY=sk-YOUR_KEY
DEEPSEEK_API_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# Brave Search
BRAVE_SEARCH_API_KEY=Brv-YOUR_KEY
ENABLE_BRAVE_SEARCH=true
BRAVE_SEARCH_TIMEOUT=10
BRAVE_SEARCH_MAX_RETRIES=3

# 排行榜
LEADERBOARD_CACHE_TTL=3600

# 数据源
HF_TOKEN=hf_YOUR_TOKEN
PROVIDERS=meta-llama,google,microsoft,openai
PROVIDERS_OPENROUTER=openai,anthropic,google

# 前端
VITE_API_BASE=http://localhost:8000

# 日志
LOGLEVEL=INFO
```

---

## 📊 API 端点速查

### 时间轴数据

```bash
# 获取时间轴（使用过滤）
curl "http://localhost:8000/api/timeline?preset=30d&page=1&page_size=50"

# 查询参数
preset=30d              # 时间范围: 30d, 6m, 1y, all
year=2024              # 指定年份
provider=openai        # 厂商过滤
model_name=gpt         # 名称搜索
open_source=true       # 开源过滤
sort=asc               # 排序: asc, desc
page=1                 # 页码
page_size=50           # 每页大小
```

### 模型目录

```bash
# 获取模型列表
curl "http://localhost:8000/api/models?page=1&page_size=50&search=gpt"

# 查询参数
page=1                 # 页码
page_size=50           # 每页大小
provider=openai        # 厂商过滤
tag=chat               # 标签过滤
search=gpt             # 搜索关键词
```

### 统计信息

```bash
# 获取厂商统计
curl http://localhost:8000/api/stats/providers

# 返回示例
{
  "openai": 15,
  "google": 12,
  "meta": 8,
  ...
}
```

### 头像和健康检查

```bash
# 获取厂商头像
curl http://localhost:8000/api/providers/openai/avatar

# 健康检查
curl http://localhost:8000/health
```

---

## 🐛 常见问题快速解决

| 问题 | 症状 | 快速修复 |
|------|------|---------|
| **连接数据库失败** | `psycopg.OperationalError` | 检查 `DATABASE_URL` 配置，确保 PostgreSQL 运行 |
| **API 密钥无效** | `InvalidAPIKey` 错误 | 检查 `.env` 中的密钥，确保无多余空格 |
| **Brave Search 超时** | `TimeoutError` | 增加 `BRAVE_SEARCH_TIMEOUT` 到 15-20，检查网络 |
| **分析耗时 > 15s** | 性能下降 | 减少 `MAX_CONCURRENT_ANALYSIS`，更新 LLM 超时 |
| **测试失败** | `TEST_DATABASE_URL not set` | 设置环境变量 `export TEST_DATABASE_URL=...` |
| **缓存命中低** | 频繁 API 调用 | 增加缓存 TTL，运行 `update_leaderboards.py` |
| **内存占用高** | 进程占用 > 500MB | 清空缓存，减少并发数 |

---

## 📈 性能指标基准

### 目标值

```
分析延迟:
├── 平均 (P50): 10-12 秒 ✅
├── P95: 13-15 秒 ✅
└── P99: 14-16 秒 ✅

API 性能:
├── Brave Search: 2-3 秒 + 重试
├── 排行榜 (4 并发): 2-3 秒
└── LLM API: 7-9 秒

缓存效果:
├── Brave Search: 80%+ 命中
├── 排行榜缓存: 80-85% 命中
└── 整体缓存: 70%+ 命中
```

### 监控命令

```bash
# 查看最近分析时间
grep "total_analysis" logs/silicon_river.log | tail -20

# 计算平均延迟
grep "total_analysis" logs/silicon_river.log | \
  awk '{print $NF}' | \
  awk '{sum+=$1; count++} END {print sum/count " ms"}'

# 查看 API 成功率
grep "brave_search" logs/silicon_river.log | grep -c "success"
```

---

## 🔑 配置调优速查

### 性能相关配置

```python
# src/analysis/async_analyzer.py

# 并发分析数
MAX_CONCURRENT_ANALYSIS = 5          # 增加 → 更快，更多资源
                                     # 减少 → 更慢，更稳定

# 分析超时
ANALYSIS_TIMEOUT_SECONDS = 30        # 秒，通常不需要改

# HTTP 超时
HTTP_TIMEOUT = 30                    # 秒

# 重试配置
MAX_RETRIES = 3                      # 次数
RETRY_DELAY = 2                      # 秒

# Brave Search 配置
BRAVE_SEARCH_TIMEOUT = 10            # 秒
BRAVE_SEARCH_MAX_RETRIES = 3         # 次数
```

### 里程碑检测阈值

```python
# src/analysis/async_analyzer.py

# 强关键词（任一匹配）
STRONG_KEYWORDS = [
    "breakthrough", "milestone", "first", "revolutionary",
    "pioneering", "paradigm-shift", "landmark", "turning-point",
    "leap", "breakthrough-moment"
]

# 弱关键词（2+ 匹配）
WEAK_KEYWORDS = [
    "create", "novel", "innovate", "development",
    "improve", "enhance", "optimize", "refine",
    "first", "inaugural", "initial", "new-generation",
    "significant", "substantial", "considerable"
]

# 排行榜阈值
LEADERBOARD_THRESHOLDS = {
    "swe-bench": 10,        # 编程能力前 10
    "lmsys_arena": 20,      # 对话能力前 20
    "hf_leaderboard": 15,   # 开源综合前 15
    "opencompass": 10,      # 综合评估前 10
}
```

---

## 📱 API 客户端示例

### Python 客户端

```python
import asyncio
from src.analysis.async_analyzer import AsyncModelAnalyzer

async def main():
    async with AsyncModelAnalyzer() as analyzer:
        # 分析单个模型
        result = await analyzer.analyze_batch(
            model_ids=["gpt-4"],
            model_names=["GPT-4"]
        )

        print(f"是否里程碑: {result[0].is_milestone}")
        print(f"里程碑理由: {result[0].milestone_features}")

asyncio.run(main())
```

### cURL 示例

```bash
# 获取时间轴数据
curl -X GET "http://localhost:8000/api/timeline?preset=30d&page=1"

# 获取模型列表
curl -X GET "http://localhost:8000/api/models?search=gpt&page=1"

# 健康检查
curl http://localhost:8000/health
```

---

## 🎯 故障排查流程图

```
问题出现
  │
  ├─ 后端无响应?
  │  └─ 检查: 是否崩溃 → 查看日志
  │
  ├─ 数据库错误?
  │  └─ 检查: psql 连接 → DATABASE_URL
  │
  ├─ API 失败?
  │  └─ 检查: API 密钥 → 超时设置 → 重试次数
  │
  ├─ 性能慢?
  │  └─ 检查: 缓存命中 → 并发数 → API 延迟
  │
  └─ 测试失败?
     └─ 检查: TEST_DATABASE_URL → 依赖安装
```

---

## 📚 文档导航

| 需求 | 文档 | 阅读时间 |
|------|------|---------|
| 快速启动 | 本文档的"快速启动"部分 | 5 分钟 |
| 配置 API | `docs/core-info-v1/1-API-INTEGRATION-GUIDE.md` | 20 分钟 |
| 理解里程碑 | `docs/core-info-v1/2-MILESTONE-DETECTION-RULES.md` | 25 分钟 |
| 监控性能 | `docs/core-info-v1/3-PERFORMANCE-MONITORING.md` | 20 分钟 |
| 部署上线 | `docs/core-info-v1/4-DEPLOYMENT-OPERATIONS.md` | 30 分钟 |

---

## 📞 获取帮助

```bash
# 查看完整日志
tail -f logs/silicon_river.log

# 查看错误堆栈
grep -A 5 "Traceback" logs/silicon_river.log

# 性能诊断
python -c "
from src.analysis.performance_monitor import get_monitor
monitor = get_monitor()
print(monitor.get_total_analysis_time_stats())
print(monitor.get_failure_analysis())
"

# 测试特定功能
pytest tests/test_brave_search.py -v -s
```

---

**版本**: 1.0 | **最后更新**: 2025-11-10 | **维护者**: Silicon River 项目团队
