"""回填 `models.merged_into`：把 OpenRouter 行并入同一模型的 Hugging Face 行（ISSUE-004）。

判定依据是 OpenRouter `/api/v1/models` 返回的 `hugging_face_id`：它指向该模型的 HF 仓库。
把「OR 行」（`hugging_face_id` 对应的库里 model_id 存在）写成 `merged_into = <HF 行的 model_id>`，
于是时间轴上只显示 HF 那张卡，价格从 OR 行取（见 backend/main.py 的 LATERAL 合并）。

写端（`fetch_models_openrouter.save_models`）每次同步也会重新计算这一列，
这个脚本用于历史数据回填与手工修复：

    .venv/bin/python scripts/backfill_merged_into.py            # dry-run
    .venv/bin/python scripts/backfill_merged_into.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

import psycopg
from dotenv import load_dotenv

DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://USER:PASSWORD@HOST:5432/silicon_river"
)
OR_MODELS_URL = "https://openrouter.ai/api/v1/models"


def fetch_or_pairs() -> list[tuple[str, str]]:
    request = urllib.request.Request(
        OR_MODELS_URL, headers={"User-Agent": "silicon-river/1.0"}
    )
    payload = json.load(urllib.request.urlopen(request, timeout=60))
    pairs: list[tuple[str, str]] = []
    for item in payload.get("data", []):
        or_id = item.get("id")
        hf_id = item.get("hugging_face_id")
        if isinstance(or_id, str) and isinstance(hf_id, str) and hf_id.strip():
            pairs.append((or_id, hf_id.strip()))
    return pairs


def run(db_url: str, *, apply: bool) -> int:
    pairs = fetch_or_pairs()
    print(f"OpenRouter 带 hugging_face_id 的条目: {len(pairs)}")

    with psycopg.connect(db_url, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT model_id, merged_into FROM models")
            rows = cur.fetchall()
        by_lid = {row["model_id"].lower(): row for row in rows}

        plan: list[tuple[str, str]] = []  # (or_row_model_id, hf_row_model_id)
        missing_hf = 0
        for or_id, hf_id in pairs:
            or_row = by_lid.get(or_id.lower())
            hf_row = by_lid.get(hf_id.lower())
            if or_row is None:
                continue  # 该 OR 模型不在白名单/库里
            if hf_row is None:
                missing_hf += 1
                continue
            if or_row["model_id"] == hf_row["model_id"]:
                continue  # 同一行，无需合并
            plan.append((or_row["model_id"], hf_row["model_id"]))

        print(f"库里有 OR 行但缺对应 HF 行（不合并）: {missing_hf}")
        print(f"待写入 merged_into: {len(plan)} 条")
        for or_id, hf_id in plan[:10]:
            print(f"  {or_id}  ->  {hf_id}")
        if len(plan) > 10:
            print(f"  ……共 {len(plan)} 条")

        if not apply:
            print("\nDRY-RUN 结束：没有修改任何数据。")
            return 0

        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '15s'")
            cur.executemany(
                "UPDATE models SET merged_into = %s WHERE model_id = %s",
                [(hf_id, or_id) for or_id, hf_id in plan],
            )
            print(f"已写入: {cur.rowcount} 行")
            # 反向清理：目标行已不存在、或自己指向自己（HF 行变成合并对象后不会再变）
            cur.execute(
                """
                UPDATE models SET merged_into = NULL
                WHERE merged_into IS NOT NULL
                  AND (merged_into = model_id
                       OR NOT EXISTS (SELECT 1 FROM models p WHERE p.model_id = models.merged_into))
                """
            )
            print(f"清理无效指向: {cur.rowcount} 行")
        # 先提交再做事后打印：这一列曾被 dict_row 的下标取值坑过一次——
        # 打印阶段抛异常会把整个事务回滚掉，屏幕上却已经显示「已写入 71 行」。
        conn.commit()

    with psycopg.connect(db_url) as verify_conn, verify_conn.cursor() as verify_cur:
        verify_cur.execute("SELECT count(*) FROM models WHERE merged_into IS NOT NULL")
        merged_rows = verify_cur.fetchone()[0]
    print(f"提交后复核：merged_into 非空 {merged_rows} 行")
    if plan and merged_rows == 0:
        print("❌ 复核失败：写入了 0 行，事务可能被回滚", file=sys.stderr)
        return 1
    print("回填完成，已提交。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回填 models.merged_into（默认 dry-run）")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认只读）")
    parser.add_argument("--db-url", "--database-url", dest="db_url", default=None)
    args = parser.parse_args(argv)
    load_dotenv(".env", override=False, encoding="utf-8-sig")
    try:
        return run(args.db_url or os.getenv("DATABASE_URL") or DEFAULT_DB_URL, apply=args.apply)
    except Exception as exc:  # noqa: BLE001 - CLI 边界
        print(f"\n❌ 回填失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
