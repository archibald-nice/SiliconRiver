# 模型重新分析指南

## 概述

**模型重新分析功能**允许你灵活地对已存储的模型进行分析更新。支持三种独立策略，可根据业务需求选择：

1. **强制重新分析** – 覆盖所有模型的分析结果
2. **时间过滤更新** – 更新指定时间之前的旧分析记录
3. **字段补充** – 为缺少特定字段的模型补充数据

此功能与常规爬取流程（`fetch_models.py`）不同：爬取只对新获取的模型分析，而重新分析可以灵活地对历史模型进行批量更新。

---

## 快速开始

### 基本用法

```bash
# 查看帮助
python -m src.scraper.reanalyze_models --help

# 预览待分析模型（无风险）
python -m src.scraper.reanalyze_models --older-than-days 7 --dry-run

# 执行分析（需确认）
python -m src.scraper.reanalyze_models --older-than-days 7
```

### 三种策略详解

#### 策略1：强制重新分析所有模型

```bash
python -m src.scraper.reanalyze_models --force --limit 50
```

**用途**：
- 需要完全刷新所有模型的分析结果
- 更新分析算法后重新处理所有数据
- 测试新增的分析特性

**查询范围**：所有模型，不限时间

**示例**：
```bash
# 强制重新分析openai提供商的所有模型（最多50个）
python -m src.scraper.reanalyze_models --force --provider openai --limit 50

# 强制重新分析所有模型，跳过交互确认
python -m src.scraper.reanalyze_models --force --no-confirm --limit 100
```

---

#### 策略2：时间过滤更新（推荐用于定时任务）

```bash
python -m src.scraper.reanalyze_models --older-than-days 30
```

**用途**：
- 定期更新旧的分析记录（推荐每周或每月运行）
- 基于排行榜API的最新数据重新评估里程碑状态
- 平衡更新频率与资源消耗

**查询范围**：`analyzed_at < NOW() - INTERVAL 'N days'`

**示例**：
```bash
# 每周更新7天前的记录
python -m src.scraper.reanalyze_models --older-than-days 7 --no-confirm

# 仅更新特定提供商，预览结果
python -m src.scraper.reanalyze_models --older-than-days 30 --provider anthropic --dry-run

# 限制处理数量，避免过长运行时间
python -m src.scraper.reanalyze_models --older-than-days 1 --limit 20
```

---

#### 策略3：字段补充

```bash
python -m src.scraper.reanalyze_models --missing-fields is_milestone,milestone_features
```

**用途**：
- 数据库结构升级后补充新字段
- 恢复丢失或错误的分析数据
- 选择性地重新计算特定指标

**查询范围**：指定字段为 `NULL` 或 `FALSE` 的模型

**示例**：
```bash
# 补充缺失的里程碑标记
python -m src.scraper.reanalyze_models --missing-fields is_milestone --no-confirm

# 只补充特定提供商的字段
python -m src.scraper.reanalyze_models --missing-fields milestone_features --provider meta-llama

# 同时补充多个字段
python -m src.scraper.reanalyze_models --missing-fields is_milestone,milestone_features,analysis_summary
```

---

## 命令行选项

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--force` | flag | – | 强制重新分析所有模型（互斥） |
| `--older-than-days N` | int | – | 重新分析N天前的记录（互斥） |
| `--missing-fields FIELDS` | str | – | 重新分析缺少指定字段的模型（互斥） |
| `--provider PROVIDERS` | str | – | 限制特定提供商（逗号分隔，如 `openai,anthropic`） |
| `--limit N` | int | 50 | 本次处理的最大模型数量 |
| `--dry-run` | flag | – | 仅查询待分析模型，不执行分析 |
| `--no-confirm` | flag | – | 跳过交互式确认，用于自动化脚本 |

**重要**：`--force`、`--older-than-days`、`--missing-fields` 三个选项只能选择一个（互斥）。如果都不指定，将使用默认行为（仅分析未分析过的模型）。

---

## 实战示例

### 场景1：第一次使用新功能

```bash
# 第一步：预览结果
python -m src.scraper.reanalyze_models --older-than-days 30 --dry-run

# 第二步：确认无误后执行（会要求确认）
python -m src.scraper.reanalyze_models --older-than-days 30
```

### 场景2：测试环境验证

```bash
# 用小样本测试新的分析算法
python -m src.scraper.reanalyze_models --force --provider openai --limit 5
```

### 场景3：定时任务配置（Cron）

```bash
# 每周一凌晨2点更新7天前的分析记录
0 2 * * 1 cd /path/to/SiliconRiver && python -m src.scraper.reanalyze_models --older-than-days 7 --no-confirm

# 每月5号重新分析所有模型
0 0 5 * * cd /path/to/SiliconRiver && python -m src.scraper.reanalyze_models --force --limit 100 --no-confirm
```

### 场景4：特定提供商分析

```bash
# 更新Meta所有模型的分析
python -m src.scraper.reanalyze_models --older-than-days 14 --provider meta-llama

