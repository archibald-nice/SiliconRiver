# 里程碑检测规则 (Milestone Detection Rules)

**版本**: v1.0 | **最后更新**: 2025-11-10 | **文档大小**: 核心规则参考手册

---

## 📌 概述 (Overview)

里程碑模型是指在 AI 发展历史中产生重要影响的模型，标志着技术的突破或范式转变。

**Silicon River 使用 4 层级联策略** 确保高准确率的里程碑检测：

| 策略 | 检测方式 | 命中率 | 优点 |
|------|---------|--------|------|
| 策略 1️⃣ | 强关键词（单个即可） | 10-15% | 最准确 |
| 策略 2️⃣ | 弱关键词（2+ 个） | 20-30% | 高精度 |
| 策略 3️⃣ | 时间轴排名 (≤20) | 40-50% | 历史验证 |
| 策略 4️⃣ | 排行榜排名 (权威) | 15-25% | 多维验证 |

---

## 策略 1️⃣：强关键词匹配 (Strong Keywords)

### 原理

LLM 在分析中明确提到突破性关键词，表示该模型具有重大意义。

### 关键词列表（10 个）

| 关键词 | 中文 | 示例 |
|--------|------|------|
| `breakthrough` | 突破 | "GPT-4 represents a breakthrough in..." |
| `milestone` | 里程碑 | "This is a milestone in AI..." |
| `first` | 首个 | "The first model to achieve..." |
| `revolutionary` | 革命性 | "Revolutionary architecture..." |
| `pioneering` | 开创性 | "Pioneering approach to..." |
| `paradigm-shift` | 范式转变 | "Paradigm shift in..." |
| `landmark` | 标志性 | "Landmark achievement..." |
| `turning-point` | 转折点 | "A turning point in..." |
| `leap` | 飞跃 | "A major leap forward..." |
| `breakthrough-moment` | 突破口 | "Breakthrough moment..." |

### 匹配逻辑

```python
def _has_strong_keywords(analysis_text: str) -> bool:
    STRONG_KEYWORDS = [
        "breakthrough", "milestone", "first", "revolutionary",
        "pioneering", "paradigm-shift", "landmark", "turning-point",
        "leap", "breakthrough-moment"
    ]

    # 任意一个关键词出现即为匹配
    for keyword in STRONG_KEYWORDS:
        if keyword.lower() in analysis_text.lower():
            return True

    return False
```

### 判定示例

| 模型 | 分析文本 | 关键词 | 判定 | 理由 |
|------|---------|--------|------|------|
| GPT-4 | "...represents a **breakthrough** in multimodal..." | breakthrough | ✅ 里程碑 | 包含强关键词 |
| BERT | "...a **landmark** in NLP...is a **milestone**..." | landmark, milestone | ✅ 里程碑 | 包含强关键词 |
| Llama-7B | "相比较有改进..." | （无） | ❌ 继续策略2 | 无强关键词 |

---

## 策略 2️⃣：弱关键词匹配 (Weak Keywords)

### 原理

LLM 使用温和表述重要模型，需要多个弱关键词共现才能判定。这捕捉那些虽然没有明确说"突破"但明显重要的模型。

### 关键词列表（13 个）

| 分类 | 关键词 | 中文 |
|------|--------|------|
| **创新** | create, novel, innovate, development | 创建、新颖、创新、发展 |
| **改进** | improve, enhance, optimize, refine | 改进、增强、优化、改善 |
| **首次** | first, inaugural, initial, new-generation | 首次、首批、初始、新一代 |
| **性能** | significant, substantial, considerable | 显著、大幅、可观 |

### 匹配逻辑

```python
def _count_weak_keywords(analysis_text: str) -> int:
    WEAK_KEYWORDS = [
        "create", "novel", "innovate", "development",
        "improve", "enhance", "optimize", "refine",
        "first", "inaugural", "initial", "new-generation",
        "significant", "substantial", "considerable"
    ]

    # 计数匹配个数
    count = 0
    for keyword in WEAK_KEYWORDS:
        if keyword.lower() in analysis_text.lower():
            count += 1

    return count

def _has_weak_keywords_match(analysis_text: str) -> bool:
    # 需要 2 个或以上弱关键词
    return _count_weak_keywords(analysis_text) >= 2
```

