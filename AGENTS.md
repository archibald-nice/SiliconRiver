# AGENTS.md

本文件是本仓库的**项目记忆**，供所有在此仓库工作的 AI agent（以及人）阅读。
它取代了早期的 `CLAUDE.md`——那份文档属于只用一个 agent 维护项目的时期，
且其中的部分字段描述已与实现不符。

**维护要求**：改动项目结构、约定或踩到新坑时，请更新本文件。
本文件是**公开仓库的一部分**，不要写入任何私密信息
（凭据、具体部署位置、个人机器环境等）。

---

## 1. 项目执行规范（最重要，先读这节）

### 1.1 沟通

- **使用中文**沟通。代码、命令、技术术语保持英文。
- **不要在执行完代码后甩一大堆总结报告**。给结论和证据，不要凑字数。
- **涉及启动应用服务时（dev server、watcher、后台服务），必须先问人**，
  不要自己起长驻进程把会话挂住。

### 1.2 报告纪律：区分「实测」与「推测」

这是本仓库最重要的一条，因为它已经反复造成返工。

- **没验证过的操作不许说成功**。实测过的写"实测"，没验证的**必须显式标注**"未验证/推测"。
- **给出结论前先看证据**。本仓库历史上出现过多次"看起来是 bug、实际是设计如此"
  的误判，浪费了大量排查时间。
- 排查问题时，**把"现象"和"根因"分开写**。本项目多个重大故障的表象与根因完全无关
  （见第 7 节）。

### 1.3 修复必须带验证

- 改代码必须**跑测试**，并且确认测试**真的覆盖到了这次改动**。
- 修静默失败类 bug 时，**必须同时加回归测试**——否则它一定会复发（有过先例）。
- 声称"已修复"时，附上**实际执行的命令和输出**，不要只贴 diff。

### 1.4 破坏性操作先确认

删除文件、改全局配置、`git push --force`、往生产数据库写入等，**先说明再执行**。
注意：往线上数据库跑一次抓取脚本就是生产写入（本项目的数据管线直接连线上库）。

### 1.5 保持技术栈与编码风格一致

- 后端 Python 用 `from __future__ import annotations` + 类型标注，日志走 `logging`。
- 前端 TypeScript 严格模式，服务端状态一律走 React Query。
- 新增依赖前先确认它不是已有依赖的重复。

---

## 2. 项目概述

**Silicon River** 是一个交互式 3D 时间轴可视化系统，展示大语言模型的发布时间线。
它从 Hugging Face 与 OpenRouter 抓取模型元数据，存入 PostgreSQL，
用 LLM 生成模型分析，并通过 Three.js 螺旋时间轴渲染。

```text
   Hugging Face        ┌──────────────────┐
   OpenRouter   ─────▶ │  数据抓取脚本     │
                       │ (Python + CLI)   │
                       └────────┬─────────┘
                                │ 写
                          PostgreSQL
                                │ 读
              ┌─────────────────┴──────────────────┐
              │                                    │
     FastAPI REST API                   React + Three.js 前端
     （只读查询，永不抓取）                （3D 时间轴 + 分析弹窗）
```

**关键设计边界**：抓取只在数据管线机器上跑，**Web 服务侧是纯只读查询**。
不要试图让 API 去抓数据。

### 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI（Pydantic 校验）、Psycopg 3 |
| 前端 | React 18 + TypeScript、Vite、Three.js |
| 样式 | Tailwind CSS + Headless UI |
| 状态 | React Query（服务端）+ Hooks（本地） |
| 数据管线 | Python CLI（Click / argparse）、huggingface_hub |
| AI 分析 | DeepSeek（OpenAI 兼容接口） |

---

## 3. 环境与开发命令

### 3.1 建虚拟环境（有坑）

```bash
uv venv .venv --python 3.12
.venv/bin/pip install -r requirements.txt -r backend/requirements.txt
```

- **不要用 `python3 -m venv`**：在 uv/pyenv 托管的 Python 上会因 `ensurepip` 失败
  建出没有 pip 的环境。用 `uv venv`。
