"""#1202bz — milestone-level granularity for --resume.

`.checkpoint` held one phase for the whole run (119 of 121 corpus runs: `agent_workflow:
planning`, nothing else), so a resume re-entered at milestone 1 every time.

The safety property under test: a milestone that COMPLETED is skipped only when the run
demonstrably moved past it. The lanes' work and every coordination tick live INSIDE the
milestone body while the gate that ends a run runs after the loop, so skipping the
milestone still in flight would walk past the only place remediation can happen — r35's
exact shape (milestone done, post-loop gate failed on one check).

LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.milestone_resume import (  # noqa: E402
    milestone_key_1202bz, should_skip_milestone_1202bz, phase_status_map_1202bz)

M1 = {"name": "core", "version": "0.1.0"}
M2 = {"name": "social", "version": "0.2.0"}
M3 = {"name": "polish", "version": "1.0.0"}


def _k(i, m):
    return milestone_key_1202bz(i, m)


def test_a_fresh_run_skips_nothing():
    assert should_skip_milestone_1202bz({}, 1, M1) is False


def test_a_completed_milestone_the_run_moved_past_is_skipped():
    phases = {_k(1, M1): "complete", _k(2, M2): "complete", _k(3, M3): "planning"}
    assert should_skip_milestone_1202bz(phases, 1, M1) is True
    assert should_skip_milestone_1202bz(phases, 2, M2) is True


def test_the_milestone_still_in_flight_is_never_skipped():
    """THE property. r35: milestone 1 completed, the post-loop gate failed, run died. If
    'complete' alone meant 'skip', a resume would walk past the only place lanes work,
    re-run the gate, fail identically and exit — worse than today."""
    assert should_skip_milestone_1202bz({_k(1, M1): "complete"}, 1, M1) is False


def test_the_last_of_several_completed_milestones_is_re_entered():
    phases = {_k(1, M1): "complete", _k(2, M2): "complete"}
    assert should_skip_milestone_1202bz(phases, 1, M1) is True
    assert should_skip_milestone_1202bz(phases, 2, M2) is False


def test_an_incomplete_milestone_is_not_skipped():
    phases = {_k(1, M1): "planning", _k(2, M2): "complete"}
    assert should_skip_milestone_1202bz(phases, 1, M1) is False


def test_a_failed_milestone_is_not_skipped():
    phases = {_k(1, M1): "failed", _k(2, M2): "complete"}
    assert should_skip_milestone_1202bz(phases, 1, M1) is False


def test_renaming_a_milestone_does_not_skip_it():
    """The key carries identity, not just position: editing the milestone list between
    attempts must not skip work that was never done under that name."""
    phases = {_k(1, M1): "complete", _k(2, M2): "complete"}
    renamed = {"name": "core-v2", "version": "0.1.0"}
    assert should_skip_milestone_1202bz(phases, 1, renamed) is False


def test_bumping_a_version_does_not_skip_it():
    phases = {_k(1, M1): "complete", _k(2, M2): "complete"}
    assert should_skip_milestone_1202bz(phases, 1, {"name": "core", "version": "0.1.1"}) is False


def test_a_milestone_without_name_or_version_still_keys_stably():
    a = milestone_key_1202bz(2, {})
    assert a == milestone_key_1202bz(2, {}) and a.startswith("milestone:2:")


def test_unrelated_phases_do_not_count_as_a_later_milestone():
    """`agent_workflow` is what the checkpoint already records; it must not be mistaken for
    a successor milestone."""
    phases = {_k(1, M1): "complete", "agent_workflow": "planning"}
    assert should_skip_milestone_1202bz(phases, 1, M1) is False


class _Ph:
    def __init__(self, status):
        self.status = status


class _CM:
    def __init__(self, phases):
        self.checkpoint = type("C", (), {"phases": phases})()


def test_phase_status_reads_objects_and_dicts():
    got = phase_status_map_1202bz(_CM({"a": _Ph("complete"), "b": {"status": "planning"}}))
    assert got == {"a": "complete", "b": "planning"}


def test_an_unreadable_checkpoint_skips_nothing():
    """Best-effort in the SAFE direction: no record means re-enter, never skip."""
    class Broken:
        @property
        def checkpoint(self):
            raise RuntimeError("boom")
    assert phase_status_map_1202bz(Broken()) == {}


def test_orchestrator_records_and_consumes_the_milestone_phase():
    """#943: landmark anchors. Both halves must survive — a skip with no completion record
    never fires, and a completion record with no skip is dead weight."""
    src = (LLM / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    loop = src.index("for _m_idx, _milestone in enumerate(milestones, start=1):")
    body = src[loop:src.index("# Hard gate: objective validation", loop)]
    assert "should_skip_milestone_1202bz(" in body
    assert "self.checkpoint.start_phase(_mkey)" in body
    assert "self.checkpoint.complete_phase(_mkey)" in body


def test_completion_is_recorded_after_the_budget_raise():
    """A milestone that raised must not be marked done. Anchored on the raise, not a byte
    window."""
    src = (LLM / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    raise_at = src.index("Run budget exceeded ({budget_exceeded}) without delivery")
    assert src.index("self.checkpoint.complete_phase(_mkey)") > raise_at
