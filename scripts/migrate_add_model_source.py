"""给 `models` 表加 `source` 列并回填历史行的数据来源 —— ISSUE-004。

背景：HF 与 OpenRouter 两个源的行混在 `models` 一张表里，库层没有任何字段标识
来源，所以「HF 原厂 vs OpenRouter 路由」的跨源双胞胎（同日复测 31 组 / 68 行）
无法安全去重——两条记录的 `model_id` 可能完全相同，也可能只差大小写
（见 `docs/issues/004-openrouter-variants-and-cross-source-duplicates.md`）。
本脚本补上这列基建：`ALTER TABLE models ADD COLUMN source ...` + 回填历史行。

列定义（与 `scripts/init_db.py` 的新建库 DDL 保持一致）：

    source TEXT NOT NULL DEFAULT 'unknown'

值域：`huggingface` / `openrouter` / `unknown`。写入方是抓取脚本
（`src/scraper/fetch_models.py` → `huggingface`，
`src/scraper/fetch_models_openrouter.py` → `openrouter`）；
`unknown` 只留给「回填之前」的历史行和手写 INSERT 省略该列的行。

回填规则：`models.provider` 命中 HF 白名单 → `'huggingface'`，否则 → `'openrouter'`。
白名单取自环境变量 `PROVIDERS`（逗号分隔，见 .env），**为空直接报错退出**：
猜一个白名单等于把回填结果变成噪音，宁可让人先配好再跑。
比较时统一 `lower()`——HF 的 `?author=` 是大小写敏感的，白名单里有 `Qwen`、
`EleutherAI` 这类混合大小写条目；但这里**只用于比较，不改写 `models.provider` 原值**。

⚠️ 回填是**启发式**，不是事实：
`PROVIDERS`（HF 作者名）与 `PROVIDERS_OPENROUTER`（OpenRouter 展示名）有重叠条目
（`google` / `openai` / `nvidia` / `qwen` / `tencent` / `moonshotai` …），
这些厂商的 OpenRouter 行会被判成 `'huggingface'`。写端的 `source` 才是真值，
本脚本只负责把「一列都不标」变成「绝大多数行可信、少数行待人工订正」。

用法：
    .venv/bin/python scripts/migrate_add_model_source.py            # dry-run（默认）
    .venv/bin/python scripts/migrate_add_model_source.py --apply    # 真正执行
    .venv/bin/python scripts/migrate_add_model_source.py --db-url postgresql://...

⚠️ **--apply 是生产库变更**：先本地测试库演练，生产由人工确认后执行。

幂等：
  - 列已存在时 `ADD COLUMN IF NOT EXISTS` 是空操作；
  - 只回填 `source` 为 NULL 或不在值域内（含 `'unknown'`）的行；已经是
    `huggingface` / `openrouter` 的行一个字都不改（UPDATE 的 WHERE 里也带了同样的守卫）；
  - 全部行都已有明确来源时，dry-run 直接报「无需回填」。
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False, encoding="utf-8-sig")

DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://USER:PASSWORD@HOST:5432/silicon_river"
)

HF_SOURCE = "huggingface"
OPENROUTER_SOURCE = "openrouter"
UNKNOWN_SOURCE = "unknown"
KNOWN_SOURCES = (HF_SOURCE, OPENROUTER_SOURCE)

ADD_COLUMN_SQL = (
    "ALTER TABLE models ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'unknown'"
)

# 守卫 `source NOT IN ('huggingface', 'openrouter')` 与 plan_backfill() 的判定同口径：
# 已有明确来源的行不会被这条 UPDATE 碰到（幂等靠它，不靠调用方记得跳过）。
BACKFILL_SQL = """
UPDATE models
   SET source = %s
 WHERE model_id = ANY(%s)
   AND (source IS NULL OR source NOT IN ('huggingface', 'openrouter'))
