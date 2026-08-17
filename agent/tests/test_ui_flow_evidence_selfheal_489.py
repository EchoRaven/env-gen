"""#489 — deterministic ui_flow evidence self-heal (netflix r58/r61, task#47).

Delivery blocked on `deliverability_ui_flow_missing` while the app is fully functional
(api_smoke green, 15/15 endpoints, frontend navigable) — the LLM verifier just never authored
the `validation:ui_flow` records the gate wants (r61: dispatched 6+ times, never complied).
The framework's authenticated browser walk auto-authors those records (#240) but only runs
AFTER the gate clears (chicken-and-egg). maybe_author_ui_flow_evidence runs that walk pre-gate,
GUARDED: only when ui_flow_missing is red AND api_smoke passed (app is up), bounded per
milestone. Here we test the guard/ordering/budget logic (the walk itself is a threaded
side-effecting call, mocked)."""
import asyncio

from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    maybe_author_ui_flow_evidence)


class _Logger:
    def warning(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


class _Orch:
    def __init__(self, raise_in_walk=False):
        self._current_milestone_version = "1.0.0"
        self._logger = _Logger()
        self.walk_calls = []
        self._raise = raise_in_walk

    def _run_test_user_validation(self, version):
        self.walk_calls.append(version)
        if self._raise:
            raise RuntimeError("boom")
        return {"ran": True}


def _run(orch, failed):
    # NB: use a dedicated loop and RESTORE a fresh current loop afterwards.
    # asyncio.run() would set the thread's event loop to None on exit, which pollutes
    # later tests that call asyncio.get_event_loop() (e.g. the visual-gate suite).
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(maybe_author_ui_flow_evidence(orch, failed))
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_noop_when_ui_flow_not_blocking():
    orch = _Orch()
    assert _run(orch, ["business_chain_failing", "database_sql_missing"]) is False
    assert orch.walk_calls == [], "walk must NOT run when ui_flow_missing is not a blocker"


def test_noop_when_api_smoke_never_passed():
    # app is not validated end-to-end (likely down) → don't spend on a browser walk
    orch = _Orch()
    out = _run(orch, ["deliverability_ui_flow_missing", "deliverability_no_successful_run"])
    assert out is False
    assert orch.walk_calls == [], "walk must NOT run when the app never validated (may be down)"


def test_runs_walk_when_ui_flow_missing_and_app_up():
    orch = _Orch()
    out = _run(orch, ["deliverability_ui_flow_missing", "business_chain_failing"])
    assert out is True
    assert orch.walk_calls == ["1.0.0"], "walk runs once to author ui_flow evidence"
    assert orch._ui_flow_walk_by_ms.get("1.0.0") == 1


def test_bounded_per_milestone():
    orch = _Orch()
    fc = ["deliverability_ui_flow_missing"]
    assert _run(orch, fc) is True   # 1/3
    assert _run(orch, fc) is True   # 2/3
    assert _run(orch, fc) is True   # 3/3
    assert _run(orch, fc) is False  # budget exhausted → no more walks
    assert len(orch.walk_calls) == 3, "at most 3 walks per milestone"


def test_budget_is_per_milestone_version():
    orch = _Orch()
    fc = ["deliverability_ui_flow_missing"]
    for _ in range(3):
        _run(orch, fc)
    assert len(orch.walk_calls) == 3
    # a new milestone version refreshes the budget
    orch._current_milestone_version = "2.0.0"
    assert _run(orch, fc) is True
    assert len(orch.walk_calls) == 4


def test_never_raises_when_walk_throws():
    orch = _Orch(raise_in_walk=True)
    # the walk raising must be swallowed (best-effort; never breaks the deliver loop)
    out = _run(orch, ["deliverability_ui_flow_missing"])
    assert out is False
    assert orch.walk_calls == ["1.0.0"], "walk was attempted, error swallowed"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
