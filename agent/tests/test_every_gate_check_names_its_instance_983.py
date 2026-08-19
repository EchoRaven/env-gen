"""#983: keep the blocker prose beside the token, so no gate check reaches a lane bare.

Four times this session a lane was handed a failure with the cause stripped off — #973 (a
postgres ERROR without its STATEMENT), #978 (a remediation whose detail was a container id),
#981 and #982 (gate checks that named no instance). Each was fixed where it was noticed.

Measured against the runs instead of guessing, the shape is systemic: of the 16 delivery-gate
blockers ACTUALLY observed across r157-r159, 11 reach the lane as a bare check name — and the
most frequent of all, `deliverability_ui_page_unwired` (37x), is one of them.

They share one origin:

    for blocker in (deliverability_report.blockers or []):
        deliverability_failed_checks.append(_deliverability_check_token(blocker))

`_deliverability_check_token` classifies human prose ("… declared but unusable: player_page")
into a stable token, and the prose — the only part naming the page — was discarded on that
line. Carrying it through fixes the whole class at the source rather than one branch at a
time, which is what #981 and #982 each had to do.
"""

import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd


def test_the_gate_keeps_the_prose():
    src = inspect.getsource(dg)
    assert "deliverability_blocker_prose.setdefault(" in src
    i_tok = src.index("_tok = _deliverability_check_token(blocker)")
    i_keep = src.index("deliverability_blocker_prose.setdefault(", i_tok)
    assert i_keep - i_tok < 300, "the prose must be kept where the token is derived"


def test_the_gate_returns_it():
    assert '"blocker_prose": deliverability_blocker_prose,' in inspect.getsource(dg)


def test_the_dispatcher_replays_it():
    src = inspect.getsource(rd)
    assert "_gate_blocker_prose_983" in src


def test_a_bespoke_branch_still_wins():
    """The generic replay must be set BEFORE the specific branches, so a check with a
    tailored body keeps it — #981/#982 are better than raw prose for their checks."""
    src = inspect.getsource(rd)
    i_generic = src.index("_gate_blocker_prose_983")
    i_specific = src.index('if name == "validation_ui_evidence_failed":')
    assert i_generic < i_specific


def test_the_token_still_classifies_the_prose():
    """The classification itself must not drift — the tokens are asserted on elsewhere."""
    assert dg._deliverability_check_token(
        "2 ui page(s) declared but unusable: player_page") == "deliverability_ui_page_unwired"


def test_the_replay_is_bounded():
    """A gate with many blockers must not paste an essay into an urgent message."""
    src = inspect.getsource(rd)
    assert "_prose[:8]" in src


def test_the_control_drops_the_prose():
    """Planted control: the PRE-FIX loop kept only the token, so the page name was gone."""
    def _pre_fix(blockers):
        return [dg._deliverability_check_token(b) for b in blockers]

    out = _pre_fix(["2 ui page(s) declared but unusable: player_page"])
    assert out == ["deliverability_ui_page_unwired"]
    assert not any("player_page" in x for x in out), (
        "the control was supposed to lose the page name; if it does not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
