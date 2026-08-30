"""#1167: the same loop's other gate knew about status; this one did not.

`_unimplemented_route` is called one line above `_shape_violation` with
`ep.get("status")` and returns None for anything not claiming `implemented` --
its own message even offers "implement the route or DEPRECATE the registration"
as the escape. `_shape_violation` was never given the status, so a deprecated
registration still had its response shape judged.

netflix-local-r6: an agent parked `GET /__noop__` at status=deprecated and the
verifier reported "run_validation/api_smoke failed on GET /__noop__ contract
shape" -- a blocker on an endpoint the contract had already retired. r6 died
holding one gate check. Both DELIVERED artifacts still carry that same
registration, so it is not a one-run accident.
"""
import inspect
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import validation_runner as vr
from env_generator.llm_generator.multi_agent.runtime.validation_runner import (
    _shape_violation as shape)

SINGLE_PATH = "/api/users/me"
LIST_BODY = '{"items": [{"id": 1}]}'


def test_an_implemented_endpoint_is_still_judged():
    """The defect this gate exists for -- instagram's GET /api/users/me answering
    {"items": [all users]} -- must still be caught."""
    assert shape("GET", SINGLE_PATH, 200, LIST_BODY)


def test_a_deprecated_registration_is_exempt():
    assert shape("GET", "/__noop__", 200, LIST_BODY, ep_status="deprecated") is None


def test_a_not_yet_implemented_registration_is_exempt():
    """Matching _unimplemented_route's rule, which the framework already settled."""
    for st in ("defined", "implementing", "revising"):
        assert shape("GET", SINGLE_PATH, 200, LIST_BODY, ep_status=st) is None, st


def test_a_missing_status_stays_judged():
    """Conservative default: an absent status must not become a free pass, or the
    exemption would silently widen to every record that omits the field."""
    assert shape("GET", SINGLE_PATH, 200, LIST_BODY, ep_status=None)
    assert shape("GET", SINGLE_PATH, 200, LIST_BODY, ep_status="")


def test_the_caller_passes_the_status():
    src = Path(vr.__file__).read_text(encoding="utf-8")
    i = src.index("_sv = _shape_violation(")
    assert "ep_status=ep.get(\"status\")" in src[i:src.index("\n\n", i)]


def test_both_gates_on_that_loop_now_agree():
    """They read the same field with the same rule; a test pins that they do not
    drift apart again."""
    assert "ep_status" in inspect.signature(shape).parameters
    assert "ep_status" in inspect.signature(vr._unimplemented_route).parameters


def test_the_delivered_artifacts_carry_the_registration_this_exempts():
    root = Path(vr.__file__).parents[5] / "generated"
    seen = 0
    for run in ("netflix-local-r13", "netflix-local-r14"):
        p = root / run / "shared" / "hubs" / "registryhub_endpoints.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for v in d.values():
            if isinstance(v, dict) and str(v.get("status")) == "deprecated":
                seen += 1
                assert shape(str(v.get("method") or "GET"), str(v.get("path") or "/x"),
                             200, LIST_BODY, ep_status=v.get("status")) is None
    if not seen:
        pytest.skip("no deprecated registration in the artifacts on this box")