- **必须装两份依赖**：根目录那份是抓取 + AI 分析侧，`backend/` 那份是 API 侧。
- **后续所有命令用 `.venv/bin/python` 完整路径**，不要直接敲 `python`。
  用错解释器会报缺包，这是本项目最高频的假故障之一。
- `requirements-dev.txt` 额外包含 `pgserver`（自带 PostgreSQL 二进制，仅本机开发用）。

### 3.2 本地数据库（无需 Docker）

```bash
bash scripts/dev_db.sh start     # 数据放 /tmp，同时建好测试库
```

### 3.3 后端与前端

```bash
# 后端
.venv/bin/python scripts/init_db.py                  # 建表（幂等）
.venv/bin/python -m uvicorn backend.main:app --reload --port 8000

# 前端（新终端）
cd frontend && npm install && npm run dev            # http://localhost:5173
cd frontend && npm run build                         # tsc 检查 + Vite 构建
```

> **启动服务前先问人**（见 1.1）。

### 3.4 测试

```bash
# 需要 TEST_DATABASE_URL；scripts/dev_db.sh start 会一并建好测试库
.venv/bin/python -m pytest tests/ -q
```

**当前基线**：`148 passed, 33 skipped`。

- 那 33 个 skipped 是 `async def` 测试，因为 venv 里**没有 `pytest-asyncio`**，
  pytest 会警告 `PytestUnhandledCoroutineWarning` 并跳过。
  **这不是回归**，但意味着**这些 async 用例实际上从未真正执行**——
  新写涉及 async 的测试时要注意这一点，别以为绿灯就代表覆盖到了。
- 测试库有保护：库名不含 `test` 时 `conftest.py` 会拒绝清表，防止误删。

### 3.5 数据管线命令

```bash
# 抓取
.venv/bin/python -m src.scraper.fetch_models                      # HF 全量
.venv/bin/python -m src.scraper.fetch_models_incr_day             # HF 每日增量
.venv/bin/python -m src.scraper.fetch_models_openrouter           # OpenRouter 全量
.venv/bin/python -m src.scraper.fetch_models_openrouter_incr_day  # OpenRouter 每日增量

# AI 分析（只分析，不抓取）
.venv/bin/python -m src.scraper.analysis_orchestrator [--limit N] [--provider X] [--json]

# 重新分析（三种互斥策略）
.venv/bin/python -m src.scraper.reanalyze_models --force --limit 50
.venv/bin/python -m src.scraper.reanalyze_models --older-than-days 30
.venv/bin/python -m src.scraper.reanalyze_models --missing-fields is_milestone

# 每日同步编排（抓取，内部会清理代理变量并强制关闭分析）
bash scripts/daily_sync.sh [--dry-run]

# 体检与自检
.venv/bin/python scripts/check_supabase.py     # 库连通性 + 六张表行数（输出已脱敏密码）
.venv/bin/python scripts/check_deepseek_api.py # DeepSeek 连通性
.venv/bin/python scripts/find_duplicate_models.py   # 跨源重复模型扫描（只读）
```

**同步与分析是分开的两个定时任务**，不要合并。原因见第 7.2 节。

---

## 4. 数据库模式（以实现为准）

> ⚠️ 早期文档对 `sync_log` / `models` 的字段描述是**错的**，以本节为准（已核对线上库）。

**六张表**：`models`、`providers`、`model_tags`、`model_analysis`、
`model_arena_info`、`sync_log`。建表语句在 [`scripts/init_db.py`](scripts/init_db.py)。

### 4.1 类型陷阱：时间列存成了 TEXT

| 表.列 | 实际类型 | 说明 |
|---|---|---|
| `sync_log.started_at` / `finished_at` | **text** | 存 ISO 字符串 |
| `models.inserted_at` | **text** | 存 ISO 字符串 |
| `model_tags.inserted_at` | **text** | 存 ISO 字符串 |

**后果**：任何按时间过滤的查询**必须显式转型**，否则直接报错：

```sql
-- ❌ operator does not exist: text >= timestamp with time zone
WHERE started_at >= NOW() - INTERVAL '1 day'
-- ✅
WHERE started_at::timestamptz >= NOW() - INTERVAL '1 day'
```

