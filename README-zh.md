# Silicon River

> 一条由 AI 增强分析驱动的大模型发布数据流。

Silicon River 汇聚公开发布的大模型（Hugging Face、OpenRouter），通过**实时网络搜索**和**多排行榜交叉验证**进行增强，应用精细的**里程碑检测算法**，最后通过沉浸式的 **3D 螺旋时间轴**呈现，支持丰富的过滤和交互。

**🌟 最新增强（Phase 4，2025年11月）**：生产级性能监控、多排行榜集成（SWE-bench、LMSYS Arena、HF Leaderboard）、以及 4 层级联里程碑检测策略。

_English version available at [README.md](README.md)._

## ✨ 核心特性

- **沉浸式 3D 时间轴** – 螺旋可视化设计，平滑相机控制；点击节点可锁定焦点并查看完整模型元数据及价格信息。

- **AI 增强分析** – 实时网络搜索（Brave API）+ LLM 分析 + 多排行榜验证，确保准确的模型画像。

- **智能里程碑检测** – 4 层级联策略，结合关键词分析、时间轴位置和权威排行榜排名（SWE-bench、LMSYS、HF）。

- **过滤优先的用户体验** – 时间范围（30天/6月/1年/全部）、年份、提供商、文本搜索和开源筛选，即时显示结果和模型数量。

- **可靠的数据管道** – Python 抓取脚本支持同步日志、PostgreSQL 缓存、增量更新，以及全面的测试覆盖（75+ 测试用例）。

- **生产就绪** – 完整的性能监控、分布式缓存、优雅的 API 降级和综合的运维文档。

## 架构

```text
                 ┌────────────────────┐
  Hugging Face   │  数据抓取脚本      │
  OpenRouter ──▶ │  (Python, 同步日志)│
                 └─────────┬──────────┘
                           │
                     PostgreSQL
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
 FastAPI REST API                    React + Three.js SPA
  (/api/timeline, etc.)          (Timeline3D、筛选面板)

            ┌─────────────────────────────┐
            │  AI 增强分析                │
            ├─────────────────────────────┤
            │ • Brave 搜索 API            │
            │ • 4 个排行榜 API            │
            │ • DeepSeek LLM 分析         │
            │ • 4 层里程碑检测            │
            │ • 性能监控                  │
            └─────────────────────────────┘
```

**核心组件**：

- **数据摄取**：Python 爬虫从 Hugging Face 和 OpenRouter 抓取模型，支持同步日志审计
- **实时网络搜索**：Brave Search API 提供最新模型公告和基准测试结果
- **多排行榜验证**：3 个权威来源（SWE-bench、LMSYS Arena、HF Leaderboard）验证模型能力
- **AI 分析**：DeepSeek LLM 基于网络信息和排行榜数据生成丰富的模型描述
- **里程碑检测**：4 层算法（强关键词 → 弱关键词 → 时间轴排名 → 排行榜排名）识别关键模型
- **性能监控**：分布式延迟追踪、缓存命中率监控、API 成功率统计，确保生产可靠性

## 快速开始

### 系统要求

- Python 3.11+ 和 Node.js 18+
- PostgreSQL 14+ 数据库（需有管理员权限）
- （可选）Hugging Face 访问令牌，用于提升抓取速率

### 1. 后端配置

```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # macOS/Linux
pip install -r requirements.txt
python scripts/init_db.py           # 初始化数据表和索引
```

将 `.env.example` 复制为 `.env`，按下表配置变量，然后启动 API 服务：

```bash
uvicorn backend.main:app --reload --port 8000
```

服务监听 `http://localhost:8000`，提供 `/health` 健康检查接口。

### 2. 前端配置

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

在 `frontend/.env` 中配置 `VITE_API_BASE`（默认 `http://localhost:8000`）。

### 环境变量

