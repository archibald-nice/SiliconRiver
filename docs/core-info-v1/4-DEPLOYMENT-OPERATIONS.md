# 部署与运维指南 (Deployment & Operations Guide)

**版本**: v1.0 | **最后更新**: 2025-11-10 | **状态**: 生产级指南

---

## 📌 概述 (Overview)

本指南覆盖 Silicon River 从本地开发到生产环境的完整部署流程，以及日常运维工作。

---

## 1️⃣ 环境准备

### 前置条件检查

```bash
# 检查 Python 版本
python --version          # 需要 >= 3.10

# 检查 PostgreSQL
psql --version           # 需要 >= 14

# 检查 Node.js
node --version           # 需要 >= 18
npm --version
```

### 创建虚拟环境

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate

# macOS/Linux:
source .venv/bin/activate

# 验证激活
which python              # 应该显示 .venv 目录下的 python
```

### 安装依赖

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 验证关键包
python -c "import aiohttp, openai, psycopg; print('✓ 所有关键依赖已安装')"

# 安装前端依赖
cd frontend && npm install && cd ..
```

---

## 2️⃣ 数据库配置

### 创建 PostgreSQL 数据库

```bash
# 使用 psql 连接到 PostgreSQL
psql -U postgres

# 在 PostgreSQL 命令行中执行：
CREATE DATABASE silicon_river OWNER postgres;
CREATE DATABASE silicon_river_test OWNER postgres;

# 退出
\q
```

### 初始化数据库模式

```bash
# 创建表和索引
python scripts/init_db.py

# 验证数据库
psql -d silicon_river -c "\dt"     # 列出所有表
psql -d silicon_river -c "\di"     # 列出所有索引
```

---

## 3️⃣ 环境变量配置

### 复制配置模板

```bash
# 复制 .env 模板
cp .env.example .env

# 编辑 .env 填入实际值
# 关键变量：
```

### 必填配置

```env
# ===== 数据库 =====
DATABASE_URL=postgresql://postgres:password@localhost:5432/silicon_river
TEST_DATABASE_URL=postgresql://postgres:password@localhost:5433/silicon_river_test

# ===== LLM API =====
DEEPSEEK_API_KEY=sk-YOUR_KEY_HERE
DEEPSEEK_API_URL=https://api.deepseek.com

# ===== Brave Search API =====
BRAVE_SEARCH_API_KEY=Brv-YOUR_KEY_HERE
ENABLE_BRAVE_SEARCH=true
BRAVE_SEARCH_TIMEOUT=10
BRAVE_SEARCH_MAX_RETRIES=3

# ===== 数据源 =====
HF_TOKEN=hf_YOUR_TOKEN_HERE          # 可选
PROVIDERS=meta-llama,google,microsoft,openai
PROVIDERS_OPENROUTER=openai,anthropic,google

# ===== 前端 =====
VITE_API_BASE=http://localhost:8000
```

### 配置验证

```bash
# 检查 .env 文件完整性
python -c "
import os
from dotenv import load_dotenv

load_dotenv()
required = ['DATABASE_URL', 'DEEPSEEK_API_KEY']
for var in required:
    if not os.getenv(var):
        print(f'❌ 缺失: {var}')
    else:
        print(f'✅ {var}')
"
```

---

## 4️⃣ 本地开发启动

### 启动后端服务

```bash
# 开发模式（自动重载）
uvicorn backend.main:app --reload --port 8000

# 生产模式（使用 gunicorn）
gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.main:app --bind 0.0.0.0:8000
```

### 启动前端开发服务器

```bash
# 在新终端中
cd frontend
npm run dev                 # 启动于 http://localhost:5173
```

### 健康检查

```bash
# 检查后端
curl http://localhost:8000/health

# 检查前端
open http://localhost:5173  # 应该看到 3D 时间轴
```

---

## 5️⃣ 数据加载

### 初始化数据集

```bash
# 从 Hugging Face 抓取模型（全量）
python src/scraper/fetch_models.py

# 从 OpenRouter 抓取模型（全量）
python src/scraper/fetch_models_openrouter.py

# 验证数据
psql -d silicon_river -c "SELECT COUNT(*) FROM models;"
```

### 定期更新

```bash
# 每日增量更新（Hugging Face）
python src/scraper/fetch_models_incr_day.py --limit 200

# 每日增量更新（OpenRouter）
python src/scraper/fetch_models_openrouter_incr_day.py --limit 300

# 更新排行榜缓存
python scripts/update_leaderboards.py
```

---

## 6️⃣ 测试和验证

### 运行测试

```bash
# 设置测试数据库
export TEST_DATABASE_URL=postgresql://postgres:password@localhost:5433/silicon_river_test

# 运行所有测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_brave_search.py -v
pytest tests/test_leaderboard_clients.py -v
pytest tests/test_integration_enhanced_analysis.py -v
```

