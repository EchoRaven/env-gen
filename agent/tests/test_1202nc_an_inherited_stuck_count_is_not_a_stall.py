"""#1202nc: the delivery-gate stuck abort must not fire on a resume's inherited count, and a latch
must not outlive the count that raised it.

tiktok-r125's M2 resume: `_fwdeliver_stuck_count` is restored across processes (#1202dv, on
purpose), and `deliverability_no_successful_run` is red by definition until the new process
records a run. The resume's first gate declines were at 04:31:09; at 04:31:40 it latched
"stuck ... for 7 consecutive cycles" and — after the failing set changed at 04:33, 04:35 and
04:36 — still aborted at 04:45:10 "after 0 coordination ticks".

#1202lu already gives the no-convergence abort a floor of evaluations made by THIS process;
this ladder gets the same floor, and a latch it raised is cleared when its count resets.
"""
import asyncio
import os
import sys
import threading
import types
import logging

LLM = os.path.join(os.path.dirname(__file__), "..", "env_generator", "llm_generator")
sys.path.insert(0, os.path.abspath(LLM))

import multi_agent.orchestrator as O  # noqa: E402
from multi_agent.orchestrator import Orchestrator  # noqa: E402

STUCK = ["business_chain_failing", "contract_alignment_failed", "deliverability_no_successful_run"]


def _orch(failed):
    orch = Orchestrator.__new__(Orchestrator)
    orch._logger = logging.getLogger("t1202nc")
    orch._project_delivered_event = threading.Event()

    class _Api:
        def get_endpoints(self):
            return {"GET:/api/x": {"id": "GET:/api/x", "method": "GET", "path": "/api/x",
                                    "kind": None, "status": "implemented"}}

    orch.hubs = types.SimpleNamespace(registryhub=_Api(), codehub=types.SimpleNamespace())
    orch._tu_squad_passed = True
    orch._gate = {"failed_checks": list(failed)}
    orch._validate_delivery_gate = lambda: dict(orch._gate)
    orch._deliver_progress_sig = lambda: ("same-source", "same-contract", "same-chains")
    return orch


def _tick(orch, n=1):
    for _ in range(n):
        asyncio.run(orch._maybe_framework_deliver())


def test_a_fresh_process_still_latches_after_enough_unchanged_evaluations():
    orch = _orch(STUCK)
    _tick(orch, O.FWVAL_STUCK_ABORT_AFTER)
    assert orch._fwval_abort_reason and "consecutive cycles" in orch._fwval_abort_reason


def test_a_resumes_inherited_count_does_not_latch_on_its_first_evaluation():
    first = _orch(STUCK)
    _tick(first)                                     # the key the dead process stored
    resumed = _orch(STUCK)
    resumed._fwdeliver_stuck_key = first._fwdeliver_stuck_key
    resumed._fwdeliver_stuck_count = O.FWVAL_STUCK_ABORT_AFTER - 1   # restored by #1202dv
    _tick(resumed)
    assert resumed._fwdeliver_stuck_count >= O.FWVAL_STUCK_ABORT_AFTER
    assert not getattr(resumed, "_fwval_abort_reason", None)


def test_the_resume_can_still_abort_once_it_has_evaluated_enough_itself():
    first = _orch(STUCK)
    _tick(first)
    resumed = _orch(STUCK)
    resumed._fwdeliver_stuck_key = first._fwdeliver_stuck_key
    resumed._fwdeliver_stuck_count = O.FWVAL_STUCK_ABORT_AFTER - 1
    _tick(resumed, O._MIN_GATE_EVALS_BEFORE_ABORT_1202LU)
    assert resumed._fwval_abort_reason, "a genuine wedge must still fail fast"


def test_a_latch_is_cleared_when_the_failing_set_changes():
    orch = _orch(STUCK)
    _tick(orch, O.FWVAL_STUCK_ABORT_AFTER)
    assert orch._fwval_abort_reason
    orch._gate = {"failed_checks": ["contract_alignment_failed", "deliverability_no_successful_run"]}
    _tick(orch)
    assert orch._fwval_abort_reason is None
    assert orch._fwval_abort_deliver_reason is None


def test_another_paths_abort_is_not_cleared_by_this_ladder():
    orch = _orch(STUCK)
    orch._fwval_abort_reason = "framework validation stuck (Site A)"
    orch._gate = {"failed_checks": ["contract_alignment_failed"]}
    _tick(orch)
    assert orch._fwval_abort_reason == "framework validation stuck (Site A)"
