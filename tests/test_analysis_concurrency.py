"""AI 分析批处理的并发行为测试。

**不需要数据库**：写库那一步（`_save_analysis_to_db`）在集成层测试里被替换成记录器，
因为它不是这里要验证的东西；真实分析器测试则完全不碰数据库。

锁住的是一个具体的性能 bug
--------------------------
`AnalysisIntegration.analyze_batch` 以前是 `for` 循环逐个调 `analyze_and_save_model`，
而后者每次只给 `AsyncModelAnalyzer.analyze_batch` 传**一个**模型 —— 于是
`AsyncModelAnalyzer` 内部那套 semaphore 每次只保护 1 个任务，
`MAX_CONCURRENT_ANALYSIS` 配了等于没配，500 个模型要串行跑一小时。

现在改成一次性把整批交过去。两组测试分别守两个不变量：

  A. 集成层：整批必须**一次**交给分析器（哪怕 200 个），而不是逐个调用；
  B. 分析器：semaphore 确实把在途请求数限制在 `max_concurrent`，且确实 > 1。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.analysis.async_analyzer import AnalysisResult, AsyncModelAnalyzer
from src.analysis.integration import AnalysisIntegration


# --------------------------------------------------------------------------
# 公共桩
# --------------------------------------------------------------------------

def _analysis_result(model_id: str) -> AnalysisResult:
    return AnalysisResult(
        model_id=model_id,
        analysis_summary="摘要",
        key_features=["能力"],
        use_cases=["问答"],
        performance_metrics={},
        llm_model_used="test-model",
    )


def _models(count: int) -> list[dict]:
    return [
        {
            "model_id": f"acme/m{i}",
            "model_name": f"Model {i}",
            "description": f"第 {i} 个模型",
            "tags": ["t"],
            "provider": "acme",
        }
        for i in range(count)
    ]


class _RecordingAnalyzer:
    """假的 AsyncModelAnalyzer：只记录“被怎么调用”，不真的打 LLM。"""

    def __init__(
        self,
        max_concurrent: int = 5,
        failures: set[str] | None = None,
        exceptions: dict[str, BaseException] | None = None,
    ):
        self.max_concurrent = max_concurrent
        self.batch_sizes: list[int] = []
        self.call_count = 0
        self._failures = set(failures or ())
        self._exceptions = dict(exceptions or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def analyze_batch(self, model_ids, model_names, descriptions, tags_list):
        # 四个入参必须等长，否则是集成层装配出了问题
        assert len(model_ids) == len(model_names) == len(descriptions) == len(tags_list)
        self.batch_sizes.append(len(model_ids))
        self.call_count += 1

        results = []
        for model_id in model_ids:
            if model_id in self._exceptions:
                results.append(self._exceptions[model_id])
            elif model_id in self._failures:
                results.append(None)
            else:
                results.append(_analysis_result(model_id))
        return results


class _StubTagGenerator:
    """假标签生成器：真的 TagGenerator 会读 .env 里的 API key 并发起真实请求。

    本文件测的是并发契约，标签生成只是写库前的一个过场；不替换的话，200 个模型
    会真打 200 次 LLM（实测 160 秒，占整个测试套件九成时间）。
    """

    calls = 0

    def generate_tags(self, **_kwargs):
        type(self).calls += 1
        return ["stub"]


def _make_integration(analyzer, monkeypatch, save_ok: bool = True):
    """构造 AnalysisIntegration，并把写库与标签生成都替换成记录器。

    返回 (integration, written)，written 里是每次“写库”收到的 kwargs。
    """
    integration = AnalysisIntegration(db_url="postgresql://unused/never-used")
    integration.analyzer = analyzer
    integration.tag_generator = _StubTagGenerator()

    written: list[dict] = []

    def fake_save(**kwargs):
        written.append(kwargs)
        return save_ok

    monkeypatch.setattr(integration, "_save_analysis_to_db", fake_save)
    return integration, written


# --------------------------------------------------------------------------
# A. 集成层契约
# --------------------------------------------------------------------------

def test_whole_batch_handed_to_analyzer_in_a_single_call(monkeypatch):
    """核心回归：5 个模型必须是 1 次调用传入 5 个，而不是 5 次各传 1 个。"""
    analyzer = _RecordingAnalyzer()
    integration, written = _make_integration(analyzer, monkeypatch)

    result = asyncio.run(integration.analyze_batch(_models(5)))

    assert analyzer.call_count == 1, (
        f"分析器被调用了 {analyzer.call_count} 次；应当只调 1 次"
        f"（逐个调用会把并发压成 1）"
    )
    assert analyzer.batch_sizes == [5], f"每次传入的模型数量为 {analyzer.batch_sizes}，期望 [5]"
    assert result["succeeded"] == 5
    assert result["failed"] == 0
    assert len(written) == 5


def test_large_batch_also_uses_exactly_one_call(monkeypatch):
    """200 个模型同样必须一次传入 —— 这是并发能生效的前提。"""
    analyzer = _RecordingAnalyzer()
    integration, written = _make_integration(analyzer, monkeypatch)

    result = asyncio.run(integration.analyze_batch(_models(200)))

    assert analyzer.batch_sizes == [200]
    assert result["succeeded"] == 200
    assert len(written) == 200


def test_model_fields_are_passed_through_in_order(monkeypatch):
    """模型字段必须按原顺序一一对应地传下去，不能错位。"""
    analyzer = _RecordingAnalyzer()
    integration, written = _make_integration(analyzer, monkeypatch)

    asyncio.run(integration.analyze_batch(_models(3)))

    assert [w["model_id"] for w in written] == ["acme/m0", "acme/m1", "acme/m2"]
    assert [w["model_name"] for w in written] == ["Model 0", "Model 1", "Model 2"]
    assert all(w["provider"] == "acme" for w in written)


def test_none_results_are_counted_as_failures(monkeypatch):
    """分析器返回 None（超时/未拿到结果）应计入 failed，且不写库。"""
    analyzer = _RecordingAnalyzer(failures={"acme/m1", "acme/m3"})
    integration, written = _make_integration(analyzer, monkeypatch)

    result = asyncio.run(integration.analyze_batch(_models(4)))

    assert result["succeeded"] == 2
    assert result["failed"] == 2
    assert len(written) == 2
    assert {w["model_id"] for w in written} == {"acme/m0", "acme/m2"}


def test_exception_objects_from_gather_are_counted_by_type(monkeypatch):
    """分析器内部用 gather(return_exceptions=True)，失败项是**异常对象**而非 None。

    这条容易被漏掉：不处理的话异常对象会被当成“成功的结果”塞进写库逻辑。
    """
    analyzer = _RecordingAnalyzer(exceptions={"acme/m2": ValueError("boom")})
    integration, written = _make_integration(analyzer, monkeypatch)

    result = asyncio.run(integration.analyze_batch(_models(3)))

    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert result["errors"].get("ValueError") == 1
    assert {w["model_id"] for w in written} == {"acme/m0", "acme/m1"}


def test_database_save_failure_is_counted(monkeypatch):
    """写库返回 False 应计入 failed。"""
    analyzer = _RecordingAnalyzer()
    integration, _ = _make_integration(analyzer, monkeypatch, save_ok=False)

    result = asyncio.run(integration.analyze_batch(_models(3)))

    assert result["succeeded"] == 0
    assert result["failed"] == 3


def test_short_result_list_is_handled(monkeypatch):
    """分析器少返回几个结果时，缺失的按失败处理，不能越界崩溃。"""

    class _ShortAnalyzer(_RecordingAnalyzer):
        async def analyze_batch(self, model_ids, model_names, descriptions, tags_list):
            self.batch_sizes.append(len(model_ids))
            self.call_count += 1
            return [_analysis_result(model_ids[0])]  # 只回 1 个

    analyzer = _ShortAnalyzer()
    integration, written = _make_integration(analyzer, monkeypatch)

    result = asyncio.run(integration.analyze_batch(_models(4)))

    assert result["succeeded"] == 1
    assert result["failed"] == 3
    assert len(written) == 1


def test_empty_batch_returns_immediately(monkeypatch):
    """空列表不应调用分析器，也不应写库。"""
    analyzer = _RecordingAnalyzer()
    integration, written = _make_integration(analyzer, monkeypatch)

    result = asyncio.run(integration.analyze_batch([]))

    assert result == {"total": 0, "succeeded": 0, "failed": 0, "skipped": 0, "errors": {}}
    assert analyzer.call_count == 0
    assert written == []


def test_batch_size_zero_does_not_divide_by_zero(monkeypatch):
    """batch_size=0 会被下限到 1；此前 `i % batch_size` 会直接 ZeroDivisionError。"""
    analyzer = _RecordingAnalyzer()
    integration, _ = _make_integration(analyzer, monkeypatch)

    result = asyncio.run(integration.analyze_batch(_models(3), batch_size=0))

    assert result["succeeded"] == 3


def test_single_model_helper_delegates_to_batch(monkeypatch):
    """单模型入口必须委托给批处理，而不是自己再写一套。"""
    analyzer = _RecordingAnalyzer()
    integration, written = _make_integration(analyzer, monkeypatch)

    ok = asyncio.run(integration.analyze_and_save_model("acme/m0", "Model 0"))

    assert ok is True
    assert analyzer.batch_sizes == [1]
    assert len(written) == 1
    assert written[0]["model_id"] == "acme/m0"


def test_single_model_helper_reports_failure(monkeypatch):
    analyzer = _RecordingAnalyzer(failures={"acme/m0"})
    integration, written = _make_integration(analyzer, monkeypatch)

    ok = asyncio.run(integration.analyze_and_save_model("acme/m0", "Model 0"))

    assert ok is False
    assert written == []


# --------------------------------------------------------------------------
# B. 真实分析器：semaphore 是否真的在限流
# --------------------------------------------------------------------------

class _StubMCP:
    """替掉 MCPDataSource：不发任何网络请求。"""

    async def search_news(self, model_name: str):
        return []

    async def search_papers(self, model_name: str):
        return []

    async def get_timeline_context(self, model_id: str):
        return {}


class _StubLeaderboard:
    async def get_model_ranks(self, model_name: str):
        return {}


class _InFlightTracker:
    """记录同时在途的 LLM 请求数峰值。"""

    def __init__(self):
        self.current = 0
        self.peak = 0
        self.calls = 0

    def enter(self):
        self.current += 1
        self.calls += 1
        self.peak = max(self.peak, self.current)

    def exit(self):
        self.current -= 1


class _StubCompletions:
    def __init__(self, tracker: _InFlightTracker, delay: float):
        self.tracker = tracker
        self.delay = delay

    async def create(self, **kwargs):
        self.tracker.enter()
        try:
            # 模拟网络等待 —— 没有等待就观察不到并发
            await asyncio.sleep(self.delay)
            payload = (
                '{"analysis_summary":"摘要","key_features":["能力"],'
                '"use_cases":["问答"],"performance_metrics":{}}'
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
            )
        finally:
            self.tracker.exit()


class _StubLLMClient:
    def __init__(self, tracker: _InFlightTracker, delay: float = 0.05):
        self.chat = SimpleNamespace(completions=_StubCompletions(tracker, delay))

    async def close(self):
        pass


def _real_analyzer(tracker: _InFlightTracker, max_concurrent: int, delay: float) -> AsyncModelAnalyzer:
    analyzer = AsyncModelAnalyzer(api_key="test-key", max_concurrent=max_concurrent)
    analyzer.mcp_source = _StubMCP()
    analyzer.leaderboard_agg = _StubLeaderboard()
    analyzer.client = _StubLLMClient(tracker, delay)
    return analyzer


def _run_batch(analyzer: AsyncModelAnalyzer, count: int):
    ids = [f"acme/m{i}" for i in range(count)]
    return asyncio.run(
        analyzer.analyze_batch(
            model_ids=ids,
            model_names=[f"Model {i}" for i in range(count)],
            descriptions=["描述"] * count,
            tags_list=[[] for _ in range(count)],
        )
    )


def test_real_analyzer_runs_concurrently():
    """开启并发后，同时在途的请求数应大于 1，且不超过 max_concurrent。"""
    tracker = _InFlightTracker()
    analyzer = _real_analyzer(tracker, max_concurrent=3, delay=0.05)

    results = _run_batch(analyzer, 9)

    assert all(r is not None for r in results), "有模型返回 None，说明测试桩没接对"
    assert tracker.calls == 9
    assert tracker.peak > 1, f"完全没有并发（峰值 {tracker.peak}）—— semaphore 没起作用"
    assert tracker.peak <= 3, f"超过并发上限：峰值 {tracker.peak} > max_concurrent=3"


def test_real_analyzer_serializes_when_max_concurrent_is_one():
    """反向确认 semaphore 被尊重：max_concurrent=1 时必须串行。"""
    tracker = _InFlightTracker()
    analyzer = _real_analyzer(tracker, max_concurrent=1, delay=0.01)

    _run_batch(analyzer, 5)

    assert tracker.peak == 1, f"max_concurrent=1 时峰值应为 1，实际 {tracker.peak}"
    assert tracker.calls == 5
