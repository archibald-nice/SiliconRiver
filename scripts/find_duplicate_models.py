#!/usr/bin/env python
"""扫描 models 表里重复或互为变体的模型记录。

背景
----
库里的数据来自两个源，两侧 `model_id` 命名规则不同：

    Hugging Face:  Qwen/Qwen3-8B            （org 保留原始大小写）
    OpenRouter:    qwen/qwen3-8b            （统一小写）
    OpenRouter:    anthropic/claude-...:batch   （`:batch` 计费枚举）
    OpenRouter:    ~anthropic/claude-...        （`~` 路由别名）

它们**不会主键冲突**（大小写不同），但同一个模型会以两条记录、
两个时间轴节点出现。

这个脚本**只读**，不删任何东西，输出候选分组供人工判断。

用法
----
    .venv/bin/python scripts/find_duplicate_models.py
    .venv/bin/python scripts/find_duplicate_models.py --show 30
    .venv/bin/python scripts/find_duplicate_models.py --min-score 0.9

判据
----
1. **归一化后名称完全相同**：去掉 `provider/` 前缀、`:batch` 之类后缀、
   全部非字母数字字符，再转小写。`Qwen/Qwen3-8B` 与 `qwen/qwen3-8b`
   都会变成 `qwen38b`。这些分组再按结构特征分成三桶：

       A 仅大小写不同        —— 最可能的两源双胞胎
       B 含 `:batch` / `~`   —— OpenRouter 独有的变体命名
       C 其他                —— 需人工判断

2. **名称相似度超过阈值**（difflib，默认 0.95）。
   调低会涌入大量同系列不同尺寸的噪音（`gemma-4-12B` vs `gemma-4-31B`）。

注意：**桶与"跨源"是两个正交维度**。一个组可能同时是"跨源双胞胎"和"含变体"，
例如 `deepseek-ai/DeepSeek-V4.1-Flash`（HF）与
`deepseek/deepseek-v4.1-flash:batch`（OR）同组，会被归到桶 B。
所以别把桶当成来源分类看。

⚠️ 本脚本**刻意不判断**每条记录来自哪个源 —— 做不到可靠：
HF 与 OpenRouter 的 `provider` 可能相同（都是 `google`），
`model_id` 也可能完全相同，在库层面无法区分。
所以只给结构特征，**不要**按脚本输出批量删除。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import psycopg
from dotenv import load_dotenv

load_dotenv(dotenv_path=project_root / ".env")


def normalize(model_id: str) -> str:
    """把 model_id 归一化成可比较的形态。

    去掉 provider/ 前缀、`:batch` 之类后缀、以及所有非字母数字字符，转小写。
    """
    s = model_id.lower()
    if "/" in s:
        s = s.split("/", 1)[1]
    s = s.split(":", 1)[0]
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def classify_group(items: list[tuple]) -> tuple[str, str]:
    """判断一个重复分组属于哪一类，返回 (桶名, 说明)。

    ⚠️ 刻意**不猜测**每条记录来自哪个源。原因是做不到可靠：

      - HF 与 OpenRouter 的 provider 字段可能完全相同（如都是 `google`）；
      - 有些 model_id 也完全相同（如 `google/gemini-4-argon` 与
        它自己的 `:batch` 变体），此时"谁写的"在库层面不可区分；
      - `model_id` 是否全小写也不能作准：HF 侧的 org 本来就可能全小写
        （`deepseek-ai/dspark_qwen3_4b_block7`）。

    所以这里只按**结构特征**分桶，这是能确定的事实：

      A. `仅大小写不同`   —— 同一模型名，一个保留原始大小写、一个全小写。
                            高度符合「HF 保留 org 大小写 vs OpenRouter 统一小写」，
                            但也可能是同一个源自己写了两遍。
      B. `含变体后缀`     —— 组里有 `:batch` / `:free` 这类枚举变体，
                            或 `~` 前缀路由变体。这是 OpenRouter 独有的命名，
                            另一条几乎必然是同源的原始模型。
      C. `其他`           —— 需要人工看。
    """
    ids = [mid for mid, _, _, _ in items]
    has_variant = any((":" in i) or i.startswith("~") for i in ids)
    base = [i.split(":", 1)[0].lstrip("~") for i in ids]
    only_case = len({b.lower() for b in base}) == 1 and len(set(base)) > 1

    if has_variant:
        return "B", "含 `:batch`/`:free` 枚举变体或 `~` 路由变体"
    if only_case:
        return "A", "仅大小写不同"
    return "C", "其他（需人工判断）"



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="扫描跨源重复模型（只读）")
    parser.add_argument("--min-score", type=float, default=0.95,
                        help="名称相似度阈值（默认 0.95；调低会涌入大量"
                             "同系列不同尺寸的噪音，如 gemma-4-12B vs gemma-4-31B）")
    parser.add_argument("--show", type=int, default=20,
                        help="最多显示多少对候选（默认 20）")
    args = parser.parse_args(argv)

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("[错误] 未找到 DATABASE_URL")
        return 1

    try:
        conn = psycopg.connect(db_url, connect_timeout=15)
    except Exception as exc:
        print(f"[失败] 无法连接数据库：{exc}")
        return 1

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT model_id, provider, model_name, created_at FROM models"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    print("=" * 70)
    print("Silicon River · 重复模型扫描（只读）")
    print("=" * 70)
    print(f"扫描 {len(rows)} 条记录，相似度阈值 {args.min_score}")
    print()

    # 1) 归一化名称精确相同的分组
    by_norm: dict[str, list[tuple]] = defaultdict(list)
    for model_id, provider, model_name, created in rows:
        by_norm[normalize(model_id)].append((model_id, provider, model_name, created))

    exact = {k: v for k, v in by_norm.items() if len(v) > 1}

    buckets: dict[str, dict] = {"A": {}, "B": {}, "C": {}}
    for key, items in exact.items():
        bucket, _ = classify_group(items)
        buckets[bucket][key] = items

    print("-" * 70)
    print(f"[1] 归一化名称完全相同的分组：{len(exact)} 组")
    print(f"      A 仅大小写不同        : {len(buckets['A'])} 组")
    print(f"      B 含变体后缀          : {len(buckets['B'])} 组")
    print(f"      C 其他（需人工判断）  : {len(buckets['C'])} 组")

    for bucket in ("A", "B", "C"):
        group = buckets[bucket]
        if not group:
            continue
        _, desc = classify_group(next(iter(group.values())))
        print()
        print(f"  ── 桶 {bucket}：{desc} ──")
        for key, items in list(group.items())[:args.show]:
            dates = sorted({str(c)[:10] for _, _, _, c in items})
            warn = "  ⚠️ created_at 不一致" if len(dates) > 1 else ""
            print(f"\n    归一化键 = {key!r}{warn}")
            for mid, prov, name, created in sorted(items, key=lambda x: str(x[3])):
                print(f"      {mid:50s} ({prov}) {created}")

    # 2) 名称相似但不完全相同的
    print()
    print("-" * 70)
    print("[2] 名称相近但非完全相同（同系列不同尺寸的噪音居多，按需调阈值）")
    norms = sorted(by_norm)
    near = []
    for i, a in enumerate(norms):
        if len(a) < 4:
            continue
        for b in norms[i + 1:]:
            if abs(len(a) - len(b)) > 4:
                continue
            score = SequenceMatcher(None, a, b).ratio()
            if score >= args.min_score:
                near.append((score, a, b))
    near.sort(reverse=True)
    print(f"  命中 {len(near)} 对（阈值 {args.min_score}）")
    for score, a, b in near[:args.show]:
        print(f"\n  相似度 {score:.3f}")
        for key in (a, b):
            for mid, prov, name, created in by_norm[key]:
                print(f"      {mid:50s} ({prov}) {created}")

    print()
    print("-" * 70)
    print("[结论]")
    extra = sum(len(v) - 1 for v in exact.values())
    print(f"  归一化名称完全相同：{len(exact)} 组，多出 {extra} 条冗余记录")
    print(f"    A 仅大小写不同      : {len(buckets['A'])} 组")
    print(f"    B 含变体后缀        : {len(buckets['B'])} 组")
    print(f"    C 其他              : {len(buckets['C'])} 组")
    print(f"  名称近似：{len(near)} 对")
    print()
    print("  ⚠️ 这是只读扫描，不会修改任何数据。")
    print("     本脚本**不判断**每条记录来自哪个源 —— 因为做不到可靠：")
    print("     HF 与 OpenRouter 的 provider 可能相同（都是 google），")
    print("     model_id 也可能完全相同，这在库层面无法区分。")
    print("     分组只依据可确定的结构特征，合并与否必须人工逐对判断。")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