**不要把"SQL 报错"误读成"没有数据"**，那会导致误告警。

### 4.2 `models`（核心表）

`id`(bigint) / `model_id`(text, 主键) / `provider`(text) / `model_name`(text) /
`description`(text) / `tags`(text, JSON 字符串) / `created_at`(timestamp, 无时区) /
`downloads`(bigint) / `likes`(bigint) / `model_card_url`(text) /
`inserted_at`(**text**) / `is_open_source`(boolean) / `price`(jsonb) / `huggingface_rank`(int)

- `model_id` 形如 `provider/name`，**含斜杠**。这影响了 API 路由设计（见第 5 节）。
- `created_at` 对 HF 是 HF 记录的发布时间；对 OpenRouter 是 API 的 `created` 时间戳。

### 4.3 `model_analysis`

`id` / `model_id` / `provider` / `model_name` / `analysis_summary`(text) /
`key_features`(ARRAY) / `use_cases`(ARRAY) / `performance_metrics`(jsonb) /
`llm_model_used`(text) / `is_milestone`(boolean) / `milestone_features`(text) /
`analyzed_at` / `updated_at`

写入用 `ON CONFLICT (model_id) DO UPDATE`。

### 4.4 `sync_log`（**只被 HF 链路写入**）

`id` / `provider` / `started_at`(**text**) / `finished_at`(**text**) / `status`(text) /
`processed`(bigint) / `inserted`(bigint) / `error_message`(text)

- **每厂商每轮一行**，`status` 实测只出现过 `'success'`。
- `processed` = 本次看到的模型数；`inserted` = 本次**真正新增**的行数。
  用 `RETURNING (xmax = 0)` 判定，**不是** `rowcount`
  （`ON CONFLICT DO UPDATE` 下 `rowcount` 恒为 1，会把"更新"误计成"新增"，
  这是修过的一个数据正确性 bug）。
- **稳态下 `inserted` 经常为 0 而 `processed` 正常，这不是故障。**
- ⚠️ **`fetch_models_openrouter*.py` 完全不写这张表**，也没有任何其他审计表。
  所以只按 `sync_log` 配监控，**OpenRouter 那条线挂了是看不见的**。

### 4.5 `model_arena_info`（排行榜评分）

`id` / `model_id` / `source` / `rank` / `score` / `category` / `updated_at` / `created_at`，
唯一键 `(model_id, source, category)`。

⚠️ **这张表目前没有任何自动化数据来源**（落库环节是空壳 TODO），
写入端只有一个需要人工喂 JSON 的 CLI `scripts/update_arena_scores.py`。
前端 `ArenaScoreDisplay` 查不到会静默显示为空，不报错。

### 4.6 `providers`

`provider_id`(主键) / `display_name` / `avatar_url` / `avatar_blob`(bytea) /
`avatar_mime` / `updated_at` / `created_at`。

头像策略：首次抓取后把二进制缓存进库，后续请求带 `Cache-Control` 直接吐缓存；
blob 为空则回退到上游 URL；有字节上限（`AVATAR_MAX_BYTES`，默认 524KB），
超标也回退上游。

---

## 5. API 端点

| 端点 | 说明 |
|---|---|
| `GET /api/timeline` | 时间轴数据。`preset`(30d/6m/1y/all)、`year`、`provider`、`model_name`、`open_source`、`page`、`page_size`(**10–500**，默认 200)、`sort`(asc/desc) |
| `GET /api/models` | 分页模型目录（无时间轴排序）。`page`、`page_size`、`provider`、`tag`、`search` |
| `GET /api/stats/providers` | 按提供商分组计数 |
| `GET /api/providers/{provider_id}/avatar` | 缓存的提供商头像，回退上游 |
| `GET /api/arena/scores/{model_id:path}` | 单模型排行榜评分 |
| `GET /health` | 最小化健康检查 |

### 两个路由相关的硬约束

1. **`model_id` 含斜杠，所以路由必须用 `{model_id:path}`**。
   用普通的 `{model_id}` 匹配不到任何真实 ID——这是修过的 bug。
