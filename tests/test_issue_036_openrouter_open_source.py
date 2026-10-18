"""ISSUE-036：OpenRouter 行的「开源/闭源」不能只看 `:free`。

历史实现：`is_open_source = True if ":free" in model_id else False`，于是所有付费的
开放权重模型（DeepSeek、Llama、Qwen…）在 OpenRouter 行上都被标成「闭源」，
与同一模型的 HF 行（license:mit → 开源）自相矛盾——页面上会出现
「DeepSeek: DeepSeek V4.1 Flash 1017」打着「闭源」标记的卡片。

修法：用 OpenRouter 返回的 `hugging_face_id`（指向模型在 HF 上的仓库）作为
「开放权重」的证据；`:free` 是计费属性，不再参与判断。
"""

from __future__ import annotations

from src.scraper import fetch_models_openrouter as orx


def _raw(**overrides) -> dict:
    payload = {
        "id": "deepseek/deepseek-v4.1-flash-1017",
        "name": "DeepSeek: DeepSeek V4.1 Flash 1017",
        "created": 1_760_000_000,
        "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
    }
    payload.update(overrides)
    return payload


def test_hugging_face_id_marks_open_source_even_when_paid():
    raw = _raw(hugging_face_id="deepseek-ai/DeepSeek-V4.1-Flash-1017")
    assert orx.infer_is_open_source(raw) is True
    record = orx.to_record(raw)
    assert record.is_open_source is True


def test_paid_model_without_hugging_face_id_stays_closed():
    raw = _raw(id="anthropic/claude-haiku-5.5", name="Anthropic: Claude Haiku 5.5")
    assert orx.infer_is_open_source(raw) is False
    assert orx.to_record(raw).is_open_source is False


def test_free_suffix_alone_is_not_evidence_of_open_weights():
    """:free 只是计费档位；没有 hf_id 时不能据此判开源。"""
    raw = _raw(id="somevendor/closed-model:free", name="SomeVendor: Closed Model")
    assert orx.infer_is_open_source(raw) is False


def test_free_suffix_with_hugging_face_id_is_open():
    raw = _raw(id="xingchen-agi/xing4.0-29b-a4b:free", hugging_face_id="XingChen-AGI/Xing4.0-29B-A4B")
    assert orx.to_record(raw).is_open_source is True


def test_blank_or_non_string_hugging_face_id_is_treated_as_absent():
    for value in (None, "", "   ", 123):
        assert orx.infer_is_open_source(_raw(hugging_face_id=value)) is False
