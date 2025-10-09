# Silicon River 项目说明

> 统一的全栈数据流水线：抓取 Hugging Face 模型元数据，写入 PostgreSQL，并通过 FastAPI 与 React 仪表盘对外提供服务。

如需英文文档，请查看 [README.md](README.md)。

## 项目概述
- 按 `PROVIDERS` 列表抓取 Hugging Face 组织的模型信息，标准化后写入 PostgreSQL。
- 暴露 REST API，支持目录浏览、时间轴查询与提供者统计。
- 提供基于 React + Three.js 的交互式仪表盘，可视化模型数据与时间线。
- 抓取器、API 和前端均可独立部署，也可以组合成一体化方案。

## 架构概览
```text
Hugging Face Hub
       |
       v
数据抓取脚本 (Python) --> PostgreSQL <-- FastAPI REST API --> React + Three.js 仪表盘
                       |
                       v
                 同步日志与测试
```

## 仓库结构
```text
SiliconRiver/
|- backend/              FastAPI 入口与依赖清单
|  |- main.py
|  |- requirements.txt
|- scripts/
|  |- init_db.py         PostgreSQL 架构初始化脚本
|- src/
|  |- scraper/
|     |- fetch_models.py Hugging Face 抓取脚本
|- frontend/             基于 Vite 的 React + Tailwind 单页应用
|- tests/                覆盖数据抓取流程的 pytest 测试
|- data/                 预置的 SQLite 样例数据库
|- requirements.txt      抓取器/测试共享的 Python 依赖
|- .env.example          根级环境变量模板（HF token、provider、DB 等）
```

## 核心组件
### 抓取器 (`src/scraper/fetch_models.py`)
- 使用 Hugging Face Hub SDK 按提供者列出模型，映射为 `ModelRecord` 并写入 `models`、`sync_log` 表。
- 统一时间戳为 UTC 字符串，截断过长描述，并以 JSON 形式存储标签。
- 复用 `scripts.init_db.create_schema`，确保插入前已创建数据表与索引。

### 数据库架构 (`scripts/init_db.py`)
- 定义 `models`（唯一 `model_id`、元数据字段、审计时间戳）与 `sync_log`（每次同步指标）。
- 针对提供者、创建时间、同步记录建立索引，提升查询效率。

### FastAPI 后端 (`backend/main.py`)
- 暴露 `/api/models`、`/api/models/{model_id}`、`/api/timeline`、`/api/stats/providers` 与 `/health`。
- 支持按提供者、标签、搜索关键字过滤，并提供分页与时间范围（30d / 6m / 1y 或自定义年份）。
- 基于 Pydantic 响应模型与 psycopg 3 `dict_row` 游标输出结构化数据。
- 允许跨域访问，并从项目 `.env` 读取 `DATABASE_URL`。

### React 前端 (`frontend/`)
- 采用 Vite + React 18 + TypeScript + Tailwind UI，配合 React Query 做数据拉取与缓存。
- `Home.tsx` 提供时间轴/列表双标签页、过滤面板与分页卡片。
- `Timeline3D.tsx` 利用 Three.js 绘制可交互曲线，支持悬浮提示与滚轮导航。
- 使用 `VITE_API_BASE` 环境变量指定后端 API 地址。

### 测试套件 (`tests/test_fetch_models.py`)
- 针对 `TEST_DATABASE_URL` 启动完整抓取流程，并模拟 Hugging Face 客户端。
- 验证去重逻辑、同步日志记录，以及通过 `TestClient` 调用 FastAPI 时间轴接口。
- 依赖 psycopg 及 `fastapi[testclient]`，若缺少依赖会自动跳过。

## 环境变量配置
可通过根级 `.env`、各服务 `.env` 或运行时变量进行配置。

| 变量 | 用途 | 备注 |
|------|------|------|
| `HF_TOKEN` | 可选 Hugging Face 令牌，提升速率限制 | 建议保存在根级 `.env` |
| `PROVIDERS` | 需要镜像的组织 ID，逗号分隔（示例 `meta-llama,google`） | 抓取器必填 |
| `DATABASE_URL` | 抓取器与 API 使用的 PostgreSQL DSN | 例如 `postgresql://user:pass@host:5432/silicon_river` |
| `TEST_DATABASE_URL` | pytest 使用的 PostgreSQL DSN | 指向一次性数据库 |
| `VITE_API_BASE` | 前端访问的后端基地址 | 默认 `http://localhost:8000` |

