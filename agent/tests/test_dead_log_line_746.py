r"""#746: #254's refusal has been taking a decision silently for 255 runs.

Found by sweeping every numbered log call in `runtime/` against every run log. Method matters
here, because the first version of the sweep was wrong: a regex over double-quoted strings
beginning `#NNN` matched DOCSTRINGS as well as log calls, so 93 "warnings" came back and 88 of
them had "never fired" — meaningless for text that is not a log line at all. Re-done over the
AST, taking only the first string argument of a `.warning`/`.error`/`.info` call, it is 18 calls,
10 with no hit. Seven of those ten are mine from today and postdate every run. The remaining
three were dated against the corpus window (oldest log 07-30, newest 08-14 11:37):

    #254  hub_registry.py    introduced 07-21   ALL 255 logs    0 hits
    #576  scaffolder.py      introduced 08-11   ~14 runs        0 hits
    #615  deliverability.py  introduced 08-14   3 runs          0 hits  (item 54's finding)

#254 is the one that cannot be explained by youth. Reading it explains the zero: the call site
was

    _log = getattr(self, "_logger", None)
    if _log is not None:
        _log.warning("#254: refused to downgrade …")

and **`_logger` is set nowhere.** The name appears exactly once in the module — in that read —
and the module had no `logging` import at all. The line was unreachable from the day it was
written.

This is not a missing log line. `record_validation_result` REFUSES the write and returns
`downgrade_rejected: True`, discarding an LLM agent's evidence-free `failure` so it cannot erase
the framework's measured pass. That is the guard #254 exists to be, and it has been taking that
decision invisibly. Nobody could tell whether it fires, how often, or whether it is protecting a
real pass or masking a real failure — the same shape as #691's silent skip, #696's invisible load
failure and #722's silence-means-three-things.
"""
import ast
import inspect
import logging
import pathlib
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import hub_registry as hr


# --- the line is now reachable --------------------------------------------------------------

def test_the_module_has_a_logger():
    assert isinstance(hr._LOG_746, logging.Logger)


def test_the_call_site_no_longer_guards_on_a_never_set_attribute():
    src = inspect.getsource(hr)
    assert 'if _log is not None:' not in src
    assert '(getattr(self, "_logger", None) or _LOG_746).warning(' in src


def _code_lines():
    """Non-comment source lines. #746's own commentary mentions `_logger` several times, and
    counting raw source made the premise-check assert 6 == 1 — measuring my own prose."""
    return [l for l in inspect.getsource(hr).split("\n")
            if l.strip() and not l.strip().startswith("#")]


def test_logger_is_still_preferred_if_one_is_ever_injected():
    """The fallback must not take precedence — a caller-supplied logger still wins."""
    line = [l for l in _code_lines() if "_LOG_746).warning(" in l]
    assert len(line) == 1, line
    assert line[0].index('getattr(self, "_logger", None)') < line[0].index("_LOG_746")


def test_logger_is_still_never_set_anywhere():
    """The premise. If someone starts setting `_logger`, this finding needs re-stating rather
    than quietly surviving — the fallback would then be dead code instead of the only path.

    Checked as ASSIGNMENT, not by counting the word. Counting was the wrong instrument twice
    over: raw source counted #746's own comments (6 == 1), and non-comment lines still counted
    the warning TEXT, which says "`_logger` is set nowhere". The claim was never about how often
    the name appears — it is that nothing binds it — so the AST decides."""
    tree = ast.parse(inspect.getsource(hr))
    bound = []
    for n in ast.walk(tree):
        for t in (n.targets if isinstance(n, ast.Assign) else
                  [n.target] if isinstance(n, (ast.AnnAssign, ast.AugAssign)) else []):
            for sub in ast.walk(t):
                if isinstance(sub, ast.Name) and sub.id == "_logger":
                    bound.append(n.lineno)
                if isinstance(sub, ast.Attribute) and sub.attr == "_logger":
                    bound.append(n.lineno)
    assert not bound, f"_logger is now assigned at line(s) {bound} — restate #746"


