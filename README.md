# Silicon River (硅基长河)

围绕 Hugging Face 模型发布构建的“硅基长河”项目骨架，包含抓取脚本、数据库 Schema、FastAPI 后端与 React 时间轴前端。

## 快速开始
1. 克隆仓库并进入目录：
   ```bash
   git clone <repo>
   cd silicon-river
   ```
2. 创建 Conda 环境并安装 Python 依赖：
   ```bash
   conda create -n silicon-river python=3.11
   conda activate silicon-river
   pip install -r requirements.txt
   ```
3. 初始化数据库：
   ```bash
   python scripts/init_db.py
   ```
4. 复制并填写环境变量：
   ```bash
   cp .env.example .env
   ```
   在 `.env` 中填入 `HF_TOKEN`（Hugging Face 读取令牌）。
5. 拉取并写入模型数据：
   ```bash
   python src/scraper/fetch_models.py
   ```
6. 启动 FastAPI 后端：
   ```bash
   cd backend
   pip install -r requirements.txt
   uvicorn main:app --reload --port 8000
   ```
7. 启动前端（Node.js >= 20）：
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

更多细节请参考 `docs/` 目录内的实施规划、架构、需求与行动指引。
