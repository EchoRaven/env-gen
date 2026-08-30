"""#981: name the failing flows, the way the missing ones have been named since #284.

r159 converged further than any run in the arc — its delivery gate fell from r158's eight
failed checks to two — and then spent hours on `deliverability_ui_flow_failed`. What the
verifier received:

    GATE-CHECK remediation dispatched to verifier (task …): deliverability_ui_flow_failed

The check name. Nothing else. Its sibling `deliverability_ui_flow_missing` has named every
offending flow since FIX #284, and the dispatcher's condition is literally
`if name == "deliverability_ui_flow_missing"`.

The data was never missing: `compute_flow_coverage` returns `failed` alongside `missing`, and
the walk had already reported the specifics (`blank=['player_page']`, a broken
`POST /api/continue-watching`). One branch read its half of the report; the other did not.

Third instance of this shape in the session — #973 (a postgres ERROR without its STATEMENT),
#978 (a remediation whose detail was a container id), and now a gate check that cannot be
located by the lane asked to clear it.
"""

import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd


class _Report:
    def __init__(self, missing=(), failed=()):
        self.missing = list(missing)
        self.failed = list(failed)


class _Orch:
    class hubs:
        registryhub = object()


def _with_report(monkeypatch, report):
    monkeypatch.setitem(rd.__dict__, "compute_flow_coverage", lambda _hub: report)


def test_the_failing_flows_are_named(monkeypatch):
    _with_report(monkeypatch, _Report(failed=["player_page", "continue_watching"]))
    got = rd._ui_flow_failed_names(_Orch())
    assert got == ["player_page", "continue_watching"]


def test_the_body_names_them(monkeypatch):
    body = rd._ui_flow_failed_extra(["player_page", "continue_watching"])
    assert "player_page" in body and "continue_watching" in body


def test_the_body_says_re_recording_is_not_the_fix():
    """A recorded-but-failing flow already HAS a record; a verifier that re-records it makes
    no progress, which is how r68's contradiction started."""
    body = rd._ui_flow_failed_extra(["player_page"])
    assert "re-recording it changes nothing" in body


def test_nothing_failing_yields_no_extra():
    assert rd._ui_flow_failed_extra([]) == ""


def test_a_hub_hiccup_falls_back_quietly(monkeypatch):
    def _boom(_hub):
        raise RuntimeError("hub down")

    _with_report(monkeypatch, None)
    monkeypatch.setitem(rd.__dict__, "compute_flow_coverage", _boom)
    assert rd._ui_flow_failed_names(_Orch()) == []


def test_duplicates_collapse(monkeypatch):
    _with_report(monkeypatch, _Report(failed=["a", "a", "b"]))
    assert rd._ui_flow_failed_names(_Orch()) == ["a", "b"]


def test_the_dispatcher_uses_it_for_the_failed_branch():
    src = inspect.getsource(rd)
    assert 'if name == "deliverability_ui_flow_failed":' in src
    # #943, again: this was `i_use - i_failed < 500`, a fixed byte window. #1176 added
    # three comment lines inside the branch and the WINDOW went red while the wiring
    # it guards was untouched. Anchor on the next branch instead of counting bytes.
    i_failed = src.index('if name == "deliverability_ui_flow_failed":')
    branch = src[i_failed:src.index('if name == "deliverability_ui_flow_missing":', i_failed)]
    assert "_ui_flow_failed_extra(" in branch, "the failed branch must set its own extra"


def test_the_missing_branch_is_untouched():
    """#284's behaviour must survive — it is the pattern this copies, not a casualty."""
    src = inspect.getsource(rd)
    assert 'if name == "deliverability_ui_flow_missing":' in src
    assert "_extra = _ui_flow_missing_extra(" in src


def test_the_control_leaves_the_failed_branch_bare():
    """Planted control: the PRE-FIX dispatcher matched only the missing name, so a failed
    check produced no extra at all."""
    def _pre_fix(name):
        extra = ""
        if name == "deliverability_ui_flow_missing":
            extra = "…names the flows…"
        return extra

    assert _pre_fix("deliverability_ui_flow_failed") == "", (
        "the control was supposed to produce nothing for the failed check; if it does not, "
        "this fix is unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
