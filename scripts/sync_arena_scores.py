#!/usr/bin/env python
"""把 LMArena / SWE-bench 的真实评分同步进 ``model_arena_info``。

为什么需要这个脚本
------------------
``model_arena_info`` 此前没有任何自动数据源：落库是空壳 TODO、零调用方，
消费端（``backend/main.py`` 的 ``_fetch_arena_summary``）静默显示为空。
更糟的是旧客户端在上游失败时回落写死的假排名（**ISSUE-001 事故**）。
本脚本只写真实抓取结果，抓不到就报错退出，绝不伪造。

数据流
------
    LMArena HF datasets ─┐
                         ├─> matcher（别名 > 归一化全等 > 尺寸守卫子集）
    SWE-bench 内嵌 JSON ─┘        │
                                  v
                    model_arena_info (UPSERT)

用法
----
    # 只看不写：打印将写入的行、命中率、未命中样例（只对 models 表做 SELECT）
    .venv/bin/python scripts/sync_arena_scores.py --source all --dry-run

    # 真写库（⚠️ 直连 DATABASE_URL，线上库就是生产写入）
    .venv/bin/python scripts/sync_arena_scores.py --source all

    # 只同步一个源 / 抽样
    .venv/bin/python scripts/sync_arena_scores.py --source swebench --limit 20

写库语义
--------
``INSERT ... ON CONFLICT (model_id, source, category) DO UPDATE``，
用 ``RETURNING (xmax = 0)`` 区分插入/更新（仓库铁律 6：``rowcount`` 在
``DO UPDATE`` 下恒为 1，会把更新误计成新增）。

source 取值：``lmarena`` / ``swebench``。category 对 LMArena 是它的 29 个
category（可另加 ``overall`` 汇总？不——上游本身就有 ``overall``），
对 SWE-bench 是 ``verified`` / ``lite``。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import psycopg

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.scraper.arena.lmarena import ArenaRow, fetch_latest_rows  # noqa: E402
from src.scraper.arena.matcher import load_aliases, match_arena_rows  # noqa: E402
from src.scraper.arena.swebench import fetch_swebench_rows  # noqa: E402

try:  # .env 里是线上库连接串；本地跑脚本时自动加载，CI 里没有这个文件也能跑。
    from dotenv import load_dotenv

    _ENV_PATH = BASE_DIR / ".env"
    if _ENV_PATH.exists():
        load_dotenv(dotenv_path=_ENV_PATH, override=False)
except ImportError:  # pragma: no cover - dotenv 是 requirements 里的依赖
    pass

LOGGER_NAME = "silicon_river.arena.sync"
LOGGER = logging.getLogger(LOGGER_NAME)

UPSERT_SQL = """
INSERT INTO model_arena_info (model_id, source, rank, score, category, updated_at)
VALUES (%s, %s, %s, %s, %s, NOW())
ON CONFLICT (model_id, source, category)
DO UPDATE SET
    rank = EXCLUDED.rank,
    score = EXCLUDED.score,
    updated_at = NOW()