# 强制重新分析OpenAI的最新10个模型
python -m src.scraper.reanalyze_models --force --provider openai --limit 10
```

### 场景5：批量字段补充

```bash
# 升级数据库结构后，补充新的里程碑字段
python -m src.scraper.reanalyze_models --missing-fields is_milestone,milestone_features --no-confirm
```

---

## 工作原理

### 内部流程

```
1. 参数验证
   ↓
2. 初始化 AnalysisOrchestrator
   ↓
3. 根据策略选择待分析模型
   ├─ --force: SELECT * FROM models WHERE 1=1
   ├─ --older-than-days N: WHERE analyzed_at < NOW() - INTERVAL 'N days'
   └─ --missing-fields: WHERE field IS NULL OR field = FALSE
   ↓
4. 如果 --dry-run: 显示预览并退出
   ↓
5. 交互式确认（可用 --no-confirm 跳过）
   ↓
6. 执行分析：analyze_batch(models, batch_size=10, delay=2.0)
   ├─ 实时网络搜索 (Brave Search API)
   ├─ 排行榜数据验证 (3个排行榜客户端)
   ├─ LLM分析 (DeepSeek)
   └─ 里程碑检测 (4层算法)
   ↓
7. Upsert 到数据库
   ├─ 更新 model_analysis 表
   └─ 更新 model_arena_info 表
   ↓
8. 显示统计结果
```

### Upsert 机制

所有分析结果使用 `ON CONFLICT DO UPDATE` 自动覆盖已有记录：

```sql
INSERT INTO model_analysis (...)
VALUES (...)
ON CONFLICT (model_id) DO UPDATE SET
  analysis_summary = EXCLUDED.analysis_summary,
  is_milestone = EXCLUDED.is_milestone,
  milestone_features = EXCLUDED.milestone_features,
  updated_at = CURRENT_TIMESTAMP;
```

这确保了：
- ✅ 新模型自动插入
- ✅ 旧模型自动更新
- ✅ 不会重复数据
- ✅ 保持 `created_at` 不变，更新 `updated_at`

---

## 性能指标

### 典型运行时间

| 场景 | 模型数 | 耗时 | 备注 |
|------|--------|------|------|
| 字段补充 | 50 | ~10 分钟 | 无网络请求 |
| 时间过滤更新 | 20 | ~4-5 分钟 | 完整分析 + Brave Search |
| 强制重新分析 | 10 | ~2-3 分钟 | 小样本测试 |

**计算**：单个模型分析平均 10-12 秒（含 Brave Search + LLM + 排行榜查询）

### 资源限制

- **单次 --limit**：建议不超过 100（避免 API 配额溢出）
- **并发批大小**：固定 10 个模型/批
- **批间延迟**：2 秒（避免 API 限流）
- **LLM API 配额**：取决于 DeepSeek 账户额度

---

## 常见问题

### Q1：与 `fetch_models.py` 有什么区别？

| 功能 | fetch_models | reanalyze_models |
|------|-------------|-----------------|
| **数据来源** | 实时爬取 HF/OR | 数据库中的已有模型 |
| **分析范围** | 仅新爬虫结果 | 灵活指定（全部/旧的/缺字段） |
| **典型用途** | 增量同步 | 批量更新/补充 |
| **运行频率** | 每天1-2次 | 每周1-2次 |

### Q2：会覆盖原有的分析结果吗？

**是的**。使用 Upsert 机制覆盖所有字段（`updated_at` 时间戳会更新）。

如果需要保留某些字段（如手工修改的备注），可在后续扩展中添加 `PRESERVE_FIELDS` 参数。

### Q3：可以同时指定多个策略吗？

**不可以**。会收到错误提示：

```
❌ --force, --older-than-days, --missing-fields 三个选项只能选择一个
```

### Q4：如何在失败后重试？

直接再运行一遍命令：
- 同一策略的重复运行是**幂等**的
- 策略3（字段补充）会跳过已完成的

### Q5：如何查看分析进度？

分析期间会显示彩色进度，完成后会汇总统计：

```
分析完成！
  ✓ 成功: 45
  ✗ 失败: 2
  ⊘ 跳过: 3

分析统计：
  总模型数: 500
  已分析: 450
  未分析: 50
  分析率: 90.0%
```

---

## 故障排查

### 问题1：分析失败率高

**症状**：大量 `✗ 失败` 输出

**原因**：
- Brave Search API 达到配额限制
- DeepSeek LLM API 超时
- 网络连接不稳定

**解决**：
1. 检查 `.env` 中的 API 密钥有效性
2. 减少 `--limit` 数量，分批处理
3. 增加 `delay_between_batches` 延迟（需代码修改）

### 问题2：交互式确认无响应

**症状**：提示确认但不接受输入

**原因**：非交互式环境（如 CI/CD）

**解决**：添加 `--no-confirm` 标志

### 问题3：特定提供商查询不到

**症状**：`--provider openai --dry-run` 返回 0 个模型

**原因**：
- 数据库中不存在该提供商的模型
- 提供商名称拼写错误
- 所有模型都已经分析过（`--older-than-days` 策略）

**解决**：
```bash
# 查询数据库中的实际提供商名称
python -c "from src.scraper.analysis_orchestrator import AnalysisOrchestrator; \
orch = AnalysisOrchestrator(); \
stats = orch.get_analysis_stats(); \
print(f'总模型数: {stats}')"
```

---

## 集成与自动化

### Docker 集成

在 `docker-compose.yml` 中添加定时任务：

```yaml
reanalyze-job:
  image: silicon-river:latest
  environment:
    DATABASE_URL: ${DATABASE_URL}
    BRAVE_SEARCH_API_KEY: ${BRAVE_SEARCH_API_KEY}
  entrypoint: >
    sh -c "
    python -m src.scraper.reanalyze_models
      --older-than-days 7
      --limit 50
      --no-confirm
    "
  restart: no
