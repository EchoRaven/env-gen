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
    assert "SHIPPED:" in out, out
    assert "1.0.0" in out and "1.1.0" in out, out
    assert "_meta" not in out, "the store's bookkeeping key was listed as a release: %s" % out


def test_it_says_nothing_when_nothing_shipped():
    """The clause must not appear for a run that really cut nothing — claiming a release
    that does not exist is the opposite defect and the more dangerous one (#1203hy's
    whole point)."""
    for rel in ({}, {"_meta": {"v": 1}}, None):
        out = _reason(_orch(rel))
        assert "SHIPPED:" not in out, (rel, out)
        assert "without a delivery" in out, out


def test_the_other_branch_carries_it_too():
    """Both sentences are about the project, so both need the clause. #1203hh/#1203ia are
    the precedent for fixing only the failing branch and leaving the other one lying."""
    out = _reason(_orch({"1.0.0": {}}, failure_set=("business_chain",)))
    assert "no abort and no cap" in out, out
    assert "SHIPPED:" in out, out


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
    assert "SHIPPED:" not in out, out


def test_the_clause_survives_the_field_cap():
    """★ #1203jhb, AND THE REASON THE CLAUSE MOVED. `run_budget` writes
    `str(reason)[:_REASON_CAP_1202EB]` with the cap at 400, and the first version appended
    184 characters LAST. The branch that actually fires carries `bits` -- a failure set, a
    stuck blocker and a decline count, 294 characters as r171 recorded them -- so 294 + 184
    = 478 and the 78 over the cap came off the END, which was exactly this clause. An
    explanation appended after the evidence loses to the cap (#1202vx, #1203d5).

    Asserted against the real cap, imported rather than retyped, and on a realistic `bits`
    payload rather than an empty one: with no bits the old version fitted, which is why the
    other tests here never saw it.
    """
    from multi_agent.runtime.run_budget import _REASON_CAP_1202EB as CAP
    # ★ THE PAYLOAD HAS TO BE THE WORST REALISTIC ONE, or position does not discriminate:
    # with three failure names the whole string was 392 and the clause fitted at either
    # end, so the mutation that moves it back to the END stayed GREEN. `bits` prints up to
    # SIX names from the failure set plus the stuck-blocker sentence and the decline count
    # — that alone exceeds the 400-char cap, and then only the clause's POSITION decides
    # whether it survives.
    o = _orch({"1.0.0": {}, "1.1.0": {}, "1.2.0": {}},
              failure_set=("business_chain", "deliverability_ui_flow_failed",
                           "validation_ui_evidence_failed", "incomplete_required_tasks",
                           "deliverability_guard_tampering", "contract_alignment_failed"))
    o._fwval_stuck_blocker = "deliverability_ui_flow_failed"
    o._fwval_stuck_count = 12
    o._fwdeliver_stuck_count = 31
    out = _reason(o)
    assert len(out) > CAP, (
        "this payload does not reach the cap (%d of %d), so it cannot show whether the "
        "clause survives truncation" % (len(out), CAP))
    # ★ `"SHIPPED:" in out[:CAP]` is NOT the property: at the END the clause STARTS at ~380
    # and so its first word is inside the cap while the tags are cut off mid-clause. What
    # has to survive is the PAYLOAD — the tags — so assert the last one does.
    kept = out[:CAP]
    assert "SHIPPED:" in kept and "1.2.0" in kept, (
        "the shipped clause does not survive the %d-char cap intact: it starts at %d of %d "
        "and the kept text ends %r" % (CAP, out.find("SHIPPED:"), len(out), kept[-40:]))
    # and the diagnostic bits must still be there, not displaced by the clause
    assert "stuck on" in out, out


def test_it_points_at_the_definition_rather_than_restating_it():
    """The clause explains the contradiction by NAMING the owner of the `delivered`
    definition, so the reader goes to one place instead of inferring. #1032: this must not
    become a second, drifting statement of what `delivered` means."""
    out = _reason(_orch({"1.0.0": {}}))
    assert "#1202jg" in out, out
    assert "status" in out and "delivered" in out, out
