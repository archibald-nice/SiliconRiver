"""ISSUE-032 回归测试：OpenRouter provider key 解析的回落顺序。

被守的行为（`provider_key_for()` / `extract_provider()`）：
  ① `model_id` 斜杠前缀，但**只有登记在 `PROVIDER_KEY_ALIASES` 里的品牌前缀**才算解析成功；
  ② `name` 里 `Display: Model` 的展示名前缀（AGENTS.md 铁律 12 的白名单口径）；
  ③ 未经别名映射的 id 前缀（`qwen` / `gryphe` / `anthracite-org` / `rekaai` 这类前缀本身即条目）；
  ④ `name` 整串小写（历史兜底）；
  ⑤ `"unknown"`。

旧实现的坑：`name` 没有冒号时直接退化成「整个 name 小写」，于是
`rekaai/reka-edge`（name `Reka Edge`）被解析成 `reka edge`，白名单里的 `rekaai`
永远匹配不上——不报错、不告警，10 条模型整家静默消失。

以及：白名单里一条都没匹配到的条目必须打 WARNING（`select_models()` 内）。

本文件**不联网、不碰数据库**：只用假的 upstream payload 字典。
"""
from __future__ import annotations

import logging

import pytest

try:
    from src.scraper import fetch_models_openrouter as om
except ModuleNotFoundError:  # pragma: no cover
    pytest.skip("src.scraper 依赖不可用（缺 psycopg/requests/dotenv）", allow_module_level=True)

LOGGER_NAME = "silicon_river.fetch.openrouter"

# 2026-10-18 `.env.example` 里 `PROVIDERS_OPENROUTER` 的真实内容（51 条）。
# 这里内嵌一份而不是读文件：断言「真实 id 的 key 落在**用户当前白名单**里」需要一个
# 稳定的参照物；白名单本身是用户决策，本测试不改它。
WHITELIST = [
    "aionlabs", "amazon", "anthracite-org", "anthropic", "arcee ai", "bytedance",
    "bytedance seed", "cohere", "deepseek", "fireworks", "google", "gryphe", "ibm",
    "inception", "inclusionai", "inference.net", "liquidai", "mancer", "meituan",
    "meta", "microsoft", "minimax", "mistral", "moonshotai", "morph", "nex agi",
    "nous", "nvidia", "openai", "perceptron", "perplexity", "poolside", "prismml",
    "qwen", "rekaai", "relace", "sakana", "sao10k", "scaledown", "spacexai", "stepfun",
    "tencent", "thedrummer", "thinking machines", "typesafe", "undi95", "upstage",
    "venice", "writer", "xiaomi", "z.ai",
]

# issue 里点名的、旧实现会吃掉的真实模型：id + 上游 name + 期望 provider key。
BROKEN_MODELS = [
    ("rekaai/reka-edge", "Reka Edge", "rekaai"),
    ("rekaai/reka-flash-3", "Reka Flash 3", "rekaai"),
    ("mistralai/mistral-large", "Mistral Large", "mistral"),
    ("mistralai/mistral-large-2407", "Mistral Large 2407", "mistral"),
    ("qwen/qwen-2.5-coder-32b-instruct", "Qwen2.5 Coder 32B Instruct", "qwen"),
    ("qwen/qwen-2.5-72b-instruct", "Qwen2.5 72B Instruct", "qwen"),
    ("microsoft/wizardlm-2-8x22b", "WizardLM-2 8x22B", "microsoft"),
    ("anthracite-org/magnum-v4-72b", "Magnum v4 72B", "anthracite-org"),
    ("undi95/remm-slerp-l2-13b", "ReMM SLERP 13B", "undi95"),
    ("gryphe/mythomax-l2-13b", "MythoMax 13B", "gryphe"),
]

# 附带的同族缺陷：展示名解析出 `xai`，但白名单里是 `spacexai`。
GROK_LATEST = ("~x-ai/grok-latest", "xAI: Grok Latest", "spacexai")

GROK_EQUIVALENT = ("x-ai/grok-4", "xAI: Grok 4", "spacexai")


def _raw(model_id: str, name: str | None = None) -> dict:
    """最小的上游 payload 条目；`to_record()` 只要求 id/name 之外的东西有默认值。"""
    return {"id": model_id, "name": name if name is not None else model_id}