2. **兜底路由必须放在所有固定路径之后**。曾经 `/api/models/{model_id:path}`
   放在前面，把后面的固定路由全吃掉了。
   [`tests/test_api_contract.py`](tests/test_api_contract.py) 里有路由顺序不变量测试守住这点。
3. 涉及长参数的查询用 **POST + 请求体**（例如带评分的分析查询），
   别把 `model_id` 塞进 query string。

### 后端请求管道

1. FastAPI 路由做 Pydantic 校验
2. `_calculate_timeline_window()` 依 `preset` / `year` 算时间窗
3. Psycopg 3 **参数化查询**（防注入），JOIN `providers` 取头像
4. Pydantic 模型序列化为类型化 JSON

> **性能约束**：纯数据库路由一律用**同步 `def`**，交给 FastAPI 线程池执行。
> 曾经用 `async def` 包同步 psycopg 调用，直接阻塞事件循环——已被契约测试守住。

---

## 6. 环境变量

从 [`.env.example`](.env.example) 复制出 `.env`。**`.env` 不进 git。**

| 变量 | 用途 |
|---|---|
| `DATABASE_URL` | 抓取与分析共享的 PostgreSQL |
| `HF_TOKEN` | HF 认证，可选；没有则 gated 仓库（如 `meta-llama`）读不到 |
| `PROVIDERS` | HF 待抓取的 org 列表（逗号分隔） |
| `PROVIDERS_OPENROUTER` | OpenRouter **白名单过滤器**（见下） |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_API_URL` / `DEEPSEEK_MODEL` | AI 分析 |
| `ENABLE_POST_SCRAPE_ANALYSIS` | 抓取后是否顺带分析。**`daily_sync.sh` 会强制设为 false** |
| `ENABLE_LEADERBOARD_LOOKUP` | **保持 false**，见第 7.3 节 |
| `ANALYSIS_LIMIT_PER_PROVIDER` | 单次分析上限（`.env.example` 给 500；代码兜底 50） |
| `MAX_CONCURRENT_ANALYSIS` / `ANALYSIS_TIMEOUT_SECONDS` | 分析并发（默认 5）与单模型预算（默认 30s） |
| `ANALYSIS_BATCH_SIZE` / `ANALYSIS_DELAY_BETWEEN_BATCHES` | 批量分析的分批大小（默认 10）与批间隔秒数（默认 2.0），用于对上游限流友好 |
| `ANALYSIS_MAX_FAILURE_RATE` | 失败率阈值，超过则以非 0 退出（默认 0.2） |
| `ENABLE_MCP_SEARCH` / `ENABLE_MCP_ARXIV` | 分析时是否做网络检索 / arXiv（后者默认 false） |
| `ENABLE_BRAVE_SEARCH` + `BRAVE_SEARCH_*` | Brave Search 集成（需 `BRAVE_SEARCH_API_KEY`） |
| `FETCH_DESCRIPTIONS` / `DESCRIPTION_*` | 模型简介抽取：并发 8、超时 10s、截断 300 字符 |
| `HTTP_TIMEOUT` / `MAX_RETRIES` / `RETRY_DELAY` | 抓取 HTTP 行为 |
| `OPENROUTER_MODELS_URL` | OpenRouter 数据源地址 |
| `LOG_LEVEL` | 日志级别 |
| `ALLOWED_ORIGINS` | CORS 白名单；**同域部署时无需改动** |
| `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` / `DB_POOL_TIMEOUT` / `DB_POOL_MAX_IDLE` | 连接池（默认 0 / 4） |
| `DB_CONNECT_TIMEOUT` | 数据库连接超时 |
| `VITE_API_BASE` | 前端 API 基址，**默认留空走相对路径** |
| `VITE_API_TARGET` / `VITE_HMR_HOST` / `VITE_HMR_PORT` | 仅 `npm run dev` 生效，且**只能从 shell 传**（见 6.2） |
| `AVATAR_MAX_BYTES` / `AVATAR_FETCH_TIMEOUT` / `AVATAR_CACHE_TTL` | 头像上游回退的大小上限（默认 524288）/ 超时（默认 6s）/ 浏览器缓存秒数（默认 86400） |

> ⚠️ **`backend/services/arena_service.py` 里的环境变量是死的**。
> 该文件读 `FETCH_HUGGINGFACE_SCORES` 与 `ARENA_SCORE_UPDATE_INTERVAL_HOURS`，
> 但**全仓库没有任何调用方**，这两个变量不生效，因此**没有收录进 `.env.example`**。
> 它内部还留着一条往 `model_arena_info` 的 INSERT（见 4.5 节说明），同样无人调用。
> 修排行榜链路时这里是候选复用点，但先确认它是否还值得保留，不要照抄。

### 6.1 `DEEPSEEK_API_URL` 必须是 base_url

填 `https://api.deepseek.com/v1`，**不要填完整端点**（`.../v1/chat/completions`）。
SDK 会自己再拼一次 `/chat/completions`，填完整端点会导致**每个模型都 404**。
（已实测确认并修正过。）

