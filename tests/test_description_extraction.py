"""模型简介抽取与 README 拉取的测试。

**不需要数据库，也不发真实网络请求**（网络层用 monkeypatch 打桩）。

背景：HF 把模型描述从卡片元数据里移除了（cardData 为 null、ModelInfo 无
description 属性、ModelCardData 无 summary），简介只能从仓库 README.md 正文抽。
这里锁住的就是那个抽取逻辑 —— 它必须能从真实模型卡那种"一堆徽章 + 标题 +
HTML 容器"的排版里稳定取出那段人话。
"""
from __future__ import annotations

import pytest
import requests

from src.scraper import fetch_models as fm


# --------------------------------------------------------------------------
# 抽取逻辑
# --------------------------------------------------------------------------

REAL_README = """---
license: mit
library_name: transformers
pipeline_tag: image-text-to-text
tags:
- deepseek_v41
---

<div align="center">
  <img src="https://example.com/logo.png" width="200"/>
</div>

# DeepSeek-V4.1-Flash

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

We introduce **DeepSeek-V4.1-Flash**, a multimodal Mixture-of-Experts (MoE) model
with 552B backbone parameters.

## Architecture
Architecture details go here.
"""


def test_extracts_first_prose_paragraph_from_realistic_readme():
    got = fm.extract_description_from_readme(REAL_README)
    assert got.startswith("We introduce DeepSeek-V4.1-Flash, a multimodal")
    assert "**" not in got, "markdown 强调符号应该被剥掉"
    assert "\n" not in got, "应当压缩成单行"


def test_yaml_front_matter_is_removed():
    text = "---\nlicense: mit\n---\n" + "x" * 40
    assert fm.extract_description_from_readme(text) == "x" * 40


def test_only_consumes_one_front_matter_block():
    """正文里再出现 --- 分隔线时，不应把后面的内容当 front matter 一起吃掉。"""
    text = "---\nlicense: mit\n---\n" + "A" * 35 + "\n\n---\n\n" + "B" * 35
    assert fm.extract_description_from_readme(text) == "A" * 35


def test_badges_and_html_are_skipped():
    text = """
<div align="center">
<img src="a.png"/>
</div>

[![Build](https://img.shields.io/badge/x.svg)](https://ci)
![cover](https://example.com/c.png)
# Title

This is the actual description of the model and it is long enough.
"""
    got = fm.extract_description_from_readme(text)
    assert got == "This is the actual description of the model and it is long enough."


def test_headings_lists_quotes_tables_are_skipped():
    text = """
# A Very Long Heading That Would Otherwise Pass The Length Check
## Another Long Heading To Be Safe Here
- a list item that is definitely longer than thirty chars
> a blockquote that is also longer than thirty characters
| col | col2 | col3 | col4 | col5 | col6 |
--- 
The real paragraph lives here and is comfortably long enough.
"""
    assert fm.extract_description_from_readme(text).startswith("The real paragraph lives here")


def test_html_tags_are_stripped():
    text = "<p>This paragraph is wrapped in an HTML tag and is plenty long.</p>"
    assert fm.extract_description_from_readme(text) == (
        "This paragraph is wrapped in an HTML tag and is plenty long."
    )


def test_markdown_link_keeps_visible_text():
    text = "See the [official report](https://example.com/report) for the full benchmark results."
    got = fm.extract_description_from_readme(text)
    assert got == "See the official report for the full benchmark results."
    assert "https://" not in got


def test_short_lines_are_skipped():
    """标题残留、单个词、分隔符这类短行不应被当成简介。"""
    text = "DeepSeek-V4.1-Flash\n\nMIT\n\n" + "y" * 30
    assert fm.extract_description_from_readme(text) == "y" * 30


def test_truncates_to_max_chars():
    text = "z" * 500
    assert len(fm.extract_description_from_readme(text, max_chars=100)) == 100
    # 默认上限来自 DESCRIPTION_MAX_CHARS
    assert len(fm.extract_description_from_readme(text)) == fm.DESCRIPTION_MAX_CHARS


@pytest.mark.parametrize("value", [None, "", "   \n\n  "])
def test_empty_input_returns_empty_string(value):
    assert fm.extract_description_from_readme(value) == ""


def test_readme_without_prose_returns_empty_string():
    """只有徽章和标题的模型卡抽不出东西 —— 调用方据此保留旧值。"""
    text = """
<div align="center"><img src="logo.png"/></div>
# Model
## Usage
"""
    assert fm.extract_description_from_readme(text) == ""


