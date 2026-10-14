"""AI 分析入口（CLI）的测试。

**不需要数据库、不发网络请求**：把取待分析列表和 analyse_batch 都换成桩。

这里守两件事：
  1. **await 回归**：run_post_scrape_analysis 曾经是同步函数却直接接收
     `async def analyze_batch` 的返回值（coroutine 对象）去取下标，必然抛
     TypeError。调用方又用 try/except 包着只打 warning，所以一直静默失败 ——
     model_analysis 长期为空就是这个原因。下面的测试会验证协程**确实被执行**。
  2. **退出码判定**：定时任务能否告警完全取决于 decide_exit_code。它是纯函数，
     这里把每个分支都钉死，尤其"小批量全失败也要报"这一条。
"""
from __future__ import annotations

import asyncio

import pytest

import src.scraper.analysis_orchestrator as ao
from src.scraper.analysis_orchestrator import AnalysisOrchestrator, decide_exit_code


# --------------------------------------------------------------------------
# 退出码判定（监控的地基）
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "result, expected, why",
    [
        # 开关关着 / 没事做 —— 都不是失败
        ({"enabled": False, "message": "已禁用"}, 0, "禁用不算失败"),
        ({"enabled": True, "total": 0, "failed": 0}, 0, "没有待分析模型"),
        # 全部成功
        ({"enabled": True, "total": 50, "failed": 0}, 0, "全成功"),
        # 少量个例失败要容忍（小众模型抽不出结果是常态）
        ({"enabled": True, "total": 50, "failed": 3}, 0, "失败率 6% 应容忍"),
        ({"enabled": True, "total": 100, "failed": 20}, 0, "恰好等于阈值不算超"),
        # 超阈值
        ({"enabled": True, "total": 100, "failed": 21}, 1, "失败率 21% 超阈值"),
        ({"enabled": True, "total": 50, "failed": 30}, 1, "失败率 60%"),
        # 全失败 —— 无论批量多小都必须报（否则小批量下密钥失效会被吞掉）
        ({"enabled": True, "total": 5, "failed": 5}, 1, "全失败（5）"),
        ({"enabled": True, "total": 1, "failed": 1}, 1, "全失败（1）—— 最关键的一条"),
    ],
)
def test_decide_exit_code(result, expected, why):
    code, _ = decide_exit_code(result, max_failure_rate=0.2)
    assert code == expected, why


def test_decide_exit_code_returns_readable_reason():
    _, reason = decide_exit_code({"enabled": True, "total": 10, "failed": 5})
    assert "50.0%" in reason or "50%" in reason

    _, reason = decide_exit_code({"enabled": True, "total": 3, "failed": 3})
    assert "全部失败" in reason
    assert "DEEPSEEK_API_KEY" in reason, "全失败时应提示去查密钥/网络"


def test_decide_exit_code_threshold_is_configurable():
    result = {"enabled": True, "total": 10, "failed": 5}
    assert decide_exit_code(result, max_failure_rate=0.9)[0] == 0
    assert decide_exit_code(result, max_failure_rate=0.1)[0] == 1


def test_decide_exit_code_tolerates_missing_keys():
    """字段缺失不该抛异常 —— 监控脚本最怕自己先崩。"""
    assert decide_exit_code({})[0] == 0
    assert decide_exit_code({"enabled": True})[0] == 0


# --------------------------------------------------------------------------
# await 回归 + limit/provider 透传
# --------------------------------------------------------------------------

def _orchestrator(monkeypatch, models):
    orch = AnalysisOrchestrator(db_url="postgresql://unused/never")
    monkeypatch.setattr(ao, "ANALYSIS_ENABLED", True)
    seen: dict = {}

    def fake_fetch(provider=None, limit=None):
        seen["provider"] = provider
        seen["limit"] = limit
        return list(models)

    monkeypatch.setattr(orch, "_fetch_unanalyzed_models", fake_fetch)
    return orch, seen


def _fake_models(n):
    return [
        {"model_id": f"fake/m{i}", "model_name": f"F{i}",
         "description": "", "tags": [], "provider": "fake"}
        for i in range(n)
    ]


def test_analyze_batch_coroutine_is_actually_awaited(monkeypatch):
    """核心回归：必须是 asyncio.run(...)，协程要真的跑起来。

    修复前这里会抛 TypeError: 'coroutine' object is not subscriptable ——
    而且因为不 await，analyze_batch 里的代码一行都不会执行。
    """
    orch, _ = _orchestrator(monkeypatch, _fake_models(3))
    executed: list[int] = []

    async def fake_analyze_batch(models, batch_size, delay_between_batches):
        # 这个函数体被执行，才说明协程真的被 await 了
        executed.append(len(models))
        return {"total": len(models), "succeeded": len(models),
                "failed": 0, "skipped": 0, "errors": {}}

    monkeypatch.setattr(orch.integration, "analyze_batch", fake_analyze_batch)

    result = orch.run_post_scrape_analysis()

    assert executed == [3], "协程没有被执行 —— await/asyncio.run 又丢了"
    assert result == {"enabled": True, "provider": None,
                      "total": 3, "analyzed": 3, "failed": 0}


