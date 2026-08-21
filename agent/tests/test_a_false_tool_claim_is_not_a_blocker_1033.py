r"""#1033: a FAILED task blocked the cut on a capability claim that was checkably false.

r174's ONLY failed task — and half of its terminal gate (`unresolved_failed_tasks`) — was:

    title  Restore verifier kickoff decision tool exposure
    reason Confirmed framework/control-plane access blocker: canonical verifier tool-profile
           is outside the generated workspace, and no lane with repository access can patch
           or lint it.

By construction unfixable by any agent, so it blocked to the abort. **The premise was false.**

    the verifier called `workhub_add_meeting_decision` 4/4 times in r172 and 6/6 in r173
    the profile grants it: `meeting_tools` bundle + an explicit "kickoff:action" allowlist entry
    `_HUB_REGISTRATION` pins it into the `edit_code` stage (base.py:458)
    `validate_stage_allowlist_alignment` reported it GRANTED — its only DEAD findings in r174
        were the debugger's `codehub_list_prs`
    in r174 the verifier never called it once; it asserted the tool was missing, another lane
        "confirmed" that, and the false claim became permanent

#751 is right that `failed` is the narrow, meaningful status — `fail_task` is authorised and
requires a reason, so it means "attempted and did not work". That argument assumes the reason
is TRUE. When the reason names a tool and we hold the granted set, it is checkable.

This changes NO verdict: the task still blocks. It says, loudly, that the blocker rests on a
falsehood, so the orchestrator can re-open or re-assign instead of accepting it.

★ The capability had to be recorded before it could be checked: `tool_schema_map` existed only
as a local inside `_log_registered_tools`, so nothing downstream could answer "is this tool
granted?". It is now stashed as `agent._registered_tool_names`, and the orchestrator unions it
across lanes.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as O
from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    contradicted_tool_claims_1033 as detect, unresolved_bug_tasks_743)

_R174 = {
    "id": "task_x", "status": "failed",
    "title": "Restore verifier kickoff decision tool exposure",
    "fail_reason": ("Confirmed framework/control-plane access blocker: required "
                    "`workhub_add_meeting_decision` is not exposed in my current tool "
                    "surface, and no lane with repository access can patch it."),
}
_GRANTED = {"workhub_add_meeting_decision", "read", "write"}


# --- the detector ------------------------------------------------------------------------

def test_the_r174_task_is_flagged_when_the_tool_is_granted():
    out = detect([_R174], _GRANTED)
    assert len(out) == 1 and out[0]["tool"] == "workhub_add_meeting_decision"


def test_a_genuinely_missing_tool_is_NOT_flagged():
    """★ Specificity. If the tool really is not granted the task is a REAL blocker and must
    keep reading as one — flagging it would teach the reader to discount true blockers."""
    assert detect([_R174], {"read", "write"}) == []


def test_an_empty_granted_set_judges_nothing():
    """An empty container is not a fact (#1023b): a cold gate must not manufacture a
    contradiction out of having registered no tools yet."""
    assert detect([_R174], set()) == []
    assert detect([_R174], None) == []


@pytest.mark.parametrize("phrasing", [
    "required `workhub_add_meeting_decision` is not exposed in my current tool surface",
    "workhub_add_meeting_decision is not available to this lane",
    "the workhub_add_meeting_decision tool is missing from my surface",
    "blocked: 'workhub_add_meeting_decision' unavailable",
])
def test_the_common_phrasings_are_recognised(phrasing):
    assert detect([dict(_R174, fail_reason=phrasing)], _GRANTED)


def test_only_failed_tasks_are_considered():
    for st in ("pending", "in_progress", "completed", "cancelled"):
        assert detect([dict(_R174, status=st)], _GRANTED) == []


def test_a_reason_naming_no_tool_is_quiet():
    assert detect([dict(_R174, fail_reason="the database would not start")], _GRANTED) == []


def test_it_never_raises_on_junk():
    for junk in ([{}], [None], ["x"], None, [dict(_R174, fail_reason=None)]):
        assert isinstance(detect(junk, _GRANTED), list)


# --- wiring: the check must not be dead --------------------------------------------------

class _WH:
    def __init__(self, tasks): self._t = tasks
    def list_tasks(self): return self._t


class _Hubs:
    def __init__(self, tasks): self.workhub = _WH(tasks)


def test_the_collector_surfaces_it():
    out = unresolved_bug_tasks_743(_Hubs([_R174]), None, _GRANTED)
    assert out["contradicted_tool_claims"], out
    assert out["failed_count"] == 1, "the task still counts as failed — no verdict changed"


def test_the_gate_reports_it():
    src = inspect.getsource(
        __import__("env_generator.llm_generator.multi_agent.runtime.delivery_gate",
                   fromlist=["x"]))
    assert "#1033" in src and "CONTRADICTED" in src


def test_the_gate_passes_the_granted_set_through():
    src = inspect.getsource(
        __import__("env_generator.llm_generator.multi_agent.runtime.delivery_gate",
                   fromlist=["x"]))
    assert "unresolved_bug_tasks_743(hubs, output_dir, granted_tool_names)" in src


def test_the_orchestrator_supplies_it():
    """★ An unwired check reports 'no contradictions' forever — the dead-check trap this
    session keeps finding. Assert the producer AND the hand-off."""
    src = inspect.getsource(O)
    assert "def _all_registered_tool_names" in src
    assert "granted_tool_names=self._all_registered_tool_names()" in src


def test_the_agent_records_its_registered_tools():
    from env_generator.llm_generator.multi_agent.agents.runtime.step_pipeline import (
        tooling as T)
    src = inspect.getsource(T)
    assert "self._registered_tool_names = set(tool_schema_map)" in src


def test_the_union_is_empty_and_safe_with_no_agents():
    """Exercised against the real method, not a source grep."""
    class _O:
        _agents = {}
    fn = O.Orchestrator._all_registered_tool_names
    assert fn(_O()) == set()


def test_the_union_gathers_names_across_lanes():
    class _A:
        def __init__(self, names): self._registered_tool_names = set(names)
    class _O:
        _agents = {"verifier": _A({"read", "workhub_add_meeting_decision"}),
                   "backend": _A({"write"})}
    got = O.Orchestrator._all_registered_tool_names(_O())
    assert got == {"read", "write", "workhub_add_meeting_decision"}


def test_a_lane_without_the_attribute_is_skipped_not_fatal():
    class _Bare: pass
    class _O:
        _agents = {"x": _Bare()}
    assert O.Orchestrator._all_registered_tool_names(_O()) == set()


def test_the_evidence_travels_with_the_check():
    d = " ".join((__doc__ or "").split())
    assert "4/4 times in r172 and 6/6 in r173" in d
    assert "changes NO verdict" in d, "the disposition must stay attached"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
