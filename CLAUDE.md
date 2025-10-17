# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此仓库工作时提供指导。

## 项目概述

Silicon River 是一个交互式 3D 时间轴可视化系统，用于展示大语言模型的发布时间线。它从 Hugging Face 和 OpenRouter 爬取模型元数据，存储到 PostgreSQL，并通过 Three.js 驱动的螺旋时间轴界面呈现。

## 架构

```text
                 ┌────────────────────┐
  Hugging Face   │  Data Scrapers     │
  OpenRouter ──▶ │  (Python, Sync Log)│
                 └─────────┬──────────┘
                           │
                     PostgreSQL
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
 FastAPI REST API                    React + Three.js Frontend
```

### 技术栈

- **后端**: FastAPI（Pydantic 验证）、Psycopg 3（PostgreSQL 驱动）
- **前端**: React 18 + TypeScript、Vite 构建系统、Three.js（3D 渲染）
- **样式**: Tailwind CSS + 无样式 UI 组件库
- **状态管理**: React Query（服务端状态）、React Hooks（本地状态）
- **数据管道**: Python CLI 工具（Click 框架）、Hugging Face Hub 集成

## 开发命令

### 快速启动

```bash
# 后端设置
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py                    # 初始化数据库模式
uvicorn backend.main:app --reload --port 8000

# 前端设置（在新终端中）
cd frontend
npm install
npm run dev                                  # 运行于 http://localhost:5173
```

### 后端命令

```bash
# 核心 API 开发
uvicorn backend.main:app --reload --port 8000

# 使用测试数据库运行测试
set TEST_DATABASE_URL=postgresql://user:pass@localhost:5433/silicon_river_test  # Windows
pytest                                       # 运行所有测试
pytest tests/test_fetch_models.py::test_name  # 运行特定测试

# 数据爬取
python src/scraper/fetch_models.py           # Hugging Face 完整同步
python src/scraper/fetch_models_incr_day.py --limit 200  # Hugging Face 增量同步
python src/scraper/fetch_models_openrouter.py           # OpenRouter 完整同步
python src/scraper/fetch_models_openrouter_incr_day.py --limit 300  # OpenRouter 增量同步
```

### 前端命令

```bash
cd frontend
npm run dev                                  # 启动开发服务器 :5173
npm run build                               # TypeScript 检查 + Vite 构建
npm run preview                             # 本地预览生产构建
```

## 核心 API 端点

**时间轴数据** (`/api/timeline`)

- 查询参数: `preset` (30d|6m|1y|all)、`year`、`provider`、`model_name`、`open_source` (bool)、`page`、`page_size` (10-500)、`sort` (asc|desc)
- 返回有序时间轴窗口及分页元数据

**模型目录** (`/api/models`)

- 查询参数: `page`、`page_size`、`provider`、`tag`、`search`
- 返回分页模型列表（无时间轴排序）

**提供商统计** (`/api/stats/providers`)

- 按提供商分组返回模型计数

**提供商头像** (`/api/providers/{provider_id}/avatar`)

- 从 PostgreSQL 提供缓存头像，并回退到上游 URL
- 实现 HTTP 缓存头和 524KB 大小限制

**健康检查** (`/health`)

- 供负载均衡器使用的最小化端点

## 高层架构

### 前端组件层次

```text
App (Timeline3D.tsx)
├── TimelineFilters （过滤芯片、搜索输入）
├── Timeline3D （Three.js 场景渲染）
│   └── 使用 timeline/modes/ 进行可视化算法
└── ModelCard （显示焦点模型元数据）
```

### 时间轴渲染管道

1. **数据加载** (`api/client.ts`): 基于 Axios 的 HTTP 客户端获取 `/api/timeline` 并应用过滤
2. **数据集处理** (`timeline/core/dataset.ts`): 将 API 响应转换为 Three.js 就绪格式
3. **模式初始化** (`timeline/modes/`): 可插拔布局系统实现 `ITimelineMode` 接口
   - **ClassicMode** （螺旋布局）: 主要可视化模式，沿 3D Catmull-Rom 曲线定位模型
4. **场景渲染**: Three.js WebGL 渲染器显示 3D 节点，相机跟随焦点
5. **交互** (`Timeline3D.tsx`): 鼠标滚轮/点击事件触发模式的导航逻辑

### 后端请求管道

1. **请求验证** (FastAPI 路由): Pydantic 验证查询参数
2. **时间轴窗口计算** (`_calculate_timeline_window()`): 根据 `preset` 或 `year` 确定日期范围
3. **数据库查询** (Psycopg 3 游标): 应用 SQL 过滤，模型与提供商 JOIN 获取头像
4. **响应序列化**: Pydantic 模型将数据库行转换为类型化 JSON

## 环境配置

从 `.env.example` 创建 `.env`:

| 变量 | 用途 | 示例 |
|------|------|------|
| `DATABASE_URL` | 爬虫和 API 共享的 PostgreSQL | `postgresql://user:pass@localhost:5432/silicon_river` |
| `HF_TOKEN` | Hugging Face API 认证（可选） | Token 字符串 |
| `PROVIDERS` | 逗号分隔的 HF 组织机构待爬取 | `meta-llama,google,microsoft,openai` |
| `PROVIDERS_OPENROUTER` | OpenRouter 提供商待包含 | `openai,anthropic,google` |
| `VITE_API_BASE` | 前端 API 目标（默认 localhost:8000） | `http://localhost:8000` |
| `TEST_DATABASE_URL` | 用于测试隔离的独立 PostgreSQL | `postgresql://user:pass@localhost:5433/silicon_river_test` |
| `AVATAR_MAX_BYTES` | 提供商头像大小限制（默认 524KB） | `524288` |
| `AVATAR_CACHE_TTL` | 浏览器缓存时长（秒）（默认 1 天） | `86400` |

