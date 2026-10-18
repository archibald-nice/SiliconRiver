"""ISSUE-004 `models.source` 迁移脚本的回归测试（`scripts/migrate_add_model_source.py`）。

不联网、不碰数据库：白名单解析 / 来源推断 / 回填计划都是纯函数，dry-run 用假
cursor + 假连接驱动（`psycopg.connect` 打桩），其余断言只读 `init_db.py` 的 DDL 字符串。

钉住的行为：
1. 回填推断：provider 命中 HF 白名单（大小写不敏感）→ `huggingface`，否则 → `openrouter`；
2. 幂等：已有 `huggingface`/`openrouter` 的行不进计划，UPDATE 的 WHERE 里也有同样的守卫；
3. dry-run 只读：假 cursor 上不能出现 ALTER/UPDATE/DELETE/INSERT；
4. schema：`init_db.py` 的 models 建表 SQL 里必须有 `source text NOT NULL DEFAULT 'unknown'`。
"""
from __future__ import annotations

import re

import pytest

from scripts import init_db
from scripts import migrate_add_model_source as mig

# 与 .env 的 PROVIDERS 同口径：存 HF 作者名，混合大小写是真实情况（`Qwen` / `EleutherAI`）
HF_WHITELIST = mig.parse_providers("meta-llama,Qwen,EleutherAI,microsoft,openai")


# ---------------------------------------------------------------------------
# 假 psycopg：只实现 dry-run 需要的那几个方法
# ---------------------------------------------------------------------------
class _FakeCursor:
    """按 SQL 内容分派结果的假 cursor，记录每一条执行过的语句。"""

    def __init__(self, rows: list[tuple], has_column: bool) -> None:
        self._rows = rows
        self._has_column = has_column
        self.executed: list[str] = []
        self._mode: str | None = None

    def execute(self, sql, params=None):  # noqa: ANN001 - 模拟 psycopg cursor
        normalized = " ".join(str(sql).split())
        self.executed.append(normalized)
        lowered = normalized.lower()
        if "information_schema.columns" in lowered:
            self._mode = "column"
        elif lowered.startswith("select model_id"):
            self._mode = "rows"
        else:
            self._mode = None

    def fetchone(self):
        if self._mode == "column":
            return (1,) if self._has_column else None
        return None

    def fetchall(self):
        return self._rows if self._mode == "rows" else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):  # noqa: ANN002
        return False


class _FakeConnection:
    def __init__(self, rows: list[tuple], has_column: bool) -> None:
        self.cursor_obj = _FakeCursor(rows, has_column)
        self.autocommit = False
        self.commits = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1


class _FakeConnect:
    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc):  # noqa: ANN002
        return False


WRITE_KEYWORDS = ("alter", "update", "delete", "insert", "drop", "truncate", "create")


def _patched_connect(monkeypatch, conn: _FakeConnection) -> None:
    monkeypatch.setattr(mig.psycopg, "connect", lambda *a, **k: _FakeConnect(conn))


# ---------------------------------------------------------------------------
# 1) 白名单解析 / 来源推断
# ---------------------------------------------------------------------------
def test_parse_providers_strips_lowercases_and_dedupes() -> None:
    assert mig.parse_providers("Meta-Llama, QWEN ,meta-llama,, Qwen") == [
        "meta-llama",
        "qwen",
    ]


@pytest.mark.parametrize("raw", [None, "", "  ", " , , "])
def test_parse_providers_empty(raw) -> None:
    assert mig.parse_providers(raw) == []


def test_load_hf_whitelist_reads_providers_env() -> None:
    assert mig.load_hf_whitelist({"PROVIDERS": "Qwen, meta-llama"}) == ["qwen", "meta-llama"]


@pytest.mark.parametrize("env", [{}, {"PROVIDERS": ""}, {"PROVIDERS": " , "}])
def test_load_hf_whitelist_fails_loudly_when_unset(env) -> None:
    """白名单为空必须报错退出——不允许猜一个白名单出来。"""
    with pytest.raises(RuntimeError, match="HF 白名单为空"):
        mig.load_hf_whitelist(env)


@pytest.mark.parametrize(
    "provider, expected",
    [
        ("Qwen", mig.HF_SOURCE),  # 白名单里是 `Qwen`，库里也是 `Qwen`
        ("qwen", mig.HF_SOURCE),  # 大小写差异不影响判定
        ("QWEN", mig.HF_SOURCE),
        ("EleutherAI", mig.HF_SOURCE),
        ("meta-llama", mig.HF_SOURCE),
        ("acme", mig.OPENROUTER_SOURCE),  # 不在白名单 → OpenRouter
        ("anthropic", mig.OPENROUTER_SOURCE),
        ("", mig.OPENROUTER_SOURCE),
        (None, mig.OPENROUTER_SOURCE),
    ],
)
def test_infer_source_matches_whitelist_case_insensitively(provider, expected) -> None:
    assert mig.infer_source(provider, HF_WHITELIST) == expected


