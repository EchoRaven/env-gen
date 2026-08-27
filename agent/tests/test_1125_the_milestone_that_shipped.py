"""#1125: the milestone that actually shipped the product was never marked delivered.

The only writer of the `delivered` status was the milestone loop head, which marks every
PREVIOUS milestone when the NEXT one starts. The last milestone of every run — and the
only milestone of a single-milestone run — has no "next", so it could never be marked.

Measured over the corpus: 69 runs carry a milestones.json and 68 of them (99%) end with
their final milestone NOT delivered — 48 still "pending", 20 still "active", 1
delivered. A four-milestone success reads ['delivered','delivered','delivered','active'],
which is the mark-the-previous rule falling straight out.

Not cosmetic: `deliverability.py` judges on `status != "delivered"`, and any reader of
the ledger asking "which runs delivered?" gets the wrong answer for the milestone that
shipped. The live case is the gpt-5.5 run this was found in — Status: SUCCESS, main()
returned 0, artifact builds/boots/authenticates/serves seeded data, milestone "pending".
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime.milestone_registry import (
    MilestoneRegistry,
    _FROZEN_STATUSES,
    _VALID_STATUSES,
)


@pytest.fixture
def registry(tmp_path):
    return MilestoneRegistry(tmp_path)


def _seed(reg, n):
    return reg.set_roadmap(
        [{"name": "M%d" % i, "version": "1.%d.0" % (i - 1)} for i in range(1, n + 1)],
        agent="orchestrator")


def test_marking_the_final_milestone_delivered_sticks(registry):
    _seed(registry, 1)
    registry.mark_status(1, "active", agent="orchestrator")
    registry.mark_status(1, "delivered", agent="orchestrator")
    got = [m for m in registry.list_milestones() if int(m["index"]) == 1][0]
    assert got["status"] == "delivered"


def test_remarking_is_idempotent(registry):
    """The delivery check can fire more than once; a re-mark must not disturb it."""
    _seed(registry, 1)
    for _ in range(3):
        registry.mark_status(1, "delivered", agent="orchestrator")
    got = [m for m in registry.list_milestones() if int(m["index"]) == 1][0]
    assert got["status"] == "delivered"


def test_the_orchestrator_marks_the_delivering_milestone_not_only_the_previous_ones():
    """The fix itself: a `delivered` write must exist on the delivery path.

    Before #1125 the only `mark_status(..., "delivered")` in the orchestrator sat in the
    loop head, guarded by `< _m_idx` — structurally unable to name the current one.
    """
    from env_generator.llm_generator.multi_agent import orchestrator as orch

    src = inspect.getsource(orch)
    # the `while not ...is_set()` wait loop shares the substring, so anchor on the
    # `if` form -- the branch taken once delivery HAS happened
    i = src.index("if orchestrator_lane._project_delivered_event.is_set():")
    # landmark-anchored: that branch, up to the budget write that closes it
    branch = src[i:src.index("_write_run_budget", i)]
    assert 'mark_status(' in branch and '"delivered"' in branch, (
        "the delivery branch does not mark the milestone that just delivered"
    )
    assert "_m_idx" in branch, "it marks something other than the current milestone"


def test_the_loop_head_still_marks_earlier_milestones():
    """#1125 adds a writer; it must not remove the one that was already there."""
    from env_generator.llm_generator.multi_agent import orchestrator as orch

    src = inspect.getsource(orch)
    assert '< _m_idx and _pm.get("status") != "delivered"' in src, (
        "the mark-the-previous rule was removed rather than supplemented"
    )


def test_frozen_statuses_does_not_guard_mark_status(registry):
    """Pin the fact the fix's comment relies on: mark_status is a plain set.

    _FROZEN_STATUSES guards structural edits and the seed merge, not this. If that ever
    changes, the fix's reasoning about idempotence needs re-reading.
    """
    assert "delivered" in _FROZEN_STATUSES
    _seed(registry, 1)
    registry.mark_status(1, "delivered", agent="orchestrator")
    registry.mark_status(1, "active", agent="orchestrator")
    got = [m for m in registry.list_milestones() if int(m["index"]) == 1][0]
    assert got["status"] == "active", (
        "mark_status now refuses a downgrade — re-read #1125's idempotence note"
    )


def test_an_invalid_status_is_still_refused(registry):
    _seed(registry, 1)
    out = registry.mark_status(1, "shipped", agent="orchestrator")
    assert "error" in out
    assert "shipped" not in _VALID_STATUSES


def test_a_multi_milestone_run_ends_all_delivered(registry):
    """The shape the corpus never produced: every milestone delivered at the end."""
    _seed(registry, 3)
    # loop head marks the previous ones as each new milestone starts
    for idx in (1, 2, 3):
        for prev in range(1, idx):
            registry.mark_status(prev, "delivered", agent="orchestrator")
        registry.mark_status(idx, "active", agent="orchestrator")
        # #1125: and the delivery branch marks THIS one when it ships
        registry.mark_status(idx, "delivered", agent="orchestrator")
    statuses = [m["status"] for m in sorted(registry.list_milestones(),
                                            key=lambda m: int(m["index"]))]
    assert statuses == ["delivered"] * 3, statuses