### 判定示例

| 模型 | 分析文本 | 匹配关键词 | 计数 | 判定 |
|------|---------|-----------|------|------|
| Llama-2-70B | "相比之前有**创新**的架构设计，**显著**提升了性能" | novel, significant | 2 | ✅ 里程碑 |
| Claude-3 | "相比 2.5 有**优化**，**增强**了能力" | optimize, enhance | 2 | ✅ 里程碑 |
| LoRA-Model | "在特定领域**改进**了性能" | improve | 1 | ❌ 继续策略3 |

---

## 策略 3️⃣：时间轴排名 (Timeline Ranking)

### 原理

数据库中的 `rank` 字段记录了模型在发布时间轴上的排名。前 20 名代表了 AI 发展的关键节点。

### 判定条件

```sql
-- 数据库查询
SELECT * FROM models
WHERE rank <= 20
ORDER BY rank ASC;
```

```python
# 代码逻辑
if model.rank is not None and model.rank <= 20:
    is_milestone = True
    reason = f"Model timeline rank: #{model.rank} (top 20)"
```

### 排名分布

```
rank <= 10:   核心里程碑（最早发布的突破性模型）
  ├─ GPT-2      (#5)
  ├─ BERT        (#8)
  ├─ GPT-3       (#3)
  └─ ...

rank 11-20:   重要历史节点（参考级别）
  ├─ RoBERTa     (#12)
  ├─ ELECTRA     (#15)
  └─ ...

rank > 20:    普通模型（非里程碑）
```

### 判定示例

| 模型 | Rank | 判定 | 理由 |
|------|------|------|------|
| GPT-3 | 3 | ✅ 里程碑 | 前 20 名，重要历史节点 |
| BERT | 8 | ✅ 里程碑 | 前 10 名，核心突破 |
| Llama-2 | 45 | ❌ 继续策略4 | rank > 20，需要其他验证 |

---

## 策略 4️⃣：多排行榜排名 (Leaderboard Rankings)

### 原理

4 个权威排行榜从不同维度评估模型。如果模型在任何排行榜中排名达到阈值，说明其在该维度为顶尖水平，也视为里程碑。

### 排行榜及阈值

| 排行榜 | 维度 | 阈值 | 理由 |
|--------|------|------|------|
| **SWE-bench** | 代码生成 | rank ≤ 10 | 编程能力前 10 代表突破 |
| **LMSYS Arena** | 对话能力 | rank ≤ 20 | 对话质量前 20 代表优秀 |
| **HF Leaderboard** | 综合开源 | rank ≤ 15 | 开源 Top 15 代表卓越 |
| **OpenCompass** | 综合评估 | rank ≤ 10 | 综合排行前 10 代表顶尖 |

### 匹配逻辑

```python
def _check_leaderboard_milestone(rank_info: dict) -> tuple[bool, str]:
    """检查是否满足排行榜里程碑条件"""

    source = rank_info.get("source", "").lower()
    rank = rank_info.get("rank")
    score = rank_info.get("score")
    category = rank_info.get("category", "")

    # SWE-bench 前 10
    if "swe-bench" in source and rank and rank <= 10:
        return True, f"SWE-bench rank #{rank} - Code generation breakthrough"

    # LMSYS Arena 前 20
    if "lmsys" in source and rank and rank <= 20:
        return True, f"LMSYS Arena rank #{rank} - Top conversation model"

    # HF Leaderboard 前 15
    if "huggingface" in source and rank and rank <= 15:
        return True, f"HF Open LLM rank #{rank} - Top open-source"

    # OpenCompass 前 10
    if "opencompass" in source and rank and rank <= 10:
        return True, f"OpenCompass rank #{rank} - Top comprehensive"

    return False, None
```

### 判定示例

