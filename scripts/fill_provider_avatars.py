#!/usr/bin/env python
"""把厂商 logo 下载成 `providers.avatar_blob`（一次性 / 可重复执行的填充脚本）。

背景
----
后端运行期是纯只读的：`/api/providers/{id}/avatar` 先读 `avatar_blob`，只有 blob
为空才回源，而回源又受 `backend/main.py:71` 的 AVATAR_ALLOWED_HOSTS 白名单限制。
所以"给 43 家缺头像的厂商补图"只能发生在抓取侧：本脚本按
`data/provider_logos.yaml` 的优先级把图抓下来、落成 blob，之后 API 和前端零改动。

用法
----
    # 先看会写谁、从哪个源、多少字节（不写库）
    .venv/bin/python scripts/fill_provider_avatars.py --dry-run

    # 只补指定的几家
    .venv/bin/python scripts/fill_provider_avatars.py --only openai,qwen,typesafe

    # 真的写库（默认跳过已有 avatar_blob 的行）
    .venv/bin/python scripts/fill_provider_avatars.py

    # 重抓（例如映射表里换了更好的源）
    .venv/bin/python scripts/fill_provider_avatars.py --force --only openai

⚠️ 不传 `--db-url` 时读 `DATABASE_URL`，也就是项目 `.env` 里那条**线上库**连接串；
跑之前确认自己在数据管线机器上。
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# `python scripts/xxx.py` 直接运行时 sys.path 只有 scripts/，仓库里其它脚本
# （check_supabase.py / update_arena_scores.py）都是这样把项目根塞进来的。
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import psycopg
from dotenv import load_dotenv

from src.scraper.fetch_models import upsert_provider
from src.scraper.provider_logos import (
    DEFAULT_MAP_PATH,
    ProviderLogoSpec,
    build_session,
    load_logo_map,
    pick_best_logo,
    resolve_logo_sources,
)

ENV_PATH = project_root / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)


@dataclass
class FillSummary:
    """一次填充的结果。`failures` 保留原因，供最后逐行打印。"""

    filled: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按 data/provider_logos.yaml 补齐 providers.avatar_blob"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析并打印将要写入的内容，不写库（仍会读库确认谁缺头像）",
    )
    parser.add_argument(
        "--only",
        default="",
        help="逗号分隔的 provider_id 白名单，例如 openai,qwen",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="连已有 avatar_blob 的也重抓（默认跳过，避免每天重复下载）",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="覆盖 DATABASE_URL；默认读环境变量（项目 .env 里是线上库，慎用）",
    )
    parser.add_argument(
        "--map",
        default=str(DEFAULT_MAP_PATH),
        help=f"映射表路径（默认 {DEFAULT_MAP_PATH}）",
    )
    return parser.parse_args(argv)


def _load_provider_rows(
    conn: psycopg.Connection, only: set[str] | None
) -> list[tuple[str, str | None, bool]]:
    """读出 `(provider_id, display_name, 是否缺头像)`，按 provider_id 排序。"""
    with conn.cursor() as cursor:
        # avatar_blob IS NULL 直接在库里判断，别在 Python 里拉 54 个 blob 再比。
        cursor.execute(
            """
            SELECT provider_id, display_name, (avatar_blob IS NULL) AS missing_avatar
            FROM providers
            ORDER BY 1
            """
        )
        rows = cursor.fetchall()
    if only is not None:
        rows = [row for row in rows if row[0] in only]
    return list(rows)


def _source_url(spec: ProviderLogoSpec, source_label: str) -> str:
    """把命中标签还原成实际 URL，写进 `providers.avatar_url` 便于事后追溯。"""
    for candidate in resolve_logo_sources(spec):
        if candidate.source == source_label:
            return candidate.url
    return ""


def fill_provider_avatars(
    conn: psycopg.Connection,
    specs: dict[str, ProviderLogoSpec],
    *,
    session,
    dry_run: bool = False,
    force: bool = False,
    only: set[str] | None = None,
) -> FillSummary:
    """主流程：读库 → 挑源下载 → 写库（dry_run 时只打印）。

    抽成独立函数（而不是全写在 `main` 里）是为了让测试可以注入假连接/假会话，
    在完全不碰真库、真网络的前提下验证"dry-run 不写库"这条关键约束。
    """
    summary = FillSummary()
    rows = _load_provider_rows(conn, only)

    if only is not None:
        unseen = sorted(only - {row[0] for row in rows})
        if unseen:
            print(f"[警告] 库里没有这些 provider_id：{', '.join(unseen)}", file=sys.stderr)

    for provider_id, db_display_name, missing in rows:
        spec = specs.get(provider_id)
        if spec is None:
            print(f"[跳过] {provider_id}：映射表里没有这一行（data/provider_logos.yaml）")
            summary.skipped += 1
            continue
        if not spec.enabled:
            print(f"[跳过] {provider_id}：映射表标记 enabled=false（{spec.note or '明确不下载'}）")
            summary.skipped += 1
            continue
        if not missing and not force:
            print(f"[跳过] {provider_id}：已有 avatar_blob（要重抓加 --force）")
            summary.skipped += 1
            continue

        trace: list[str] = []
        picked = pick_best_logo(spec, session=session, trace=trace)
        if picked is None:
            reason = "；".join(trace) or "所有候选均未命中"
            print(f"[失败] {provider_id}：{reason}")
            summary.failed += 1
            summary.failures.append((provider_id, reason))
            continue

        blob, mime, source_label = picked
        # 库里已有的显示名不要在补图时被清空：映射表里 display_name 是可选的。
        display_name = spec.display_name or db_display_name or provider_id
        avatar_url = _source_url(spec, source_label)

        if dry_run:
            print(
                f"[dry-run] {provider_id} <- {source_label} "
                f"{len(blob)} 字节 {mime} {avatar_url}"
            )
            # dry-run 的 filled 表示"本来会写入多少家"，方便和真实运行的输出对比。
            summary.filled += 1
            continue

        # 参数顺序是 upsert_provider(conn, provider_id, avatar_url, display_name,
        # avatar_content, avatar_mime)——avatar_url 在 display_name 之前。
        upsert_provider(conn, provider_id, avatar_url, display_name, blob, mime)
        # 逐条提交：中途网络挂掉时，已经补好的厂商不必重跑。
        conn.commit()
        print(
            f"[写入] {provider_id} <- {source_label} "
            f"{len(blob)} 字节 {mime} {avatar_url}"
        )
        summary.filled += 1

    return summary


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    db_url = args.db_url or os.getenv("DATABASE_URL")
    if not db_url:
        print(
            "[错误] 没有数据库连接串：传 --db-url 或设置 DATABASE_URL。",
            file=sys.stderr,
        )
        return 2

    try:
        specs = load_logo_map(Path(args.map))
    except (FileNotFoundError, ValueError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    only = {item.strip() for item in args.only.split(",") if item.strip()} or None
    if only is not None:
        unknown = sorted(only - set(specs))
        if unknown:
            print(
                f"[警告] --only 里的 provider 不在映射表中：{', '.join(unknown)}",
                file=sys.stderr,
            )

    session = build_session()
    try:
        with psycopg.connect(db_url) as conn:
            summary = fill_provider_avatars(
                conn,
                specs,
                session=session,
                dry_run=args.dry_run,
                force=args.force,
                only=only,
            )
    finally:
        session.close()

    if args.dry_run:
        print(
            f"filled={summary.filled} skipped={summary.skipped} "
            f"failed={summary.failed}（dry-run，未写库）"
        )
    else:
        print(
            f"filled={summary.filled} skipped={summary.skipped} failed={summary.failed}"
        )

    if summary.failures:
        print("失败明细：")
        for provider_id, reason in summary.failures:
            print(f"  - {provider_id}: {reason}")

    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