### 6.2 前端环境变量的作用域（高频坑）

- **Vite 的 `envDir` 是 `frontend/`**，所以**根目录的 `.env` 对前端构建完全无效**。
  前端相关变量要写进 `frontend/.env`。
- 该值在**构建期被内联进产物**。一旦填成 `http://localhost:8000` 之类，
  线上页面会去请求**访问者自己机器**的 8000 端口：页面能打开、数据全空、
  控制台一堆 `ERR_CONNECTION_REFUSED`。这是本项目最著名的部署坑。
- `VITE_API_TARGET` 是给 dev server 的代理用的，**仅 `npm run dev` 生效**，
  且 `vite.config.ts` 用 `process.env` 读它——所以写在 `.env` 里对
  `npm run dev` **也不生效**，要用 `VITE_API_TARGET=... npm run dev` 传。
- 同理还有 `VITE_HMR_HOST` / `VITE_HMR_PORT`（HMR 的 WebSocket 地址）。
  用另一台设备 / 容器 / 反向代理访问 dev server 时，若 HMR 连不上
  （控制台反复报 WebSocket 失败、改代码页面不刷新），
  把 `VITE_HMR_HOST` 指向**访问者实际使用的地址**，同样只能从 shell 传。

### 6.3 `PROVIDERS_OPENROUTER` 是白名单过滤器（两个坑）

代码语义（`fetch_models_openrouter.py`）：

```python
if providers_filter and provider_key not in providers_filter:
    continue        # 非白名单 org 直接丢弃
```

**留空 = 不过滤（全收）**。当前默认放行 **51 家**厂商。

#### 坑 1：必须填「展示名」，不是 `model_id` 的 id 前缀

`provider` 入库时取的是接口 `name` 字段里冒号前的部分（展示名），
两者对很多厂商**并不一致**（已实测）：

| id 前缀 | 实际入库的 provider key |
|---|---|
| `mistralai` | **`mistral`** |
| `z-ai` | **`z.ai`** |
| `x-ai` | **`spacexai`** |
| `meta-llama` | **`meta`** |

填错的表现是**该厂商一条都进不来，且不报错**。只有 `google` / `openai` /
`anthropic` 这几家展示名与前缀恰好一致，所以这个坑很容易被掩盖。

另有一类**解析降级**：部分条目 `name` 不含冒号（如 `Mistral Large 2407`、
`Qwen2.5 72B Instruct`），`extract_provider()` 会回退成把**整个模型名**
当 provider，产出 `mistral large 2407`、`sao10k` 这类伪 key。白名单不要收录它们。

#### 坑 2：limit 在过滤**之前**截断

```python
raw_models = raw_models[:limit]        # 先截断
for item in raw_models:
    if provider_key not in providers_filter: continue   # 再过滤
```

所以 `OPENROUTER_DAILY_FETCH_LIMIT` **必须 ≥ OpenRouter 全量模型数**，
否则排在后面的厂商会被整体挤掉，表现为「一条都没有」。当前设为 462。

---

## 7. 踩坑记录（**最重要的一节**）

> 下面每一条都是**真实发生过、且表象与根因严重不符**的故障。
> 排查任何"奇怪现象"之前，先扫一遍这节。

