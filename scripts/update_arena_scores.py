#!/usr/bin/env python
"""把排行榜评分写入 model_arena_info 表（本地 CLI）。

背景
----
原先有一个 `POST /api/arena/scores/batch` 接口做同样的事，但它是**公开且无鉴权的
写接口**——任何人都能往生产库里批量写评分数据。实测确认全仓库没有任何调用方
（前端不调、脚本也不调，`leaderboard_aggregator` 的落库一直是 TODO），
所以把它从 HTTP 层撤掉，改成这个只能在本机跑的脚本：能力保留，攻击面消失。

用法
----
    # 从 JSON 文件读
    .venv/bin/python scripts/update_arena_scores.py scores.json

    # 从标准输入读
    echo '{"source":"swe-bench","scores":[...]}' | .venv/bin/python scripts/update_arena_scores.py -

    # 只校验不写库
    .venv/bin/python scripts/update_arena_scores.py scores.json --dry-run

JSON 结构（与旧接口请求体一致）
------------------------------
    {
      "source": "swe-bench",
      "scores": [
        {"model_id": "deepseek-ai/DeepSeek-V4-Pro-0813",
         "rank": 3, "score": 71.2, "category": "overall"}
      ]
    }

`category` 可省略，默认 `overall`。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)

DEFAULT_DB_URL = os.getenv("DATABASE_URL", "postgresql://USER:PASSWORD@HOST:5432/silicon_river")

UPSERT_SQL = """
INSERT INTO model_arena_info (model_id, source, rank, score, category)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (model_id, source, category)
DO UPDATE SET
    rank = EXCLUDED.rank,
    score = EXCLUDED.score,
    updated_at = CURRENT_TIMESTAMP
"""


def load_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[失败] JSON 解析错误：{exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("[失败] 顶层必须是 JSON 对象")
    return payload


def validate(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    source = payload.get("source")
    scores = payload.get("scores")
    if not source or not isinstance(source, str):
        raise SystemExit("[失败] 缺少必要参数：source")
    if not scores or not isinstance(scores, list):
        raise SystemExit("[失败] 缺少必要参数：scores（非空数组）")

    for index, item in enumerate(scores):
        if not isinstance(item, dict):
            raise SystemExit(f"[失败] scores[{index}] 不是对象")
        if not item.get("model_id"):
            raise SystemExit(f"[失败] scores[{index}] 缺少 model_id")
    return source, scores


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="写入 model_arena_info 排行榜评分")
    parser.add_argument("source", nargs="?", default="-",
                        help="JSON 文件路径，或 - 表示从标准输入读（默认）")
    parser.add_argument("--dry-run", action="store_true", help="只校验与打印，不写库")
    parser.add_argument("--database-url", default=DEFAULT_DB_URL, help="覆盖 DATABASE_URL")
    args = parser.parse_args(argv)

    raw = sys.stdin.read() if args.source == "-" else Path(args.source).read_text(encoding="utf-8")
    source, scores = validate(load_payload(raw))

    print(f"source = {source}")
    print(f"条目数 = {len(scores)}")

    if args.dry_run:
        for item in scores:
            print(f"  [dry-run] {item['model_id']} "
                  f"rank={item.get('rank')} score={item.get('score')} "
                  f"category={item.get('category', 'overall')}")
        print("[dry-run] 未写库。")
        return 0

    with psycopg.connect(args.database_url, prepare_threshold=None) as conn:
        with conn.cursor() as cursor:
            for item in scores:
                cursor.execute(UPSERT_SQL, (
                    item["model_id"],
                    source,
                    item.get("rank"),
                    item.get("score"),
                    item.get("category", "overall"),
                ))
        conn.commit()

    print(f"[完成] 已写入 {len(scores)} 条评分。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