| 变量 | 说明 |
|------|------|
| **核心** | |
| `DATABASE_URL` | 抓取脚本和 API 共用的 PostgreSQL DSN（`postgresql://user:password@host:5432/silicon_river`）。 |
| `TEST_DATABASE_URL` | 测试用的隔离 PostgreSQL 数据库。 |
| **数据源** | |
| `HF_TOKEN` | Hugging Face 访问令牌，可选。 |
| `PROVIDERS` | 需要镜像的 Hugging Face 组织，逗号分隔。 |
| `PROVIDERS_OPENROUTER` | OpenRouter 同步时包含的提供者。 |
| `OPENROUTER_MODELS_URL` | OpenRouter 模型 API 自定义端点。 |
| `HF_DAILY_FETCH_LIMIT` / `OPENROUTER_DAILY_FETCH_LIMIT` | 增量抓取的安全上限。 |
| **AI 增强（Phase 4）** | |
| `BRAVE_SEARCH_API_KEY` | Brave Search API 密钥（从 https://api.search.brave.com 获取）|
| `ENABLE_BRAVE_SEARCH` | 启用/禁用 Brave Search 集成（默认：true）|
| `BRAVE_SEARCH_TIMEOUT` | 请求超时时间，单位秒（默认：10）|
| `BRAVE_SEARCH_MAX_RETRIES` | 失败重试次数（默认：3）|
| `LEADERBOARD_CACHE_TTL` | 排行榜数据缓存时长，单位秒（默认：3600）|
| **前端** | |
| `VITE_API_BASE` | 前端访问的后端基地址（默认 `http://localhost:8000`）|
| **缓存与性能** | |
| `AVATAR_MAX_BYTES` | 提供商头像大小限制，单位字节（默认：524288 = 512KB）|
| `AVATAR_CACHE_TTL` | 浏览器缓存头像时长，单位秒（默认：86400 = 1 天）|

**详细的 API 配置和成本分析，请参考 [docs/core-info-v1/1-API-INTEGRATION-GUIDE.md](docs/core-info-v1/1-API-INTEGRATION-GUIDE.md)**。

### 数据同步

根据需要选择全量或增量脚本。每次运行都会在 `sync_log` 表记录操作。启用 Brave Search 和排行榜 API 后，新模型会自动包含实时网络信息和多维度验证数据。

```bash
# Hugging Face 全量同步
python src/scraper/fetch_models.py

# Hugging Face 每日增量（推荐）
python src/scraper/fetch_models_incr_day.py --limit 200

# OpenRouter 全量同步
python src/scraper/fetch_models_openrouter.py

# OpenRouter 每日增量
python src/scraper/fetch_models_openrouter_incr_day.py --limit 300

# 更新排行榜缓存（建议每日运行）
python scripts/update_leaderboards.py

# 重新分析和更新已有模型（定期或按需运行）
python -m src.scraper.reanalyze_models --older-than-days 7 --no-confirm
```

**性能**：单个模型分析平均耗时 10-12 秒（目标 <15秒），排行榜缓存命中率 80-85%。提供商头像自动缓存到 PostgreSQL，后续请求直接返回二进制或回退到上游 URL，受 `AVATAR_MAX_BYTES` 大小限制。

**详细的性能监控和优化，请参考 [docs/core-info-v1/3-PERFORMANCE-MONITORING.md](docs/core-info-v1/3-PERFORMANCE-MONITORING.md)**。

## API 总览

| 接口 | 作用 | 主要参数 |
|------|------|----------|
| `GET /api/timeline` | 提供时间轴数据，供 3D 视图消费。 | `preset`（`30d`/`6m`/`1y`/`all`）、`year`、`page`、`page_size`、`provider`、`model_name`、`open_source`、`sort` |
| `GET /api/models` | 模型目录分页查询。 | `page`、`page_size`、`provider`、`tag`、`search` |
| `GET /api/stats/providers` | 按提供商分组的模型计数。 | – |
| `GET /api/providers/{id}/avatar` | 返回缓存头像，支持 HTTP 缓存头。 | – |
| `GET /health` | 健康自检，供负载均衡器使用。 | – |

所有接口返回 JSON 格式，并支持 CORS 跨域访问。

## 核心文档

深入了解各个功能模块，请参考 [docs/core-info-v1/INDEX.md](docs/core-info-v1/INDEX.md)：