"""


# ---------------------------------------------------------------------------
# 纯函数：白名单解析 + 来源推断 + 回填计划（测试直接打这些，不碰库）
# ---------------------------------------------------------------------------
def parse_providers(raw: str | None) -> list[str]:
    """把逗号分隔的白名单解析成**小写去重**列表（保持原顺序）。"""
    if not raw:
        return []
    parsed: list[str] = []
    for item in raw.split(","):
        key = item.strip().lower()
        if key and key not in parsed:
            parsed.append(key)
    return parsed


def load_hf_whitelist(env: Mapping[str, str] | None = None) -> list[str]:
    """读 HF 白名单（`PROVIDERS`）。为空直接报错——不猜一个白名单出来。"""
    source = os.environ if env is None else env
    whitelist = parse_providers(source.get("PROVIDERS"))
    if not whitelist:
        raise RuntimeError(
            "HF 白名单为空：环境变量 PROVIDERS 未配置或没有有效条目。\n"
            "  回填规则靠它判断哪些 provider 属于 Hugging Face；"
            "猜一个白名单会把回填变成噪音，所以这里直接退出。\n"
            f"  请先在 {ENV_PATH} 或 shell 里配置（逗号分隔的 HF 作者名），"
            "参考 .env.example 的 PROVIDERS 一行。"
        )
    return whitelist


def infer_source(provider: str | None, whitelist: Collection[str]) -> str:
    """按 provider 推断来源：命中 HF 白名单 → `huggingface`，否则 → `openrouter`。

    白名单应已经是 `lower()` 之后的形式（`parse_providers` 会做）。比较用
    `lower()`，但**不改写** `models.provider` 的原值——`Qwen/Qwen3.8-27B` 这个
    `provider='Qwen'` 回填后仍然是 `Qwen`，`source` 才是新信息。
    """
    if provider and provider.strip().lower() in whitelist:
        return HF_SOURCE
    return OPENROUTER_SOURCE


@dataclass(frozen=True)
class ModelRow:
    """回填只需要三列：主键 + 推断依据 + 当前来源。"""

    model_id: str
    provider: str | None
    current_source: str | None


@dataclass
class BackfillPlan:
    """回填计划：哪些行要改、哪些行已经不用管。"""

    rows: list[ModelRow] = field(default_factory=list)
    already_tagged: int = 0

    @property
    def pending(self) -> int:
        return len(self.rows)

    def by_source(self, whitelist: Collection[str]) -> dict[str, int]:
        """待回填行按**推断出的** source 分组计数（dry-run 报告用）。"""
        counts = Counter(infer_source(row.provider, whitelist) for row in self.rows)
        return dict(sorted(counts.items()))

    def grouped(self, whitelist: Collection[str]) -> dict[str, list[str]]:
        """待回填行按目标 source 分组成 `model_id` 列表（一条 UPDATE 打一批）。"""
        groups: dict[str, list[str]] = {}
        for row in self.rows:
            groups.setdefault(infer_source(row.provider, whitelist), []).append(row.model_id)
        return groups


def plan_backfill(rows: Iterable[ModelRow], whitelist: Collection[str]) -> BackfillPlan:
    """算回填计划：`source` 已是 huggingface/openrouter 的行原样留下，其余待回填。"""
    plan = BackfillPlan()
    for row in rows:
        if row.current_source in KNOWN_SOURCES:
            plan.already_tagged += 1
            continue
        plan.rows.append(row)
    return plan


# ---------------------------------------------------------------------------
# 读库（只读路径，dry-run 只走这一段）
# ---------------------------------------------------------------------------
def column_exists(cur) -> bool:
    """`models.source` 是否已经存在（本脚本幂等的判断依据）。"""
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'models' AND column_name = 'source'
        """
    )
    return cur.fetchone() is not None


def fetch_rows(cur, has_column: bool) -> list[ModelRow]:
    """把整张表的 (model_id, provider, source) 读进内存（~千行量级，够用）。"""
    if has_column:
        cur.execute("SELECT model_id, provider, source FROM models ORDER BY model_id")
    else:
        cur.execute("SELECT model_id, provider, NULL FROM models ORDER BY model_id")
    return [
        ModelRow(model_id=row[0], provider=row[1], current_source=row[2])
        for row in cur.fetchall()
    ]


def format_distribution(rows: Iterable[ModelRow]) -> str:
    """按 source 打印行数分布；NULL 归到 `unknown`（列缺失时也走这里）。"""
    counts = Counter(row.current_source or UNKNOWN_SOURCE for row in rows)
    if not counts:
        return "    （表里没有行）"
    return "\n".join(f"    {source}: {count} 行" for source, count in counts.most_common())


def verify_after_apply(
    before: Sequence[ModelRow], after: Sequence[ModelRow]
) -> None:
    """回填后断言：总行数不变 + 没有残留的 unknown/NULL。

    对不上就抛异常——调用方在同一个事务里，异常会让整次 APPLY 回滚，
    不留下「回填到一半」的库。
    """
    if len(after) != len(before):
        raise RuntimeError(
            f"总行数变了：{len(before)} → {len(after)}（回填不应增删行）"
        )
    leftovers = [row for row in after if row.current_source not in KNOWN_SOURCES]
    if leftovers:
        providers = sorted({row.provider or "<NULL>" for row in leftovers})
        shown = ", ".join(providers[:20]) + (" …" if len(providers) > 20 else "")
        raise RuntimeError(
            f"回填后仍有 {len(leftovers)} 行 source 不是 huggingface/openrouter；"
            f"涉及的 provider: {shown}"
        )


# ---------------------------------------------------------------------------
# 写库（只有 --apply 会走）
# ---------------------------------------------------------------------------
def apply_backfill(conn, plan: BackfillPlan, whitelist: Collection[str]) -> None:
    """加列 + 按目标 source 分两批 UPDATE（列已存在时加列是空操作）。"""
    groups = plan.grouped(whitelist)
    with conn.cursor() as cur:
        # 拿不到锁就快速失败，不要跟在线抓取/分析任务死等
        cur.execute("SET LOCAL lock_timeout = '15s'")
        print(f"→ {ADD_COLUMN_SQL};")
        cur.execute(ADD_COLUMN_SQL)
        for target in (HF_SOURCE, OPENROUTER_SOURCE):
            ids = groups.get(target, [])
            if not ids:
                continue
            print(f"→ UPDATE ... SET source = {target!r} WHERE model_id = ANY(...)：{len(ids)} 行")
            cur.execute(BACKFILL_SQL, (target, ids))


