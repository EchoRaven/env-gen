"""#1202lr / #1202ls — r121's resume aborted 39 seconds before its last blockers cleared.

GROUND TRUTH (tiktok-web-r121 resume, 2026-09-13), from its gate ledger and workhub:

    02:18:01-02:18:16  the gate SYNTHESISES four required tasks, three of them against
                       endpoints the registry already carries as `deprecated`:
                         GET /__noop_orchestrator_read_not_allowed__   (framework sentinel)
                         GET /api/videos/{encodeURIComponent}(id)      (a JS template literal
                         GET /api/videos/{encodeURIComponent}(id)/comments  from a fetch call)
    02:21 4 -> 02:22 7 -> 02:24 6 -> 02:25 6 -> 02:26 2 -> 02:27 2 -> 02:28 2  blocking instances
    02:28:30           DELIVERY-GATE NO-CONVERGENCE ABORT (failing {'incomplete_required_tasks'})
    02:29:09/02:29:10  the last two tasks reach completed_at

Two defects, one after the other.

#1202lr — `incomplete_required_tasks` skipped deprecated endpoints out of `reg_clean`, which
is the EVIDENCE map. `_endpoint_validated` opens with "not registered -> cannot be validated",
so a task naming a retired endpoint can never be satisfied by evidence and is re-reported
every evaluation. The comment said "do NOT count them as required"; the code made them
permanently unsatisfiable-by-evidence instead. (A lane can still hand-close such a task, and
r121's did — `task_p0_backend_remove_dead_noop_endpoints_final_gate` — which is exactly the
ten minutes of an exhausted clock this was worth.)

#1202ls — #228's grace exists for this precise situation ("the verifier cleared the LAST gate
36s after the abort fired"), but it keys on `last_shrink_age_s`, the age of the last time the
failing CHECK SET lost a member. r121 held `['incomplete_required_tasks']` unchanged for its
last eight minutes, so that clock never moved while the instances under the name fell 7 -> 2.
The same falling-instance signal #1202lo gives the wall-clock cap now satisfies #228's
recency requirement — `max_failed` and the `max_grace` budget still bound everything.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


# ------------------------------------------------------------------ #1202lr

class _RH:
    def __init__(self, endpoints, tests=None):
        self._e, self._t = endpoints, (tests or {})

    def get_endpoints(self):
        return self._e

    def get_contract_test_results(self, key):
        return self._t.get(key) or []


class _SH:
    def list_tables(self):
        return {}


class _WH:
    def __init__(self, tasks):
        self._t = tasks

    def list_tasks(self):
        return self._t


class _Hubs:
    def __init__(self, endpoints, tasks, tests=None):
        self.registryhub = _RH(endpoints, tests)
        self.schema_hub = _SH()
        self.workhub = _WH(tasks)


R121_ENDPOINTS = {
    "_meta": {},
    "GET /__noop_orchestrator_read_not_allowed__": {
        "method": "GET", "path": "/__noop_orchestrator_read_not_allowed__",
        "status": "deprecated", "provider": "backend"},
    "GET /api/videos/{encodeURIComponent}(id)": {
        "method": "GET", "path": "/api/videos/{encodeURIComponent}(id)",
        "status": "deprecated", "provider": "backend"},
    "GET /api/feed": {
        "method": "GET", "path": "/api/feed", "status": "implemented",
        "provider": "backend"},
}

R121_TASKS = [
    {"id": "impl.endpoint.get.__noop_orchestrator_read_not_allowed",
     "status": "pending", "metadata": {"kind": "implement_endpoint"}},
    {"id": "validate.api_smoke.get.__noop_orchestrator_read_not_allowed",
     "status": "in_progress", "metadata": {"kind": "validate_api_smoke"}},
    {"id": "impl.endpoint.get._api_videos_{encodeURIComponent}(id)",
     "status": "pending", "metadata": {"kind": "implement_endpoint"}},
]


def test_retired_endpoints_stop_manufacturing_requirements():
    """★ r121's own registry and task ids."""
    out = dg.incomplete_required_tasks(_Hubs(R121_ENDPOINTS, R121_TASKS))
    assert out == [], [t["id"] for t in out]


def test_a_live_endpoint_with_no_evidence_still_blocks():
    """★ Non-vacuity: the gate must keep its teeth for endpoints that are NOT retired."""
    tasks = [{"id": "impl.endpoint.get._api_feed_missing", "status": "pending",
              "metadata": {"kind": "implement_endpoint",
                           "endpoint": {"method": "GET", "path": "/api/feed/missing"}}}]
    eps = dict(R121_ENDPOINTS)
    eps["GET /api/feed/missing"] = {"method": "GET", "path": "/api/feed/missing",
                                    "status": "defined", "provider": "backend"}
    out = dg.incomplete_required_tasks(_Hubs(eps, tasks))
    assert [t["id"] for t in out] == ["impl.endpoint.get._api_feed_missing"]


def test_deprecating_an_endpoint_does_not_hide_a_different_open_task():
    both = R121_TASKS + [{"id": "impl.endpoint.post._auth_logout", "status": "pending",
                          "metadata": {"kind": "implement_endpoint"}}]
    eps = dict(R121_ENDPOINTS)
    eps["POST /auth/logout"] = {"method": "POST", "path": "/auth/logout",
                                "status": "defined", "provider": "backend"}
    out = dg.incomplete_required_tasks(_Hubs(eps, both))
    assert [t["id"] for t in out] == ["impl.endpoint.post._auth_logout"], (
        "r121's genuinely-open blocker must survive; only the retired ones go")


# ------------------------------------------------------------------ #1202ls

def test_a_flat_check_name_no_longer_starves_the_grace():
    """★ r121's exact inputs: one failing check, no set shrink in ages, instances falling."""
    assert dg.convergence_grace(failed_count=1, last_shrink_age_s=1e9, grace_used=0,
                                instances_shrinking=True) > 0


def test_without_the_instance_signal_it_still_refuses():
    assert dg.convergence_grace(failed_count=1, last_shrink_age_s=1e9,
                                grace_used=0) == 0.0
    assert dg.convergence_grace(failed_count=1, last_shrink_age_s=1e9, grace_used=0,
                                instances_shrinking=False) == 0.0


def test_the_instance_signal_relaxes_recency_only():
    """It must not widen the size bound or the budget — otherwise it is a second,
    unbudgeted grace wearing #228's name."""
    # too many failing checks: still refused, however fast the instances fall
    assert dg.convergence_grace(failed_count=9, last_shrink_age_s=0, grace_used=0,
                                instances_shrinking=True) == 0.0
    # budget spent: still refused
    assert dg.convergence_grace(failed_count=1, last_shrink_age_s=0, grace_used=2,
                                instances_shrinking=True) == 0.0
    # zero failing checks is not a grace case
    assert dg.convergence_grace(failed_count=0, last_shrink_age_s=0, grace_used=0,
                                instances_shrinking=True) == 0.0


def test_the_orchestrator_passes_the_signal():
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "env_generator" / "llm_generator"
           / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "convergence_grace"]
    assert calls, "the no-convergence grace call moved"
    kws = {k.arg for k in calls[0].keywords}
    assert "instances_shrinking" in kws, (
        "the abort still cannot see a failing set that shrinks without losing a member")


def test_the_signal_comes_from_the_same_predicate_the_wall_clock_uses():
    """One fact, one measurement — #1202lo validated it on the corpus; a second hand-rolled
    notion of 'converging' would drift away from that validation."""
    import inspect
    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator._converging_instances_1202ls_impl)
    assert "converging_at_the_gate_1202lo" in src
