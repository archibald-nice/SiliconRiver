"""把历史时间列迁移成 `timestamp with time zone`（UTC 存储）—— ISSUE-006。

背景：`models.created_at` 是 `timestamp without time zone`（值语义是 UTC 但没标记），
`models.inserted_at` / `sync_log.started_at` / `sync_log.finished_at` /
`model_tags.inserted_at` 是 text。这些列让 API 序列化出不带偏移的字符串，
浏览器按本地时区解析 → 时间轴整体偏移。本脚本把它们统一成 timestamptz。

⚠️ **这是生产库变更**（`ALTER TABLE ... ALTER COLUMN ... TYPE` 会重写整表并重建索引）：
    1. 先在本地测试库验证（`TEST_DATABASE_URL`，见 `bash scripts/dev_db.sh start`）；
    2. dry-run（不带 `--apply`）只读，可以安全地对生产库跑，用来核对类型与 min/max；
    3. `--apply` 必须**经人工确认后由人执行**，agent / CI 不要自动跑。

用法：
    .venv/bin/python scripts/migrate_timestamps_to_timestamptz.py            # dry-run（默认）
    .venv/bin/python scripts/migrate_timestamps_to_timestamptz.py --apply    # 真正执行

幂等：已经是 `timestamp with time zone` 的列直接跳过。列的实际类型与预期不符时
**直接报错退出**，不会猜一个表达式硬转——错的转换比不转更危险。

转换表达式（必须显式按 UTC 解释 naive 值，否则会跟着会话时区漂移）：
  - naive timestamp 列：`<col> AT TIME ZONE 'UTC'`
  - text 列：末尾带偏移（`Z` / `+HH` / `+HH:MM`）的按 `::timestamptz` 解析，
    不带偏移的按 `::timestamp AT TIME ZONE 'UTC'` 解释。
  - 注意：`model_tags.inserted_at` 实测是**混合格式**（既有 `... +00`，也有裸 naive），
    所以 CASE 分支是必需的，不能整列一刀切。
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
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

TARGET_TYPE = "timestamp with time zone"
NAIVE_TYPE = "timestamp without time zone"

# 末尾偏移：`Z`、`+00`、`+08`、`+00:00`、`-05:00`。
# 生产库 model_tags.inserted_at 里有 `...+00`（只有小时、没有分钟），
# 所以 `(:[0-9]{2})?` 这一段必须是可选的。
OFFSET_SUFFIX_PATTERN = r"(Z|[+-][0-9]{2}(:[0-9]{2})?)$"
# 只用来做「值看起来像不像时间」的兜底校验，不参与转换。
ISO_LITERAL_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}"


@dataclass(frozen=True)
class ColumnSpec:
    """一列迁移定义。

    Attributes:
        source_type: 迁移前的预期类型；不符就直接报错。
        expression: 由旧值算出 timestamptz 的 SQL 表达式，`$COL` 会被替换成带引号的列名。
        note: 打印到报告里的说明。
        target_default: 迁移后要补的 DEFAULT（与 scripts/init_db.py 的新 DDL 对齐）；
            None 表示该列按新 schema 也不带默认值。老库原本没有这两列的默认值，
            不补的话「迁移过的库」和「新建的库」DDL 不一致。
    """

    table: str
    column: str
    source_type: str
    expression: str
    note: str
    target_default: str | None = None

    @property
    def fqname(self) -> str:
        return f"{self.table}.{self.column}"

    def quoted(self) -> str:
        return f'"{self.column}"'

    def sql_expression(self) -> str:
        return self.expression.replace("$COL", self.quoted())

    def alter_sql(self) -> str:
        return (
            f"ALTER TABLE {self.table} ALTER COLUMN {self.quoted()} "
            f"TYPE {TARGET_TYPE} USING {self.sql_expression()}"
        )

    def default_sql(self) -> str | None:
        if not self.target_default:
            return None
        return (
            f"ALTER TABLE {self.table} ALTER COLUMN {self.quoted()} "
            f"SET DEFAULT {self.target_default}"
        )


def _text_case_expression() -> str:
    return (
        "CASE WHEN $COL ~ '" + OFFSET_SUFFIX_PATTERN + "' "
        "THEN $COL::timestamptz "
        "ELSE $COL::timestamp AT TIME ZONE 'UTC' END"
    )


COLUMN_SPECS: tuple[ColumnSpec, ...] = (
    ColumnSpec(
        table="models",
        column="created_at",
        source_type=NAIVE_TYPE,
        expression="$COL AT TIME ZONE 'UTC'",
        note="HF/OpenRouter 发布时间，旧值语义已是 UTC，显式按 UTC 补时区",
    ),
    ColumnSpec(
        table="models",
        column="inserted_at",
        source_type="text",
        expression=_text_case_expression(),
        note="首次入库时间；实测全是 naive `YYYY-MM-DD HH:MM:SS`",
        target_default="CURRENT_TIMESTAMP",
    ),
    ColumnSpec(
        table="sync_log",
        column="started_at",
        source_type="text",
        expression=_text_case_expression(),
        note="同步开始时间；实测都带 `+00:00` 偏移",
    ),
    ColumnSpec(
        table="sync_log",
        column="finished_at",
        source_type="text",
        expression=_text_case_expression(),
        note="同步结束时间；实测都带 `+00:00` 偏移",
    ),
    ColumnSpec(
        table="model_tags",
        column="inserted_at",
        source_type="text",
        expression=_text_case_expression(),
        note="标签写入时间；实测混合格式（裸 naive 与 `+00` 并存），CASE 必需",
        target_default="CURRENT_TIMESTAMP",
    ),
)


@dataclass
class ColumnSnapshot:
    """迁移前后的列状态，用于报告与转换后一致性断言。"""

    spec: ColumnSpec
    data_type: str
    row_count: int
    raw_min: object
    raw_max: object
    utc_min: object = None
    utc_max: object = None
    offset_suffix_rows: int | None = None
    naive_rows: int | None = None
    suspicious_rows: int = 0
    column_default: str | None = None


def fetch_column_info(
    conn: psycopg.Connection, spec: ColumnSpec
) -> tuple[str | None, str | None]:
    """返回 (information_schema data_type, column_default)。列不存在时第一项为 None。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT data_type, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
            """,
            (spec.table, spec.column),
        )
        row = cur.fetchone()
    return (row[0], row[1]) if row else (None, None)


def snapshot(conn: psycopg.Connection, spec: ColumnSpec) -> ColumnSnapshot:
    """采集单列的当前状态（只读）。`utc_min/utc_max` 用转换表达式算出来，是期望值。"""
    data_type, column_default = fetch_column_info(conn, spec)
    if data_type is None:
        raise RuntimeError(
            f"{spec.fqname} 不存在：可能连错库，或 schema 还没用 scripts/init_db.py 建过"
        )

    snap = ColumnSnapshot(
        spec=spec,
        data_type=data_type,
        row_count=0,
        raw_min=None,
        raw_max=None,
        column_default=column_default,
    )

    col = spec.quoted()
    expr = spec.sql_expression()
    with conn.cursor() as cur:
        # 先用表达式自己算出「期望的 UTC min/max」：迁移后必须一模一样。
        cur.execute(f"SELECT COUNT(*), MIN({col}), MAX({col}) FROM {spec.table}")
        snap.row_count, snap.raw_min, snap.raw_max = cur.fetchone()

        if data_type == TARGET_TYPE:
            # 已是目标类型：旧值本身带时区，期望值就是它自己
            snap.utc_min, snap.utc_max = snap.raw_min, snap.raw_max
            return snap

        cur.execute(f"SELECT MIN({expr}), MAX({expr}) FROM {spec.table}")
        snap.utc_min, snap.utc_max = cur.fetchone()

        if data_type == "text":
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE {col} ~ %s),
                    COUNT(*) FILTER (WHERE {col} !~ %s),
                    COUNT(*) FILTER (WHERE {col} !~* %s)
                FROM {spec.table}
                """,
                (OFFSET_SUFFIX_PATTERN, OFFSET_SUFFIX_PATTERN, ISO_LITERAL_PATTERN),
            )
            (
                snap.offset_suffix_rows,
                snap.naive_rows,
                snap.suspicious_rows,
            ) = cur.fetchone()

    return snap


