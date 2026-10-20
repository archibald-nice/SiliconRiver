# Silicon River

> 一条由 AI 增强分析驱动的大模型发布数据流。

Silicon River 汇聚公开发布的大模型目录（Hugging Face、OpenRouter），可选地用 Brave 网络搜索和三个排行榜客户端做增强，应用基于关键词与排名的**里程碑判定策略**，最后通过交互式 **3D 螺旋时间轴**呈现，支持过滤和悬浮提示。

**最新增强（Phase 5，2026年10月）**：真实的 arena 评分——由 `scripts/sync_arena_scores.py` 从 **LMArena**（HF `lmarena-ai/leaderboard-dataset`）与 **SWE-bench** 导入；全链路 UTC `timestamptz`；HF 抓取按 `pipeline_tag` 过滤；测试套件完全不碰网络。那三个老的进程内排行榜客户端仍**默认关闭**（见[已知缺口](#已知缺口)）。

_English version available at [README.md](README.md)._

## ✨ 核心特性

- **沉浸式 3D 时间轴** – 螺旋可视化设计，平滑相机控制；点击节点可锁定焦点并查看完整模型元数据及价格信息。

- **AI 增强分析** – 可选的 Brave 搜索上下文 + DeepSeek LLM 分析。排行榜增强是 opt-in（默认关闭）。

- **智能里程碑检测** – 四分支策略：强关键词 → 弱关键词组合 → 时间轴位置 → 排行榜排名（最后一条要等 arena 评分导入后才会生效）。

- **过滤优先的用户体验** – 时间范围（30天/6月/1年/全部）、年份、提供商、文本搜索和开源筛选，即时显示结果和模型数量。

- **数据管道** – Python 抓取脚本、同步日志、PostgreSQL 存储、增量任务，以及 475 条后端测试用例（见[测试](#测试)）。

- **可观测性** – 进程内延迟/成功率指标，支持文本和 JSON 报告；提供商头像二进制缓存在 PostgreSQL。没有分布式缓存，也不做多实例指标聚合。

## 架构

```mermaid
flowchart LR
    hf["Hugging Face"] --> scrapers["Python 抓取脚本<br/>（HF 任务写 sync_log）"]
    orx["OpenRouter"] --> scrapers
    scrapers --> db[("PostgreSQL")]
    db --> analysis["可选 AI 分析<br/>DeepSeek LLM + Brave 搜索<br/>+ 3 个排行榜客户端（默认关闭）"]
    analysis --> db
    db --> api["FastAPI REST API"]
    api --> spa["React + Three.js SPA"]
```

**核心组件**：

- **数据摄取**：Python 抓取脚本从 Hugging Face 和 OpenRouter 抓取模型。Hugging Face 任务每次运行写一行 `sync_log`；OpenRouter 任务目前不写（已知缺口）。
- **实时网络搜索**：可选的 Brave Search API 上下文，用于最新公告和基准测试；`.env.example` 里默认关闭，直到配置 Key。
- **排行榜增强**：arena 评分来自两个真实数据源——LMArena（HF `lmarena-ai/leaderboard-dataset`，按 parquet 直读）与 SWE-bench（`swebench.com` 内嵌 JSON）——由 `scripts/sync_arena_scores.py` 把榜单名匹配到库里的 `model_id` 并 upsert 进 `model_arena_info`。那三个老的进程内客户端仍存在，但默认关闭。
- **AI 分析**：DeepSeek LLM 基于模型目录数据（以及启用后的网络/排行榜上下文）生成模型描述。
- **里程碑检测**：四分支策略（强关键词 → 弱关键词组合 → 时间轴排名 → 排行榜排名）识别关键模型；排行榜分支在 arena 数据导入前不会生效。
- **可观测性**：`PerformanceMonitor` 维护一个有界的进程内样本窗口，`performance_reporter` 输出文本/JSON 报告。没有分布式延迟追踪，也没有缓存命中率指标。

## 已知缺口

以下是明确记录的限制，不是"功能完备"的声明：

- **老的排行榜在线查询默认关闭**（`ENABLE_LEADERBOARD_LOOKUP=false`）。三个上游客户端串起来约 70 秒，远超单模型 30 秒的分析预算；上游失败时现在返回空结果 + WARNING，不再回落写死的示例排名（假数据已在 `c9327ec` 删除）。
- **arena 同步是定时任务，不是请求时查询。** 分数只在 `scripts/sync_arena_scores.py` 运行时更新（产线上每周一次）；榜单上仍有约四分之一条目在库里找不到对应模型，这些模型的 arena 面板为空。
- **抓取每天跑一次，不是每小时。** 目前每个模型写库要约 1.3 秒往返，全量一轮约一小时；提高频率需要先做批量写改造（本地 issue 档有记录）。
- **OpenRouter 抓取不写 `sync_log`。** 只有 Hugging Face 抓取脚本记录运行。
- **指标是单进程的。** 没有 Redis、没有分布式缓存、也没有跨 API 实例的聚合；`LEADERBOARD_CACHE_TTL` 没有任何代码读取。
- **测试套件曾经依赖真实网络。** 三个排行榜用例只 mock 了三个客户端中的一个，另外两个会真发请求、超时后回落到示例数据——耗时 206 秒而不是 0.06 秒，还会因执行顺序偶发失败。现在全部 mock，测试必须保持离线自洽。

## 快速开始

### 系统要求

- Python 3.11+（CI 用 3.12）和 Node.js 20+
- PostgreSQL 14+ 数据库（需有管理员权限）
- （可选）Hugging Face access token，用于提高限流额度

**密钥**：所有凭据（数据库连接串、HF token、DeepSeek key）都从环境变量或本机
`.env` 读取，而 `.env` 已被 git 忽略。仓库里只有占位模板
（`.env.example`、`backend/.env.example`、`frontend/.env.example`），
**不含任何真实密钥、token 或带凭据的连接串**。
- （可选）Hugging Face 访问令牌，用于提升抓取速率

### 1. 后端配置

```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # macOS/Linux
pip install -r requirements.txt           # 抓取 + AI 分析侧依赖
pip install -r backend/requirements.txt   # FastAPI 服务侧依赖（本地跑通需要装两份）
pip install -r requirements-dev.txt       # 可选：测试工具 + 本地 pgserver
python scripts/init_db.py           # 初始化数据表和索引
```

> 若 `python -m venv` 报 `ensurepip` 失败（macOS 上常见：`python3` 是 uv/pyenv 托管的
> 可重定位构建），改用 `uv venv .venv --python 3.12`。
>
> 本机没有 PostgreSQL？`bash scripts/dev_db.sh start` 会用 `.venv` 里 pgserver 自带的
> 二进制起一个本地库，不需要 Homebrew 或 Docker。

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
| `DEEPSEEK_API_KEY` | 可选；不填则跳过 AI 分析。 |
| `DEEPSEEK_API_URL` | DeepSeek base URL（`https://api.deepseek.com/v1`），不要带 `/chat/completions`。 |
| `DEEPSEEK_MODEL` | 分析模型（默认 `deepseek-chat`）。 |
| `ENABLE_POST_SCRAPE_ANALYSIS` | 抓取结束后顺带跑分析（默认 `false`；推荐拆成独立分析任务）。 |
| `BRAVE_SEARCH_API_KEY` | Brave Search API 密钥（从 https://api.search.brave.com 获取）|
| `ENABLE_BRAVE_SEARCH` | 启用/禁用 Brave Search 集成（代码默认 `true`；`.env.example` 在配 Key 前为 `false`）|
| `BRAVE_SEARCH_TIMEOUT` | 请求超时时间，单位秒（默认：10）|
| `BRAVE_SEARCH_MAX_RETRIES` | 失败重试次数（默认：3）|
| `ENABLE_LEADERBOARD_LOOKUP` | 分析时在线查询排行榜（默认 `false`；原因见[已知缺口](#已知缺口)）|
| **前端** | |
| `VITE_API_BASE` | 前端访问的后端基地址（默认 `http://localhost:8000`）|
| **缓存与性能** | |
| `AVATAR_MAX_BYTES` | 提供商头像大小限制，单位字节（默认：524288 = 512KB）|
| `AVATAR_CACHE_TTL` | 浏览器缓存头像时长，单位秒（默认：86400 = 1 天）|

### 数据同步

根据需要选择全量或增量脚本。Hugging Face 任务每次运行都会在 `sync_log` 表记录操作，OpenRouter 任务目前不会。Brave Search 和排行榜增强默认关闭，需要显式开启。

> **注意两个坑**：
> 1. 抓取脚本**必须用 `-m` 模块方式执行**。用 `python src/scraper/xxx.py` 直接按路径执行会报 `ModuleNotFoundError: No module named 'src'`，因为这些脚本内部用的是 `from src.scraper import ...` 这种包内导入。
> 2. 抓取数量**不看命令行参数**，而是读 `.env` 里的 `HF_DAILY_FETCH_LIMIT` / `OPENROUTER_DAILY_FETCH_LIMIT`。写成 `--limit 200` 不会生效。

```bash
# Hugging Face 全量同步
python -m src.scraper.fetch_models

# Hugging Face 每日增量（推荐）
python -m src.scraper.fetch_models_incr_day

# OpenRouter 全量同步
python -m src.scraper.fetch_models_openrouter

# OpenRouter 每日增量
python -m src.scraper.fetch_models_openrouter_incr_day

# 一键增量同步（Hugging Face + OpenRouter，适合挂到定时任务）
bash scripts/daily_sync.sh

# 数据库体检：确认表建好、数据到位
python scripts/check_supabase.py

# 老路径：预热进程内排行榜缓存（不写库；真正的落库同步走 sync_arena_scores.py）
python scripts/update_leaderboards.py

# 从 LMArena + SWE-bench 同步 arena 评分进 model_arena_info
python scripts/sync_arena_scores.py --source all

# 重新分析和更新已有模型（定期或按需运行）
python -m src.scraper.reanalyze_models --older-than-days 7 --no-confirm
```

**性能**：本仓库不附带基准测试结果。单模型耗时取决于 LLM 和可选的上游接口；在排行榜查询关闭（默认）时，不涉及排行榜缓存。提供商头像自动缓存到 PostgreSQL，后续请求直接返回二进制或回退到上游 URL，受 `AVATAR_MAX_BYTES` 大小限制。

## API 总览

| 接口 | 作用 | 主要参数 |
|------|------|----------|
| `GET /api/timeline` | 提供时间轴数据，供 3D 视图消费。 | `preset`（`30d`/`6m`/`1y`/`all`）、`year`、`page`、`page_size`、`provider`、`model_name`、`open_source`、`sort` |
| `GET /api/models` | 模型目录分页查询。 | `page`、`page_size`、`provider`、`tag`、`search` |
| `GET /api/stats/providers` | 按提供商分组的模型计数。 | – |
| `GET /api/providers/{id}/avatar` | 返回缓存头像，支持 HTTP 缓存头。 | – |
| `GET /health` | 健康自检，供负载均衡器使用。 | – |

所有接口返回 JSON 格式，并支持 CORS 跨域访问。

## 前端特性

- 在时间轴上滚动或滑动即可浏览节点；点击节点可锁定焦点。
- 悬浮卡片展示提供商、发布时间（本地时区）、开源/闭源标签和描述；悬停标签可查看闭源模型的价格信息。
- 筛选标签、文本搜索实时生效，无需页面刷新；面板底部同步显示当前节点总数。
- 提供商头像仅在首次出现时请求，之后从缓存读取，避免界面闪烁。
- AI 驱动的里程碑标签突出显示关键模型，基于四分支检测策略（关键词、时间轴位置，以及有数据时的排行榜排名）。

## 测试

先安装开发依赖（测试工具已从生产依赖中移出）：

```bash
pip install -r requirements-dev.txt
export TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/silicon_river_test   # macOS/Linux
# set TEST_DATABASE_URL=...                                                        # Windows
.venv/bin/python -m pytest tests/ -q
```

后端测试共收集 **475 条用例，跑完约 22 秒**（`475 passed`）。

两件值得记住的历史：

- 2026-10-18 之前基线是 `148 passed, 33 skipped`：`async def` 用例因为没装 `pytest-asyncio` 被跳过，**从未真正执行过**。装上之后立刻暴露 5 个过期 mock，现已修复。
- 测试套件不许碰真实网络。三个排行榜用例原来只 mock 了三个客户端中的一个，其余会真发请求、每次超时约 70 秒，再回落到写死的示例数据（结果还跟执行顺序有关）。

测试套件会自动建表并在用例之间清表，覆盖抓取转换、API 接口和里程碑算法。未设置 `TEST_DATABASE_URL` 时，依赖数据库的用例会跳过。CI（`.github/workflows/ci.yml`）用 `postgres:16` service 跑同一套测试，外加前端 `npm ci && npm run build`。

**覆盖范围**：

- 数据抓取转换（Hugging Face 和 OpenRouter 格式解析）
- API 端点验证（时间轴过滤、头像缓存、arena 评分查询）
- 数据库模式完整性（索引、约束、JOIN 操作）
- 里程碑检测算法（四分支策略验证）
- 搜索客户端行为（缓存、重试、错误路径）
- 优雅的 API 降级和错误处理

## 项目结构

```text
backend/              FastAPI 应用和入口（uvicorn）
frontend/             React + Vite 单页应用（Timeline3D、筛选）
scripts/              数据库初始化与维护 CLI
src/scraper/          Hugging Face 和 OpenRouter 抓取程序
src/analysis/         AI 增强分析（Brave Search、排行榜、里程碑检测）
tests/                Pytest 测试套件（475 条后端用例）
.github/workflows/    CI（后端 pytest + 前端构建）
.env.example          环境变量模板
requirements.txt      运行时 Python 依赖
requirements-dev.txt  测试工具 + 本地 PostgreSQL（pgserver）
```

**Phase 4 新增模块**：

- `src/analysis/brave_search.py` – Brave Search API 客户端，支持缓存和重试机制
- `src/analysis/async_analyzer.py` – 异步模型分析器，集成实时网络信息
- `src/analysis/leaderboard_aggregator.py` – 3 个排行榜客户端，支持进程内缓存和模型名称规范化（未设 `ENABLE_LEADERBOARD_LOOKUP=true` 时禁用）
- `src/analysis/performance_monitor.py` – 进程内延迟追踪和统计（有界样本窗口）
- `src/analysis/performance_reporter.py` – 文本和 JSON 格式的性能报告
- `src/scraper/reanalyze_models.py` – 模型重新分析工具（三种策略）
- `scripts/update_leaderboards.py` – 预热进程内排行榜缓存；不写入 PostgreSQL

## 许可证

MIT License – 详见 [LICENSE](LICENSE)。