# ---------------------------------------------------------------------------
# 2) 回填计划：推断 + 幂等
# ---------------------------------------------------------------------------
def _row(model_id: str, provider: str | None, source: str | None = None) -> mig.ModelRow:
    return mig.ModelRow(model_id=model_id, provider=provider, current_source=source)


def test_plan_backfill_groups_pending_rows_by_inferred_source() -> None:
    rows = [
        _row("Qwen/Qwen3.8-27B", "Qwen"),
        _row("acme/alpha-1", "acme"),
        _row("acme/beta-2", "acme"),
    ]

    plan = mig.plan_backfill(rows, HF_WHITELIST)

    assert plan.pending == 3
    assert plan.already_tagged == 0
    assert plan.by_source(HF_WHITELIST) == {
        mig.HF_SOURCE: 1,
        mig.OPENROUTER_SOURCE: 2,
    }
    assert plan.grouped(HF_WHITELIST) == {
        mig.HF_SOURCE: ["Qwen/Qwen3.8-27B"],
        mig.OPENROUTER_SOURCE: ["acme/alpha-1", "acme/beta-2"],
    }


def test_plan_backfill_never_rewrites_rows_with_known_source() -> None:
    """幂等：第二次跑时已有明确来源的行不进计划（列已回填过就不会再动）。"""
    rows = [
        _row("Qwen/Qwen3.8-27B", "Qwen", mig.HF_SOURCE),
        _row("acme/alpha-1", "acme", mig.OPENROUTER_SOURCE),
    ]

    plan = mig.plan_backfill(rows, HF_WHITELIST)

    assert plan.pending == 0
    assert plan.already_tagged == 2
    assert plan.grouped(HF_WHITELIST) == {}


def test_plan_backfill_only_touches_unset_or_unknown_rows() -> None:
    rows = [
        _row("acme/alpha-1", "acme", "unknown"),
        _row("acme/beta-2", "acme", None),
        _row("Qwen/Qwen3.8-27B", "Qwen", mig.HF_SOURCE),  # 保留
        _row("globex/gamma-3", "globex", "openrouter"),  # 保留
    ]

    plan = mig.plan_backfill(rows, HF_WHITELIST)

    assert [row.model_id for row in plan.rows] == ["acme/alpha-1", "acme/beta-2"]
    assert plan.already_tagged == 2


def test_plan_backfill_keeps_original_provider_value() -> None:
    """`lower()` 只用于比较：provider 的原始大小写必须原样留在行里。"""
    plan = mig.plan_backfill([_row("Qwen/Qwen3.8-27B", "Qwen")], HF_WHITELIST)

    assert plan.rows[0].provider == "Qwen"


# ---------------------------------------------------------------------------
# 3) SQL 文本：加列口径 + 回填守卫
# ---------------------------------------------------------------------------
def test_add_column_sql_matches_init_db_ddl() -> None:
    assert (
        " ".join(mig.ADD_COLUMN_SQL.split())
        == "ALTER TABLE models ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'unknown'"
    )


def test_backfill_sql_is_idempotent_and_does_not_touch_provider() -> None:
    sql = " ".join(mig.BACKFILL_SQL.split())

    assert sql.startswith("UPDATE models")
    assert "SET source = %s" in sql
    # 守卫：已有明确来源的行不会被这条 UPDATE 碰到
    assert "source IS NULL OR source NOT IN ('huggingface', 'openrouter')" in sql
    # provider 只用于推断，绝不能被改写（HF 的 author 大小写敏感）
    assert "provider =" not in sql
    assert "provider=" not in sql


# ---------------------------------------------------------------------------
# 4) 回填后断言
# ---------------------------------------------------------------------------
def test_verify_after_apply_accepts_complete_backfill() -> None:
    before = [_row("acme/alpha-1", "acme", "unknown"), _row("acme/beta-2", "acme", None)]
    after = [
        _row("acme/alpha-1", "acme", mig.OPENROUTER_SOURCE),
        _row("acme/beta-2", "acme", mig.OPENROUTER_SOURCE),
    ]

    mig.verify_after_apply(before, after)  # 不抛就是过


def test_verify_after_apply_rejects_leftover_unknown() -> None:
    before = [_row("acme/alpha-1", "acme", "unknown")]
    after = [_row("acme/alpha-1", "acme", "unknown")]

    with pytest.raises(RuntimeError, match="仍有 1 行 source 不是"):
        mig.verify_after_apply(before, after)