def describe(snap: ColumnSnapshot) -> str:
    s = snap.spec
    lines = [
        f"- {s.fqname}",
        f"    当前类型: {snap.data_type}",
        f"    行数: {snap.row_count}",
        f"    原始 min/max: {snap.raw_min!r} ~ {snap.raw_max!r}",
        f"    按 UTC 解释后的 min/max: {snap.utc_min!r} ~ {snap.utc_max!r}",
        f"    当前默认值: {snap.column_default!r}"
        + (f"（迁移后设为 {s.target_default}）" if s.target_default else ""),
        f"    说明: {s.note}",
    ]
    if snap.offset_suffix_rows is not None:
        lines.append(
            f"    末尾带偏移的行: {snap.offset_suffix_rows}；"
            f"无偏移（按 UTC 解释）的行: {snap.naive_rows}"
        )
        if snap.suspicious_rows:
            lines.append(f"    ⚠️ 不像 ISO 时间的行: {snap.suspicious_rows}")
    if snap.data_type == TARGET_TYPE:
        lines.append("    状态: 已是 timestamptz，跳过")
    return "\n".join(lines)


def verify_after_apply(snap_before: ColumnSnapshot, conn: psycopg.Connection) -> None:
    """复查：类型必须是 timestamptz，且 UTC min/max 与转换前一致。"""
    snap_after = snapshot(conn, snap_before.spec)
    if snap_after.data_type != TARGET_TYPE:
        raise RuntimeError(
            f"{snap_before.spec.fqname} 转换后类型仍是 {snap_after.data_type!r}，"
            f"期望 {TARGET_TYPE!r}"
        )
    if snap_after.row_count != snap_before.row_count:
        raise RuntimeError(
            f"{snap_before.spec.fqname} 行数变了：{snap_before.row_count} → "
            f"{snap_after.row_count}（转换不应增删行）"
        )
    if (snap_after.raw_min, snap_after.raw_max) != (
        snap_before.utc_min,
        snap_before.utc_max,
    ):
        raise RuntimeError(
            f"{snap_before.spec.fqname} 时间值不一致：转换前按 UTC 解释为 "
            f"{snap_before.utc_min!r} ~ {snap_before.utc_max!r}，转换后变成 "
            f"{snap_after.raw_min!r} ~ {snap_after.raw_max!r}"
        )
    if snap_before.spec.target_default:
        if not snap_after.column_default:
            raise RuntimeError(
                f"{snap_before.spec.fqname} 迁移后没有默认值，"
                f"期望 {snap_before.spec.target_default!r}"
            )
    print(
        f"  ✅ {snap_before.spec.fqname}: 类型={snap_after.data_type}，"
        f"行数={snap_after.row_count}，min/max={snap_after.raw_min!r} ~ {snap_after.raw_max!r}，"
        f"默认值={snap_after.column_default!r}"
    )


