"""#1120: agents write milestone_index="1"; the hub demanded an int and rejected it.

Measured over the 85-run corpus by replaying the recorded tool calls: 518 calls failed
this validator across 35 runs — 41% of all runs — and 505 of them passed a numeric
STRING ('1' ×403, '2' ×69, '0' ×33, plus one '"1"' still carrying its quotes). They
arrive through `kickoff_declare_predicate` (385) and `workhub_add_meeting_decision`
(118), which both funnel into the same two hub validators.

Same class as #335, which `drop_unaccepted_kwargs` names outright — an LLM-authored
argument list meeting a strict boundary unnormalised — and the same answer as #338 and
#1104: coerce str↔int at the boundary rather than reject.
"""
import shutil
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry
from env_generator.llm_generator.multi_agent.runtime.hubs.workhub.service import (
    _coerce_milestone_index_1120 as coerce,
)


@pytest.fixture
def workhub():
    tmp = Path(tempfile.mkdtemp(prefix="wh_1120_"))
    try:
        yield HubRegistry(tmp).workhub
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _meeting(workhub):
    return workhub.create_meeting(
        agenda="kickoff", attendees=["frontend"], milestone_index=1,
        agent="orchestrator")["id"]


# --- the values the corpus actually produced -----------------------------------------

@pytest.mark.parametrize("written,expected", [
    ("1", 1),      # ×403
    ("2", 2),      # ×69
    ("0", 0),      # ×33
    ('"1"', 1),    # ×1 — the model left the quotes on
    ("  3  ", 3),  # whitespace is the same slip
])
def test_a_numeric_string_is_accepted(workhub, written, expected):
    mid = _meeting(workhub)
    workhub.add_meeting_decision(
        meeting_id=mid,
        decision={"section": "frontend", "content": {}},
        agent="frontend",
        milestone_index=written,
    )
    doc = workhub.get_document(mid)
    stored = (doc.get("metadata") or {}).get("decisions") or []
    assert stored, "the decision was not recorded at all"
    got = stored[-1].get("milestone_index")
    assert got == expected and isinstance(got, int) and not isinstance(got, bool), (
        "a coerced index must be stored as the int, not the string: %r" % (got,)
    )


def test_close_meeting_takes_it_too(workhub):
    """The second validator carries the identical shape and the identical slip."""
    mid = _meeting(workhub)
    workhub.close_meeting(
        meeting_id=mid, agent="orchestrator", produced_artifacts=[],
        milestone_index="2",
    )


# --- everything that was rejected before is still rejected ---------------------------

@pytest.mark.parametrize("bad", [True, False, -1, "-1", "abc", "1.5", "", "  ", 2.0, "1e3"])
def test_a_malformed_index_is_still_refused(workhub, bad):
    mid = _meeting(workhub)
    with pytest.raises(ValueError):
        workhub.add_meeting_decision(
            meeting_id=mid,
            decision={"section": "frontend", "content": {}},
            agent="frontend",
            milestone_index=bad,
        )


def test_none_is_still_optional(workhub):
    """milestone_index is optional; None must not be coerced into 0."""
    mid = _meeting(workhub)
    workhub.add_meeting_decision(
        meeting_id=mid, decision={"section": "frontend", "content": {}},
        agent="frontend", milestone_index=None,
    )


# --- the coercion itself --------------------------------------------------------------

def test_the_coercion_never_invents_a_number():
    for v in (True, False, None, 2.0, -1, "abc", "1.5", "", "  ", "1e3", "٣"):
        out = coerce(v, "t")
        assert out is v or out == v, "coerce fabricated a value from %r -> %r" % (v, out)


def test_an_int_passes_through_untouched():
    for v in (0, 1, 7, 4096):
        assert coerce(v, "t") is v