def _safe_db_label(db_url: str) -> str:
    """打印主机 / 库名，但不泄露用户名密码。"""
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(db_url)
        host = parts.hostname or "?"
        port = f":{parts.port}" if parts.port else ""
        dbname = (parts.path or "/?").lstrip("/") or "?"
        return f"{host}{port}/{dbname}"
    except Exception:  # pragma: no cover - URL 解析失败不该阻断迁移
        return "<无法解析 DATABASE_URL>"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run_migration(
    db_url: str, apply: bool, whitelist: list[str] | None = None
) -> int:
    whitelist = load_hf_whitelist() if whitelist is None else whitelist

    print("=" * 78)
    print("ISSUE-004 models.source：新增来源列 + 按 HF 白名单回填")
    print(f"模式: {'APPLY（会真正写库）' if apply else 'DRY-RUN（只读，不写库）'}")
    print(f"数据库: {_safe_db_label(db_url)}")
    print(f"HF 白名单 PROVIDERS（{len(whitelist)} 条）: {', '.join(whitelist)}")
    print("=" * 78)

    with psycopg.connect(db_url, connect_timeout=15) as conn:
        if not apply:
            conn.autocommit = True

        with conn.cursor() as cur:
            has_column = column_exists(cur)
            rows = fetch_rows(cur, has_column)

        print(
            "\n列 models.source: "
            + ("已存在" if has_column else "不存在（APPLY 时会 ADD COLUMN）")
        )
        print(f"总行数: {len(rows)}")
        print("回填前分布:")
        if has_column:
            print(format_distribution(rows))
        else:
            print(f"    {UNKNOWN_SOURCE}: {len(rows)} 行（列不存在，历史行全部视为 unknown）")

        if not rows:
            # 空表时说「无需回填」会让人以为已经回填过；这里明确区分「表是空的」。
            print("\n表里没有行：没有需要回填的数据（先配好库/数据再跑）。")
            return 0

        plan = plan_backfill(rows, whitelist)
        print(f"\n已有明确来源（不会被改写）: {plan.already_tagged} 行")
        print(f"待回填: {plan.pending} 行")
        if plan.rows:
            print("待回填行按推断出的 source 分组:")
            for source, count in plan.by_source(whitelist).items():
                print(f"    {source}: {count} 行")

        print("\n将执行的 SQL（按顺序，同一事务内）：")
        print(f"  {ADD_COLUMN_SQL};")
        groups = plan.grouped(whitelist)
        for target in (HF_SOURCE, OPENROUTER_SOURCE):
            ids = groups.get(target, [])
            if not ids:
                continue
            print(f"  -- $1 = {target!r}，$2 = {len(ids)} 个 model_id，例如:")
            print(f"  --   {', '.join(ids[:5])}" + (" …" if len(ids) > 5 else ""))
            print("  " + " ".join(BACKFILL_SQL.split()) + ";")

        if not plan.rows:
            print("\n无需回填：所有行的 source 都已是 huggingface/openrouter（幂等）。")
            return 0

        if not apply:
            print("\nDRY-RUN 结束：没有修改任何数据。")
            print("确认以上分布无误后，由人工执行：")
            print(
                f"  {sys.executable} "
                f"{Path(__file__).relative_to(BASE_DIR)} --apply"
            )
            return 0

        print()
        apply_backfill(conn, plan, whitelist)

        # 断言在同一事务里做：对不上就整体回滚。
        print("\n回填后复查（总行数 + unknown 断言）：")
        with conn.cursor() as cur:
            after = fetch_rows(cur, has_column=True)
        verify_after_apply(rows, after)
        print(f"  ✅ 总行数 {len(rows)} 未变；source 为 unknown/NULL 的行数 0")
        print("回填后分布:")
        print(format_distribution(after))

        conn.commit()

    print("\n迁移完成，已提交。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="给 models 表加 source 列并回填来源（默认 dry-run，只读）"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正执行 ALTER + UPDATE（生产库必须先经人工确认；默认只读）",
    )
    parser.add_argument(
        "--db-url",
        "--database-url",
        dest="db_url",
        default=None,
        help="覆盖 DATABASE_URL（例如指向本地测试库做演练）",
    )
    args = parser.parse_args(argv)
    db_url = args.db_url or DEFAULT_DB_URL
    try:
        return run_migration(db_url, apply=args.apply)
    except Exception as exc:  # noqa: BLE001 - CLI 边界：打印干净的错误 + 非 0 退出码
        print(
            f"\n❌ 迁移失败（事务已回滚，未提交任何改动）: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
