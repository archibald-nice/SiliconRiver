"""守住「测试不许依赖真实网络」这道闸（2026-10-20 CI 连续红的根因）。

历史事故：`test_fetch_and_store_inserts` 会真的去连 Hugging Face。本机 shell 里有
`http_proxy=127.0.0.1:7890`，连接走回环被守卫放行 → 本地绿；CI 上没有代理，直连
外网被守卫拦下 → CI 连续多次红，而没人注意到。

修法有两层：
  ① 那个用例补上 mock；
  ② 守卫改成抛 `BaseException` 子类，**任何 `except Exception` 都吞不掉它**。

这组用例锁第二层：即使有人写了 `except Exception: pass`，测试照样会炸。
"""

from __future__ import annotations

import socket
import sys

import pytest

# pytest 把 conftest.py 当顶层模块 `conftest` 导入；再从 `tests.conftest` 导一次会得到
# 另一个类对象，`except` 就匹配不上了（第一次写这组用例就踩了这个坑）。
_conftest = sys.modules.get("conftest") or sys.modules["tests.conftest"]
NetworkAccessBlocked = _conftest.NetworkAccessBlocked


def test_guard_raises_baseexception_that_except_exception_cannot_swallow():
    """内层 `except Exception` 模仿生产代码的兜底；守卫必须照样穿出去。

    注意不能用 `pytest.raises`：它对 BaseException 子类的处理会让上下文管理器自己
    抛错，测不出「兜底吞不掉」这一点。
    """
    escaped: BaseException | None = None
    try:
        try:
            socket.create_connection(("example.com", 443), timeout=1)
        except Exception:  # noqa: BLE001 - 故意模仿「生产代码里的兜底」
            pass  # 必须吞不掉
    except NetworkAccessBlocked as exc:
        escaped = exc

    assert isinstance(escaped, NetworkAccessBlocked), (
        "守卫抛的异常必须是 BaseException 子类，否则会被 except Exception 吞掉"
    )


def test_guard_exception_is_not_an_exception_subclass():
    """刻意用 BaseException：`except Exception` 拦不住它，这正是设计意图。"""
    assert issubclass(NetworkAccessBlocked, BaseException)
    assert not issubclass(NetworkAccessBlocked, Exception)


def test_loopback_is_still_allowed():
    """回环必须放行，否则连本地测试库都连不上（conftest 自己就要连 127.0.0.1）。"""
    sock = socket.socket()
    try:
        sock.connect(("127.0.0.1", 9))  # 端口不通也行，只要不是被守卫拒绝
    except NetworkAccessBlocked:  # pragma: no cover - 出现即说明守卫误伤
        pytest.fail("127.0.0.1 不该被网络守卫拦截")
    except OSError:
        pass  # 连接被拒绝是预期（端口 9 一般没人监听）
    finally:
        sock.close()
