# Silicon River (硅河流)

> 融合 Hugging Face 模型生态的开放数据管道与展示应用。

Silicon River 将模型抓取、数据归档、API 服务和 React 可视化整合为一套轻量级工具链，帮助团队快速搭建模型情报面板。

## 项目简介
- 通过 `src/scraper/fetch_models.py` 从 Hugging Face 抓取指定 Provider 的模型元数据，并存入 SQLite。
- 提供 FastAPI (`backend/main.py`) REST 接口，支持分页、筛选、模糊搜索及 Provider 统计。
- 使用 React + Vite + Tailwind 构建的前端 (`frontend/`)，展示模型列表、时间轴等可视化。
- 内置 pytest 用例覆盖抓取逻辑与数据库入库流程。

## 技术栈
- **后端**：FastAPI、Pydantic、SQLite、python-dotenv。
- **数据采集**：Hugging Face Hub SDK、tqdm、sqlite-utils。
- **前端**：React 18、Vite、React Query、Tailwind CSS、Headless UI。
- **测试 & 开发工具**：Pytest、TypeScript、ESBuild/Vite。

## 目录导览
```text
SiliconRiver/
|- backend/              FastAPI 应用与依赖
|  |- main.py
|  |- requirements.txt
|- src/
|  |- scraper/
|     |- fetch_models.py Hugging Face 抓取脚本
|- scripts/
|  |- init_db.py         初始化 SQLite 架构
|- frontend/             React + Tailwind 可视化界面
|- tests/                Pytest 覆盖抓取管道
|- requirements.txt      后端/脚本通用依赖
|- .env.example          环境变量范例
```

## 环境要求
- Python >= 3.11
- Node.js >= 20
- npm 或 pnpm
- Hugging Face API Token（用于提升抓取额度）

## 快速开始
1. 克隆仓库并进入目录：
   ```bash
   git clone <repo-url>
   cd SiliconRiver
   ```
2. 准备 Python 虚拟环境并安装依赖：
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   # source .venv/bin/activate # macOS/Linux
   pip install -r requirements.txt
   ```
   后端附加依赖位于 `backend/requirements.txt`，建议同步安装：
   ```bash
   pip install -r backend/requirements.txt
   ```
3. 复制环境变量模板并填写：
   ```bash
   cp .env.example .env
   cp backend/.env.example backend/.env
   cp frontend/.env.example frontend/.env
   ```
   - `HF_TOKEN`：Hugging Face 个人访问令牌。
   - `PROVIDERS`：需要采集的发布者（逗号分隔）。
   - `VITE_API_BASE`：前端访问的后端地址（默认 `http://localhost:8000`）。
4. 初始化数据库结构：
   ```bash
   python scripts/init_db.py
   ```
5. 抓取最新模型数据（可重复执行以刷新数据；可通过 `PROVIDERS` 与命令行参数控制 `limit`）：
   ```bash
   python src/scraper/fetch_models.py
   ```
6. 启动 FastAPI 服务：
   ```bash
   cd backend
   uvicorn main:app --reload --port 8000
   ```
7. 启动前端界面（另起终端）：
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   前端默认在 `http://localhost:5173/`，会通过 `VITE_API_BASE` 访问后端 API。

## API 速查
- `GET /api/models`：分页获取模型列表，支持 `page`、`page_size`、`provider`、`tag`、`search` 查询参数。
- `GET /api/models/{model_id}`：返回单个模型详情。
- `GET /api/stats/providers`：统计各 Provider 模型数量。
- `GET /health`：服务健康检查。

## 测试
使用 pytest 校验抓取与入库逻辑：
```bash
pytest
```
测试覆盖了去重逻辑、日志记录以及 `PROVIDERS` 解析等关键路径。

## 数据刷新与部署提示
- 定时刷新：可在 CI / 定时任务中运行 `python src/scraper/fetch_models.py`，保持数据最新。
- 外部数据库：若需将数据写入其他存储，请调整 `.env` 内的 `DATABASE_URL`，目前默认实现仅支持 `sqlite:///` 路径。
- 生产部署：建议为 FastAPI 使用 `uvicorn` + `--host 0.0.0.0` 或搭配反向代理；前端可 `npm run build` 后部署静态资源。

## 许可证
本项目基于 [MIT License](LICENSE) 开源。