```

### Kubernetes CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: silicon-river-reanalyze
spec:
  schedule: "0 2 * * 1"  # 每周一凌晨2点
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: reanalyze
            image: silicon-river:latest
            env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: silicon-river-secrets
                  key: database-url
            command:
            - python
            - -m
            - src.scraper.reanalyze_models
            - --older-than-days
            - "7"
            - --no-confirm
          restartPolicy: OnFailure
```

### GitHub Actions

```yaml
name: Weekly Reanalysis

on:
  schedule:
    - cron: '0 2 * * 1'  # 每周一凌晨2点（UTC）

jobs:
  reanalyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run reanalysis
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          BRAVE_SEARCH_API_KEY: ${{ secrets.BRAVE_SEARCH_API_KEY }}
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
        run: |
          python -m src.scraper.reanalyze_models \
            --older-than-days 7 \
            --no-confirm \
            --limit 50
```

---

## 最佳实践

### 1. 分阶段采用

```bash
# 第一阶段：测试小样本
python -m src.scraper.reanalyze_models --force --provider openai --limit 5 --dry-run

# 第二阶段：扩大范围
python -m src.scraper.reanalyze_models --older-than-days 30 --limit 20

# 第三阶段：生产自动化
# 添加到 crontab 或 k8s CronJob
```

### 2. 监控和告警

记录分析统计信息：

```python
# 在 CI/CD 中收集指标
result = orchestrator.integration.analyze_batch(models)
if result['failed'] > 0.1 * len(models):  # 失败率超过10%
    send_alert("High reanalysis failure rate")
```

### 3. 备份策略

重要更新前进行备份：

```bash
# 备份数据库
pg_dump $DATABASE_URL > backup_$(date +%s).sql

# 执行重新分析
python -m src.scraper.reanalyze_models --older-than-days 30

# 如需回滚
psql $DATABASE_URL < backup_xxx.sql
```

### 4. 成本优化

```bash
# 方案A：每日轻量更新
0 2 * * * python -m src.scraper.reanalyze_models --older-than-days 1 --limit 10

# 方案B：每周全量更新
0 2 * * 0 python -m src.scraper.reanalyze_models --older-than-days 7 --limit 50

# 方案C：按需强制更新
# 手动执行（不加入自动化）
```

---

## 相关命令速查表

```bash
# ========== 预览命令 ==========
# 查看所有待分析模型
python -m src.scraper.reanalyze_models --dry-run

# 查看30天前的记录
python -m src.scraper.reanalyze_models --older-than-days 30 --dry-run

# 查看缺少里程碑标记的模型
python -m src.scraper.reanalyze_models --missing-fields is_milestone --dry-run


# ========== 执行命令 ==========
# 定期更新（推荐）
python -m src.scraper.reanalyze_models --older-than-days 7

# 强制重新分析（谨慎）
python -m src.scraper.reanalyze_models --force --limit 50

# 补充新字段
python -m src.scraper.reanalyze_models --missing-fields is_milestone,milestone_features


# ========== 高级用法 ==========
# 特定提供商 + 自动化
python -m src.scraper.reanalyze_models --older-than-days 14 --provider meta-llama --no-confirm

# 限制数量 + 预览
python -m src.scraper.reanalyze_models --force --limit 5 --dry-run

# 完整流水线
python -m src.scraper.reanalyze_models --older-than-days 30 --limit 100 --no-confirm
```

---

## 进阶话题

### 扩展功能建议

1. **选择性保留字段**
   ```bash
   --preserve-fields manual_notes,custom_tags
   ```

2. **并行处理**
   ```bash
   --parallel-workers 4  # 同时处理4个模型
   ```

3. **分布式处理**
   ```bash
   --worker-id 1 --total-workers 4  # 分布式部署
   ```

4. **详细日志**
   ```bash
   --log-level DEBUG --log-file reanalyze.log
   ```

这些功能可在后续版本中添加。

---

## 参考资源

- [分析编排器文档](./2-MILESTONE-DETECTION-RULES.md) – 了解分析算法细节
- [性能监控指南](./3-PERFORMANCE-MONITORING.md) – 监控分析性能
- [快速参考卡](./5-QUICK-REFERENCE-CARD.md) – 命令速查表
- [API集成指南](./1-API-INTEGRATION-GUIDE.md) – 配置 Brave Search 和排行榜 API

