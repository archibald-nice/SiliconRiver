"""provider_logos 的单测：映射表覆盖、候选顺序、下载校验、dry-run 不写库。

全部用假的 `requests.Session` / `Response`，绝不触网——`tests/conftest.py` 的
autouse fixture 会把 `socket.connect` 掐掉，漏一个真请求就是 RuntimeError。
"""
from __future__ import annotations

import requests
import pytest

from scripts import fill_provider_avatars as filler
from src.scraper import provider_logos as pl

# 数据库里 `SELECT DISTINCT provider FROM models` 的 54 个值（2026-10 快照）。
# 写死在测试里而不是从 YAML 读回来再比：那是拿 YAML 验 YAML，等于没验。
DB_PROVIDERS = [
    "google",
    "microsoft",
    "Qwen",
    "tencent",
    "zai-org",
    "openai",
    "deepseek-ai",
    "mistralai",
    "meta-llama",
    "qwen",
    "anthropic",
    "01-ai",
    "baichuan-inc",
    "mistral",
    "z.ai",
    "deepseek",
    "meta",
    "nvidia",
    "moonshotai",
    "minimax",
    "spacexai",
    "cohere",
    "aionlabs",
    "bytedance seed",
    "perplexity",
    "amazon",
    "xiaomi",
    "thinking machines",
    "sakana",
    "poolside",
    "sao10k",
    "stepfun",
    "inclusionai",
    "thedrummer",
    "upstage",
    "nous",
    "morph",
    "nex agi",
    "liquidai",
    "perceptron",
    "inference.net",
    "inception",
    "relace",
    "scaledown",
    "ibm",
    "fireworks",
    "prismml",
    "typesafe",
    "mancer",
    "venice",
    "writer",
    "arcee ai",
    "bytedance",
    "meituan",
]

SVG_URL = pl.LOBEHUB_SVG_TEMPLATE.format(slug="openai")
PNG_URL = pl.LOBEHUB_PNG_TEMPLATE.format(slug="openai")
GITHUB_URL = pl.GITHUB_TEMPLATE.format(org="openai")
FAVICON_URL = pl.FAVICON_TEMPLATE.format(domain="openai.com")


class FakeResponse:
    """只实现被测代码用到的字段：status_code / headers / content / close。"""

    def __init__(
        self,
        *,
        status_code: int = 200,
        content: bytes = b"",
        content_type: str | None = "image/png",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = dict(headers or {})
        if content_type is not None:
            self.headers.setdefault("Content-Type", content_type)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """按 URL 返回预置响应；没预置就报错，逼测试显式声明每一次请求。"""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.requested: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def get(self, url: str, **kwargs):
        self.requested.append(url)
        self.calls.append((url, kwargs))
        response = self.responses.get(url)
        if response is None:
            raise AssertionError(
                f"测试没有为 {url} 准备假响应（真实网络已被 conftest 禁止）"
            )
        if isinstance(response, Exception):
            raise response
        return response


def _openai_spec(**overrides) -> pl.ProviderLogoSpec:
    data = {
        "provider": "openai",
        "display_name": "OpenAI",
        "lobe_slug": "openai",
        "github_org": "openai",
        "domain": "openai.com",
    }
    data.update(overrides)
    return pl.ProviderLogoSpec(**data)


# ---------------------------------------------------------------------------
# 映射表本身
# ---------------------------------------------------------------------------
def test_load_logo_map_covers_every_db_provider() -> None:
    specs = pl.load_logo_map()

    assert len(specs) == 54
    assert sorted(specs) == sorted(DB_PROVIDERS)
    # 大小写敏感：Qwen 与 qwen、zai-org 与 z.ai 是各自独立的行，不能被归一化合并
    assert "Qwen" in specs and "qwen" in specs
    assert specs["Qwen"] is not specs["qwen"]

    for provider in DB_PROVIDERS:
        spec = specs[provider]
        candidates = pl.resolve_logo_sources(spec)
        if spec.enabled:
            assert candidates, f"{provider} 标记可用却没有任何候选来源"
        else:
            assert candidates == []


def test_load_logo_map_missing_file_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="映射表不存在"):
        pl.load_logo_map(tmp_path / "not-there.yaml")