def test_verify_after_apply_rejects_row_count_change() -> None:
    before = [_row("acme/alpha-1", "acme", "unknown")]
    after = []

    with pytest.raises(RuntimeError, match="总行数变了"):
        mig.verify_after_apply(before, after)


def test_format_distribution_counts_sources() -> None:
    rows = [
        _row("a/1", "a", mig.HF_SOURCE),
        _row("a/2", "a", mig.OPENROUTER_SOURCE),
        _row("a/3", "a", None),
    ]

    text = mig.format_distribution(rows)

    assert "huggingface: 1 行" in text
    assert "openrouter: 1 行" in text
    assert "unknown: 1 行" in text


# ---------------------------------------------------------------------------
# 5) dry-run 不产生任何写操作
# ---------------------------------------------------------------------------
DRY_RUN_URL = "postgresql://postgres@127.0.0.1:55432/silicon_river_test"


def test_dry_run_only_issues_selects(monkeypatch, capsys) -> None:
    conn = _FakeConnection(
        rows=[
            ("Qwen/Qwen3.8-27B", "Qwen", None),
            ("acme/alpha-1", "acme", None),
        ],
        has_column=False,
    )
    _patched_connect(monkeypatch, conn)

    assert mig.run_migration(DRY_RUN_URL, apply=False, whitelist=HF_WHITELIST) == 0

    executed = conn.cursor_obj.executed
    assert executed, "dry-run 至少应该读一次 information_schema"
    for statement in executed:
        assert statement.lower().startswith("select"), f"dry-run 出现了写操作: {statement!r}"
        for keyword in WRITE_KEYWORDS:
            assert not re.search(rf"\b{keyword}\b", statement.lower()), statement
    assert conn.commits == 0

    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "待回填: 2 行" in out
    assert "huggingface: 1 行" in out
    assert "openrouter: 1 行" in out
    assert "没有修改任何数据" in out


def test_dry_run_reports_nothing_to_do_when_already_backfilled(monkeypatch, capsys) -> None:
    """第二次 dry-run：所有行都已标好 → 报「无需回填」，不再打印待回填分组。"""
    conn = _FakeConnection(
        rows=[
            ("Qwen/Qwen3.8-27B", "Qwen", mig.HF_SOURCE),
            ("acme/alpha-1", "acme", mig.OPENROUTER_SOURCE),
        ],
        has_column=True,
    )
    _patched_connect(monkeypatch, conn)

    assert mig.run_migration(DRY_RUN_URL, apply=False, whitelist=HF_WHITELIST) == 0

    out = capsys.readouterr().out
    assert "列 models.source: 已存在" in out
    assert "已有明确来源（不会被改写）: 2 行" in out
    assert "待回填: 0 行" in out
    assert "无需回填" in out
    assert conn.commits == 0


def test_dry_run_distinguishes_empty_table_from_backfilled(monkeypatch, capsys) -> None:
    """空表不能报「无需回填」——那会让人误以为已经回填过。"""
    conn = _FakeConnection(rows=[], has_column=False)
    _patched_connect(monkeypatch, conn)

    assert mig.run_migration(DRY_RUN_URL, apply=False, whitelist=HF_WHITELIST) == 0

    out = capsys.readouterr().out
    assert "表里没有行" in out
    assert "无需回填" not in out


def test_run_migration_uses_providers_env_when_whitelist_omitted(monkeypatch) -> None:
    """不传 whitelist 时必须走 PROVIDERS（并由 load_hf_whitelist 报空缺）。"""
    conn = _FakeConnection(rows=[], has_column=False)
    _patched_connect(monkeypatch, conn)
    monkeypatch.delenv("PROVIDERS", raising=False)

    with pytest.raises(RuntimeError, match="HF 白名单为空"):
        mig.run_migration(DRY_RUN_URL, apply=False)
    assert conn.cursor_obj.executed == []


# ---------------------------------------------------------------------------
# 6) schema：init_db.py 的 models 建表 SQL
# ---------------------------------------------------------------------------
def test_init_db_models_ddl_declares_source_column() -> None:
    ddl = " ".join(init_db.MODEL_TABLE_SQL.split())

    assert "source text NOT NULL DEFAULT 'unknown'" in ddl
    # 值域就写在 DDL 旁边，谁在写这一列也写在注释里（防止后来人删默认值）
    assert "'huggingface'" in ddl and "'openrouter'" in ddl
    assert "fetch_models.py" in ddl and "fetch_models_openrouter.py" in ddl


def test_init_db_models_ddl_keeps_timestamptz_columns() -> None:
    """ISSUE-006 的迁移不能被这次加列顺手改回去。"""
    ddl = " ".join(init_db.MODEL_TABLE_SQL.split())

    assert "created_at timestamp with time zone NOT NULL" in ddl
    assert "inserted_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP" in ddl