def run_migration(db_url: str, apply: bool) -> int:
    print("=" * 78)
    print("ISSUE-006 时间列迁移：text / naive timestamp → timestamptz（UTC 存储）")
    print(f"模式: {'APPLY（会真正执行 ALTER）' if apply else 'DRY-RUN（只读，不写库）'}")
    print(f"数据库: {_safe_db_label(db_url)}")
    print("=" * 78)

    with psycopg.connect(db_url, connect_timeout=15) as conn:
        if not apply:
            conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SHOW TimeZone")
            session_tz = cur.fetchone()[0]
            # 只影响 timestamptz 的「显示」，不影响转换结果（表达式已显式 AT TIME ZONE 'UTC'）；
            # 固定成 UTC 是为了报告里的 min/max 一眼可比，不随本机时区漂。
            cur.execute("SET timezone = 'UTC'")
        print(
            f"会话 TimeZone: {session_tz} → 本脚本改为 UTC 显示"
            "（转换表达式显式按 UTC 解释，不依赖会话时区）\n"
        )

        snapshots: list[ColumnSnapshot] = []
        for spec in COLUMN_SPECS:
            snap = snapshot(conn, spec)
            snapshots.append(snap)
            print(describe(snap))

        pending = [s for s in snapshots if s.data_type != TARGET_TYPE]
        print()
        if not pending:
            print("所有列都已是 timestamptz，无需迁移（幂等）。")
            return 0

        for snap in pending:
            if snap.data_type != snap.spec.source_type:
                raise RuntimeError(
                    f"{snap.spec.fqname} 实际类型是 {snap.data_type!r}，"
                    f"预期 {snap.spec.source_type!r}。不认识的类型不做自动转换，"
                    "请人工确认后再跑（见脚本头部注释）。"
                )
            if snap.suspicious_rows:
                raise RuntimeError(
                    f"{snap.spec.fqname} 有 {snap.suspicious_rows} 行不像 ISO 时间，"
                    "硬转会失败或产生错误时刻；请先人工检查这些值"
                )

        print("待执行语句（按顺序，同一事务内）：")
        for snap in pending:
            print(f"  {snap.spec.alter_sql()};")
            if snap.spec.default_sql():
                print(f"  {snap.spec.default_sql()};")
        print()

        if not apply:
            print("DRY-RUN 结束：没有修改任何数据。")
            print("确认以上类型 / 行数 / min/max 无误后，由人工执行：")
            print(
                f"  DATABASE_URL=... {sys.executable} "
                f"{Path(__file__).relative_to(BASE_DIR)} --apply"
            )
            return 0

        # 整个 APPLY 走同一个事务（连接默认 autocommit=False，前面只读查询已开启事务）：
        # 任何一列转换/复查失败，异常抛出后 `with psycopg.connect(...)` 会整体回滚，
        # 不留下"迁移到一半"的库。
        with conn.cursor() as cur:
            # 拿不到锁就快速失败，不要跟在线抓取/分析任务死等
            cur.execute("SET LOCAL lock_timeout = '15s'")
        for snap in pending:
            print(f"→ {snap.spec.alter_sql()};")
            with conn.cursor() as cur:
                cur.execute(snap.spec.alter_sql())
                default_sql = snap.spec.default_sql()
                if default_sql:
                    cur.execute(default_sql)
            suffix = (
                f"，DEFAULT {snap.spec.target_default}"
                if snap.spec.target_default
                else ""
            )
            print(f"  ✅ {snap.spec.fqname} 已转为 {TARGET_TYPE}{suffix}")

        # 断言在同一个事务里做：对不上就整体回滚。
        print("\n转换后复查（类型 + 行数 + UTC min/max）：")
        for snap in snapshots:
            verify_after_apply(snap, conn)

        conn.commit()

    print("\n迁移完成，已提交。")
    return 0


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把 ISSUE-006 涉及的时间列迁移成 timestamptz（默认 dry-run）"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正执行 ALTER（生产库必须先经人工确认；默认只读）",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="覆盖 DATABASE_URL（例如指向本地测试库做演练）",
    )
    args = parser.parse_args(argv)
    db_url = args.database_url or DEFAULT_DB_URL
    return run_migration(db_url, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