def test_load_logo_map_rejects_duplicate_provider(tmp_path) -> None:
    path = tmp_path / "dup.yaml"
    path.write_text(
        "- provider: openai\n  lobe_slug: openai\n"
        "- provider: openai\n  github_org: openai\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="重复"):
        pl.load_logo_map(path)


def test_real_map_marks_personal_avatars_and_unfindable_as_disabled() -> None:
    specs = pl.load_logo_map()

    # thedrummer 是真人照片；nex agi 三源都查不到（favicon 只返回默认地球图）
    for provider in ("thedrummer", "nex agi"):
        assert specs[provider].enabled is False
        assert pl.resolve_logo_sources(specs[provider]) == []


@pytest.mark.parametrize("provider", ["gryphe", "undi95", "thedrummer"])
def test_disabled_personal_avatar_specs_return_no_candidates(provider: str) -> None:
    """真人头像必须 enabled=false，不能靠"下一级来源"兜底抓到照片。

    gryphe / undi95 当前不在数据库的 54 个 provider 里（报告里排除，库里没有行），
    这里用等价 spec 守住行为：将来有人把这两家加回映射表时，测试会提醒他们
    必须写 enabled: false。
    """
    spec = pl.ProviderLogoSpec(provider=provider, github_org=provider, enabled=False)
    assert pl.resolve_logo_sources(spec) == []


# ---------------------------------------------------------------------------
# 候选顺序与回落
# ---------------------------------------------------------------------------
def test_candidate_order_is_lobehub_then_github_then_favicon() -> None:
    labels = [candidate.source for candidate in pl.resolve_logo_sources(_openai_spec())]
    assert labels == ["lobehub-svg", "lobehub-png", "github", "favicon"]


def test_lobehub_svg_hit_does_not_try_github() -> None:
    session = FakeSession(
        {SVG_URL: FakeResponse(content=b"<svg/>", content_type="image/svg+xml")}
    )

    result = pl.pick_best_logo(_openai_spec(), session=session)

    assert result == (b"<svg/>", "image/svg+xml", "lobehub-svg")
    assert session.requested == [SVG_URL]
    # GitHub 头像与 Google favicon 都靠跳转拿图，必须允许 redirect
    assert session.calls[0][1]["allow_redirects"] is True


def test_lobehub_404_falls_back_to_github() -> None:
    session = FakeSession(
        {
            SVG_URL: FakeResponse(status_code=404, content_type="text/plain", content=b"404"),
            PNG_URL: FakeResponse(status_code=404, content_type="text/plain", content=b"404"),
            GITHUB_URL: FakeResponse(content=b"\x89PNG-github", content_type="image/png"),
        }
    )

    result = pl.pick_best_logo(_openai_spec(), session=session)

    assert result == (b"\x89PNG-github", "image/png", "github")
    assert session.requested == [SVG_URL, PNG_URL, GITHUB_URL]


def test_github_404_falls_back_to_favicon() -> None:
    session = FakeSession(
        {
            SVG_URL: FakeResponse(status_code=404, content_type="text/plain", content=b"404"),
            PNG_URL: FakeResponse(status_code=404, content_type="text/plain", content=b"404"),
            GITHUB_URL: FakeResponse(status_code=404, content_type="text/plain", content=b"404"),
            FAVICON_URL: FakeResponse(content=b"\x89PNG-favicon", content_type="image/png"),
        }
    )

    result = pl.pick_best_logo(_openai_spec(), session=session)

    assert result == (b"\x89PNG-favicon", "image/png", "favicon")
    assert session.requested[-1] == FAVICON_URL


def test_pick_best_logo_reports_why_every_candidate_failed() -> None:
    session = FakeSession(
        {
            SVG_URL: FakeResponse(status_code=404, content_type="text/plain"),
            PNG_URL: FakeResponse(status_code=404, content_type="text/plain"),
            GITHUB_URL: FakeResponse(status_code=404, content_type="text/plain"),
            FAVICON_URL: FakeResponse(content_type="text/html", content=b"<html/>"),
        }
    )
    trace: list[str] = []

    result = pl.pick_best_logo(_openai_spec(), session=session, trace=trace)

    assert result is None
    assert len(trace) == 4
    assert trace[0] == "lobehub-svg: HTTP 404"
    assert "content-type 不是图片" in trace[-1]


# ---------------------------------------------------------------------------
# 下载校验
# ---------------------------------------------------------------------------
def _candidate(url: str = "https://example.test/logo.png") -> pl.LogoCandidate:
    return pl.LogoCandidate(url=url, source="github")


@pytest.mark.parametrize("content_type", ["text/html", "application/json"])
def test_download_rejects_non_image_content_type(content_type: str) -> None:
    session = FakeSession(
        {"https://example.test/logo.png": FakeResponse(content_type=content_type, content=b"{}")}
    )

    assert pl.download_logo(_candidate(), session=session) is None


def test_download_rejects_oversized_body() -> None:
    session = FakeSession(
        {
            "https://example.test/logo.png": FakeResponse(
                content=b"x" * 101, content_type="image/png"
            )
        }
    )

    assert pl.download_logo(_candidate(), session=session, max_bytes=100) is None


def test_download_rejects_oversized_content_length_before_reading() -> None:
    session = FakeSession(
        {
            "https://example.test/logo.png": FakeResponse(
                content=b"x",
                content_type="image/png",
                headers={"Content-Length": "999999"},
            )
        }
    )

    assert pl.download_logo(_candidate(), session=session, max_bytes=100) is None


def test_download_returns_blob_and_normalised_mime() -> None:
    session = FakeSession(
        {
            "https://example.test/logo.png": FakeResponse(
                content=b"\x89PNG", content_type="image/PNG; charset=binary"
            )
        }
    )

    assert pl.download_logo(_candidate(), session=session) == (b"\x89PNG", "image/png")


def test_download_swallows_request_exception() -> None:
    session = FakeSession(
        {"https://example.test/logo.png": requests.ConnectionError("boom")}
    )

    assert pl.download_logo(_candidate(), session=session) is None


# ---------------------------------------------------------------------------
# 填充脚本：dry-run 只打印、不写库
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.executed: list[str] = []

    def execute(self, sql: str, params=None) -> None:
        self.executed.append(sql)

    def fetchall(self) -> list[tuple]:
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


class _FakeConnection:
    """只实现脚本用到的 cursor / commit / 上下文管理器。"""

    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.rows)

    def commit(self) -> None:
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


