"""#532 / #533 (2026-08-06) — delivery-convergence fixes in the framework delivery path.

GROUND TRUTH: the framework delivery gate (_maybe_framework_deliver) ran the TEST-USER SQUAD
gate INLINE — `await run_squad_for_delivery(...)`, ~42min of work (12 browser agents in 3
sequential waves) — which BLOCKED the coordination loop synchronously, so create_release (the
sole caller lives further down the same function) was never reached and the run never delivered.

FIX #532 (primary): the squad gate now runs the squad as a SINGLE-FLIGHT BACKGROUND task and
DEFERS each delivery tick while it runs (the loop stays live and can reach create_release once
gates clear). The launch-vs-defer-vs-consume decision is the pure `squad_gate_tick_action`
helper, unit-tested here. The wall-clock/attempt escape (squad_release_decision) is unchanged
and still preempts to RELEASE even while the background squad is running.

FIX #532 (complementary safety bound): run_test_user_squad's per_agent_timeout default drops
900 -> 180s (squad findings are advisory; this bounds any single wave). Still overridable.

FIX #533 (secondary): the LLM-deliver GUARD 2c predicate (_visual_delivery_defer_active) now
honors the #521 sticky escape-release — it returns False once gate.released is True (even when
gate.passed is still False), so an earned below-threshold visual release no longer blocks
deliver_project. No false-delivery risk: `released` is True only AFTER the bounded escape fired.
"""
import inspect
import os
import time
import types

import pytest


# ── #532: single-flight decision (pure helper) ────────────────────────────────
from env_generator.llm_generator.multi_agent.runtime.test_user_squad import (
    run_test_user_squad, squad_gate_tick_action, squad_release_decision)


def test_tick_action_no_task_launches():
    # First defer (no background squad yet) → launch exactly one, then defer this tick.
    assert squad_gate_tick_action(task_exists=False, task_done=False) == "launch"
    # task_done is irrelevant when no task exists.
    assert squad_gate_tick_action(task_exists=False, task_done=True) == "launch"


def test_tick_action_running_task_defers_no_relaunch():
    # A squad is in flight but not finished → defer (single-flight: never a 2nd launch).
    assert squad_gate_tick_action(task_exists=True, task_done=False) == "defer"


def test_tick_action_done_task_consumes():
    # The background squad finished → consume its result this tick.
    assert squad_gate_tick_action(task_exists=True, task_done=True) == "consume"


def test_tick_action_is_total_and_pure():
    # Every (exists, done) combination maps to exactly one of the three actions.
    seen = {squad_gate_tick_action(task_exists=e, task_done=d)
            for e in (False, True) for d in (False, True)}
    assert seen == {"launch", "defer", "consume"}


def test_single_flight_sequence_with_mocked_task_state():
    # Simulate the orchestrator's per-tick handle transitions with a fake asyncio task.
    class _FakeTask:
        def __init__(self):
            self._done = False
        def done(self):
            return self._done

    task = None  # self._tu_squad_task starts absent

    # Tick 1: no task → launch (orchestrator would create_task + defer).
    act = squad_gate_tick_action(task_exists=task is not None,
                                 task_done=bool(task is not None and task.done()))
    assert act == "launch"
    task = _FakeTask()  # orchestrator stores the background task

    # Tick 2: task in flight, not done → defer, and DO NOT launch a second.
    act = squad_gate_tick_action(task_exists=task is not None,
                                 task_done=bool(task is not None and task.done()))
    assert act == "defer"
    assert task is not None  # single-flight: the same handle is retained

    # Tick 3: task finished → consume; the orchestrator then clears the handle.
    task._done = True
    act = squad_gate_tick_action(task_exists=task is not None,
                                 task_done=bool(task is not None and task.done()))
    assert act == "consume"
    task = None  # consumed → handle cleared so a later defer re-arms

    # Tick 4: consumed & re-deferred (e.g. retry/defect) → launch a fresh single-flight run.
    act = squad_gate_tick_action(task_exists=task is not None,
                                 task_done=bool(task is not None and task.done()))
    assert act == "launch"


def test_squad_release_decision_wallclock_still_preempts():
    # #532 preserves squad_release_decision: the wall-clock escape must still RELEASE the
    # gate even while a background squad is running past its budget. This is what lets the
    # loop reach create_release regardless of the background task's state.
    now = 10_000.0
    # Fresh, under budget → defer.
    assert squad_release_decision(now, 0, now) == "defer"
    # Wall-clock (900s default) elapsed since the first defer → release.
    assert squad_release_decision(now - 901.0, 0, now) == "release"
    # Attempt cap reached → release.
    assert squad_release_decision(now, 3, now) == "release"


def test_per_agent_timeout_default_bounded_to_180():
    # Complementary safety bound: the per-wave agent timeout default drops 900 -> 180s,
    # still overridable via the keyword.
    default = inspect.signature(run_test_user_squad).parameters["per_agent_timeout"].default
    assert default == 180.0


# ── #533: GUARD 2c honors the #521 sticky escape-release ───────────────────────
from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator


def _defer_active(gate, *, refs=("ref.png",), final=True):
    """Call _visual_delivery_defer_active on a lightweight stub (getattr-pure method)."""
    stub = types.SimpleNamespace(
        _reference_images=list(refs), _is_final_milestone=final, _vf_gate=gate)
    return Orchestrator._visual_delivery_defer_active(stub)


def _gate(**kw):
    g = types.SimpleNamespace(
        passed=False, released=False, deferred_since=None, attempts=0,
        total_judgments=0, plateau_rounds=0, last_judgment_at=None)
    for k, v in kw.items():
        setattr(g, k, v)
    return g


@pytest.fixture(autouse=True)
def _visual_blocking_on(monkeypatch):
    # The predicate short-circuits to False if visual blocking is disabled; keep it ON so
    # the tests exercise the gate/released logic rather than the env short-circuit.
    monkeypatch.setenv("ENVGEN_VISUAL_BLOCKING", "1")


def test_released_true_passed_false_returns_false():
    # #533 CORE: sticky escape-release → GUARD 2c must NOT block deliver_project.
    assert _defer_active(_gate(released=True, passed=False)) is False


def test_passed_true_returns_false():
    # Unchanged: a passed gate is not deferring.
    assert _defer_active(_gate(passed=True, released=False)) is False


def test_both_false_no_escape_returns_true():
    # Unchanged: not passed, not released, deferral anchored & under budget → still deferring.
    assert _defer_active(_gate(passed=False, released=False,
                               deferred_since=time.time())) is True


def test_both_false_not_yet_anchored_returns_true():
    # Unchanged: final milestone reached, deferral not yet anchored → defer.
    assert _defer_active(_gate(passed=False, released=False, deferred_since=None)) is True


def test_no_reference_images_returns_false():
    # Unchanged guard: nothing to compare against → never defer on visuals.
    assert _defer_active(_gate(released=True), refs=()) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
