#!/usr/bin/env python
"""体检脚本：检查 DATABASE_URL 指向的数据库（Supabase / 本地 PostgreSQL）是否连通、表是否建好、数据是否到位。

用法（在项目根目录执行）：
    python scripts/check_supabase.py

输出会隐藏连接串里的密码，可安全截图。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import psycopg
from dotenv import load_dotenv

load_dotenv(dotenv_path=project_root / ".env")

# init_db.py 会创建的 6 张表
EXPECTED_TABLES = (
    "models",
    "providers",
    "model_tags",
    "model_analysis",
    "model_arena_info",
    "sync_log",
)


def mask_url(url: str) -> str:
    """隐藏连接串中的密码，便于安全输出。"""
    parts = urlsplit(url)
    if not parts.password:
        return url
    netloc = f"{parts.username}:***@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def main() -> int:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("[错误] 未找到 DATABASE_URL。")
        print("       请在项目根目录创建 .env 文件，内容形如：")
        print("       DATABASE_URL=postgresql://postgres.xxxx:密码@aws-0-区域.pooler.supabase.com:5432/postgres?sslmode=require")
        return 1

    print("=" * 62)
    print("Silicon River · 数据库体检")
    print("=" * 62)
    print(f"目标: {mask_url(db_url)}")
    print()

    try:
        conn = psycopg.connect(db_url, connect_timeout=15)
    except Exception as exc:
        print(f"[失败] 无法连接数据库：{exc}")
        print()
        print("排查清单：")
        print("  1. 连接串是否用了 Supabase 的 Session Pooler（端口 5432）")
        print("  2. 是否带上了 ?sslmode=require")
        print("  3. 密码里的特殊字符是否需要 URL 编码")
        print("  4. Supabase 项目是否处于暂停状态")
        return 1

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user, version()")
            dbname, dbuser, version = cur.fetchone()
            print(f"[连通] 数据库={dbname}  用户={dbuser}")
            print(f"       {version.split(',')[0]}")
            print()

            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
            existing = {row[0] for row in cur.fetchall()}

            print("-" * 62)
            print(f"{'表名':<20}{'状态':<10}{'行数':>10}")
            print("-" * 62)

            missing = []
            empty = []
            for table in EXPECTED_TABLES:
                if table not in existing:
                    print(f"{table:<20}{'缺失':<10}{'-':>10}")
                    missing.append(table)
                    continue
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                print(f"{table:<20}{'存在':<10}{count:>10}")
                if count == 0:
                    empty.append(table)

            print("-" * 62)
            print()

            # 额外看一眼最新的几条模型数据，确认时间与厂商正常
            if "models" in existing:
                cur.execute(
                    "SELECT provider, model_name, created_at FROM models "
                    "ORDER BY created_at DESC LIMIT 5"
                )
                rows = cur.fetchall()
                if rows:
                    print("最新的 5 条模型记录：")
                    for provider, name, created in rows:
                        print(f"  {created}  {provider:<16}{name}")
                    print()

            if missing:
                print(f"[待办] 还缺 {len(missing)} 张表 —— 请运行: python scripts/init_db.py")
            if empty:
                print(f"[待办] 有 {len(empty)} 张表为空 —— 请运行: python src/scraper/fetch_models.py")
            if not missing and not any(t in empty for t in ("models", "providers")):
                print("[就绪] 表结构与核心数据都已到位，可以部署前端了。")
            return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
