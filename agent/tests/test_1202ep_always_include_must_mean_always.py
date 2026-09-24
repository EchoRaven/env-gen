r"""#1202ep: always_include was filtered by the candidate pool, so it failed exactly when needed.

    always_include = [name for name in (always_include or []) if name in set(candidate_names)]

This is the root cause of the resume blocker measured on googlemaps-r16 and netflix.

The kickoff decision tools -- `workhub_add_meeting_decision`, `kickoff_declare_predicate` --
appear in ONE stage allowlist, `kickoff:action`, and only for backend/frontend/verifier. The
lookup is keyed `f"{phase}:{stage_name}"`, so a lane is offered them only while the run's
phase IS kickoff.

A RESUME re-enters at `phase=implement` and re-runs kickoff anyway. The candidate pool then
comes from `implement:action`, which has neither tool; the line above dropped them from
always_include; and the lane answered the kickoff request, in its own words in the meeting
doc, with "the required kickoff decision/declaration tool ... is not available in this step".

Kickoff stalled on every resume measured -- 243s, 309s, 301s -- each followed by tick=0 and
a delivery-gate abort. It is the main failure mode of the resume path.

The filter's real job is to refuse a name no tool answers to. `tool_instances` is what says
that; `candidate_names` is a ranking pool, not an existence check.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.tool_surface import rank_tool_names  # noqa: E402

KICKOFF = "workhub_add_meeting_decision"


class _T:
    def __init__(self, name):
        self.name = name
        self.description = name.replace("_", " ")
        self.categories = set()


def _pool(*names):
    return {n: _T(n) for n in names}


def test_the_resume_case_end_to_end():
    """A narrowed implement-phase pool, with the kickoff tool force-set. It must be offered."""
    instances = _pool(KICKOFF, "read", "write", "edit", "lint")
    got = rank_tool_names(
        tool_instances=instances,
        candidate_names=["read", "write", "edit", "lint"],   # implement:action — no kickoff tool
        query_text="record the kickoff decision for section backend",
        preferred_categories=set(),
        limit=4,
        always_include=[KICKOFF],
    )
    assert KICKOFF in got, "the lane cannot answer a kickoff request without it"


def test_a_name_no_tool_answers_to_is_still_refused():
    """The filter's real job survives."""
    got = rank_tool_names(
        tool_instances=_pool("read", "write"),
        candidate_names=["read", "write"],
        query_text="anything",
        preferred_categories=set(),
        limit=2,
        always_include=["a_tool_that_does_not_exist"],
    )
    assert "a_tool_that_does_not_exist" not in got


def test_an_always_include_that_is_a_candidate_still_works():
    got = rank_tool_names(
        tool_instances=_pool(KICKOFF, "read"),
        candidate_names=[KICKOFF, "read"],
        query_text="x",
        preferred_categories=set(),
        limit=1,
        always_include=[KICKOFF],
    )
    assert KICKOFF in got


def test_the_limit_still_bounds_the_ranked_tail():
    """always_include is additive; it must not blow the surface open."""
    instances = _pool(KICKOFF, *[f"t{i}" for i in range(30)])
    got = rank_tool_names(
        tool_instances=instances,
        candidate_names=[f"t{i}" for i in range(30)],
        query_text="x",
        preferred_categories=set(),
        limit=5,
        always_include=[KICKOFF],
    )
    assert KICKOFF in got
    assert len(got) <= 6, len(got)


def test_no_always_include_is_unchanged():
    got = rank_tool_names(
        tool_instances=_pool("read", "write", "edit"),
        candidate_names=["read", "write", "edit"],
        query_text="read the file",
        preferred_categories=set(),
        limit=2,
        always_include=None,
    )
    assert len(got) <= 2 and set(got) <= {"read", "write", "edit"}


def test_an_empty_instance_pool_falls_back_to_candidates():
    """Defensive: a caller that passes no instances must not lose its always-includes."""
    got = rank_tool_names(
        tool_instances={},
        candidate_names=["read", KICKOFF],
        query_text="x",
        preferred_categories=set(),
        limit=1,
        always_include=[KICKOFF],
    )
    assert KICKOFF in got
