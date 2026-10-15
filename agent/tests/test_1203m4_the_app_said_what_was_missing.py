r"""#1203m4: the app named the field it wanted, and the probe scored that against it.

`#1203e0` passes a 400/422 when the PLAN knew its request was incomplete, computed from the
registered request schema. Its own neighbour names the hole: "the framework registers its own
request schema as `{}` or `null` while its handlers require fields, so #1203e0 cannot even see
them as incomplete" -- and a lane-authored endpoint that declares no required fields behaves
the same way, so `{}` goes out and the correct rejection comes back as a failure.

MEASURED: 44 such records in 3 modern runs, all of which POSTDATE #1203e0 (landed 10-03 22:30;
r152 10-04, r173 10-10, r186 10-13) -- `POST /api/auth/signup` 35 and `GET /oauth/authorize` 9.
The cost is not the unreachable "latest run has N failed endpoint probe(s)" blocker but the
consequence `deliverability` records beside it: a run with `fail_count > 0` cannot be
`last_successful_run_since`, so the gate reads staler evidence. Counted per validation run,
**9 runs (7 modern) have exactly one failing probe and it is this one** -- r173 six times
running, over batteries of 25 to 44 probes.

Discriminating, not vacuous: of the 191 failing 400/422 probes across every era, 179 match and
12 do not -- r124/r136's `int_parsing` on an unsubstituted `{id}` in the PATH, a different
fault that keeps failing here.
"""
from __future__ import annotations

import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime.hubs.runhub.probes import (
    classify_probe_result)

# verbatim body excerpts from the runs named beside each one
BODY_SIGNUP = '{"detail":"email and password are required"}'                      # r186/r173
BODY_QUERY = ('{"detail":[{"type":"missing","loc":["query","response_type"],'
              '"msg":"Field required","input":null}]}')                           # r152
BODY_PATH_INT = ('{"detail":[{"type":"int_parsing","loc":["path","id"],'
                 '"msg":"Input should be a valid integer, unable to parse s"}]}')  # r124/r136


@pytest.mark.parametrize("status", [400, 422])
@pytest.mark.parametrize("body", [BODY_SIGNUP, BODY_QUERY])
def test_a_rejection_that_names_what_was_missing_is_not_the_handlers_fault(status, body):
    out = classify_probe_result(status_code=status, body_excerpt=body,
                                auth_required=False, request_had_data=False)
    assert out.verdict == "pass"
    assert "#1203m4" in (out.note or "")


def test_the_control_keeps_failing():
    """r124/r136: the probe put an unsubstituted `{id}` in the PATH. Different owner."""
    out = classify_probe_result(status_code=422, body_excerpt=BODY_PATH_INT,
                                auth_required=False, request_had_data=False)
    assert out.verdict == "fail"


def test_a_probe_that_sent_data_is_told_the_truth():
    """The clause self-retires: with a real body, a 422 is about the handler again."""
    out = classify_probe_result(status_code=422, body_excerpt=BODY_SIGNUP,
                                auth_required=False, request_had_data=True)
    assert out.verdict == "fail"


@pytest.mark.parametrize("status,why", [(404, "route not wired"), (500, "server error")])
def test_the_answers_that_are_about_the_handler_still_fail(status, why):
    out = classify_probe_result(status_code=status, body_excerpt=BODY_SIGNUP,
                                auth_required=False, request_had_data=False)
    assert out.verdict == "fail" and why in (out.note or "")


def test_1203e0_is_untouched():
    """A plan that KNEW it was incomplete still passes, with its own note."""
    out = classify_probe_result(status_code=400, body_excerpt="nothing useful",
                                auth_required=False, request_complete=False,
                                request_had_data=False)
    assert out.verdict == "pass" and "#1203m4" not in (out.note or "")


def test_the_default_is_the_conservative_one():
    """Any other caller that does not pass the flag keeps the old verdict."""
    sig = inspect.signature(classify_probe_result)
    assert sig.parameters["request_had_data"].default is True
    out = classify_probe_result(status_code=422, body_excerpt=BODY_SIGNUP,
                                auth_required=False)
    assert out.verdict == "fail"


def test_the_prober_tells_the_classifier_what_it_sent():
    """The CALLER, not the helper: service.py must derive the flag from its own plan.

    Asserted on the AST because reaching this call needs a live stack: the keyword must be
    present at the `classify_probe_result` call and its value must read `plan`.
    """
    from env_generator.llm_generator.multi_agent.runtime.hubs.runhub import service

    tree = ast.parse(inspect.getsource(service))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", getattr(n.func, "attr", "")) == "classify_probe_result"]
    assert calls, "the classifier is no longer called from the prober"
    for call in calls:
        kw = {k.arg: k for k in call.keywords if k.arg}
        assert "request_had_data" in kw, "the prober does not say whether it sent anything"
        src = ast.unparse(kw["request_had_data"].value)
        assert "plan" in src, "the flag is not derived from the plan that sent the request"
        assert "body" in src, "the flag ignores the request body"
