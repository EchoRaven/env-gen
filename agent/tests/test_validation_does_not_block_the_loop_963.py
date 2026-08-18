"""#963: run_validation must not freeze the event loop.

``run_smoke_validation`` is fully synchronous (subprocess ``compose down/build/up``
plus urllib probes). It used to be called straight from ``RunValidationTool.execute``,
an ``async def``, so for the whole duration of a boot NOTHING else on the loop could
run — including the LLM client's 60s "[LLM] Still waiting" heartbeat and the
orchestrator's stall nudges. A working cold build therefore emitted zero log lines
and was indistinguishable from a dead process (netflix r155: 683s of silence, read
as a hang and killed).

The test is behavioral: a co-scheduled ticker must keep ticking while the blocking
validation runs. ``test_the_control_starves`` plants the pre-fix shape on a SYNTHETIC
coroutine and proves the same assertion fails there, so a green result here cannot be
vacuous.
"""

import asyncio
import time

import pytest

from env_generator.llm_generator.tools import validation_tools as vt

BLOCK_S = 0.30
TICK_S = 0.02


def _blocking_runner(project_dir, biz, teardown=False):
    """Stand-in for a cold compose build: synchronous, holds the thread."""
    time.sleep(BLOCK_S)
    return {"passed": True, "summary": "ok", "checks": [], "endpoints": []}


async def _count_ticks_while(awaitable) -> int:
    """Run ``awaitable`` with a 20ms ticker co-scheduled; return the tick count."""
    ticks = 0

    async def _ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(TICK_S)
            ticks += 1

    beat = asyncio.create_task(_ticker())
    try:
        await awaitable
    finally:
        beat.cancel()
    return ticks


def _tool(monkeypatch, tmp_path):
    tool = vt.RunValidationTool(workspace=None)
    monkeypatch.setattr(tool, "_project_dir", lambda: tmp_path)
    monkeypatch.setattr(tool, "_business_endpoints", lambda _pd: [{"path": "/api/x"}])
    for name, ret in (("_record_contract_tests", 1), ("_record_runhub_run", "run-1"),
                      ("_record_build_checks", 1), ("_record_frontend_build_check", 1),
                      ("_record_chain_status", 1), ("_record_api_smoke_check", 1)):
        monkeypatch.setattr(tool, name, lambda *a, _r=ret, **k: _r)
    monkeypatch.setattr(vt, "_import_runner", lambda: _blocking_runner)
    from multi_agent.runtime import chain_executor
    monkeypatch.setattr(chain_executor, "load_verifier_chains", lambda _pd: [{"name": "c"}])
    return tool


def test_the_loop_keeps_breathing_during_validation(monkeypatch, tmp_path):
    tool = _tool(monkeypatch, tmp_path)
    ticks = asyncio.run(_count_ticks_while(tool.execute()))
    # BLOCK_S/TICK_S == 15 ticks if the loop is free; allow generous slack for a
    # loaded CI box. Zero (or near-zero) means execute() held the loop.
    assert ticks >= 5, (
        f"only {ticks} ticks during a {BLOCK_S}s validation — the event loop was "
        "blocked, so every heartbeat and stall nudge is starved while it runs")


def test_validation_still_returns_its_verdict(monkeypatch, tmp_path):
    """Offloading must not change the tool's contract."""
    tool = _tool(monkeypatch, tmp_path)
    result = asyncio.run(tool.execute())
    assert result.success, result.error
    assert result.data["passed"] is True
    assert result.data["runhub_run_id"] == "run-1"


def test_the_control_starves(monkeypatch, tmp_path):
    """Planted control: the PRE-FIX shape (direct call from the coroutine) must fail
    the assertion above. Proven on a synthetic coroutine, not on the supervised tree,
    so fixing the real code can never make this test go red."""

    async def _pre_fix_execute():
        return _blocking_runner(tmp_path, [], teardown=False)

    ticks = asyncio.run(_count_ticks_while(_pre_fix_execute()))
    assert ticks < 5, (
        "the control was supposed to starve the ticker; if it did not, the tick "
        "threshold no longer discriminates and the main test proves nothing")


def test_two_smokes_never_overlap(monkeypatch):
    """Unfreezing the loop made a CONCURRENT second smoke reachable for the first
    time (orchestrator framework-validation + verifier lane). Two at once race
    `compose down -v` against each other's build, so they must serialise."""
    vt._SMOKE_LOCK = None  # a fresh lock bound to this test's loop
    overlap = {"max": 0, "now": 0}

    def _runner(project_dir, biz, teardown=False):
        overlap["now"] += 1
        overlap["max"] = max(overlap["max"], overlap["now"])
        time.sleep(0.05)
        overlap["now"] -= 1
        return {"passed": True}

    async def _both():
        await asyncio.gather(
            vt._run_smoke_single_flight(_runner, "p", []),
            vt._run_smoke_single_flight(_runner, "p", []),
        )

    asyncio.run(_both())
    assert overlap["max"] == 1, (
        f"{overlap['max']} smokes ran at once — concurrent `compose down -v` wipes "
        "the other's volumes mid-probe and the verdict describes a dead env")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