def test_crlf_line_endings_are_handled():
    text = "---\r\nlicense: mit\r\n---\r\n" + "c" * 40
    assert fm.extract_description_from_readme(text) == "c" * 40


def test_bom_is_stripped():
    text = "\ufeff---\nlicense: mit\n---\n" + "d" * 40
    assert fm.extract_description_from_readme(text) == "d" * 40


# --------------------------------------------------------------------------
# 网络层（打桩）
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code

    @property
    def ok(self) -> bool:
        return self.status_code < 400


def test_fetch_model_description_hits_the_raw_readme_url(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs.get("headers", {})
        return _FakeResponse("---\nlicense: mit\n---\n" + "e" * 40)

    monkeypatch.setattr(requests, "get", fake_get)
    got = fm.fetch_model_description("acme/model-1")

    assert seen["url"] == "https://huggingface.co/acme/model-1/raw/main/README.md"
    assert got == "e" * 40
    assert "Authorization" not in seen["headers"], "没给 token 时不应带认证头"


def test_fetch_model_description_sends_token_when_provided(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen["headers"] = kwargs.get("headers", {})
        return _FakeResponse("f" * 40)

    monkeypatch.setattr(requests, "get", fake_get)
    fm.fetch_model_description("acme/model-1", token="hf_secret")
    assert seen["headers"]["Authorization"] == "Bearer hf_secret"


def test_fetch_model_description_returns_empty_on_404(monkeypatch):
    """没有 README 的仓库会 404 —— 正常情况，不该抛异常。"""
    monkeypatch.setattr(requests, "get", lambda url, **kw: _FakeResponse("", status_code=404))
    assert fm.fetch_model_description("acme/no-readme") == ""


def test_fetch_model_description_returns_empty_on_network_error(monkeypatch):
    def boom(url, **kwargs):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(requests, "get", boom)
    assert fm.fetch_model_description("acme/model-1") == ""


def test_fetch_model_description_returns_empty_when_readme_has_no_prose(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, **kw: _FakeResponse("# Title\n"))
    assert fm.fetch_model_description("acme/model-1") == ""


# --------------------------------------------------------------------------
# 批量拉取
# --------------------------------------------------------------------------

def test_fetch_descriptions_collects_only_successes(monkeypatch):
    def fake_get(url, **kwargs):
        if "good" in url:
            return _FakeResponse("g" * 40)
        if "no-readme" in url:
            return _FakeResponse("", status_code=404)
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(requests, "get", fake_get)
    got = fm.fetch_descriptions(["acme/good", "acme/no-readme", "acme/broken"])

    assert list(got.keys()) == ["acme/good"]
    assert got["acme/good"] == "g" * 40


def test_fetch_descriptions_skips_everything_when_disabled(monkeypatch):
    monkeypatch.setattr(fm, "FETCH_DESCRIPTIONS", False)
    called = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: called.append(url) or _FakeResponse())

    assert fm.fetch_descriptions(["acme/one", "acme/two"]) == {}
    assert called == [], "关闭后不应发出任何请求"


def test_fetch_descriptions_handles_empty_input(monkeypatch):
    called = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: called.append(url) or _FakeResponse())
    assert fm.fetch_descriptions([]) == {}
    assert called == []


# --------------------------------------------------------------------------
# to_record 接线
# --------------------------------------------------------------------------

class _StubInfo:
    def __init__(self, model_id: str):
        self.modelId = model_id
        self.cardData = None          # 现状：HF 一律返回 null
        self.tags = ["transformers"]
        self.created_at = None
        self.lastModified = None
        self.downloads = 1
        self.likes = 1
        self.private = False


def test_to_record_uses_provided_description():
    record = fm.to_record("acme", _StubInfo("acme/m"), description="hello world")
    assert record.description == "hello world"


def test_to_record_falls_back_to_card_data_when_not_provided():
    info = _StubInfo("acme/m")
    info.cardData = {"summary": "from card data"}
    assert fm.to_record("acme", info).description == "from card data"


def test_to_record_truncates_to_max_chars():
    record = fm.to_record("acme", _StubInfo("acme/m"), description="x" * 999)
    assert len(record.description) == fm.DESCRIPTION_MAX_CHARS


def test_to_record_without_any_description_is_empty():
    """这是修复前的常态：cardData 为 null 且无 description 属性。"""
    assert fm.to_record("acme", _StubInfo("acme/m")).description == ""