def _patch_db(monkeypatch, rows: list[tuple]) -> _FakeConnection:
    conn = _FakeConnection(rows)
    monkeypatch.setattr(filler.psycopg, "connect", lambda *args, **kwargs: conn)
    return conn


def test_dry_run_does_not_write(monkeypatch, capsys) -> None:
    conn = _patch_db(monkeypatch, [("openai", "OpenAI", True)])
    monkeypatch.setattr(
        filler,
        "build_session",
        lambda: FakeSession(
            {SVG_URL: FakeResponse(content=b"<svg/>", content_type="image/svg+xml")}
        ),
    )
    writes: list[tuple] = []
    monkeypatch.setattr(
        filler,
        "upsert_provider",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )

    exit_code = filler.main(
        ["--dry-run", "--db-url", "postgresql://test/test", "--only", "openai"]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert writes == []
    assert conn.commits == 0
    assert "filled=1 skipped=0 failed=0" in output
    assert "未写库" in output
    assert "lobehub-svg" in output


def test_real_run_writes_blob_mime_and_hit_url(monkeypatch) -> None:
    conn = _patch_db(monkeypatch, [("openai", "OpenAI", True)])
    monkeypatch.setattr(
        filler,
        "build_session",
        lambda: FakeSession(
            {SVG_URL: FakeResponse(content=b"<svg/>", content_type="image/svg+xml")}
        ),
    )
    records: list[tuple] = []

    def fake_upsert(conn_arg, provider_id, avatar_url, display_name, blob, mime):
        records.append((provider_id, avatar_url, display_name, blob, mime))

    monkeypatch.setattr(filler, "upsert_provider", fake_upsert)

    exit_code = filler.main(["--db-url", "postgresql://test/test", "--only", "openai"])

    assert exit_code == 0
    # 参数顺序必须是 avatar_url 在 display_name 之前（upsert_provider 的签名）
    assert records == [
        ("openai", SVG_URL, "OpenAI", b"<svg/>", "image/svg+xml"),
    ]
    assert conn.commits == 1


def test_existing_avatar_is_skipped_without_download(monkeypatch, capsys) -> None:
    _patch_db(monkeypatch, [("google", "Google", False)])  # False = 已有 blob
    monkeypatch.setattr(
        filler,
        "build_session",
        lambda: FakeSession({}),  # 任何下载都会因"未预置响应"而失败
    )

    exit_code = filler.main(
        ["--db-url", "postgresql://test/test", "--only", "google"]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "filled=0 skipped=1 failed=0" in output
    assert "已有 avatar_blob" in output
