"""ISSUE-030 回归测试：OpenRouter 抓取必须「先白名单过滤、后 limit 截断」。

被守的行为：`OPENROUTER_DAILY_FETCH_LIMIT` 只截断**已命中白名单**的模型；
上游模型总数超过 limit 时，排在窗口后面的白名单条目一条都不能丢，真的截断则必须告警。

本文件**不联网、不碰数据库**：上游响应、DB 连接、写库全部打桩。
"""
from __future__ import annotations

import contextlib
import logging

import pytest

try:
    from src.scraper import fetch_models_openrouter as om
except ModuleNotFoundError:  # pragma: no cover
    pytest.skip("src.scraper 依赖不可用（缺 psycopg/requests/dotenv）", allow_module_level=True)

LOGGER_NAME = "silicon_river.fetch.openrouter"

# 与 .env.example 的白名单口径一致：存的是「展示名」（name 字段冒号前那段的小写）。
# 只列 payload 里真的出现的厂商：ISSUE-032 之后，「白名单条目 0 命中」会打 WARNING，
# 列上 mistral / spacexai 会让本文件里多处 `_warning_records(caplog) == []` 误报失败。
WHITELIST = ["openai", "mancer"]

# 复刻 issue 里的真实尾部：6 条命中白名单，3 条不命中，全部排在第 462 条之后。
TAIL_MODELS = [
    {"id": "filler/late-0", "name": "Filler Late 0: Model"},
    {"id": "openai/gpt-3.5-turbo-instruct", "name": "OpenAI: GPT-3.5 Turbo Instruct"},
    {"id": "openai/gpt-3.5-turbo-16k", "name": "OpenAI: GPT-3.5 Turbo 16K"},
    {"id": "mancer/weaver", "name": "Mancer: Weaver"},
    {"id": "filler/late-1", "name": "Filler Late 1: Model"},
    {"id": "filler/late-2", "name": "Filler Late 2: Model"},
    {"id": "openai/gpt-3.5-turbo", "name": "OpenAI: GPT-3.5 Turbo"},
    {"id": "openai/gpt-3.5-turbo:batch", "name": "OpenAI: GPT-3.5 Turbo Batch"},
    {"id": "openai/gpt-4", "name": "OpenAI: GPT-4"},
]
TAIL_WHITELISTED_IDS = [
    "openai/gpt-3.5-turbo-instruct",
    "openai/gpt-3.5-turbo-16k",
    "mancer/weaver",
    "openai/gpt-3.5-turbo",
    "openai/gpt-3.5-turbo:batch",
    "openai/gpt-4",
]


def _raw(model_id: str, name: str) -> dict:
    return {"id": model_id, "name": name, "created": 1_700_000_000, "pricing": {"prompt": "0"}}


def _filler_models(count: int) -> list[dict]:
    """构造 count 条**不命中白名单**的原始条目（show 名的冒号前是 Filler N）。"""
    return [_raw(f"filler/model-{i}", f"Filler {i}: Model {i}") for i in range(count)]


def _upstream_payload() -> list[dict]:
    """462 条不命中 + 9 条尾部（其中 6 条命中）= 471 条，对齐 2026-10-18 实测上游。"""
    return _filler_models(462) + TAIL_MODELS


def _warning_records(caplog) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.WARNING
    ]


# ---------------------------------------------------------------------------
# 1) select_models：截断顺序与告警
# ---------------------------------------------------------------------------


def test_tail_whitelisted_models_survive_upstream_larger_than_limit(caplog):
    """上游 471 条 > 窗口 462 条：排在窗口之后的 6 条白名单模型一条都不能少。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    selected, stats = om.select_models(_upstream_payload(), WHITELIST, limit=462)

    selected_ids = [item["id"] for item in selected]
    assert selected_ids == TAIL_WHITELISTED_IDS
    # 过滤发生在截断之前 → 命中数 6 < 窗口 462，压根没截断，所以不能有 WARNING
    assert stats == {"upstream_total": 471, "matched_total": 6, "selected": 6, "dropped": 0}
    assert _warning_records(caplog) == []


def test_limit_counts_whitelisted_results_not_raw_entries(caplog):
    """窗口只对「已过滤结果」生效：白名单条目再靠后也不会被窗口挤掉。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    raw = _filler_models(10) + [_raw("openai/at-the-end", "OpenAI: At The End")]

    # 这里只放 openai：ISSUE-032 之后白名单里的 mancer 在本 payload 里 0 命中会打
    # WARNING，会污染下面「不能有 WARNING」的断言。
    selected, stats = om.select_models(raw, ["openai"], limit=2)

    assert [item["id"] for item in selected] == ["openai/at-the-end"]
    assert stats["upstream_total"] == 11
    assert stats["matched_total"] == 1
    assert stats["dropped"] == 0
    assert _warning_records(caplog) == []