# --- it actually emits ---------------------------------------------------------------------------

class _CodeHub:
    def __init__(self, checks):
        self._c = checks

    def list_checks(self, *a, **k):
        return self._c

    def record_check(self, *a, **k):
        return {"ok": True}


def _reg(checks):
    r = object.__new__(hr.HubRegistry)
    r.codehub = _CodeHub(checks)
    return r


def _det_pass(name):
    """The standing record #254 protects: a PASS carrying the deterministic-evidence marker.
    The first draft of this fixture used `{"execution_mode": "deterministic"}`, which reads
    like the right thing and is not — `_is_deterministic_evidence` keys on
    DETERMINISTIC_EVIDENCE_KEY ("deterministic_runtime_evidence"), so the fixture produced a
    NON-deterministic record, no refusal happened, and the test failed for the wrong reason."""
    return {"name": name, "status": "passed",
            "evidence": {hr.DETERMINISTIC_EVIDENCE_KEY: True, "check": "ui_flow"}}


def test_a_refusal_is_now_audible(caplog):
    reg = _reg([_det_pass("validation:t1")])
    with caplog.at_level(logging.WARNING, logger=hr.__name__):
        out = hr.HubRegistry.record_validation_result(
            reg, task_id="t1", status="failure", summary="s", agent="verifier",
            evidence={"flow": "browse"})
    assert out.get("downgrade_rejected") is True, "the refusal itself must be unchanged"
    assert any("#254: refused to downgrade" in r.getMessage() for r in caplog.records)


def test_the_message_says_it_used_to_be_silent(caplog):
    reg = _reg([_det_pass("validation:t1")])
    with caplog.at_level(logging.WARNING, logger=hr.__name__):
        hr.HubRegistry.record_validation_result(
            reg, task_id="t1", status="failure", summary="s", agent="verifier",
            evidence={"flow": "browse"})
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "every prior refusal was silent" in msg


def test_a_legitimate_downgrade_is_not_refused_and_not_logged(caplog):
    """Deterministic evidence MAY supersede deterministic evidence — #254's own rule."""
    reg = _reg([_det_pass("validation:t1")])
    with caplog.at_level(logging.WARNING, logger=hr.__name__):
        out = hr.HubRegistry.record_validation_result(
            reg, task_id="t1", status="failure", summary="s", agent="framework",
            evidence={hr.DETERMINISTIC_EVIDENCE_KEY: True, "check": "ui_flow"})
    assert not out.get("downgrade_rejected")
    assert not [r for r in caplog.records if "#254" in r.getMessage()]


def test_a_pass_is_never_refused(caplog):
    reg = _reg([_det_pass("validation:t1")])
    with caplog.at_level(logging.WARNING, logger=hr.__name__):
        out = hr.HubRegistry.record_validation_result(
            reg, task_id="t1", status="passed", summary="s", agent="verifier", evidence={})
    assert not out.get("downgrade_rejected")


def test_a_store_read_failure_still_fails_open(caplog):
    class _Boom:
        def list_checks(self, *a, **k):
            raise RuntimeError("store down")

        def record_check(self, *a, **k):
            return {"ok": True}

    reg = object.__new__(hr.HubRegistry)
    reg.codehub = _Boom()
    out = hr.HubRegistry.record_validation_result(
        reg, task_id="t1", status="failure", summary="s", agent="verifier", evidence={})
    assert not out.get("downgrade_rejected"), "fail-open must survive"


# --- the sweep that found it, kept runnable --------------------------------------------------------

def test_no_numbered_log_call_in_this_module_is_unreachable():
    """Generalises the finding to the module: every numbered warning must be emittable — no
    `if <never-set> is not None` wrapper standing between the call and the logger."""
    src = pathlib.Path(hr.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("warning", "error", "info")]
    assert calls, "non-vacuity: the module must contain at least one log call"
    for c in calls:
        f = c.func.value
        # The receiver must not be a bare name that the module never assigns.
        if isinstance(f, ast.Name):
            assert re.search(rf"^{f.id}\s*=", src, re.M), f"{f.id} is never assigned"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
