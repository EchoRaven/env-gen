r"""#865: the branch logged a fallback and performed none.

`plan_milestones`' contract is explicit — *"None on any failure (**caller falls back to a single
milestone**)"*. The caller's `else` branch logged *"Milestone planning unavailable — single
milestone"* and **assigned nothing**. It was correct only because an M1 is synthesized ~230 lines
earlier, at a site the branch does not mention and which is easy to remove without noticing.

★ A promise kept by coincidence at a distance, which is the class this whole session has been
about — and unusually, one where the cost is already measured. #864 established that
`start_kickoff` runs **inside** the loop over `milestones`, so an empty list is a total loss with
no exception anywhere: 7 corpus runs (r19, r35, r38, r42, r44, r136, r140) died exactly that way.
This branch is not what emptied the list in those runs — the planner returning `None` leaves the
default intact — but it is the one place that *claims* to guarantee the invariant those runs
violated, and it did not.

**No behaviour change today.** The guard is a no-op whenever the invariant already holds, which is
every corpus run that reached this point. What changes is that the invariant is now enforced
where it is claimed, and a violation is loud instead of a total-loss run that looks idle.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch


def _branch():
    """The `else` arm, anchored between its own marker and the roadmap seed that follows."""
    src = inspect.getsource(orch)
    start = src.index("#865: HONOUR the fallback")
    end = src.index("set_roadmap(milestones", start)
    return src[start:end]


def test_the_branch_is_findable():
    """Non-vacuity: every case below reads this arm."""
    src = inspect.getsource(orch)
    assert "#865: HONOUR the fallback" in src
    assert "Milestone planning unavailable" in src


def test_the_fallback_actually_assigns():
    """The defect: the log claimed a single milestone and no milestone was created."""
    b = _branch()
    assert "milestones = [{" in b
    assert '"name": "M1"' in b and '"version": "1.0.0"' in b


def test_it_only_fires_when_the_invariant_is_broken():
    """★ A no-op on every healthy run. A fallback that overwrote a real list would be a far worse
    bug than the one being fixed — it would silently discard a planned roadmap."""
    b = _branch()
    assert "if not milestones:" in b
    i = b.index("if not milestones:")
    assert b.index("milestones = [{") > i, "the assignment must be inside the guard"


def test_the_violation_is_loud():
    """This state is unrecoverable downstream (#864), so it is an error, not the warning the line
    already had — a warning is exactly what let 7 runs pass unnoticed."""
    b = _branch()
    assert "_logger.error" in b
    assert "start_kickoff" in b, "the message must name the consequence"


def test_the_normal_warning_survives_and_reports_the_count():
    """The original line stays — it is a legitimate signal that planning did not run — but it now
    prints how many milestones there actually are, so it cannot describe a fallback that did not
    happen."""
    b = _branch()
    assert "single milestone (%d)" in b
    assert "len(milestones)" in b


def test_the_slice_matches_the_original_synthesis():
    """The fallback must produce the SAME milestone the top-of-function synthesis does, or the two
    paths diverge and the invariant becomes 'a milestone' rather than 'the right one'."""
    src = inspect.getsource(orch)
    top = src.index('"description_slice": (requirements[0] if requirements else goal)')
    assert top > 0, "the original synthesis moved — the fallback must be re-checked against it"
    b = _branch()
    assert "requirements[0] if requirements else goal" in b


def test_the_planner_contract_still_says_what_this_honours():
    """★ Non-vacuity for the premise. If `plan_milestones` stops promising a caller fallback, this
    fix is answering a claim nobody makes any more."""
    from env_generator.llm_generator.multi_agent.runtime import reference_materials as rm
    doc = inspect.getdoc(rm.plan_milestones) or ""
    assert "falls back to a single milestone" in doc, doc


def test_an_empty_planner_result_still_keeps_the_default():
    """The path that is NOT this branch: `plan_milestones` returning `[]` is falsy, so control
    reaches here and the pre-existing list survives. Pinned because a future `if _planned is not
    None:` would route an empty list into `milestones` and re-create #864's total loss."""
    src = inspect.getsource(orch)
    assert re.search(r"\n\s*if _planned:\s*\n", src), "the truthiness test guards the empty list"
    assert "if _planned is not None" not in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