### 测试覆盖率

```bash
# 生成覆盖率报告
pytest tests/ --cov=src/analysis --cov-report=html

# 查看报告
open htmlcov/index.html
```

### 性能基准测试

```bash
# 测试 10 个模型的分析延迟
python scripts/benchmark_analysis.py --models 10

# 预期结果：平均 < 15 秒
```

---

## 7️⃣ 生产环境部署

### 部署前检查清单

```bash
# 1. 代码质量检查
pytest tests/ -v --cov=src/analysis        # 覆盖率 > 80%

# 2. 配置验证
# 检查 .env 中所有必填变量都已设置
grep "^[A-Z_]*=" .env | wc -l             # 应该 > 20

# 3. 数据库就绪
psql -d silicon_river -c "SELECT COUNT(*) FROM models;"

# 4. 排行榜数据最新
python scripts/update_leaderboards.py

# 5. 日志路径准备
mkdir -p logs
```

### Docker 部署

```dockerfile
# Dockerfile 示例
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install -r requirements.txt

# 复制代码
COPY . .

# 初始化数据库
RUN python scripts/init_db.py

# 启动应用
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "backend.main:app", "--bind", "0.0.0.0:8000"]

EXPOSE 8000
```

```bash
# 构建镜像
docker build -t silicon-river:latest .

# 运行容器
docker run -e DATABASE_URL="postgresql://..." \
           -e DEEPSEEK_API_KEY="sk-..." \
           -e BRAVE_SEARCH_API_KEY="Brv-..." \
           -p 8000:8000 \
           silicon-river:latest
```

### Kubernetes 部署

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: silicon-river
spec:
  replicas: 3
  selector:
    matchLabels:
      app: silicon-river
  template:
    metadata:
      labels:
        app: silicon-river
    spec:
      containers:
      - name: backend
        image: silicon-river:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: silicon-river-secrets
              key: database-url
        - name: DEEPSEEK_API_KEY
          valueFrom:
            secretKeyRef:
              name: silicon-river-secrets
              key: deepseek-api-key
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: silicon-river-service
spec:
  type: LoadBalancer
  selector:
    app: silicon-river
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
```

---

## 8️⃣ 监控和告警

### 日志配置

```python
# logging.yaml 示例
version: 1
disable_existing_loggers: false

formatters:
  standard:
    format: '%(asctime)s [%(levelname)s] %(name)s: %(message)s'

handlers:
  file:
    class: logging.handlers.RotatingFileHandler
    filename: logs/silicon_river.log
    maxBytes: 10485760  # 10MB
    backupCount: 10
    formatter: standard

  console:
    class: logging.StreamHandler
    formatter: standard

root:
  level: INFO
  handlers:
    - console
    - file
```

### 性能告警

```python
# 告警配置
ALERT_RULES = {
    "high_latency": {
        "condition": "p95_latency > 18000",  # ms
        "severity": "warning",
        "action": "notify_slack"
    },
    "low_success_rate": {
        "condition": "api_success_rate < 0.95",
        "severity": "critical",
        "action": "page_oncall"
    },
    "cache_degradation": {
        "condition": "cache_hit_rate < 0.50",
        "severity": "info",
        "action": "log_alert"
    }
}
```

### 健康检查

```bash
# 定期检查端点
curl -s http://localhost:8000/health | jq .

# 预期响应
# {
#   "status": "healthy",
#   "database": "connected",
#   "apis": "operational"
# }
```

---

## 9️⃣ 日常运维任务

### 每日任务

```bash
# 检查日志
tail -100 logs/silicon_river.log | grep ERROR

# 统计分析数量
grep "total_analysis" logs/silicon_river.log | wc -l

# 检查磁盘空间
df -h

# 检查数据库连接
psql -d silicon_river -c "SELECT now();"
```

### 每周任务

```bash
# 生成性能报告
python -c "
from src.analysis.performance_reporter import print_performance_report
print_performance_report()
" > performance_report_$(date +%Y%m%d).txt

# 检查排行榜更新
python scripts/update_leaderboards.py

# 清理日志
find logs -name "*.log.*" -mtime +30 -delete
```

### 每月任务

```bash
# 数据库优化
psql -d silicon_river -c "VACUUM ANALYZE;"

# 生成月度报告
python -c "
from src.analysis.performance_monitor import get_monitor
monitor = get_monitor()
stats = monitor.get_statistics()
total = monitor.get_total_analysis_time_stats()
print(f'本月分析: {total[\"total_analyses\"]}')
print(f'平均延迟: {total[\"average_time_ms\"]} ms')
print(f'SLA 达成: {total[\"meets_sla\"]}')
"

# 备份数据库
pg_dump silicon_river > backup_$(date +%Y%m%d).sql