def test_real_truncation_emits_warning_with_counts(caplog):
    """真的截断（命中数 > 窗口）时必须 WARNING，并说明上游 / 命中 / 窗口 / 丢弃数。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    raw = _filler_models(10) + [
        _raw("openai/a", "OpenAI: A"),
        _raw("openai/b", "OpenAI: B"),
        _raw("mancer/c", "Mancer: C"),
    ]

    selected, stats = om.select_models(raw, WHITELIST, limit=1)

    assert len(selected) == 1
    assert stats == {"upstream_total": 13, "matched_total": 3, "selected": 1, "dropped": 2}

    warnings = _warning_records(caplog)
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "上游 13 条" in message
    assert "白名单命中 3 条" in message
    assert "窗口 1 条" in message
    assert "丢弃 2 条" in message


@pytest.mark.parametrize("limit", [None, 0, -1])
def test_no_truncation_when_limit_disabled(limit, caplog):
    """limit 为 None / 0 / 负数 = 不截断（配置里 0 是推荐值）。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    selected, stats = om.select_models(_upstream_payload(), WHITELIST, limit=limit)

    assert [item["id"] for item in selected] == TAIL_WHITELISTED_IDS
    assert stats["dropped"] == 0
    assert _warning_records(caplog) == []


def test_empty_whitelist_means_no_filter(caplog):
    """白名单留空 = 全收，此时 limit 才是对上游总数的截断（仍要告警）。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    selected, stats = om.select_models(_upstream_payload(), [], limit=462)

    assert len(selected) == 462
    assert stats == {"upstream_total": 471, "matched_total": 471, "selected": 462, "dropped": 9}
    assert len(_warning_records(caplog)) == 1


def test_whitelist_match_is_case_insensitive():
    """白名单大小写不敏感（get_providers 会小写化，provider key 本身也是小写）。"""
    raw = [_raw("openai/gpt-4", "OpenAI: GPT-4")]

    selected, _stats = om.select_models(raw, om.get_providers("OpenAI,  MANCER "), limit=10)

    assert [item["id"] for item in selected] == ["openai/gpt-4"]


# ---------------------------------------------------------------------------
# 2) fetch_and_store：真实管线路径（DB 打桩，不写库）
# ---------------------------------------------------------------------------


class _FakeStore:
    """记录 save_models / upsert_provider 的调用，替代真库。"""

    def __init__(self) -> None:
        self.saved: list[str] = []
        self.providers: list[str] = []

    def upsert_provider(self, conn, provider_id, display_name=None, avatar_url=None) -> None:
        self.providers.append(provider_id)

    def save_models(self, conn, provider, records) -> tuple[int, int]:
        records = list(records)
        self.saved.extend(record.model_id for record in records)
        return len(records), len(records)


@pytest.fixture()
def patched_pipeline(monkeypatch):
    """把上游、DB、写库全部换成假的，只保留 fetch_and_store 自己的编排逻辑。"""
    fake = _FakeStore()
    monkeypatch.setenv("PROVIDERS_OPENROUTER", ",".join(WHITELIST))
    monkeypatch.setattr(om, "fetch_remote_models", lambda endpoint: _upstream_payload())
    monkeypatch.setattr(om, "ensure_db", lambda *args, **kwargs: contextlib.nullcontext(object()))
    monkeypatch.setattr(om, "upsert_provider", fake.upsert_provider)
    monkeypatch.setattr(om, "save_models", fake.save_models)
    return fake


def test_fetch_and_store_keeps_every_tail_whitelisted_model(patched_pipeline, caplog):
    """整条管线（含 limit=462 的日常抓取）跑完，尾部白名单模型全部入库。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    summary = om.fetch_and_store(limit=462)

    assert sorted(patched_pipeline.saved) == sorted(TAIL_WHITELISTED_IDS)
    assert not any(model_id.startswith("filler/") for model_id in patched_pipeline.saved)
    assert summary == {"openai": (5, 5), "mancer": (1, 1)}
    assert _warning_records(caplog) == []


def test_fetch_and_store_warns_and_keeps_first_matched_models(patched_pipeline, caplog):
    """管线里设了过小的窗口：只砍已命中模型，并且必须告警（不许静默）。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    summary = om.fetch_and_store(limit=2)

    assert patched_pipeline.saved == ["openai/gpt-3.5-turbo-instruct", "openai/gpt-3.5-turbo-16k"]
    assert summary == {"openai": (2, 2)}
    warnings = _warning_records(caplog)
    assert len(warnings) == 1
    assert "丢弃 4 条" in warnings[0].getMessage()


# ---------------------------------------------------------------------------
# 3) 过滤 key 与入库 provider 必须同口径（防止两处解析分叉）
# ---------------------------------------------------------------------------


def test_provider_key_for_matches_record_provider():
    for item in _upstream_payload():
        assert om.provider_key_for(item) == om.to_record(item).provider
