"""ISSUE-034 回归测试：HF pipeline_tag 过滤 / 分阶段计时 / models.source 写入。

被守的行为：
  ① `client.list_models` 默认带 `pipeline_tag="text-generation"`（ISSUE-031 前置：
     不带 filter 时 HF 会把该 org 的全部仓库拉回来，nvidia 975 个里只有 269 个是
     text-generation，视觉/语音仓库会污染时间轴）；`HF_PIPELINE_TAG=""` 时不带这个 kwarg。
  ② 每个 provider 结束（含异常中断）都要打一条分阶段计时汇总，形如
     `Provider meta-llama 计时: list=53.3s readme=0.2s write=0.9s profile=1.8s 共 56.2s（70 个模型）`。
  ③ 写 `models` 时带上 `source`（huggingface / openrouter），INSERT 列与
     ON CONFLICT UPDATE 的 SET 都要有，供 ISSUE-004 跨源去重使用。

本文件**不联网、不碰数据库**：上游客户端、头像、README 拉取、DB 连接全部打桩，
写库用一个只记录 SQL 与参数的假 cursor。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

try:
    from src.scraper import fetch_models as fm
    from src.scraper import fetch_models_openrouter as om
except ModuleNotFoundError:  # pragma: no cover
    pytest.skip("src.scraper 依赖不可用（缺 psycopg/requests/dotenv）", allow_module_level=True)

HF_LOGGER = "silicon_river.fetch"
OR_LOGGER = "silicon_river.fetch.openrouter"

TIMING_RE = re.compile(
    r"Provider (?P<provider>\S+) 计时(?P<suffix>[^:]*): "
    r"list=(?P<list>\d+\.\ds) readme=(?P<readme>\d+\.\ds) "
    r"write=(?P<write>\d+\.\ds) profile=(?P<profile>\d+\.\ds) "
    r"共 (?P<total>\d+\.\ds)（(?P<count>\d+) 个模型）"
)


# ---------------------------------------------------------------------------
# 假 DB：只记录 SQL / 参数，不连库
# ---------------------------------------------------------------------------
class FakeCursor:
    """记录所有 execute 的 SQL 与参数；`RETURNING (xmax = 0)` 恒返回「新增」。"""

    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []
        self._last_sql = ""

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self._last_sql = " ".join(sql.split())
        self.executions.append((self._last_sql, params))

    def executemany(self, sql: str, rows: object) -> None:
        self.executions.append((" ".join(sql.split()), list(rows) if rows else rows))

    def fetchone(self):
        if "RETURNING (xmax = 0)" in self._last_sql:
            return (True,)
        # resolve_case_variant 的 SELECT：库里没有大小写变体
        return None

    def fetchall(self):
        # load_existing_descriptions：库里没有旧简介
        return []

    def model_upserts(self) -> list[tuple[str, object]]:
        return [
            (sql, params)
            for sql, params in self.executions
            if sql.startswith("INSERT INTO models")
        ]


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.commits = 0

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1


def _make_model(model_id: str):
    created_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    return SimpleNamespace(
        modelId=model_id,
        cardData=None,
        tags=["text-generation"],
        created_at=created_at,
        lastModified=created_at,
        downloads=10,
        likes=2,
        private=False,
    )


class FakeHfClient:
    def __init__(self, models, *, error: Exception | None = None) -> None:
        self.models = models
        self.error = error
        self.list_models_kwargs: dict | None = None

    def list_models(self, **kwargs):
        self.list_models_kwargs = dict(kwargs)
        if self.error is not None:
            raise self.error
        return list(self.models)


def _run_hf_fetch(monkeypatch, models, *, pipeline_tag=None, error=None):
    """跑一遍 `fm.fetch_and_store()`，返回 (FakeClient, FakeConnection)。"""
    conn = FakeConnection()
    client = FakeHfClient(models, error=error)
    monkeypatch.setenv("PROVIDERS", "meta-llama")
    monkeypatch.setenv("HF_TOKEN", "dummy")
    if pipeline_tag is None:
        monkeypatch.delenv("HF_PIPELINE_TAG", raising=False)
    else:
        monkeypatch.setenv("HF_PIPELINE_TAG", pipeline_tag)
    monkeypatch.setattr(fm, "hf_client", lambda: client)
    monkeypatch.setattr(fm, "ensure_db", lambda *a, **k: conn)
    monkeypatch.setattr(
        fm, "resolve_provider_profile", lambda _client, provider: (provider, None)
    )
    monkeypatch.setattr(fm, "download_provider_avatar", lambda _url, _token: (None, None))
    # README 拉取是唯一会放大请求量的地方（每个模型一次 HTTP），这里直接空手而归。
    monkeypatch.setattr(fm, "fetch_descriptions", lambda ids, token=None: {})
    fm.fetch_and_store(limit=10)
    return client, conn


# ---------------------------------------------------------------------------
# ① pipeline_tag 过滤
# ---------------------------------------------------------------------------
def test_list_models_defaults_to_text_generation_filter(monkeypatch):
    """未设置 HF_PIPELINE_TAG 时，默认按 text-generation 过滤。"""
    client, _conn = _run_hf_fetch(monkeypatch, [_make_model("meta-llama/Llama-1")])

    kwargs = client.list_models_kwargs
    assert kwargs is not None
    assert kwargs["pipeline_tag"] == "text-generation"
    assert kwargs["author"] == "meta-llama"
    assert kwargs["limit"] == 10
    assert kwargs["full"] is True


def test_pipeline_tag_env_override(monkeypatch):
    """HF_PIPELINE_TAG 可换成别的 tag（不是写死 text-generation）。"""
    client, _conn = _run_hf_fetch(
        monkeypatch, [_make_model("meta-llama/Llama-1")], pipeline_tag="automatic-speech-recognition"
    )

    assert client.list_models_kwargs["pipeline_tag"] == "automatic-speech-recognition"


def test_empty_pipeline_tag_sends_no_filter_kwarg(monkeypatch):
    """HF_PIPELINE_TAG="" 表示不过滤：连 pipeline_tag 这个 kwarg 都不能传。"""
    client, _conn = _run_hf_fetch(
        monkeypatch, [_make_model("meta-llama/Llama-1")], pipeline_tag=""
    )

    kwargs = client.list_models_kwargs
    assert "pipeline_tag" not in kwargs and "filter" not in kwargs
    assert kwargs["author"] == "meta-llama"


def test_pipeline_tag_logging(monkeypatch, caplog):
    """过滤生效 / 未过滤都要有 INFO 说明，日志里能看出到底过没过。"""
    caplog.set_level(logging.INFO, logger=HF_LOGGER)
    _run_hf_fetch(monkeypatch, [_make_model("meta-llama/Llama-1")])
    assert any(
        "pipeline_tag=text-generation" in record.getMessage() for record in caplog.records
    )

    caplog.clear()
    _run_hf_fetch(monkeypatch, [_make_model("meta-llama/Llama-1")], pipeline_tag="")
    assert any("未过滤" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# ② 分阶段计时日志
# ---------------------------------------------------------------------------
def test_stage_timing_summary_logged(monkeypatch, caplog):
    """结束时必须有一条 list=/readme=/write=/profile= 的汇总行。"""
    caplog.set_level(logging.INFO, logger=HF_LOGGER)
    models = [_make_model(f"meta-llama/Llama-{i}") for i in range(3)]

    _run_hf_fetch(monkeypatch, models)

    summaries = [
        record.getMessage()
        for record in caplog.records
        if "计时" in record.getMessage() and record.name == HF_LOGGER
    ]
    assert len(summaries) == 1, summaries
    match = TIMING_RE.search(summaries[0])
    assert match, summaries[0]
    assert match.group("provider") == "meta-llama"
    assert match.group("suffix") == ""
    assert match.group("count") == "3"


def test_stage_timing_logged_when_interrupted(monkeypatch, caplog):
    """异常退出也要能看出卡在哪一段，且不能改变原有异常语义。"""
    caplog.set_level(logging.INFO, logger=HF_LOGGER)

    with pytest.raises(RuntimeError, match="list boom"):
        _run_hf_fetch(
            monkeypatch,
            [_make_model("meta-llama/Llama-1")],
            error=RuntimeError("list boom"),
        )

    summaries = [record.getMessage() for record in caplog.records if "计时" in record.getMessage()]
    assert len(summaries) == 1, summaries
    match = TIMING_RE.search(summaries[0])
    assert match, summaries[0]
    assert "中断于 list 段" in match.group("suffix")


# ---------------------------------------------------------------------------
# ③ models.source 写入
# ---------------------------------------------------------------------------
def _last_model_upsert(cursor: FakeCursor) -> tuple[str, tuple]:
    upserts = cursor.model_upserts()
    assert upserts, "没有捕获到 INSERT INTO models"
    sql, params = upserts[-1]
    return sql, params


def test_huggingface_write_sets_source(monkeypatch):
    """HF 侧 upsert 的 INSERT 列、参数与 ON CONFLICT SET 都带 source='huggingface'。"""
    _client, conn = _run_hf_fetch(monkeypatch, [_make_model("meta-llama/Llama-1")])

    sql, params = _last_model_upsert(conn.cursor_obj)
    assert "source" in sql.split("VALUES")[0]
    assert "source = COALESCE(NULLIF(models.source, 'unknown'), EXCLUDED.source)" in sql
    assert params[-1] == "huggingface"


def test_openrouter_write_sets_source():
    """OpenRouter 侧 upsert 写 source='openrouter'（同样要有 ON CONFLICT SET）。"""
    conn = FakeConnection()
    record = om.ModelRecord(
        model_id="openai/gpt-4",
        provider="openai",
        model_name="OpenAI: GPT-4",
        description="desc",
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        model_card_url="https://openrouter.ai/models/openai%2Fgpt-4",
        inserted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        price=None,
        is_open_source=False,
        huggingface_rank=None,
    )

    processed, inserted = om.save_models(conn, "openai", [record])

    assert (processed, inserted) == (1, 1)
    sql, params = _last_model_upsert(conn.cursor_obj)
    assert "source" in sql.split("VALUES")[0]
    assert "source = COALESCE(NULLIF(models.source, 'unknown'), EXCLUDED.source)" in sql
    # 参数尾部依次是：source、hf_model_id、hf_model_id、target_id（ISSUE-004 合并用）
    assert params[-4] == "openrouter"
    assert "merged_into" in sql.split("VALUES", 1)[0]
    assert "merged_into = EXCLUDED.merged_into" in sql


def test_source_constants_match_schema_value_domain():
    """值域见 scripts/init_db.py：huggingface / openrouter / unknown。"""
    assert fm.SOURCE_HUGGINGFACE == "huggingface"
    assert fm.SOURCE_OPENROUTER == "openrouter"
    assert fm.SOURCE_UNKNOWN == "unknown"


# ---------------------------------------------------------------------------
# OpenRouter 侧计时（fetch / write 两段）
# ---------------------------------------------------------------------------
def test_openrouter_stage_timing_logged(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=OR_LOGGER)
    conn = FakeConnection()
    payload = [
        {
            "id": "openai/gpt-4",
            "name": "OpenAI: GPT-4",
            "created": 1700000000,
            "pricing": {"prompt": "0.000001"},
        }
    ]
    monkeypatch.setenv("PROVIDERS_OPENROUTER", "openai")
    monkeypatch.setattr(om, "fetch_remote_models", lambda endpoint: payload)
    monkeypatch.setattr(om, "ensure_db", lambda *a, **k: conn)

    om.fetch_and_store()

    summaries = [record.getMessage() for record in caplog.records if "计时" in record.getMessage()]
    assert len(summaries) == 1, summaries
    assert re.search(r"fetch=\d+\.\ds write=\d+\.\ds 共 \d+\.\ds（1 个模型）", summaries[0])