# 清空性能统计
python -c "from src.analysis.performance_monitor import reset_monitor; reset_monitor()"
```

---

## 🔟 故障恢复

### 问题 1：数据库连接失败

```bash
# 诊断
psql -d silicon_river -c "SELECT 1;"

# 解决
# ① 检查 DATABASE_URL 配置
grep DATABASE_URL .env

# ② 检查 PostgreSQL 是否运行
pg_isready -h localhost -p 5432

# ③ 检查防火墙规则
# ④ 重启 PostgreSQL
sudo systemctl restart postgresql
```

### 问题 2：API 密钥无效

```bash
# 验证 Brave Search 密钥
pytest tests/test_brave_search.py::test_invalid_key -v

# 验证 DeepSeek 密钥
python -c "
from openai import AsyncOpenAI
client = AsyncOpenAI(api_key='YOUR_KEY')
print('✓ 密钥有效')
"
```

### 问题 3：内存占用过高

```bash
# 检查内存使用
ps aux | grep python | grep main

# 解决方案
# ① 减少 MAX_CONCURRENT_ANALYSIS
# ② 清空缓存
# ③ 检查是否有内存泄漏
python -c "
from src.analysis.leaderboard_aggregator import LeaderboardAggregator
agg = LeaderboardAggregator()
agg.clear_cache()
"
```

### 问题 4：性能下降

```bash
# 分析最近的延迟
grep "total_analysis" logs/silicon_river.log | tail -20 | awk '{print $NF}'

# 检查是否有 API 超时
grep "TimeoutError" logs/silicon_river.log | wc -l

# 检查缓存命中率
python -c "
from src.analysis.performance_monitor import get_monitor
stats = get_monitor().get_statistics()
for c, info in stats['cache_statistics'].items():
    print(f'{c}: {info[\"hit_rate\"]}')
"
```

### 回滚步骤

```bash
# 1. 停止应用
systemctl stop silicon-river

# 2. 恢复代码
git checkout <previous-commit>

# 3. 重新安装依赖
pip install -r requirements.txt

# 4. 重启应用
systemctl start silicon-river

# 5. 验证
curl http://localhost:8000/health

# 预计时间：< 5 分钟
```

---

## 🕐 定时任务配置

### Cron 任务示例

```bash
# 编辑 crontab
crontab -e

# 添加以下任务
# 每天凌晨 2 点更新排行榜
0 2 * * * /usr/bin/python /app/scripts/update_leaderboards.py >> /app/logs/cron.log 2>&1

# 每天凌晨 3 点更新 Hugging Face 数据
0 3 * * * /usr/bin/python /app/src/scraper/fetch_models_incr_day.py --limit 200 >> /app/logs/cron.log 2>&1

# 每天凌晨 4 点更新 OpenRouter 数据
0 4 * * * /usr/bin/python /app/src/scraper/fetch_models_openrouter_incr_day.py --limit 300 >> /app/logs/cron.log 2>&1

# 每天凌晨 5 点清理旧日志
0 5 * * * find /app/logs -name "*.log.*" -mtime +30 -delete
```

### Systemd 服务示例

```ini
# /etc/systemd/system/silicon-river.service
[Unit]
Description=Silicon River API Service
After=network.target postgresql.service

[Service]
Type=notify
User=silicon
WorkingDirectory=/app

Environment="PATH=/app/.venv/bin"
ExecStart=/app/.venv/bin/gunicorn \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  backend.main:app \
  --bind 0.0.0.0:8000

Restart=always
RestartSec=10

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
# 启用并启动服务
sudo systemctl enable silicon-river
sudo systemctl start silicon-river

# 检查状态
sudo systemctl status silicon-river

# 查看日志
sudo journalctl -u silicon-river -f
```

---

## 📋 部署检查清单

- [ ] Python 3.10+ 已安装
- [ ] PostgreSQL 14+ 已安装并运行
- [ ] .env 文件已配置（所有必填项）
- [ ] 依赖已安装：`pip install -r requirements.txt`
- [ ] 数据库已初始化：`python scripts/init_db.py`
- [ ] 测试通过：`pytest tests/ -v`
- [ ] 数据已加载：`python src/scraper/fetch_models.py`
- [ ] 排行榜已更新：`python scripts/update_leaderboards.py`
- [ ] 后端可启动：`uvicorn backend.main:app`
- [ ] 前端可启动：`npm run dev`（在 frontend 目录）
- [ ] 健康检查通过：`curl http://localhost:8000/health`
- [ ] 日志目录已创建：`mkdir -p logs`
- [ ] 备份策略已制定
- [ ] 告警规则已配置
- [ ] 定时任务已设置

---

**版本**: 1.0 | **最后更新**: 2025-11-10 | **维护者**: Silicon River 项目团队