### 7.1 静默失败模式：被 `try/except` 吞掉的 bug

本仓库最危险的故障类型。已有两次重大事故都是这个模式：

- **`coroutine` 未 await**：分析入口是同步函数，却直接拿 `async def analyze_batch`
  的返回值（一个 coroutine 对象）去取下标 → 必然抛
  `TypeError: 'coroutine' object is not subscriptable`。
  调用方用 `try/except` 包着只打一行 warning，**退出码仍是 0**。
  结果：这个功能**从来没真正跑通过**，`model_analysis` 长期为空。
- **抓取后分析**：两个增量脚本各自在结尾调一次分析，失败同样被吞成 warning。

**教训与规范**：

- 任何"顺手做点额外事"的代码，**不要用 `try/except` 静默吞掉**，
  至少要以非 0 退出或明确告警。
- 引入 `asyncio.run()` 调用协程时，**确认真的 await 了**。
- **修这类 bug 必须配回归测试**，否则会复发。

### 7.2 监控必须能看到失败：同步与分析是两个任务

因为 7.1，同步脚本里的分析失败对监控完全不可见。
所以现在：

- `scripts/daily_sync.sh` **只抓数据**，内部强制 `ENABLE_POST_SCRAPE_ANALYSIS=false`。
- AI 分析是**独立任务**，入口 `.venv/bin/python -m src.scraper.analysis_orchestrator`，
  有自己的退出码语义（`decide_exit_code()`）：
  - `0` 成功或失败在容忍范围内（个例失败是常态）；
  - `1` 失败率超阈值，**或全部失败**；
  - `2` 参数错误。
- **不要打开 `SILICON_RIVER_SYNC_WITH_ANALYSIS`**，也不要把两者合并回去。

### 7.3 在线排行榜查询会吃掉整个分析预算（且会喂假数据）

分析流程里有一段"在线抓取 SWE-bench / LMSYS / HF 排行榜排名"的逻辑。实测：

- 三个上游客户端串联耗时约 **68 秒/模型**（一个 404 且要重试、一个 20s 超时），
  而单模型预算是 `ANALYSIS_TIMEOUT_SECONDS=30`。
  → **LLM 调用还没开始就被 `asyncio.wait_for` 掐断**，分析全军覆没。
- 更糟：上游失败后会**回落到写死的假排名数据**
  （`_get_mock_leaderboard()` 里写死的"Llama-2 排第 1、64.42 分"），
  等于拿编造事实喂给 LLM。

**现状**：已加 `ENABLE_LEADERBOARD_LOOKUP` 开关并**默认关闭**，
关闭时不建客户端、直接返回空列表。**不要打开它**，也不要把日志里的
"排行榜在线查询未启用"当故障去修。

### 7.4 代理环境变量会打死 httpx，但抓取脚本不受影响

如果 shell 里配了 `all_proxy=socks5://...`，或 `no_proxy` 里含 `[::1]`：

| 组件 | 用哪个库 | 是否受影响 |
|---|---|---|
| `src/analysis/*`（LLM 调用） | `openai` → **httpx** | ❌ 直接抛异常 |
| `backend/main.py` 头像回退抓取 | **httpx** | ❌ 同样受影响 |
| `src/scraper/*`（抓取） | `requests` / `huggingface_hub` | ✅ 不受影响 |
| 排行榜客户端 | `aiohttp` | ✅ 不受影响 |

两个**与"代理"字面无关**的报错，极难联想：

- `ImportError: Using SOCKS proxy, but the 'socksio' package is not installed`
  —— 字面意思是让你去装 socksio，但装了只是把"抛异常"变成"走代理"，
  代理不通时依旧失败，只是报错更含糊。
- `Invalid port: ':1]'` —— `no_proxy` 里的 `[::1]` 被 httpx 的 URL 解析器
  当成了畸形端口。

**症状极具误导性：抓取正常、AI 分析 100% 失败。**

**现状**：`scripts/daily_sync.sh` 内部已清理这两个变量（且有注释说明），
但 `analysis_orchestrator` 入口**没有**清理。要在本机直接跑分析入口，
先 `unset all_proxy ALL_PROXY` 并修掉 `no_proxy` 里的 `[::1]`。

