"""#982: name the pages whose UI evidence records failure — the other half of #981.

r159 died on a pair of gate checks:

    ['deliverability_ui_flow_failed', 'validation_ui_evidence_failed']

#981 gave the first one its instances. The second had no branch in the dispatcher at all, so
the verifier received generic text. Both name lists were already computed:
`_ui_evidence_breadth_739` returns `pages_failed` beside the count the gate trips on, and #757
added those names with the comment "a gate that cannot say WHICH page failed cannot be acted
on". The gate could say it. Nothing passed it on.
"""

import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd


class _Orch:
    _last_validation_results = object()


def _with_breadth(monkeypatch, out):
    monkeypatch.setitem(rd.__dict__, "_ui_evidence_breadth_739", lambda _r: out)


def test_the_failing_pages_are_named(monkeypatch):
    _with_breadth(monkeypatch, {"pages_failed": ["player_page", "browse_home"]})
    assert rd._ui_evidence_failed_pages(_Orch()) == ["player_page", "browse_home"]


def test_the_unknown_placeholder_is_dropped(monkeypatch):
    """#757: a record with no page/route/name reads as '?', which names nothing."""
    _with_breadth(monkeypatch, {"pages_failed": ["?", "player_page"]})
    assert rd._ui_evidence_failed_pages(_Orch()) == ["player_page"]


def test_the_body_names_them():
    body = rd._ui_evidence_failed_extra(["player_page"])
    assert "player_page" in body


def test_the_body_says_re_recording_is_not_the_fix():
    assert "re-recording it is not" in rd._ui_evidence_failed_extra(["player_page"])


def test_no_pages_yields_no_extra():
    assert rd._ui_evidence_failed_extra([]) == ""


def test_a_broken_report_falls_back_quietly(monkeypatch):
    def _boom(_r):
        raise RuntimeError("no results")

    _with_breadth(monkeypatch, None)
    monkeypatch.setitem(rd.__dict__, "_ui_evidence_breadth_739", _boom)
    assert rd._ui_evidence_failed_pages(_Orch()) == []


def test_the_dispatcher_uses_it():
    """The named-pages body is built INSIDE this branch — anchored on the next branch
    landmark, not on a byte count. The original `- i < 500` was a fixed window: #1176
    added three comment lines above the assignment and the window, not the wiring,
    was what went red."""
    src = inspect.getsource(rd)
    i = src.index('if name == "validation_ui_evidence_failed":')
    branch = src[i:src.index('if name == "deliverability_ui_flow_failed":', i)]
    # Not "_extra = _ui_evidence_failed_extra(": #1177 wrapped the assignment in
    # parentheses to append its own text, and the literal prefix stopped matching
    # while the wiring was correct. Assert the CALL, not its punctuation.
    assert "_ui_evidence_failed_extra(" in branch


def test_both_halves_of_the_pair_are_covered():
    """r159's terminal blocker set was these two; neither may regress to generic text."""
    src = inspect.getsource(rd)
    assert 'if name == "deliverability_ui_flow_failed":' in src
    assert 'if name == "validation_ui_evidence_failed":' in src


def test_the_control_has_no_branch():
    """Planted control: the PRE-FIX dispatcher matched neither failed check."""
    def _pre_fix(name):
        return "…names…" if name == "deliverability_ui_flow_missing" else ""

    assert _pre_fix("validation_ui_evidence_failed") == ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