## 数据库模式

**models** 表:

- `model_id` (主键): 来自源的唯一标识符
- `provider`: 组织机构名称
- `model_name`、`description`、`tags`: 可搜索的元数据
- `created_at`: 发布时间戳（UTC）
- `is_open_source`、`price`: 许可证和成本信息
- `opencompass_rank`、`huggingface_rank`: 排名指标
- 在 `created_at`、`provider`、`model_name` 上建立索引以提高查询性能

**providers** 表:

- `provider_id` (主键): 提供商名称
- `avatar_url`: 上游头像源 URL
- `avatar_blob`、`avatar_mime`: 缓存的二进制 + MIME 类型
- 回退: 若 blob 为空，API 从上游 URL 获取

**sync_log** 表:

- `run_id`、`scraper_type`、`start_time`、`end_time`、`status`
- 数据爬取的审计跟踪及时长记录

## 时间轴模式系统

时间轴可视化通过 `ITimelineMode` 接口（`frontend/src/timeline/modes/ITimelineMode.ts`）进行扩展:

```typescript
interface ITimelineMode {
  init(config, dataset): Promise<void>        // 初始化 3D 场景
  layoutNodes(nodes): void                    // 在 3D 空间中定位节点
  handleWheelEvent(direction, index): number  // 导航输入
  handleNodeClick(mesh): number|null          // 点击交互
  setFocus(index, callback): void             // 动画相机到节点
  update(deltaTime): void                     // 逐帧渲染更新
  dispose(): void                             // 清理资源
  getScene/getCamera/getRenderer(): ...       // Three.js 访问器
}
```

**ClassicMode** 实现（`classic-mode.ts`）:

- 从排序的模型时间戳创建 Catmull-Rom 曲线
- 沿曲线参数化均匀分布模型
- 相机沿曲线运动，焦点间平滑缓动
- 支持鼠标滚轮和直接点击导航

## 关键实现细节

### 头像缓存策略

- 第一次获取后在 PostgreSQL 中缓存 Blob
- 后续请求使用 HTTP `Cache-Control` 头从缓存提供
- 大小验证（<=524KB）回退到上游 URL
- 通过 HTTPX 异步获取，6 秒超时并跟随重定向

### 过滤管道

- 过滤器是累加的: `time_range AND provider AND text_search AND open_source`
- `preset="all"` 绕过时间过滤；特定 `year` 覆盖 preset
- 搜索对 model_name 和 description 字段应用 ILIKE
- 结果按时间顺序排序（默认 ASC）以保证时间轴一致性

### 性能优化

- 数据库查询使用参数化语句（Psycopg 3 防止 SQL 注入）
- 分页（默认 200 项）减小大型结果集的有效负载大小
- Three.js 使用视锥剔除；屏幕外节点不渲染
- React Query 缓存 API 响应以最小化过滤变更时的重新获取
- 前端在初始渲染后在后台延迟加载提供商头像

## 测试策略

使用隔离的测试数据库运行测试:

```bash
set TEST_DATABASE_URL=postgresql://user:pass@localhost:5433/silicon_river_test
pytest                                       # 自动配置/清理模式
```

测试覆盖:

- 爬虫数据转换（HF/OpenRouter 格式解析）
- API 端点验证（时间轴过滤、头像服务）
- 数据库模式完整性（索引、约束）
- PostgreSQL 不可用时测试正常跳过

## 常见任务

**添加新的时间轴过滤器:**

1. 在 [`backend/main.py`](backend/main.py) 中的 `timeline_models()` 端点添加查询参数
2. 使用新条件扩展 WHERE 子句过滤列表
3. 在 [`frontend/src/components/TimelineFilters.tsx`](frontend/src/components/TimelineFilters.tsx) 中添加 UI 过滤芯片
4. 通过 `useQuery()` 依赖数组将过滤器传递给 React Query

**支持新的数据源:**

1. 在 [`src/scraper/`](src/scraper/) 中创建爬虫脚本，按照 HF/OpenRouter 模式
2. 如果需要新字段，在 [`scripts/init_db.py`](scripts/init_db.py) 中扩展数据库模式
3. 更新 `PROVIDERS` 或 `PROVIDERS_OPENROUTER` 环境变量
4. 添加 sync_log 条目用于审计跟踪

**实现新的时间轴可视化模式:**

1. 创建实现 `ITimelineMode` 接口的新类
2. 在模式工厂中注册（如果继承行为可扩展 ClassicMode）
3. 连接到 Timeline3D 组件模式切换器
4. 使用 `timeline/core/dataset.ts` 测试数据进行测试

## 代码模式注记

- **Pydantic 模型**: FastAPI 中处理请求/响应验证；重用以确保类型安全
- **依赖注入**: 通过 FastAPI `Depends()` 干净地管理数据库连接
- **TypeScript 严格模式**: 在 `frontend/tsconfig.json` 中强制执行；所有模型类型在 [`api/client.ts`](frontend/src/api/client.ts) 中定义
- **曲线数学**: ClassicMode 中使用参数化定位（沿 Catmull-Rom 的 0.0-1.0）实现平滑分布
- **UTC 时间戳**: 整个后端使用，确保跨时区的一致过滤
