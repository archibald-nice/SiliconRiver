#!/usr/bin/env python
"""清理 ``models`` 表里的大小写重复行（ISSUE-004）。

背景
----
同一个模型会在两个数据源里以两种大小写出现：HF 保留 org 原样
（``Qwen/Qwen3.6-27B``），OpenRouter 一律小写（``qwen/qwen3.6-27b``）。
生产库 1707 行实测有 29 组 / 60 行属于「仅大小写/写法差异」，
时间轴上它们就是两个节点。

抓取侧已经在写库时归一到先入库的那一行（``fetch_models.resolve_case_variant``），
本脚本负责**一次性清理历史遗留**：每组只保留一行，其余删除。

保留哪一行（确定性规则，按顺序）
--------------------------------
1. 有 AI 分析记录的（``model_analysis`` 有行）——分析没有 FK，删行不会带走它，
   但留在待删行上就成了孤儿；
2. ``inserted_at`` 最早的（先入库的那行，通常来自 HF，保留 org 原始大小写）；
3. 信息量更大的（描述 / 价格 / 标签数）——兜底，正常走不到。

**不**按「信息量」优先，是为了不改动 provider 归属：先入库的 HF 行带的是 org 原名
（``meta-llama``），OpenRouter 行带展示名（``meta``）。留哪一行都会让少数行的
provider 变掉，凡是能不选就不选——命名统一是 ISSUE-005 的事，这里只去重。
保留行缺的字段（描述 / 价格 / 下载量）会从待删行补过来，不丢数据。

删除前先**合并**：
- ``model_tags`` / ``model_arena_info`` 有 FK 级联，先把保留行缺的行复制过去；
- ``model_analysis`` **没有** FK（历史遗留），如果不处理就会变成孤儿行：保留行没有
  分析时把待删行的分析改成保留行的 model_id；两边都有分析时保留行胜出，
  待删行的重复分析会被删掉（同一模型分析过两次，内容等价）。

默认只打印、不删；``--apply`` 时先把「将删除的 model_id 清单 + 各组保留行 +
被丢弃的分析」写成 CSV 备份。

用法::

    # 只看（默认）
    .venv/bin/python scripts/dedupe_models.py

    # 真删（⚠️ 直连 DATABASE_URL，线上库即生产写入）
    .venv/bin/python scripts/dedupe_models.py --apply
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:  # 本地跑时自动加载 .env；CI 里没有这个文件也不影响 --help
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except Exception:  # pragma: no cover
    pass

DEFAULT_DB_URL = os.getenv("DATABASE_URL", "")


def _keeper_score(row: dict[str, Any]) -> tuple:
    """保留优先级：有分析 > 入库早 > 信息多（用于 max() 取最优行）。"""
    return (
        1 if row["analyzed"] else 0,
        # 越大越早：用负的时间戳参与 max()，让最早入库的行胜出
        -(row["inserted_at"].timestamp() if row["inserted_at"] else 0),
        1 if row["description"] else 0,
        1 if row["price"] else 0,
        row["tag_count"],
        row["model_id"],
    )


def fetch_candidates(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        # price 是 jsonb，`jsonb::text` 里空值会写成 'null' / '{}'，一并算作「没有价格」。
        cur.execute(
            """
            SELECT m.model_id,
                   m.provider,
                   COALESCE(m.description, '') <> '' AS has_desc,
                   (SELECT count(*) FROM model_tags t WHERE t.model_id = m.model_id) AS tag_count,
                   EXISTS (SELECT 1 FROM model_analysis a WHERE a.model_id = m.model_id) AS analyzed,
                   COALESCE(m.price::text, 'null') NOT IN ('null', '{}', '[]') AS has_price,
                   m.inserted_at
            FROM models m
            ORDER BY lower(m.model_id), m.model_id
            """
        )
        rows = cur.fetchall()
        price_map = {r["model_id"]: r["has_price"] for r in rows}
    out = []
    for r in rows:
        out.append(
            {
                "model_id": r["model_id"],
                "provider": r["provider"],
                "description": r["has_desc"],
                "price": price_map.get(r["model_id"], False),
                "tag_count": r["tag_count"],
                "analyzed": r["analyzed"],
                "inserted_at": r["inserted_at"],
            }
        )
    return out


def group_case_variants(rows: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """按 lower(model_id) 分组，只返回成员数 > 1 的组。"""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[row["model_id"].lower()].append(row)
    return [members for members in buckets.values() if len(members) > 1]


def plan(groups: Sequence[Sequence[dict[str, Any]]]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """返回 [(保留行, [待删除行...]), ...]。"""
    plan_rows = []
    for members in groups:
        keeper = max(members, key=_keeper_score)
        doomed = [m for m in members if m["model_id"] != keeper["model_id"]]
        plan_rows.append((keeper, doomed))
    return plan_rows


def print_plan(plan_rows, *, limit: int = 20) -> None:
    total_doomed = sum(len(doomed) for _, doomed in plan_rows)
    print(f"大小写重复组: {len(plan_rows)}；待删除行: {total_doomed}")
    for keeper, doomed in plan_rows[:limit]:
        print(f"  保留 {keeper['model_id']:<48} provider={keeper['provider']}"
              f"{' (有分析)' if keeper['analyzed'] else ''}")
        for row in doomed:
            print(f"    删 {row['model_id']:<48} provider={row['provider']}"
                  f"{' (有分析!)' if row['analyzed'] else ''}")
    if len(plan_rows) > limit:
        print(f"  …… 其余 {len(plan_rows) - limit} 组未显示")


def backup(plan_rows, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"dedupe_models_{stamp}.csv"
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["action", "model_id", "provider", "analyzed", "tag_count"])
        for keeper, doomed in plan_rows:
            writer.writerow(["keep", keeper["model_id"], keeper["provider"], keeper["analyzed"], keeper["tag_count"]])
            for row in doomed:
                writer.writerow(["delete", row["model_id"], row["provider"], row["analyzed"], row["tag_count"]])
    return path


def _merge_dependents(cur, keeper_id: str, doomed_id: str) -> dict[str, int]:
    """把待删行的字段与从属数据合并到保留行，返回各类计数。"""
    stats = {"tags": 0, "arena": 0, "analysis_moved": 0, "analysis_dropped": 0}

    # 主表字段：保留行缺什么就补什么，已有的不覆盖（保留行是「先入库」的那份）
    cur.execute(
        """
        UPDATE models AS k
        SET description = COALESCE(k.description, d.description),
            price = COALESCE(k.price, d.price),
            downloads = COALESCE(k.downloads, d.downloads),
            likes = COALESCE(k.likes, d.likes),
            is_open_source = COALESCE(k.is_open_source, d.is_open_source),
            model_card_url = CASE
                WHEN k.model_card_url IS NULL OR k.model_card_url = '' THEN d.model_card_url
                ELSE k.model_card_url
            END
        FROM models AS d
        WHERE k.model_id = %s AND d.model_id = %s
        """,
        (keeper_id, doomed_id),
    )

    # 标签：先复制保留行缺的（UNIQUE(model_id, tag) 兜底），删行时 FK 级联清掉旧的
    cur.execute(
        """
        INSERT INTO model_tags (model_id, tag, inserted_at)
        SELECT %s, tag, inserted_at FROM model_tags WHERE model_id = %s
        ON CONFLICT (model_id, tag) DO NOTHING
        """,
        (keeper_id, doomed_id),
    )
    stats["tags"] = cur.rowcount

    # 评分：同 UNIQUE(model_id, source, category)
    cur.execute(
        """
        INSERT INTO model_arena_info (model_id, source, rank, score, category, updated_at, created_at)
        SELECT %s, source, rank, score, category, updated_at, created_at
        FROM model_arena_info WHERE model_id = %s
        ON CONFLICT (model_id, source, category) DO NOTHING
        """,
        (keeper_id, doomed_id),
    )
    stats["arena"] = cur.rowcount

    # 分析没有 FK：保留行没有分析就迁过去，否则删掉重复分析（避免孤儿行）
    cur.execute("SELECT 1 FROM model_analysis WHERE model_id = %s", (keeper_id,))
    keeper_has_analysis = cur.fetchone() is not None
    if keeper_has_analysis:
        cur.execute("DELETE FROM model_analysis WHERE model_id = %s", (doomed_id,))
        stats["analysis_dropped"] = cur.rowcount
    else:
        cur.execute(
            "UPDATE model_analysis SET model_id = %s WHERE model_id = %s",
            (keeper_id, doomed_id),
        )
        stats["analysis_moved"] = cur.rowcount
    return stats


def apply_plan(conn: psycopg.Connection, plan_rows) -> dict[str, int]:
    """先合并从属数据，再删重复行。返回汇总计数（便于 --apply 后核对）。"""
    doomed = [(keeper["model_id"], row["model_id"]) for keeper, rows in plan_rows for row in rows]
    if not doomed:
        return {"deleted": 0, "tags": 0, "arena": 0, "analysis_moved": 0, "analysis_dropped": 0}

    totals = {"deleted": 0, "tags": 0, "arena": 0, "analysis_moved": 0, "analysis_dropped": 0}
    with conn.cursor() as cur:
        for keeper_id, doomed_id in doomed:
            for key, value in _merge_dependents(cur, keeper_id, doomed_id).items():
                totals[key] += value
        cur.execute(
            "DELETE FROM models WHERE model_id = ANY(%s)",
            ([doomed_id for _, doomed_id in doomed],),
        )
        totals["deleted"] = cur.rowcount
    conn.commit()
    return totals


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="清理 models 表的大小写重复行（ISSUE-004）")
    parser.add_argument("--apply", action="store_true", help="真的删除（默认只打印计划）")
    parser.add_argument("--db-url", default=None, help="数据库连接串，默认 DATABASE_URL")
    parser.add_argument("--limit", type=int, default=20, help="打印多少组样例")
    parser.add_argument(
        "--backup-dir",
        default="/tmp/sr_dedupe_backup",
        help="--apply 前的清单备份目录",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    db_url = args.db_url or DEFAULT_DB_URL
    if not db_url:
        print("缺少数据库连接串：设置 DATABASE_URL 或传 --db-url", file=sys.stderr)
        return 2

    with psycopg.connect(db_url, connect_timeout=20) as conn:
        if not args.apply:
            conn.read_only = True
        rows = fetch_candidates(conn)
        groups = group_case_variants(rows)
        plan_rows = plan(groups)
        print(f"库内模型数: {len(rows)}")
        print_plan(plan_rows, limit=args.limit)

        if plan_rows:
            losers_with_analysis = [
                row for _, doomed in plan_rows for row in doomed if row["analyzed"]
            ]
            if losers_with_analysis:
                print(
                    f"注：{len(losers_with_analysis)} 个待删除行也带 AI 分析记录；"
                    "保留行已有分析时，这些重复分析会在 --apply 时丢弃（同一模型分析两次）",
                    file=sys.stderr,
                )

        if not args.apply:
            print("DRY-RUN：未修改任何数据（确认后加 --apply）")
            return 0

        if not plan_rows:
            print("没有需要清理的重复行")
            return 0

        path = backup(plan_rows, Path(args.backup_dir))
        print(f"备份清单: {path}")
        totals = apply_plan(conn, plan_rows)
        print(
            "已删除 {deleted} 行；迁移标签 {tags}、评分 {arena}、分析 {analysis_moved}，"
            "丢弃重复分析 {analysis_dropped}".format(**totals)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
