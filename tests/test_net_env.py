"""``src.net_env`` 的回归测试（ISSUE-002）。

断言对应两种真实故障：``no_proxy`` 里的 ``[::1]`` 让 httpx 建 Client 就抛
``InvalidURL``；``all_proxy`` 是 socks 但没装 socksio 让 httpx 抛 ``ImportError``。
测试不联网，只改环境变量与模块级探测函数。
"""

from __future__ import annotations

import os

import httpx
import pytest

from src import net_env

PROXY_KEYS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
)


@pytest.fixture(autouse=True)
def _clean_proxy_env(monkeypatch):
    for key in PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


def test_drops_bracketed_ipv6_entries(monkeypatch):
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1,::1,[::1]")
    fixes = net_env.sanitize_proxy_environment()
    assert fixes
    assert os.environ["no_proxy"] == "localhost,127.0.0.1,::1"


def test_keeps_clean_no_proxy_untouched(monkeypatch):
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1,::1")
    assert net_env.sanitize_proxy_environment() == []


def test_drops_empty_entries(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,,127.0.0.1,")
    net_env.sanitize_proxy_environment()
    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1"


def test_socks_proxy_dropped_without_socksio(monkeypatch):
    monkeypatch.setattr(net_env, "has_socks_support", lambda: False)
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:7891")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")
    fixes = net_env.sanitize_proxy_environment()
    assert "all_proxy" not in os.environ
    assert os.environ["http_proxy"] == "http://127.0.0.1:7890"
    assert any("socksio" in item for item in fixes)


def test_socks_proxy_kept_when_supported(monkeypatch):
    monkeypatch.setattr(net_env, "has_socks_support", lambda: True)
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:7891")
    assert net_env.sanitize_proxy_environment() == []
    assert os.environ["all_proxy"] == "socks5://127.0.0.1:7891"


def test_http_all_proxy_kept(monkeypatch):
    monkeypatch.setattr(net_env, "has_socks_support", lambda: False)
    monkeypatch.setenv("all_proxy", "http://127.0.0.1:7890")
    assert net_env.sanitize_proxy_environment() == []
    assert os.environ["all_proxy"] == "http://127.0.0.1:7890"


def test_httpx_client_builds_after_sanitize(monkeypatch):
    """真实的失败形态：方括号 no_proxy 让 httpx.Client() 直接抛 InvalidURL。"""
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1,::1,[::1]")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")
    with pytest.raises(httpx.InvalidURL):
        httpx.Client()
    net_env.sanitize_proxy_environment()
    with httpx.Client() as client:
        assert client is not None