| 模型 | SWE-bench | LMSYS | HF | OpenCompass | 判定 |
|------|-----------|-------|----|----|------|
| GPT-4 | rank #1 | rank #1 | - | rank #1 | ✅ 里程碑 |
| Claude-3-Opus | rank #2 | rank #2 | - | rank #3 | ✅ 里程碑 |
| Llama-2-70B | - | rank #25 | rank #1 | - | ✅ 里程碑 |
| 微调模型 | - | - | - | - | ❌ 非里程碑 |

---

## 🎯 完整判定流程

### 流程图

```
输入: 模型分析结果 + 排行榜数据
  │
  ▼
┌─────────────────────────────┐
│ 策略 1: 强关键词匹配?       │
└──────────┬──────────────────┘
           │ 匹配 ──→ ✅ 里程碑
           │ 不匹配 ↓
           ▼
┌─────────────────────────────┐
│ 策略 2: 弱关键词 ≥ 2 个?    │
└──────────┬──────────────────┘
           │ 匹配 ──→ ✅ 里程碑
           │ 不匹配 ↓
           ▼
┌─────────────────────────────┐
│ 策略 3: 时间轴 rank ≤ 20?   │
└──────────┬──────────────────┘
           │ 匹配 ──→ ✅ 里程碑
           │ 不匹配 ↓
           ▼
┌─────────────────────────────┐
│ 策略 4: 排行榜达到阈值?     │
└──────────┬──────────────────┘
           │ 匹配 ──→ ✅ 里程碑
           │ 不匹配 ↓
           ▼
         ❌ 非里程碑
```

### 6 个完整示例

#### 示例 1: GPT-4（所有策略匹配）

```
模型: GPT-4

策略 1 检查:
└─ 分析包含: "breakthrough" + "milestone" + "revolutionary"
└─ 结果: ✅ 匹配

里程碑理由: "具有突破性的多模态能力，标志着 AI 能力的重大进步"
```

#### 示例 2: BERT（强关键词）

```
模型: BERT

策略 1 检查:
└─ 分析包含: "landmark" in "landmark NLP breakthrough"
└─ 结果: ✅ 匹配

里程碑理由: "开创性的 Transformer 预训练方法"
```

#### 示例 3: Llama-2-70B（弱关键词）

```
模型: Llama-2-70B

策略 1: ❌ 无强关键词
策略 2:
└─ "novel architecture" (novel)
└─ "significant improvements" (significant)
└─ 计数: 2 ✅ 匹配

里程碑理由: "开源社区的重要模型，性能改进明显"
```

#### 示例 4: GPT-3（时间轴）

```
模型: GPT-3 (rank = 3)

策略 1: ❌ 通用分析，无强关键词
策略 2: ❌ 仅 1 个弱关键词
策略 3:
└─ rank = 3 ≤ 20 ✅ 匹配

里程碑理由: "模型发展时间线中排名前 20 的关键模型"
```

#### 示例 5: Claude-3-Opus（排行榜）

```
模型: Claude-3-Opus

策略 1-3: ❌ 都不匹配
策略 4:
└─ LMSYS Arena rank #2 ≤ 20 ✅ 匹配

里程碑理由: "LMSYS Chatbot Arena 排名第 2 的顶尖对话模型"
```

#### 示例 6: 普通微调模型（无）

```
模型: LoRA-Tuned-Base

策略 1: ❌ 无强关键词
策略 2: ❌ < 2 个弱关键词
策略 3: ❌ rank = 1000 > 20
策略 4: ❌ 无排行榜排名

判定: ❌ 非里程碑
理由: "不满足任何里程碑条件"
```

---

## ⚙️ 配置与调优

### 修改关键词列表

编辑 `src/analysis/async_analyzer.py`:

```python
# 强关键词列表
STRONG_MILESTONE_KEYWORDS = [
    "breakthrough", "milestone", "first", "revolutionary",
    "pioneering", "paradigm-shift", "landmark", "turning-point",
    "leap", "breakthrough-moment",
    # 添加自定义关键词
    "historic", "groundbreaking",
]

# 弱关键词列表
WEAK_MILESTONE_KEYWORDS = [
    "create", "novel", "innovate", "development",
    "improve", "enhance", "optimize", "refine",
    "first", "inaugural", "initial", "new-generation",
    "significant", "substantial", "considerable",
    # 添加自定义关键词
    "advance", "evolution",
]
```

