# Silicon River 项目说明

Silicon River 将公开发布的大模型汇集成一条可以交互的“时间长河”：抓取 Hugging Face 与 OpenRouter 的元数据，写入 PostgreSQL，并通过 Three.js 呈现可滚动、可锁定的 3D 时间轴。

_For English readers, please see [README.md](README.md)._

## 核心特性
- **沉浸式 3D 时间轴**：滚轮或拖拽即可浏览节点，点击模型锁定视角；悬浮卡片展示发布时间、标签与描述，闭源条目还带价格提示气泡。
- **轻量化筛选体验**：紧凑的标签式控件，可以即时切换时间范围（含“全部”视图）、指定年份、厂商、名称关键字与开源状态。
- **稳健的数据同步**：Python 抓取脚本镜像 Hugging Face / OpenRouter 数据，自动补齐厂商头像并写入同步日志，方便审计。
- **FastAPI + PostgreSQL 后端**：提供结构化 JSON 接口、头像缓存与分页支持，既服务前端也适合外部系统集成。
- **React + React Query 前端**：Vite 打包、Tailwind 风格、按需缓存，面对成百上千个时间节点依旧顺滑。

## 架构总览
```text
                 ┌────────────────────┐
  Hugging Face   │  数据抓取脚本       │
  OpenRouter ──▶ │  (Python, Sync Log)│
                 └─────────┬──────────┘
                           │
                     PostgreSQL
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
 FastAPI REST API                    React + Three.js 前端
```

## 快速开始
### 准备条件
- Python 3.11+、Node.js 18+
- 可写入的 PostgreSQL 14+ 实例
- （可选）Hugging Face 访问令牌，用于提升抓取速率

### 1. 后端环境
```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # macOS/Linux
pip install -r requirements.txt
python scripts/init_db.py           # 初始化数据表与索引
```

将 `.env.example` 复制为 `.env`，根据下方表格配置变量，然后启动接口服务：
```bash
uvicorn backend.main:app --reload --port 8000
```
默认监听 `http://localhost:8000`，`/health` 可用于健康检查。

### 2. 前端环境
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```
在 `frontend/.env` 中设置 `VITE_API_BASE`（默认为 `http://localhost:8000`）。

### 环境变量速查
| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | 抓取脚本与 API 共用的 PostgreSQL DSN，如 `postgresql://user:password@host:5432/silicon_river`。 |
| `HF_TOKEN` | Hugging Face 访问令牌，可选。 |
| `PROVIDERS` | 需要镜像的 Hugging Face 组织 ID，逗号分隔。 |
| `PROVIDERS_OPENROUTER` | OpenRouter 同步时允许的提供者。 |
| `OPENROUTER_MODELS_URL` | OpenRouter 模型 API 自定义地址。 |
| `HF_DAILY_FETCH_LIMIT` / `OPENROUTER_DAILY_FETCH_LIMIT` | 增量抓取的安全上限。 |
| `VITE_API_BASE` | 前端访问的后端基地址。 |
| `TEST_DATABASE_URL` | 运行测试时使用的 PostgreSQL 数据库。 |

### 数据同步
根据需求选择全量或增量脚本，运行后会把处理结果写入 `sync_log`：

```bash
# Hugging Face 全量
python src/scraper/fetch_models.py

# Hugging Face 每日增量
python src/scraper/fetch_models_incr_day.py --limit 200

# OpenRouter 全量
python src/scraper/fetch_models_openrouter.py

# OpenRouter 每日增量
python src/scraper/fetch_models_openrouter_incr_day.py --limit 300
```

提供者头像自动缓存到 PostgreSQL；若超过 `AVATAR_MAX_BYTES` 或抓取失败，接口会回退到源站资源。

## API 总览
| 接口 | 作用 | 主要参数 |
|------|------|----------|
| `GET /api/timeline` | 提供时间轴数据，供 3D 视图消费。 | `preset`（`30d`/`6m`/`1y`/`all`）、`year`、`page`、`page_size`、`provider`、`model_name`、`open_source`、`sort` |
| `GET /api/models` | 模型目录分页查询。 | `page`、`page_size`、`provider`、`tag`、`search` |
| `GET /api/stats/providers` | 厂商维度的模型数量。 | – |
| `GET /api/providers/{id}/avatar` | 返回缓存头像，并带缓存控制头。 | – |
| `GET /health` | 健康自检。 | – |

接口统一返回 JSON，并开启 CORS 以便前端直接访问。

## 前端体验
- 在时间轴上滚动或滑动即可浏览节点；左键点击可固定当前模型，滚动进一步浏览。
- 悬浮卡片展示厂商、名称、发布日、开源状态及摘要；对闭源模型悬停“开源/闭源”标签即可看到价格信息。
- 筛选标签、年份输入与文本搜索实时生效，面板底部同步展示当前节点总数。
- 厂商头像仅在首次出现时请求一次，后续从缓存中读取，避免闪烁。

## 测试
```bash
set TEST_DATABASE_URL=postgresql://user:pass@localhost:5433/silicon_river_test  # Windows
# export TEST_DATABASE_URL=...                                                 # macOS/Linux
pytest
```
测试会自动创建/清空数据表，覆盖抓取流程与 `/api/timeline` 接口；若缺少 PostgreSQL 或 FastAPI 测试客户端，将跳过相关用例。

## 目录结构
```text
backend/           FastAPI 应用与入口（uvicorn main:app）
frontend/          React + Vite 单页应用（Timeline3D、筛选面板）
scripts/           数据库初始化脚本
src/scraper/       Hugging Face / OpenRouter 抓取程序
tests/             覆盖抓取与 API 的 pytest 用例
.env.example       环境变量模版
requirements.txt   Python 依赖清单
```

## 许可证
MIT License – 详见 [LICENSE](LICENSE)。