### 7.5 "看起来坏了、其实没数据源"：`model_arena_info`

排查"排行榜评分区是空的"时，容易一路怀疑前端 / 接口 / JOIN。
实际根因是**这张表从来没有自动数据源**：落库函数
`LeaderboardAggregator.sync_to_database()` 是个空壳 TODO 且零调用方，
三个上游的数据接口又大面积失效。

**教训**：先分清"功能坏了"还是"功能从未被接上"。
后者不会报错，只会安静地什么都不做。

### 7.6 数据管线直连线上库，脚本会改生产数据

抓取/分析脚本读 `DATABASE_URL`，**没有本地/线上保护**。
跑一次 `fetch_models*` 就是往线上写。
所以：**不要为了"测试脚本能不能跑"而随手跑抓取**，
用 `--dry-run`（`daily_sync.sh` 支持）或先确认影响范围。

### 7.7 描述提取：HF 已把 description 从卡片元数据移除

模型简介一度全空。根因是 HF 改了接口——描述不再出现在卡片元数据里，
需要**从 README 抽取**。相关逻辑在 `fetch_models.py` 的
`extract_description_from_readme()` / `fetch_descriptions()`。

增量抓取只给**还没有简介**的模型拉 README，避免每天白跑上千次请求。

### 7.8 `rowcount` 在 `ON CONFLICT DO UPDATE` 下不可用于计数

`rowcount` 无论新增还是更新都是 1，会把"更新"算成"新增"，
污染 `sync_log` 的审计数据。**正确做法**：

```sql
INSERT INTO ... ON CONFLICT ... DO UPDATE SET ...
RETURNING (xmax = 0) AS is_insert
```

`xmax = 0` 表示这一行是本次 INSERT 产生的（新行）。

---

## 8. 架构细节

### 8.1 前端组件层次

```text
App
├── ThemeProvider
└── HomeWithAnalysis（唯一页面：时间轴）
    ├── MobileFilterButton / MobileFilterDrawer   移动端筛选
    ├── TimelineFilters                            桌面筛选芯片 + 搜索
    ├── ModeSwitcher                               经典螺旋 / 河流巡航 / 星轨螺旋
    └── Timeline3D                                 Three.js 场景
        ├── timeline/modes/ 的 ITimelineMode 实现
        └── ModelAnalysisModal                     点击节点后的分析详情
```

### 8.2 时间轴渲染管道

1. **数据加载** (`api/client.ts`)：Axios 拉 `/api/timeline` 并应用过滤
2. **数据集处理** (`timeline/core/dataset.ts`)：转成 Three.js 就绪格式
3. **模式初始化** (`timeline/modes/`)：可插拔布局，实现 `ITimelineMode`
4. **渲染**：WebGL 渲染 3D 节点，相机跟随焦点
5. **交互** (`Timeline3D.tsx`)：滚轮 / 点击触发模式导航

### 8.3 `ITimelineMode` 接口

`frontend/src/timeline/modes/ITimelineMode.ts`：

```typescript
interface ITimelineMode {
  init(config, dataset): Promise<void>        // 初始化 3D 场景
  layoutNodes(nodes): void                    // 在 3D 空间定位节点
  handleWheelEvent(direction, index): number  // 导航输入
  handleNodeClick(mesh): number | null        // 点击交互
  setFocus(index, callback): void             // 相机动画到节点
  update(deltaTime): void                     // 逐帧更新
  dispose(): void                             // 清理资源
  getScene/getCamera/getRenderer(): ...       // Three.js 访问器
}
```

**ClassicMode**：由排序后的模型时间戳构造 Catmull-Rom 曲线，
沿曲线按参数（0.0–1.0）均匀分布模型，相机沿曲线平滑缓动到焦点。

### 8.4 过滤管道

- 过滤器**累加**：`time_range AND provider AND text_search AND open_source`
- `preset="all"` 绕过时间过滤；指定 `year` 覆盖 `preset`
- 搜索对 `model_name` 与 `description` 应用 `ILIKE`
- 结果默认按时间 `ASC` 排序，保证时间轴顺序一致