### 调整排名阈值

```python
# 在 _detect_milestone() 中修改

# 时间轴阈值（默认 20，可改为 10/15/25）
TIMELINE_RANK_THRESHOLD = 20

# 排行榜阈值（可逐个调整）
LEADERBOARD_THRESHOLDS = {
    "swe-bench": 10,        # 编程能力前 10
    "lmsys_arena": 20,      # 对话能力前 20
    "hf_leaderboard": 15,   # 开源综合前 15
    "opencompass": 10,      # 综合评估前 10
}

# 严格模式示例（高精度）
STRICT_THRESHOLDS = {
    "swe-bench": 5,
    "lmsys_arena": 10,
    "hf_leaderboard": 8,
    "opencompass": 5,
}

# 宽松模式示例（高召回）
LOOSE_THRESHOLDS = {
    "swe-bench": 20,
    "lmsys_arena": 50,
    "hf_leaderboard": 30,
    "opencompass": 20,
}
```

---

## 📊 数据质量保证

### 月度验证清单

```python
verification_checklist = {
    "已知里程碑模型被正确标记": [
        "GPT-2 → ✅ 里程碑",
        "BERT → ✅ 里程碑",
        "GPT-3 → ✅ 里程碑",
        "GPT-4 → ✅ 里程碑",
    ],
    "历史性早期模型被标记": [
        "ELMo (2018) → ✅",
        "ALBERT (2019) → ✅",
    ],
    "非里程碑模型不被误标": [
        "LoRA 微调版 → ❌ 非里程碑",
        "低排名开源 → ❌ 非里程碑",
    ],
    "排行榜数据同步": [
        "所有 4 个排行榜已更新",
        "缓存统计正常",
    ],
}
```

### 人工审查流程

```
1. 每月抽样检查 50 个标记为里程碑的模型
2. 验证理由是否充分（关键词/排名是否真实）
3. 若发现错误，调整关键词或阈值
4. 记录调整日志和原因
5. 更新配置文件
```

---

## 🔍 监控和日志

### 查看里程碑检测统计

```bash
# 统计里程碑率
grep "is_milestone: True" logs/silicon_river.log | wc -l
grep "is_milestone" logs/silicon_river.log | wc -l

# 统计各策略命中分布
grep "策略 1" logs/silicon_river.log | wc -l
grep "策略 2" logs/silicon_river.log | wc -l
grep "策略 3" logs/silicon_river.log | wc -l
grep "策略 4" logs/silicon_river.log | wc -l
```

### 预期分布

```
总里程碑数: 50-150 (占全部 2000+ 模型的 2-5%)

各策略命中率:
├── 策略 1 (强关键词): 10-15%
├── 策略 2 (弱关键词): 20-30%
├── 策略 3 (时间轴): 40-50%
└── 策略 4 (排行榜): 15-25%

总和 > 100% (因为有重叠)
```

---

## ❓ 常见问题

**Q: 为什么某个明显很重要的模型没被标记为里程碑？**

A: 可能的原因：
1. LLM 分析文本中缺少关键词
2. 排行榜中排名太低
3. 时间轴排名太靠后

解决方案：
- 检查 LLM 分析质量
- 确认排行榜数据是否最新
- 考虑降低阈值

**Q: 如何调整阈值来改变里程碑率？**

A:
- **要求更严格** → 降低阈值（rank ≤ 5）
- **要求更宽松** → 提高阈值（rank ≤ 30）
- **改变关键词** → 添加或移除关键词

**Q: 里程碑率应该多少才合适？**

A: 通常 2-5% 比较合理（100-300 个里程碑 / 5000+ 总模型）

---

**版本**: 1.0 | **最后更新**: 2025-11-10 | **维护者**: Silicon River 项目团队
