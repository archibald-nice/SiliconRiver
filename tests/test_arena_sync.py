"""``scripts/sync_arena_scores.py`` 的离线测试（假连接，禁止真实网络/数据库）。

覆盖：

* ``--dry-run`` 只发 SELECT，且连接被设为只读；
* UPSERT 的 SQL 形态与参数顺序（``ON CONFLICT`` + ``updated_at=NOW()``）；
* 用 ``RETURNING (xmax = 0)`` 区分插入/更新（仓库铁律 6，不能用 rowcount）；
* 同一 (model_id, category) 的重复行去重取最好名次；
* 抓取失败必须非 0 退出，不能静默。
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from scripts import sync_arena_scores as sync
from src.scraper.arena.lmarena import ArenaRow


class FakeCursor:
    def __init__(self, conn: "FakeConnection"):
        self.conn = conn
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        normalized = " ".join(sql.split())
        self.conn.statements.append((normalized, list(params or [])))
        if normalized.upper().startswith("SELECT"):
            self._rows = [(model_id,) for model_id in self.conn.model_ids]
        else:
            outcome = self.conn.outcomes.popleft()
            self._rows = [(outcome,)]

    def fetchall(self) -> list[tuple]:
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    """最小 psycopg 连接替身：记录语句、按队列返回 xmax 标记。"""

    def __init__(self, model_ids: list[str], outcomes: list[bool] | None = None):
        self.model_ids = model_ids
        self.outcomes: deque[bool] = deque(outcomes or [])
        self.statements: list[tuple[str, list]] = []
        self.read_only = False
        self.commits = 0

    def cursor(self, row_factory=None):  # noqa: ARG002 - 对齐真实签名
        return FakeCursor(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> bool:
        return False

    def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def fake_connect(monkeypatch):
    """把 ``psycopg.connect`` 替换成可配置的假连接工厂。"""

    def _install(model_ids: list[str], outcomes: list[bool] | None = None):
        conn = FakeConnection(model_ids, outcomes)

        def _connect(*args, **kwargs):  # noqa: ARG001
            return conn

        monkeypatch.setattr(sync.psycopg, "connect", _connect)
        return conn

    return _install


def _row(name: str, *, rank: int = 1, score: float = 71.5, category: str = "overall") -> ArenaRow:
    return ArenaRow(
        model_name=name,
        organization="acme",
        category=category,
        rank=rank,
        score=score,
    )


def _insert_statements(conn: FakeConnection) -> list[tuple[str, list]]:
    return [entry for entry in conn.statements if entry[0].upper().startswith("INSERT")]


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def test_dry_run_issues_only_select_and_marks_connection_read_only(
    fake_connect, monkeypatch, capsys
):
    conn = fake_connect(["acme/model-70b"])
    monkeypatch.setattr(
        sync, "fetch_source_rows", lambda source, limit, workers=None: [_row("model-70b")]
    )

    exit_code = sync.main(
        ["--source", "lmarena", "--dry-run", "--db-url", "postgresql://fake"]
    )

    assert exit_code == 0
    assert conn.read_only is True
    assert conn.commits == 0
    assert _insert_statements(conn) == []
    assert conn.statements[0][0] == "SELECT model_id FROM models"
    output = capsys.readouterr().out
    assert "[dry-run] 未写库" in output
    assert "命中率        : 100.0%" in output


def test_dry_run_prints_pending_rows(fake_connect, monkeypatch, capsys):
    fake_connect(["acme/model-70b"])
    monkeypatch.setattr(
        sync, "fetch_source_rows", lambda source, limit, workers=None: [_row("model-70b", rank=3)]
    )

    sync.main(["--source", "lmarena", "--dry-run", "--db-url", "postgresql://fake"])

    output = capsys.readouterr().out
    assert "[dry-run] acme/model-70b" in output
    assert "rank=3" in output


# ---------------------------------------------------------------------------
# UPSERT 形态与计数
# ---------------------------------------------------------------------------


def test_upsert_statement_shape_and_parameter_order(fake_connect, monkeypatch):
    conn = fake_connect(["acme/model-70b"], outcomes=[True])
    monkeypatch.setattr(
        sync,
        "fetch_source_rows",
        lambda source, limit, workers=None: [_row("model-70b", rank=3, score=71.5)],
    )

    exit_code = sync.main(["--source", "lmarena", "--db-url", "postgresql://fake"])

    assert exit_code == 0
    assert conn.read_only is False
    inserts = _insert_statements(conn)
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert "INSERT INTO model_arena_info" in sql
    assert "ON CONFLICT (model_id, source, category)" in sql
    assert "updated_at = NOW()" in sql
    assert "RETURNING (xmax = 0)" in sql
    assert "rowcount" not in sql.lower()
    assert params == ["acme/model-70b", "lmarena", 3, 71.5, "overall"]
    assert conn.commits == 1


def test_xmax_flag_distinguishes_insert_and_update(fake_connect, monkeypatch, capsys):
    conn = fake_connect(
        ["acme/a", "acme/b", "acme/c"], outcomes=[True, False, True]
    )
    monkeypatch.setattr(
        sync,
        "fetch_source_rows",
        lambda source, limit, workers=None: [
            _row("a", rank=1),
            _row("b", rank=2),
            _row("c", rank=3),
        ],
    )

    exit_code = sync.main(["--source", "lmarena", "--db-url", "postgresql://fake"])

    assert exit_code == 0
    assert len(_insert_statements(conn)) == 3
    output = capsys.readouterr().out
    assert "插入 / 更新   : 2 / 1" in output
    assert "[完成] 插入 2 条，更新 1 条。" in output


def test_duplicate_rows_for_same_model_and_category_keep_best_rank():
    from src.scraper.arena.matcher import ArenaMatch

    matches = [
        ArenaMatch(row=_row("model-70b", rank=5), model_id="acme/model-70b", method="exact"),
        ArenaMatch(row=_row("model-70b", rank=2), model_id="acme/model-70b", method="exact"),
    ]
    pending = sync.build_pending_rows("lmarena", matches)
    assert len(pending) == 1
    assert pending[0].rank == 2


def test_unmatched_rows_are_reported_not_written(fake_connect, monkeypatch, capsys):
    conn = fake_connect(["acme/model-70b"], outcomes=[])
    monkeypatch.setattr(
        sync,
        "fetch_source_rows",
        lambda source, limit, workers=None: [_row("totally-unknown-model")],
    )

    exit_code = sync.main(["--source", "lmarena", "--db-url", "postgresql://fake"])

    assert exit_code == 0
    assert _insert_statements(conn) == []
    output = capsys.readouterr().out
    assert "命中率        : 0.0%" in output
    assert "- totally-unknown-model" in output


# ---------------------------------------------------------------------------
# 失败语义
# ---------------------------------------------------------------------------


def test_missing_db_url_exits_nonzero(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    exit_code = sync.main(["--source", "lmarena", "--dry-run", "--db-url", ""])
    assert exit_code == 2
    assert "没有数据库连接串" in capsys.readouterr().err


def test_fetch_failure_exits_nonzero(fake_connect, monkeypatch, capsys):
    fake_connect(["acme/model-70b"])

    def _boom(source, limit, workers=None):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(sync, "fetch_source_rows", _boom)

    exit_code = sync.main(["--source", "lmarena", "--db-url", "postgresql://fake"])

    assert exit_code == 1
    assert "upstream down" in capsys.readouterr().err


def test_empty_models_table_exits_nonzero(fake_connect, monkeypatch, capsys):
    fake_connect([])
    exit_code = sync.main(["--source", "lmarena", "--dry-run", "--db-url", "postgresql://fake"])
    assert exit_code == 1
    assert "models 表为空" in capsys.readouterr().err


def test_alias_sections_are_scoped_per_source(tmp_path, monkeypatch):
    """``lmarena:`` 小节里的别名不能串到 swebench 匹配上。"""
    alias_path = tmp_path / "aliases.yaml"
    alias_path.write_text(
        'shared: {}\nlmarena:\n  "weird name 70b": acme/model-70b\nswebench: {}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sync,
        "fetch_source_rows",
        lambda source, limit, workers=None: [_row("weird name 70b")],
    )
    swe = sync.collect_source("swebench", None, ["acme/model-70b"], str(alias_path))
    lma = sync.collect_source("lmarena", None, ["acme/model-70b"], str(alias_path))
    assert swe.matched_rows == 0
    assert lma.matched_rows == 1
