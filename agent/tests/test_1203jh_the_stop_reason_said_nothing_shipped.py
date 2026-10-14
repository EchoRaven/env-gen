r"""#1203jh: the stop reason said nothing was delivered beside a ledger of releases.

`_generic_stop_reason_1202je` is only called for `not success`, so "the coordination loop
exited without a delivery" is true OF THE PROJECT. Beside it, `usage.status` reads
`delivered` the moment ONE release was cut — #1202jg's definition, not a bug — and
`codehub_releases.json` lists the tags.

★ Measured over the 65 modern runs with a ledger: 8 carry that exact sentence and ALL
EIGHT cut releases (r145, r146 with two, r147, r152, r153, r156, r157, r160). So the field
contradicts the two records next to it in every instance it has ever had — and that
contradiction has a cost on record: this project misread `delivered` twice, which is why
`feedback_delivered_means_cut_a_release_not_finished` exists.

★ DENOMINATOR, HONESTLY: the last run to take this branch was r160 (2026-10-05); the
twenty since all hit a cap, a stuck-abort, or recorded no reason. This is not expected to
fire soon. It changes a sentence a human reads and nothing else — no verdict, no gate, no
behaviour — which is why it is worth landing on a denominator that small, and why these
tests assert only what the sentence says.
"""
import os
import sys
import types

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.orchestrator as ORCH  # noqa: E402


class _Store:
    def __init__(self, val):
        self._v = val

    def value(self):
        return self._v


def _orch(releases, *, failure_set=(), raising=False):
    """Only what the reason reader touches."""
    if raising:
        class _Bad:
            def value(self):
                raise RuntimeError("store unreadable")
        rel = _Bad()
    else:
        rel = _Store(releases) if releases is not None else None
    o = types.SimpleNamespace()
    o.hubs = types.SimpleNamespace(
        codehub=types.SimpleNamespace(stores=types.SimpleNamespace(releases=rel)),
        registryhub=None)
    o._fwval_failure_set = tuple(failure_set)
    o._fwval_stuck_blocker = None
    o._fwval_stuck_count = 0
    o._fwdeliver_stuck_count = 0
    return o


def _reason(o):
    return ORCH.Orchestrator._generic_stop_reason_1202je(o)


def test_it_names_the_releases_it_did_cut():
    """★ THE TICKET, on r146's shape: two tags cut and the sentence used to say the loop
    exited without a delivery, full stop."""
    out = _reason(_orch({"1.0.0": {}, "1.1.0": {}, "_meta": {"v": 1}}))
    assert "without a delivery" in out, out            # the project-level fact is kept
    assert "DID ship 2 release(s)" in out, out
    assert "1.0.0" in out and "1.1.0" in out, out
    assert "_meta" not in out, "the store's bookkeeping key was listed as a release: %s" % out


def test_it_says_nothing_when_nothing_shipped():
    """The clause must not appear for a run that really cut nothing — claiming a release
    that does not exist is the opposite defect and the more dangerous one (#1203hy's
    whole point)."""
    for rel in ({}, {"_meta": {"v": 1}}, None):
        out = _reason(_orch(rel))
        assert "DID ship" not in out, (rel, out)
        assert "without a delivery" in out, out


def test_the_other_branch_carries_it_too():
    """Both sentences are about the project, so both need the clause. #1203hh/#1203ia are
    the precedent for fixing only the failing branch and leaving the other one lying."""
    out = _reason(_orch({"1.0.0": {}}, failure_set=("business_chain",)))
    assert "no abort and no cap" in out, out
    assert "DID ship 1 release(s)" in out, out


def test_an_unreadable_store_still_produces_a_reason():
    """The method's own docstring: "accounting must never be the reason a run fails to
    record itself". An exception reading the releases must cost the CLAUSE, not the
    sentence.

    ★ `"without a delivery" in out` is NOT a pin here: the method's OUTER handler returns
    "the loop exited without a delivery; the stop state could not be read", which also
    contains it — so letting the inner failure escape left this test green. The assertion
    is the phrase only the real branch has.
    """
    out = _reason(_orch(None, raising=True))
    assert "an abort or a cap" in out, (
        "the release-store failure escaped to the outer handler and cost the real "
        "sentence: %r" % out)
    assert "DID ship" not in out, out


def test_it_points_at_the_definition_rather_than_restating_it():
    """The clause explains the contradiction by NAMING the owner of the `delivered`
    definition, so the reader goes to one place instead of inferring. #1032: this must not
    become a second, drifting statement of what `delivered` means."""
    out = _reason(_orch({"1.0.0": {}}))
    assert "#1202jg" in out, out
    assert "usage.status" in out, out