### 8.5 性能要点

- 全部使用参数化 SQL（Psycopg 3 防注入）
- 分页上限 500、默认 200，控制大结果集负载
- Three.js 视锥剔除，屏幕外节点不渲染
- React Query 缓存 API 响应
- 头像在首屏渲染后延迟加载

---

## 9. 常见任务

**加时间轴过滤器**

1. 在 [`backend/main.py`](backend/main.py) 的 `timeline_models()` 加查询参数
2. 扩展 WHERE 子句
3. 在 [`frontend/src/components/TimelineFilters.tsx`](frontend/src/components/TimelineFilters.tsx) 加 UI 芯片
4. 通过 `useQuery()` 依赖数组传给 React Query

**支持新数据源**

1. 在 [`src/scraper/`](src/scraper/) 按 HF / OpenRouter 模式新建脚本
2. 需要新字段则在 [`scripts/init_db.py`](scripts/init_db.py) 扩展模式
3. 更新 `PROVIDERS` 或 `PROVIDERS_OPENROUTER`
4. **写 `sync_log` 审计记录**（注意 OpenRouter 那两条脚本目前没写，
   新脚本请补上，否则监控看不见它）

**新增时间轴可视化模式**

1. 实现 `ITimelineMode` 的类
2. 在模式工厂注册
3. 接入 `Timeline3D` 的模式切换器
4. 用 `timeline/core/dataset.ts` 的测试数据验证

---

## 10. 代码模式注记

- **Pydantic**：请求/响应校验，尽量复用模型保证类型安全
- **依赖注入**：`Depends()` 管理数据库连接
- **TypeScript 严格模式**（`frontend/tsconfig.json`）：模型类型集中在
  [`frontend/src/api/client.ts`](frontend/src/api/client.ts)
- **UTC 时间戳**：后端统一用 UTC，保证跨时区过滤一致
- **日志**：Python 侧走 `logging`，`LOG_LEVEL` 控制级别

---

## 11. 已知缺口

这些问题**已知且未修**，排查时不要重复投入。详见 `docs/issues/`（本地文档，不在公开仓库）：

- **排行榜评分链路断裂**：`model_arena_info` 无自动化数据源
  （落库是空壳 TODO，上游接口大面积失效，且有假数据兜底）。
  消费端静默显示为空。
- **OpenRouter 的变体与跨源重复**：`:batch` 枚举变体（91 条）、`~` 路由变体（17 条）
  会一起入库；同一模型还会被 HF 与 OpenRouter 各收一条，时间轴上出现两个节点。
  实测 929 条记录里有 **126 组归一化名重复（多出 131 条冗余）**：
  仅大小写不同 19 组、含变体后缀 87 组、其他 20 组。
  ⚠️ **库层面无法判定一条记录来自哪个源**（provider 可能相同、model_id 可能完全相同），
  所以合并必须人工判断。`models` 表也**没有 `source` 列**。
  查重工具：`scripts/find_duplicate_models.py`（只读）。
- **代理变量会打死分析链路**：`daily_sync.sh` 已处理，分析入口未处理。
- **两个数据源的命名规则互相冲突**：同一家厂商在 HF 与 OpenRouter 侧可能存成
  **两个 `provider` 键**（实测 `Qwen` 50 行 + `qwen` 40 行 → 前端筛选器出现两条
  "Qwen"；`providers` 表里还有一条 `display_name='Qwen (Qwen)'`）。
  另外 `model_name` 风格混杂：**441 条带 `厂商: ` 前缀**（OpenRouter 的 `name` 字段）、
  488 条不带，且有 **4 家 provider 内部两种风格并存**。
  改 `provider` / `model_name` 相关逻辑前先读 `docs/issues/005`。
- **OpenRouter 不写审计日志**：`sync_log` 只被 HF 链路写入，
  所以 OpenRouter 那条线的失败在监控里不可见（见 4.4 节）。

> 注：`docs/` 目录被 `.gitignore` 忽略（内部文档，提交历史已清除），
> 所以 clone 出来的仓库里没有它。**不要把 `docs/` 加回 git。**