def _warning_records(caplog) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.WARNING
    ]


# ---------------------------------------------------------------------------
# 1) 回落顺序：name 带冒号 / 不带冒号但 id 前缀命中 / 都解析不出
# ---------------------------------------------------------------------------


def test_display_prefix_used_when_name_has_colon():
    """name 有 `Display:` 前缀时用展示名（铁律 12 的老口径不能丢）。"""
    assert om.provider_key_for(_raw("openai/gpt-4o", "OpenAI: GPT-4o")) == "openai"
    assert om.provider_key_for(_raw("mancer/weaver", "Mancer: Weaver")) == "mancer"
    # 已登记别名也覆盖展示名一侧：`Mistral:` → `mistral`
    assert om.provider_key_for(_raw("mistralai/mistral-large-2407", "Mistral: Mistral Large")) == "mistral"


def test_id_prefix_via_alias_when_name_has_no_colon():
    """name 没有冒号时，已登记的 id 前缀经别名映射解析（旧实现在这里崩掉）。"""
    assert om.provider_key_for(_raw("mistralai/mistral-large", "Mistral Large")) == "mistral"
    assert om.provider_key_for(_raw("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B Instruct")) == "meta"
    assert om.provider_key_for(_raw("z-ai/glm-4.5", "GLM 4.5")) == "z.ai"
    assert om.provider_key_for(_raw("liquid/lfm-2-24b", "LFM 2 24B")) == "liquidai"
    assert om.provider_key_for(_raw("nousresearch/hermes-4-70b", "Hermes 4 70B")) == "nous"


def test_unregistered_id_prefix_is_its_own_key_when_whitelisted():
    """前缀本身就是白名单条目（`qwen` / `gryphe` / `anthracite-org` / `rekaai`）。"""
    for model_id, name, expected in BROKEN_MODELS:
        if expected != model_id.split("/", 1)[0]:
            continue
        assert om.provider_key_for(_raw(model_id, name)) == expected


def test_unregistered_prefix_does_not_beat_display_name():
    """未登记前缀是 org 命名空间，不是品牌——展示名优先（否则反向丢掉老模型）。"""
    # `cognitivecomputations` 不在白名单里，展示名 `Venice:` 才是它真正的 provider
    assert om.provider_key_for(
        _raw("cognitivecomputations/dolphin-mistral-24b-venice-edition", "Venice: Uncensored")
    ) == "venice"
    # `openrouter` 是转售路由命名空间，不进白名单也不该被 id 前缀放行
    assert om.provider_key_for(_raw("openrouter/auto", "Auto Router")) == "openrouter"


def test_falls_back_to_id_prefix_then_lowercased_name():
    """③ 未登记前缀本身直接当 key；只有连前缀都没有时才退回 ④ 整串 name 小写。"""
    # 未登记前缀（品牌也没登记）= 身份映射，不可能是「整个 name 小写」
    assert om.provider_key_for(_raw("some-new-lab/foo-1", "Foo-1 Preview")) == "some-new-lab"
    # id 没有斜杠 → 没有前缀可用 → 退回历史行为（整串 name 小写）
    assert om.provider_key_for({"id": "foo-1", "name": "Foo-1 Preview"}) == "foo-1 preview"
    # 没有 name 字段时用 id 兜底
    assert om.provider_key_for({"id": "some-new-lab/foo-2"}) == "some-new-lab"


def test_unknown_when_payload_is_empty():
    assert om.provider_key_for({"id": "", "name": ""}) == "unknown"
    assert om.extract_provider(None, None) == "unknown"
    assert om.extract_provider("   ", None) == "unknown"


def test_tilde_latest_alias_resolves_through_registered_prefix():
    """`~x-ai/grok-latest`：`~` 与 `x-ai` 都要处理，最终落到 `spacexai`。"""
    model_id, name, expected = GROK_LATEST
    assert om.provider_key_for(_raw(model_id, name)) == expected
    assert om.provider_key_for(_raw(*GROK_EQUIVALENT[:2])) == GROK_EQUIVALENT[2]
    assert om._id_prefix("~x-ai/grok-latest") == "x-ai"


