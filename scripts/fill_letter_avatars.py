"""给没有品牌图的厂商补字母占位头像（ISSUE-017 的收尾选项 B）。

`data/provider_logos.yaml` 里标了 `enabled: false` 的厂商（LobeHub 上是真人头像、
或三个来源都查不到品牌图）不写数据库，前端 `<img>` 失败后会退化成纯文字，
在时间轴和弹窗里看着像"漏图"。这里用厂商名首字母生成一枚 SVG 占位图，
直接写进 `providers.avatar_blob`——与 `/api/providers/{id}/avatar` 的缓存语义一致，
写入后接口不会再回源上游。

设计取舍：
- 生成 SVG 而不是 PNG：无第三方依赖（不引入 Pillow），体积约 300 字节；
- 底色由 provider_id 哈希决定，保证同一厂商每次生成的颜色稳定；
- 只处理显式 --only 指定的厂商，或 --missing 时处理"既没有头像也没有品牌图来源"的厂商，
  避免误覆盖已有真实头像。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from typing import Iterable

import psycopg
from dotenv import load_dotenv

SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">'
    '<rect width="128" height="128" rx="28" fill="{background}"/>'
    '<text x="64" y="64" text-anchor="middle" dominant-baseline="central" '
    'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" '
    'font-size="{font_size}" font-weight="600" fill="#ffffff">{letter}</text>'
    "</svg>"
)

# 色相按 provider_id 散列，饱和度与明度固定，保证深色页面上白字可读。
PALETTE = (
    ("#475569", 54),  # slate-600
    ("#7c3aed", 54),  # violet-600
    ("#0e7490", 54),  # cyan-700
    ("#b45309", 54),  # amber-700
    ("#be123c", 54),  # rose-700
    ("#15803d", 54),  # green-700
    ("#1d4ed8", 54),  # blue-700
    ("#a21caf", 54),  # fuchsia-700
)


def letter_for(display_name: str | None, provider_id: str) -> str:
    """取厂商名首字母；中文名取第一个非空白字符。"""
    source = (display_name or "").strip() or provider_id
    for char in source:
        if char.isalnum() or "\u4e00" <= char <= "\u9fff":
            return char.upper()
    return provider_id[:1].upper() or "?"


def background_for(provider_id: str) -> str:
    digest = hashlib.sha256(provider_id.encode("utf-8")).digest()
    color, _ = PALETTE[digest[0] % len(PALETTE)]
    return color


def build_letter_avatar_svg(display_name: str | None, provider_id: str) -> str:
    letter = letter_for(display_name, provider_id)
    font_size = 64 if len(letter) == 1 else 44
    return SVG_TEMPLATE.format(
        background=background_for(provider_id), letter=letter, font_size=font_size
    )


def fetch_targets(
    conn: psycopg.Connection,
    only: Iterable[str] | None = None,
    missing_only: bool = False,
) -> list[tuple[str, str | None, bool]]:
    """返回 (provider_id, display_name, has_blob)。"""
    sql = "SELECT provider_id, display_name, (avatar_blob IS NOT NULL) AS has_blob FROM providers"
    params: tuple = ()
    if only:
        ids = list(only)
        sql += " WHERE provider_id = ANY(%s)"
        params = (ids,)
    elif missing_only:
        sql += " WHERE avatar_blob IS NULL"
    sql += " ORDER BY provider_id"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [(row[0], row[1], bool(row[2])) for row in rows]


def apply_avatars(
    conn: psycopg.Connection,
    targets: list[tuple[str, str | None, bool]],
    force: bool,
) -> dict[str, int]:
    stats = {"filled": 0, "overwritten": 0, "skipped": 0}
    for provider_id, display_name, has_blob in targets:
        if has_blob and not force:
            stats["skipped"] += 1
            print(f"[跳过] {provider_id}：已有 avatar_blob（--force 可覆盖）")
            continue
        svg = build_letter_avatar_svg(display_name, provider_id)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE providers SET avatar_blob = %s, avatar_mime = %s, "
                "updated_at = CURRENT_TIMESTAMP WHERE provider_id = %s",
                (svg.encode("utf-8"), "image/svg+xml", provider_id),
            )
        conn.commit()
        if has_blob:
            stats["overwritten"] += 1
            print(f"[覆盖] {provider_id} <- 首字母占位图 {len(svg)} 字节")
        else:
            stats["filled"] += 1
            print(f"[写入] {provider_id} <- 首字母占位图 {len(svg)} 字节")
    return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="给厂商补首字母占位头像")
    parser.add_argument("--only", help="逗号分隔的 provider_id，只处理这些")
    parser.add_argument("--missing", action="store_true", help="只处理还没有 avatar_blob 的厂商")
    parser.add_argument("--force", action="store_true", help="已有 avatar_blob 也覆盖")
    parser.add_argument("--apply", action="store_true", help="真正写库；默认只 dry-run")
    parser.add_argument("--db-url", default=None, help="覆盖 DATABASE_URL")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    db_url = args.db_url or os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL 未配置", file=sys.stderr)
        return 2

    only = [item.strip() for item in args.only.split(",") if item.strip()] if args.only else None
    if not only and not args.missing:
        print("必须指定 --only 或 --missing，避免误给全部厂商换图", file=sys.stderr)
        return 2

    with psycopg.connect(db_url) as conn:
        targets = fetch_targets(conn, only=only, missing_only=args.missing)
        if not targets:
            print("没有匹配的厂商")
            return 1
        if not args.apply:
            for provider_id, display_name, has_blob in targets:
                if has_blob and not args.force:
                    print(f"[dry-run][跳过] {provider_id}：已有 avatar_blob")
                    continue
                svg = build_letter_avatar_svg(display_name, provider_id)
                print(
                    f"[dry-run][写入] {provider_id} <- 首字母 {letter_for(display_name, provider_id)}"
                    f" {len(svg)} 字节 image/svg+xml"
                )
            print(f"共 {len(targets)} 家待处理（dry-run，加 --apply 执行）")
            return 0

        stats = apply_avatars(conn, targets, force=args.force)

    print(
        f"完成：写入 {stats['filled']}，覆盖 {stats['overwritten']}，跳过 {stats['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