"""

SUPPORTED_SOURCES = ("lmarena", "swebench")

# 一次性 executemany 三万条会把连接打挂（实测 ``SSL error: bad length`` + 连接丢失），
# 按块提交：300 条一块实测 0.5-1.4 秒/块，稳。
WRITE_CHUNK_SIZE = 300


@dataclass(frozen=True, slots=True)
class PendingRow:
    """一条待写入 ``model_arena_info`` 的记录。"""

    model_id: str
    source: str
    rank: int | None
    score: float | None
    category: str

    def as_tuple(self) -> tuple[Any, ...]:
        return (self.model_id, self.source, self.rank, self.score, self.category)


@dataclass
class SourceReport:
    """一个数据源的抓取/匹配统计，dry-run 和真写都打印它。"""

    source: str
    fetched_rows: int = 0
    categories: int = 0
    matched_rows: int = 0
    unmatched_rows: int = 0
    pending: list[PendingRow] = None  # type: ignore[assignment]
    unmatched_names: list[str] = None  # type: ignore[assignment]
    alias_count: int = 0
    inserted: int = 0
    updated: int = 0

    def __post_init__(self) -> None:
        if self.pending is None:
            self.pending = []
        if self.unmatched_names is None:
            self.unmatched_names = []

    @property
    def hit_rate(self) -> float:
        if not self.fetched_rows:
            return 0.0
        return self.matched_rows / self.fetched_rows


def build_pending_rows(
    source: str,
    matches: Iterable[Any],
) -> list[PendingRow]:
    """把匹配结果摊平成待写入行，按 (model_id, category) 去重取最高名次。

    同一 category 里一个 model_id 可能被两条排行榜行命中（别名 + 归一化），
    也可能因为同分并列出现两条；写入时只保留 rank 最小（最好）的那条，
    否则 UPSERT 的最终结果取决于执行顺序，不确定。
    """
    best: dict[tuple[str, str], PendingRow] = {}
    for match in matches:
        row = match.row
        key = (match.model_id, row.category)
        candidate = PendingRow(
            model_id=match.model_id,
            source=source,
            rank=row.rank,
            score=row.score,
            category=row.category,
        )
        previous = best.get(key)
        if previous is None:
            best[key] = candidate
            continue
        # rank 为 None 视为最差；同 rank 保留分数高的。
        previous_rank = previous.rank if previous.rank is not None else 10**9
        candidate_rank = candidate.rank if candidate.rank is not None else 10**9
        if candidate_rank < previous_rank or (
            candidate_rank == previous_rank
            and (candidate.score or float("-inf")) > (previous.score or float("-inf"))
        ):
            best[key] = candidate
    return sorted(best.values(), key=lambda item: (item.source, item.category, item.model_id))


def fetch_source_rows(
    source: str, limit: int | None, workers: int | None = None
) -> list[ArenaRow]:
    if source == "lmarena":
        if workers is None:
            return fetch_latest_rows(limit=limit)
        return fetch_latest_rows(limit=limit, workers=workers)
    if source == "swebench":
        return fetch_swebench_rows(limit=limit)
    raise ValueError(f"不支持的数据源：{source}")


def load_model_ids(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT model_id FROM models")
        return [row[0] for row in cursor.fetchall()]


def collect_source(
    source: str,
    limit: int | None,
    candidates: Sequence[str],
    alias_path: str | None,
    workers: int | None = None,
) -> SourceReport:
    # 按源读取别名：``shared`` + 该源的专属小节，避免 lmarena 的别名串到 swebench。
    aliases = load_aliases(alias_path, source)
    rows = fetch_source_rows(source, limit, workers)
    matched, unmatched = match_arena_rows(rows, candidates, aliases)
    report = SourceReport(source=source, alias_count=len(aliases))
    report.fetched_rows = len(rows)
    report.categories = len({row.category for row in rows})
    report.matched_rows = len({id(match.row) for match in matched})
    report.unmatched_rows = len(unmatched)
    report.pending = build_pending_rows(source, matched)
    report.unmatched_names = sorted({row.model_name for row in unmatched})
    return report


def write_rows(conn: psycopg.Connection, pending: Sequence[PendingRow]) -> tuple[int, int]:
    """批量写 ``model_arena_info``，返回 (新增, 更新)。

    逐行 ``execute`` 在 Supabase 上是灾难：单条 UPSERT 一次跨洋往返 ≈ 0.42 秒
    （2026-10-18 实测 20 条 8.47 秒），三万多条要跑 4 小时，还会在中间撞上
    ``statement timeout``。改成 ``executemany``（psycopg3 内部走 pipeline，一次
    round-trip 发一批），新增/更新数靠写入前查一次已有 key 集合来判断
    ——``executemany`` 拿不到逐行 ``RETURNING (xmax = 0)``。
    """
    if not pending:
        return 0, 0

    sources = sorted({row.source for row in pending})
    keys = [(row.model_id, row.source, row.category) for row in pending]
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT model_id, source, category FROM model_arena_info WHERE source = ANY(%s)",
            (sources,),
        )
        existing = {(r[0], r[1], r[2]) for r in cursor.fetchall()}
        for start in range(0, len(pending), WRITE_CHUNK_SIZE):
            chunk = pending[start : start + WRITE_CHUNK_SIZE]
            cursor.executemany(UPSERT_SQL, [row.as_tuple() for row in chunk])
            LOGGER.info(
                "写入进度 %d/%d（%.1f%%）", start + len(chunk), len(pending),
                100.0 * (start + len(chunk)) / len(pending),
            )
    conn.commit()
    inserted = sum(1 for key in keys if key not in existing)
    return inserted, len(keys) - inserted


def print_report(report: SourceReport, *, dry_run: bool, sample_size: int) -> None:
    print(f"\n=== {report.source} ===")
    print(f"拉到行数      : {report.fetched_rows}")
    print(f"category 数   : {report.categories}")
    print(f"别名条数      : {report.alias_count}")
    print(f"命中行数      : {report.matched_rows}")
    print(f"未命中行数    : {report.unmatched_rows}")
    print(f"命中率        : {report.hit_rate:.1%}")
    print(f"待写入记录数  : {len(report.pending)}（按 model_id+category 去重后）")
    if not dry_run:
        print(f"插入 / 更新   : {report.inserted} / {report.updated}")

    if dry_run and report.pending:
        print("将写入的行（前 10 条）:")
        for row in report.pending[:10]:
            print(
                f"  [dry-run] {row.model_id}  source={row.source} "
                f"category={row.category} rank={row.rank} score={row.score}"
            )

    if report.unmatched_names:
        print(f"未命中样例（前 {min(sample_size, len(report.unmatched_names))} 个）:")
        for name in report.unmatched_names[:sample_size]:
            print(f"  - {name}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从 LMArena / SWE-bench 同步真实评分到 model_arena_info"
    )
    parser.add_argument(
        "--source",
        choices=(*SUPPORTED_SOURCES, "all"),
        default="all",
        help="数据源（默认 all）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只抓取/匹配/打印，不写库"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="每个源最多取多少行（调试用；截断后的排名不是完整快照）",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL"),
        help="数据库连接串；默认读 DATABASE_URL（项目 .env 里是线上库，慎用）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=f"LMArena 并发翻页数（默认 {8}；遇到 HTTP 429 就调小）",
    )
    parser.add_argument(
        "--aliases",
        default=None,
        help="别名 YAML 路径；默认 data/arena_aliases.yaml",
    )
    parser.add_argument(
        "--unmatched-sample",
        type=int,
        default=20,
        help="每个源打印多少条未命中样例（默认 20）",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    # 同步一次要几分钟，写入进度必须看得见（默认 root logger 是 WARNING，
    # 不配的话 INFO 全被丢掉，跑起来像卡死）。
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.limit is not None and args.limit <= 0:
        print("[错误] --limit 必须是正整数", file=sys.stderr)
        return 2
    if not args.db_url:
        print(
            "[错误] 没有数据库连接串：传 --db-url 或设置 DATABASE_URL"
            "（读取现有 model_id 列表需要只读连接）",
            file=sys.stderr,
        )
        return 2

    sources = (
        list(SUPPORTED_SOURCES) if args.source == "all" else [args.source]
    )

    reports: list[SourceReport] = []
    try:
        with psycopg.connect(args.db_url, prepare_threshold=None) as conn:
            if args.dry_run:
                # 双保险：dry-run 连接设为只读，即使代码写错也写不进去。
                conn.read_only = True
            candidates = load_model_ids(conn)
            print(f"库内 model 数: {len(candidates)}")
            if not candidates:
                print("[错误] models 表为空：先跑 fetch_models.py，再同步评分", file=sys.stderr)
                return 1

            for source in sources:
                report = collect_source(
                    source, args.limit, candidates, args.aliases, args.workers
                )
                reports.append(report)
                if not args.dry_run:
                    report.inserted, report.updated = write_rows(conn, report.pending)

        for report in reports:
            print_report(
                report, dry_run=args.dry_run, sample_size=args.unmatched_sample
            )
    except Exception as exc:  # noqa: BLE001 - 顶层必须非 0 退出，不能静默失败
        print(f"[失败] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n[dry-run] 未写库。")
    else:
        total_inserted = sum(report.inserted for report in reports)
        total_updated = sum(report.updated for report in reports)
        print(f"\n[完成] 插入 {total_inserted} 条，更新 {total_updated} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