样例数据：`data/silicon_river.db` 为预填充的 SQLite 快照，便于快速浏览或离线调试。

## 快速上手
1. **克隆仓库**
   ```bash
   git clone <repo-url>
   cd SiliconRiver
   ```
2. **创建虚拟环境并安装 Python 依赖**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   # source .venv/bin/activate  # macOS/Linux
   pip install -r requirements.txt
   pip install -r backend/requirements.txt
   ```
3. **准备环境变量文件**
   ```bash
   cp .env.example .env
   cp backend/.env.example backend/.env
   cp frontend/.env.example frontend/.env
   ```
   然后填写：
    - `HF_TOKEN`（可选）：Hugging Face 访问令牌，用于提高速率限制。
    - `PROVIDERS`（必填）：需要同步的组织 ID，逗号分隔。
    - `DATABASE_URL`：PostgreSQL 连接串，例如 `postgresql://user:password@host:5432/silicon_river`。
    - `VITE_API_BASE`：FastAPI 服务地址，默认 `http://localhost:8000`。
4. **初始化数据库结构**
   ```bash
   python scripts/init_db.py
   ```
5. **运行抓取器**（可重复执行以刷新数据）
   ```bash
   python src/scraper/fetch_models.py
   ```
6. **启动 API**
   ```bash
   cd backend
   uvicorn main:app --reload --port 8080
   ```
7. **启动前端**（新终端）
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   访问 `http://localhost:5173/`，开发服务器会将 API 请求代理到 `VITE_API_BASE`。

## API 接口
| 接口 | 说明 | 查询参数 |
|------|------|----------|
| `GET /api/models` | 模型目录分页列表 | `page`, `page_size`, `provider`, `tag`, `search` |
| `GET /api/models/{model_id}` | 单个模型详情 | 无 |
| `GET /api/timeline` | 按预设或自定义年份返回时间轴数据 | `preset`, `year`, `page`, `page_size`, `sort` |
| `GET /api/stats/providers` | 按提供者统计模型数量 | 无 |
| `GET /health` | 健康检查 | 无 |

## 数据刷新流程
- 使用 cron、GitHub Actions 或其他任务调度器定时运行 `python src/scraper/fetch_models.py`。
- 关注 `sync_log` 表，了解处理/插入数量、运行状态与错误信息。
- 若数据量快速增长，可考虑定期清理或归档历史记录。

## 测试与质量保障
- 将 `TEST_DATABASE_URL` 指向一次性 PostgreSQL 实例后执行 `pytest`。
- 测试会在每次运行后重置 `models`、`sync_log`，保证断言稳定。
- 数据写入后，可手动访问 `/health` 与 `/api/stats/providers` 验证 API 联通。

## 部署建议
- **后端**：使用 `uvicorn main:app --host 0.0.0.0 --port 8000`，并配置 `DATABASE_URL`；若抓取器与后端同环境运行，需要保证能够访问 Hugging Face。
- **前端**：执行 `npm run build` 生成 `frontend/dist/`，再部署到静态站点（如 Vercel、Netlify、Cloudflare Pages）。
- **数据库**：需提供 PostgreSQL，首次部署时运行 `python scripts/init_db.py` 创建表结构。
- **机密管理**：将 token 和 DSN 存入平台机密存储，避免提交 `.env` 文件。

## 已知限制与后续规划
- 时间戳目前以文本存储，迁移到 `TIMESTAMP WITH TIME ZONE` 可提升 SQL 分析能力。
- 部署时请确保静态资源与文档均以 UTF-8 编码输出，避免中文乱码。
- 前端以浏览为主，可考虑增加搜索建议、排序控制或更丰富的模型详情页。
- 若提供者数量庞大，可调整时间轴 `page_size` 等分页参数以保持响应速度。

## 许可协议
MIT 许可证 - 详见 [LICENSE](LICENSE)。
