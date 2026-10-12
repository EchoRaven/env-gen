"""#1203i6: the one suggestion that named nothing, with the instance on the same dict.

Every other entry in `delivery_gate_suggestions` names a path or a tool -- `app/backend`,
`registryhub_register_endpoint(...)`, `registryhub_register_verification_chain`. The one for
`verification_checklist_not_ready` said

    "Run and record verification/build checks until checklist is ready for delivery."

and named nothing, while the per-item statuses sit on the same `gate` dict the function
already receives -- `gate["verification"]["checklist"]`, which the report builder 200 lines
further down prints verbatim.

Measured over the persisted gate ledgers: 802 rows carry this check across 104 runs, and ALL
802 carry the checklist.

    exactly ONE item not success      217 rows (27%)
    all four not success              576 rows (72%)
    two or three                        9 rows

`{'sql_syntax': 'success', 'docker_build': 'success', 'npm_install': 'failure',
 'backend_start': 'success'}` is a real row: the gate knew a single item was red and told the
lane to run all four.

The two states are split because their remedies are OPPOSITE -- #1202ik's lesson about two
stops sharing one name. A `failure` was recorded and has to be fixed; a `pending` was never
run. The vocabulary is measured, not assumed: across 47312 checklist entries the only
statuses are `success` (44063), `failure` (2545) and `pending` (704), over four fixed names.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    _CHECKLIST_GENERIC_1203I6,
    _checklist_advice_1203i6,
    delivery_gate_suggestions,
)

ITEMS = ("sql_syntax", "docker_build", "npm_install", "backend_start")


def _gate(statuses, failed=("verification_checklist_not_ready",)):
    return {
        "failed_checks": list(failed),
        "verification": {"checklist": {k: {"status": v} for k, v in statuses.items()}},
    }


def _all(**over):
    s = {k: "success" for k in ITEMS}
    s.update(over)
    return s


def _advice(g):
    return [s for s in delivery_gate_suggestions(g) if "checklist" in s.lower()]


# ------------------------------------------------------------------- the 27% case


def test_a_single_failed_item_is_named():
    """The real row from the corpus."""
    out = _checklist_advice_1203i6(_gate(_all(npm_install="failure")))
    assert "npm_install" in out, out
    assert "FAILED" in out, out
    for other in ("sql_syntax", "docker_build", "backend_start"):
        assert other not in out, (other, out)


def test_the_named_item_reaches_the_suggestion_list():
    got = _advice(_gate(_all(npm_install="failure")))
    assert len(got) == 1, got
    assert "npm_install" in got[0], got[0]


def test_two_failed_items_are_both_named():
    out = _checklist_advice_1203i6(_gate(_all(npm_install="failure", sql_syntax="failure")))
    assert "npm_install" in out and "sql_syntax" in out, out


# ---------------------------------------------------- failure and pending differ


def test_a_pending_item_says_run_it_not_fix_it():
    out = _checklist_advice_1203i6(_gate(_all(backend_start="pending")))
    assert "backend_start" in out, out
    assert "never been recorded" in out, out
    assert "FAILED" not in out, out


def test_a_failure_says_fix_it_not_run_it():
    out = _checklist_advice_1203i6(_gate(_all(backend_start="failure")))
    assert "must be fixed" in out, out
    assert "never been recorded" not in out, out


def test_a_mix_says_both_and_keeps_them_apart():
    """★ The whole point of the split: opposite remedies must not be merged."""
    out = _checklist_advice_1203i6(
        _gate(_all(npm_install="failure", backend_start="pending")))
    assert "npm_install" in out and "backend_start" in out, out
    f, p = out.index("npm_install"), out.index("backend_start")
    assert "FAILED" in out and "never been recorded" in out, out
    assert f < p, "the failed item must not be described as unrecorded: %r" % out


def test_the_72_percent_case_names_all_four():
    """All four red is the early-run state; naming them is still more than naming none."""
    out = _checklist_advice_1203i6(_gate({k: "pending" for k in ITEMS}))
    for k in ITEMS:
        assert k in out, (k, out)
    assert "have never been recorded" in out, out


# ------------------------------------------------------- absence is not emptiness


def test_an_unreadable_checklist_keeps_the_original_sentence():
    """An unreadable checklist is not evidence that every item is pending."""
    for g in ({"failed_checks": ["verification_checklist_not_ready"]},
              {"failed_checks": ["verification_checklist_not_ready"], "verification": None},
              {"failed_checks": ["verification_checklist_not_ready"],
               "verification": {"checklist": {}}},
              {"failed_checks": ["verification_checklist_not_ready"],
               "verification": {"checklist": "nope"}}):
        assert _checklist_advice_1203i6(g) == _CHECKLIST_GENERIC_1203I6, g


def test_an_all_green_checklist_keeps_the_original_sentence():
    """The check fired for some other reason; do not invent a red item."""
    assert _checklist_advice_1203i6(_gate(_all())) == _CHECKLIST_GENERIC_1203I6


def test_junk_cannot_raise():
    for g in (None, [], "", 7, {"verification": 7}, {"verification": {"checklist": [1]}}):
        assert isinstance(_checklist_advice_1203i6(g), str), g


class _HostileChecklist(dict):
    """★ Passes `isinstance(..., dict)` and then raises INSIDE the loop. The first version of
    `test_junk_cannot_raise` used None / [] / 7, which all return early on the isinstance
    guard and never reach the body -- so a mutation turning the final `except` into `raise`
    survived a round. A guard is only load-bearing against an input that gets past the
    guards before it."""

    def __init__(self):
        super().__init__({"npm_install": {"status": "failure"}})

    def items(self):
        raise RuntimeError("the checklist blew up mid-iteration")


def test_a_checklist_that_raises_mid_read_still_returns_advice():
    g = {"failed_checks": ["verification_checklist_not_ready"],
         "verification": {"checklist": _HostileChecklist()}}
    assert _checklist_advice_1203i6(g) == _CHECKLIST_GENERIC_1203I6
    # and the suggestion list must still be produced, not blow up the whole gate report
    assert isinstance(delivery_gate_suggestions(g), list)


def test_nothing_is_said_when_the_check_is_not_failing():
    assert _advice(_gate(_all(npm_install="failure"), failed=("business_chain_failing",))) == []


# --------------------------------------------------------------- the status vocabulary


def test_every_measured_status_is_handled():
    """`success` / `failure` / `pending` are the only three in 47312 entries; each must land
    in the right half, and an UNKNOWN one must be treated as unrun rather than ignored."""
    assert _checklist_advice_1203i6(_gate(_all())) == _CHECKLIST_GENERIC_1203I6
    assert "FAILED" in _checklist_advice_1203i6(_gate(_all(npm_install="failure")))
    assert "never been recorded" in _checklist_advice_1203i6(_gate(_all(npm_install="pending")))
    out = _checklist_advice_1203i6(_gate(_all(npm_install="who-knows")))
    assert "npm_install" in out, out