def test_analyze_batch_failures_are_reported(monkeypatch):
    orch, _ = _orchestrator(monkeypatch, _fake_models(4))

    async def fake_analyze_batch(models, batch_size, delay_between_batches):
        return {"total": 4, "succeeded": 1, "failed": 3, "skipped": 0, "errors": {}}

    monkeypatch.setattr(orch.integration, "analyze_batch", fake_analyze_batch)
    result = orch.run_post_scrape_analysis()

    assert result["analyzed"] == 1
    assert result["failed"] == 3
    # 失败率 75% → 必须让定时任务感知到
    assert decide_exit_code(result, max_failure_rate=0.2)[0] == 1


def test_provider_and_limit_are_passed_through(monkeypatch):
    orch, seen = _orchestrator(monkeypatch, _fake_models(1))

    async def fake_analyze_batch(models, batch_size, delay_between_batches):
        return {"total": len(models), "succeeded": len(models),
                "failed": 0, "skipped": 0, "errors": {}}

    monkeypatch.setattr(orch.integration, "analyze_batch", fake_analyze_batch)
    orch.run_post_scrape_analysis(provider="Qwen", limit=7)

    assert seen == {"provider": "Qwen", "limit": 7}


def test_empty_candidate_list_skips_analysis(monkeypatch):
    """没有待分析模型时不该调用分析器。"""
    orch, _ = _orchestrator(monkeypatch, [])
    called = []

    async def fake_analyze_batch(**kwargs):
        called.append(1)
        return {}

    monkeypatch.setattr(orch.integration, "analyze_batch", fake_analyze_batch)
    result = orch.run_post_scrape_analysis()

    assert called == []
    assert result == {"enabled": True, "provider": None,
                      "total": 0, "analyzed": 0, "failed": 0}
    assert decide_exit_code(result)[0] == 0


def test_disabled_switch_short_circuits(monkeypatch):
    orch, _ = _orchestrator(monkeypatch, _fake_models(3))
    monkeypatch.setattr(ao, "ANALYSIS_ENABLED", False)

    async def boom(**kwargs):  # pragma: no cover
        raise AssertionError("禁用时不该调用分析器")

    monkeypatch.setattr(orch.integration, "analyze_batch", boom)
    assert orch.run_post_scrape_analysis()["enabled"] is False


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def test_cli_rejects_non_positive_limit():
    with pytest.raises(SystemExit) as exc:
        ao.main(["--limit", "0"])
    assert exc.value.code == 2


def test_cli_returns_zero_when_analysis_disabled(monkeypatch, capsys):
    monkeypatch.setattr(ao, "ANALYSIS_ENABLED", False)
    assert ao.main([]) == 0
    assert "已禁用" in capsys.readouterr().out


def test_cli_returns_one_when_everything_fails(monkeypatch, capsys):
    monkeypatch.setattr(ao, "ANALYSIS_ENABLED", True)

    def fake_run(provider=None, limit=None):
        return {"enabled": True, "provider": provider,
                "total": 4, "analyzed": 0, "failed": 4}

    monkeypatch.setattr(ao, "run_post_scrape_analysis", fake_run)
    assert ao.main([]) == 1
    assert "全部失败" in capsys.readouterr().out


def test_cli_emits_machine_readable_json(monkeypatch, capsys):
    monkeypatch.setattr(ao, "ANALYSIS_ENABLED", True)

    def fake_run(provider=None, limit=None):
        return {"enabled": True, "provider": None,
                "total": 10, "analyzed": 9, "failed": 1}

    monkeypatch.setattr(ao, "run_post_scrape_analysis", fake_run)
    assert ao.main(["--json"]) == 0

    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    assert len(lines) == 1
    import json
    payload = json.loads(lines[0])
    assert payload["total"] == 10 and payload["exit_code"] == 0


def test_cli_passes_arguments_to_orchestrator(monkeypatch, capsys):
    monkeypatch.setattr(ao, "ANALYSIS_ENABLED", True)
    seen = {}

    def fake_run(provider=None, limit=None):
        seen.update(provider=provider, limit=limit)
        return {"enabled": True, "provider": provider,
                "total": 0, "analyzed": 0, "failed": 0}

    monkeypatch.setattr(ao, "run_post_scrape_analysis", fake_run)
    ao.main(["--provider", "Qwen", "--limit", "5", "--max-failure-rate", "0.9"])
    assert seen == {"provider": "Qwen", "limit": 5}


# --------------------------------------------------------------------------
# 入口点存在性（防止有人把 __main__ 守卫删掉）
# --------------------------------------------------------------------------

def test_main_is_callable_with_explicit_argv():
    """main(argv) 必须支持显式参数 —— 测试与外部监控都靠它。"""
    import inspect
    sig = inspect.signature(ao.main)
    assert "argv" in sig.parameters


def test_run_post_scrape_analysis_is_sync_and_runs_the_loop(monkeypatch):
    """对外入口是同步的，内部自己起事件循环。

    如果哪天有人把它改成 async def，所有同步调用方（fetch_models 等）会
    重新变成"拿到 coroutine 不执行"的静默失败。
    """
    import inspect
    assert not inspect.iscoroutinefunction(ao.run_post_scrape_analysis)
    assert not inspect.iscoroutinefunction(AnalysisOrchestrator.run_post_scrape_analysis)
