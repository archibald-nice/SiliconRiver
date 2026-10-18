"""给 `models` 加 `merged_into` 列（ISSUE-004 跨源合并的落地点）。

语义：`merged_into IS NULL` = 这一行自己就是时间轴上的一张卡；
非 NULL = 这一行被并入 `merged_into` 指向的那一行（同一模型在 HF / OpenRouter 各有一行），
列表与详情接口不再单独显示它，但价格、arena 分数等仍从它取。

默认 dry-run（只读），带 `--apply` 才写库，与 `migrate_add_model_source.py` 保持一致：

    .venv/bin/python scripts/migrate_add_merged_into.py            # 看要做什么
    .venv/bin/python scripts/migrate_add_merged_into.py --apply    # 执行
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg
from dotenv import load_dotenv

DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://USER:PASSWORD@HOST:5432/silicon_river"
)

ADD_COLUMN_SQL = "ALTER TABLE models ADD COLUMN IF NOT EXISTS merged_into TEXT NULL"
ADD_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS models_merged_into_idx ON models (merged_into)"
)


def run_migration(db_url: str, *, apply: bool) -> int:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'models' AND column_name = 'merged_into'
                """
            )
            exists = cur.fetchone() is not None

            cur.execute("SELECT count(*) FROM models")
            total = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM models WHERE source = 'openrouter'")
            or_rows = cur.fetchone()[0]

            print(f"列 models.merged_into: {'已存在' if exists else '不存在'}")
            print(f"models 总行数: {total}（其中 openrouter {or_rows} 行）")
            print("将执行的 SQL:")
            print(f"  {ADD_COLUMN_SQL};")
            print(f"  {ADD_INDEX_SQL};")

            if not apply:
                print("\nDRY-RUN 结束：没有修改任何数据。")
                return 0

            cur.execute("SET LOCAL lock_timeout = '15s'")
            cur.execute(ADD_COLUMN_SQL)
            cur.execute(ADD_INDEX_SQL)
            cur.execute(
                """
                SELECT column_name, data_type FROM information_schema.columns
                WHERE table_name = 'models' AND column_name = 'merged_into'
                """
            )
            print("迁移后列元数据:", cur.fetchone())
        conn.commit()
    print("迁移完成，已提交。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="给 models 表加 merged_into 列（默认 dry-run）")
    parser.add_argument("--apply", action="store_true", help="真正执行 ALTER（默认只读）")
    parser.add_argument("--db-url", "--database-url", dest="db_url", default=None)
    args = parser.parse_args(argv)
    # 先加载 .env 再解析连接串：DEFAULT_DB_URL 在 import 时求值，那时 .env 还没读
    load_dotenv(".env", override=False, encoding="utf-8-sig")
    db_url = args.db_url or os.getenv("DATABASE_URL") or DEFAULT_DB_URL
    try:
        return run_migration(db_url, apply=args.apply)
    except Exception as exc:  # noqa: BLE001 - CLI 边界：打印干净的错误 + 非 0 退出码
        print(f"\n❌ 迁移失败（事务已回滚）: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