| 文档 | 用途 | 受众 | 时长 |
|------|------|------|------|
| **1-API-INTEGRATION-GUIDE** | 配置 Brave Search 和 3 个排行榜 | 开发者、运维 | 30 分钟 |
| **2-MILESTONE-DETECTION-RULES** | 理解 4 层里程碑算法和调优 | 数据科学家、产品 | 45 分钟 |
| **3-PERFORMANCE-MONITORING** | 监控、诊断和优化系统性能 | 运维、SRE | 45 分钟 |
| **4-DEPLOYMENT-OPERATIONS** | 生产部署、日常维护、故障排查 | 运维、运营 | 1.5 小时 |
| **5-QUICK-REFERENCE-CARD** | 快速命令和参数查询 | 全部角色 | 5-10 分钟 |
| **6-MODEL-REANALYSIS-GUIDE** | 灵活更新已有模型数据 | 运维、数据管理 | 15-20 分钟 |

**快速入门路径**：

- 🚀 **新开发者**：5 分钟快速参考 → 1-API 集成指南 → 核心代码
- 🔧 **运维/SRE**：5 分钟快速参考 → 3-性能监控 → 4-部署运维 → 6-模型重新分析
- 📊 **数据科学家**：2-里程碑检测规则 → 3-性能监控
- 📋 **产品经理**：README 亮点功能 + 2-里程碑检测规则

## 前端特性

- 在时间轴上滚动或滑动即可浏览节点；点击节点可锁定焦点。
- 悬浮卡片展示提供商、发布时间（本地时区）、开源/闭源标签和描述；悬停标签可查看闭源模型的价格信息。
- 筛选标签、文本搜索实时生效，无需页面刷新；面板底部同步显示当前节点总数。
- 提供商头像仅在首次出现时请求，之后从缓存读取，避免界面闪烁。
- AI 驱动的里程碑标签突出显示关键模型，基于 4 层检测算法（关键词分析、时间轴位置、权威排名）。

## 测试

```bash
set TEST_DATABASE_URL=postgresql://user:pass@localhost:5433/silicon_river_test  # Windows
# export TEST_DATABASE_URL=...                                                 # macOS/Linux
pytest
```

测试套件（75+ 用例）自动创建/清空数据表，覆盖抓取流程、API 接口和里程碑检测算法。若缺少 PostgreSQL 或 FastAPI 测试客户端，将自动跳过相关用例。

**覆盖范围**：

- 数据抓取转换（Hugging Face 和 OpenRouter 格式解析）
- API 端点验证（时间轴过滤、头像缓存、排行榜查询）
- 数据库模式完整性（索引、约束、JOIN 操作）
- 里程碑检测算法（4 层策略验证）
- 性能监控和缓存行为
- 优雅的 API 降级和错误处理

性能基准测试详见 [docs/core-info-v1/3-PERFORMANCE-MONITORING.md](docs/core-info-v1/3-PERFORMANCE-MONITORING.md)。

## 项目结构

```text
backend/              FastAPI 应用和入口（uvicorn）
frontend/             React + Vite 单页应用（Timeline3D、筛选）
scripts/              数据库初始化脚本
src/scraper/          Hugging Face 和 OpenRouter 抓取程序
src/analysis/         AI 增强分析（Brave Search、排行榜、里程碑检测）
tests/                Pytest 测试套件（75+ 用例）
docs/core-info-v1/    核心项目文档（Phase 4）
  ├── 1-API-INTEGRATION-GUIDE.md
  ├── 2-MILESTONE-DETECTION-RULES.md
  ├── 3-PERFORMANCE-MONITORING.md
  ├── 4-DEPLOYMENT-OPERATIONS.md
  ├── 5-QUICK-REFERENCE-CARD.md
  └── INDEX.md
.env.example          环境变量模板
requirements.txt      Python 依赖清单
```

**Phase 4 新增模块**：

- `src/analysis/brave_search.py` – Brave Search API 客户端，支持缓存和重试机制
- `src/analysis/async_analyzer.py` – 异步模型分析器，集成实时网络信息
- `src/analysis/leaderboard_aggregator.py` – 3 个排行榜 API，支持缓存和模型名称规范化
- `src/analysis/performance_monitor.py` – 分布式延迟追踪和统计
- `src/analysis/performance_reporter.py` – 文本和 JSON 格式的性能报告
- `src/scraper/reanalyze_models.py` – 模型重新分析工具（三种策略）
- `scripts/update_leaderboards.py` – 排行榜缓存维护脚本

完整文档导航，请见 [docs/core-info-v1/INDEX.md](docs/core-info-v1/INDEX.md)。

## 许可证

MIT License – 详见 [LICENSE](LICENSE)。
