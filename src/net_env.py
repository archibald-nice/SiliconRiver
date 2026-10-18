"""把 shell 里的代理变量整理成 httpx / openai SDK 能接受的形式。

背景（ISSUE-002）：本机 shell 同时导出 ``http_proxy`` 与 ``all_proxy=socks5://``，
``no_proxy`` 里还带 ``[::1]`` 这种方括号 IPv6 地址。这套配置对 ``requests`` 无害，
但 httpx 系（openai SDK、后端头像回退）会直接崩，而且报错完全看不出是代理配置问题：

- 缺 ``socksio`` 时装了 ``all_proxy=socks5://`` → ``ImportError: Using SOCKS proxy,
  but the 'socksio' package is not installed``（提示你去装 socksio，实际只要别用 socks）；
- ``no_proxy`` 含 ``[::1]`` → 建 Client 时 httpx 解析代理配成 ``URLPattern('[::1]')``，
  抛 ``httpx.InvalidURL: Invalid port: ':1]'``。

``sanitize_proxy_environment()`` 只做两件保守的事，且都可回滚：

1. 丢掉 ``no_proxy`` 里带方括号的条目（httpx 解析不了，其余条目照常保留）；
2. 没装 ``socksio`` 时丢掉 socks 协议的 ``all_proxy``，让 httpx 回落到
   ``http_proxy`` / ``https_proxy``（本地 Clash 类代理通常三个变量指向同一端口，
   HTTP CONNECT 一样能出去）。

装了 ``socksio``（``pip install httpx[socks]``）时保持原样，不劫持用户的代理选择。
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

LOGGER = logging.getLogger("silicon_river.net_env")

_NO_PROXY_KEYS = ("no_proxy", "NO_PROXY")
_ALL_PROXY_KEYS = ("all_proxy", "ALL_PROXY")
_SOCKS_PREFIXES = ("socks5://", "socks5h://", "socks4://", "socks4a://", "socks://")


def has_socks_support() -> bool:
    """httpx 是否装好了 SOCKS 支持（socksio）。"""
    try:
        import socksio  # noqa: F401
    except Exception:  # pragma: no cover - 取决于运行环境
        return False
    return True


def _clean_no_proxy(raw: str) -> str:
    """去掉 httpx 解析不了的条目（方括号 IPv6）与空项，保留其余顺序。"""
    kept: list[str] = []
    for entry in raw.split(","):
        item = entry.strip()
        if not item:
            continue
        if "[" in item or "]" in item:
            continue
        if item not in kept:
            kept.append(item)
    return ",".join(kept)


def _is_socks(value: str) -> bool:
    if value.lower().startswith(_SOCKS_PREFIXES):
        return True
    try:
        return (urlsplit(value).scheme or "").startswith("socks")
    except ValueError:
        return False


def sanitize_proxy_environment(logger: logging.Logger | None = None) -> list[str]:
    """就地修整进程环境里的代理变量，返回人类可读的修改说明（无改动时为空列表）。"""
    log = logger or LOGGER
    fixes: list[str] = []

    for key in _NO_PROXY_KEYS:
        raw = os.environ.get(key)
        if not raw:
            continue
        cleaned = _clean_no_proxy(raw)
        if cleaned != raw:
            os.environ[key] = cleaned
            fixes.append(f"{key}: 去掉 httpx 无法解析的方括号条目 -> {cleaned or '(空)'}")

    if not has_socks_support():
        for key in _ALL_PROXY_KEYS:
            value = os.environ.get(key)
            if value and _is_socks(value):
                os.environ.pop(key, None)
                fixes.append(
                    f"{key}: 忽略 {value}（未安装 socksio，httpx 会直接 ImportError；"
                    "改用 http_proxy/https_proxy；需要 socks 时 pip install 'httpx[socks]'）"
                )

    for message in fixes:
        log.warning("代理环境变量已修正：%s", message)
    return fixes