# ---------------------------------------------------------------------------
# 2) issue 点名的那批真实模型：key 必须落在白名单里
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id,name,expected", BROKEN_MODELS + [GROK_LATEST])
def test_real_broken_models_now_match_whitelist(model_id, name, expected):
    key = om.provider_key_for(_raw(model_id, name))
    assert key == expected, f"{model_id} 解析成 {key!r}，期望 {expected!r}"
    assert key in WHITELIST, f"{key!r} 不在 PROVIDERS_OPENROUTER 白名单里，模型会被静默过滤"


def test_provider_key_matches_record_provider():
    """过滤用的 key 必须与入库写的 provider 同口径，否则过滤放行、入库算别家。"""
    for model_id, name, _ in BROKEN_MODELS + [GROK_LATEST, GROK_EQUIVALENT]:
        raw = _raw(model_id, name)
        assert om.provider_key_for(raw) == om.to_record(raw).provider


def test_alias_table_targets_are_all_in_whitelist():
    """别名映射的目标必须真的是白名单条目，否则映射了也没用。"""
    targets = set(om.PROVIDER_KEY_ALIASES.values())
    assert targets <= set(WHITELIST), sorted(targets - set(WHITELIST))


# ---------------------------------------------------------------------------
# 3) 白名单条目 0 命中必须告警（ISSUE-032 修法 3）
# ---------------------------------------------------------------------------


def test_zero_hit_whitelist_entry_warns(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    raw = [
        _raw("openai/gpt-4o", "OpenAI: GPT-4o"),
        _raw("qwen/qwen-2.5-72b-instruct", "Qwen2.5 72B Instruct"),
    ]

    selected, stats = om.select_models(raw, ["openai", "qwen", "rekaai"])

    assert stats["matched_total"] == 2
    assert [item["id"] for item in selected] == ["openai/gpt-4o", "qwen/qwen-2.5-72b-instruct"]
    warnings = _warning_records(caplog)
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "rekaai" in message
    assert "openai" not in message and "qwen" not in message


def test_zero_hit_warning_lists_every_missing_entry_once(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    raw = [_raw("openai/gpt-4o", "OpenAI: GPT-4o")]

    om.select_models(raw, ["openai", "gryphe", "gryphe", "undi95"])

    warnings = _warning_records(caplog)
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "2 个条目" in message          # 去重后是 2 个，不是 3 个
    assert message.count("gryphe") == 1
    assert "undi95" in message


def test_no_zero_hit_warning_when_every_entry_matches(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    raw = [
        _raw("openai/gpt-4o", "OpenAI: GPT-4o"),
        _raw("gryphe/mythomax-l2-13b", "MythoMax 13B"),
        # 不用 `~x-ai/grok-latest`：那是 ISSUE-004 之后要跳过的别名 id，
        # 留着它会让 spacexai 在本 payload 里 0 命中，测不到「全命中不告警」。
        _raw("x-ai/grok-4", "xAI: Grok 4"),
    ]

    _, stats = om.select_models(raw, ["openai", "gryphe", "spacexai"])

    assert stats["matched_total"] == 3
    assert _warning_records(caplog) == []


def test_empty_filter_never_warns_about_zero_hit(caplog):
    """留空白名单 = 不过滤，此时没有「0 命中条目」这个概念。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    selected, stats = om.select_models([_raw("openai/gpt-4o", "OpenAI: GPT-4o")], [])

    assert stats == {
        "upstream_total": 1,
        "matched_total": 1,
        "selected": 1,
        "dropped": 0,
        "skipped_variants": 0,
    }
    assert len(selected) == 1
    assert _warning_records(caplog) == []


def test_zero_hit_warning_coexists_with_limit_truncation(caplog):
    """0 命中告警不能顶替 ISSUE-030 的截断告警，两者各管各的。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    raw = [_raw(f"openai/model-{i}", f"OpenAI: Model {i}") for i in range(5)]

    _, stats = om.select_models(raw, ["openai", "nope-lab"], limit=2)

    assert stats["selected"] == 2
    assert stats["dropped"] == 3
    messages = [record.getMessage() for record in _warning_records(caplog)]
    assert any("nope-lab" in message for message in messages)
    assert any("丢弃" in message for message in messages)
