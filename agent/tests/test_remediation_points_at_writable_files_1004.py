"""#1004: a remediation must not order a lane to edit a file it cannot write.

r162 produced 17 tasks against a single `POST /api/continue-watching → 405` and never fixed
it. The framework's own instruction was:

    "registered+implemented endpoints answer 404/405 … Wire them in app/backend/main.py
     (include_router / the @app.<method> path) so each declared path responds."

`main.py` is in `_BACKEND_FRAMEWORK_OWNED`, so `is_framework_owned()` makes the write guard
DENY every lane edit to it. **The remediation ordered the backend lane to do the one thing it
is structurally forbidden from doing** — and a lane cannot wire a route in a file it cannot
open for writing, no matter how capable it is.

`custom_routes.py` is deliberately NOT framework-owned. It is the lane's file, main.py already
discovers and includes the router it defines, and that is where a missing route belongs.

Swept the other 13 remediation entries for the same mistake: none. This was the only one.
"""

import re
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.auto_commit import (
    _BACKEND_FRAMEWORK_OWNED, _FRONTEND_FRAMEWORK_OWNED)

_SRC = pathlib.Path(
    "env_generator/llm_generator/multi_agent/runtime/remediation_dispatcher.py"
).read_text(encoding="utf-8")


def _spec_bodies():
    """Every remediation spec's guidance text, keyed by check name.

    Bounded at the NEXT spec, not by a fixed width. A 1400-char window bled from
    `frontend_reachable` into `business_endpoints_reachable` and reported a second offender
    that does not exist — the fixed-width-source-window mistake this repo's own meta-test
    forbids, and the third time this session it produced a false finding.
    """
    starts = [(m.group(1), m.start()) for m in
              re.finditer(r'"([a-z_]+)": \(\s*"(\w+)",\s*"([^"]{5,90})",', _SRC)]
    out = {}
    for i, (name, pos) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(_SRC)
        out[name] = _SRC[pos:end]
    return out


def test_the_sweep_has_a_denominator():
    """A guard that parses nothing reports everything as clean — items 366/381/391/398."""
    assert len(_spec_bodies()) >= 10


def test_no_remediation_orders_an_edit_to_a_framework_owned_file():
    """The class, not just the instance. An explanatory mention ('main.py is framework-owned,
    your writes are denied') is fine; an instruction to edit one is not."""
    owned = ({f"app/backend/{n}" for n in _BACKEND_FRAMEWORK_OWNED}
             | {f"app/frontend/src/{n}" for n in _FRONTEND_FRAMEWORK_OWNED})
    offenders = []
    for check, body in _spec_bodies().items():
        for path in owned:
            if path not in body:
                continue
            # allowed only when the text says the lane must NOT write it
            if not re.search(r"framework-owned|writes to it are denied|do not edit", body, re.I):
                offenders.append((check, path))
    assert offenders == [], f"remediation names an unwritable file as the fix site: {offenders}"


def test_the_endpoint_remediation_names_the_lane_owned_file():
    body = _spec_bodies()["business_endpoints_reachable"]
    assert "custom_routes.py" in body


def test_it_says_why_main_py_is_not_the_answer():
    """Naming the right file is half of it; a lane that has been told 'main.py' for months
    needs to know why the instruction changed."""
    body = _spec_bodies()["business_endpoints_reachable"]
    assert "framework-owned" in body and "denied" in body


def test_custom_routes_really_is_writable():
    """The premise. If custom_routes.py ever becomes framework-owned this fix inverts."""
    assert "custom_routes.py" not in _BACKEND_FRAMEWORK_OWNED


def test_main_py_really_is_not():
    assert "main.py" in _BACKEND_FRAMEWORK_OWNED


def test_the_control_names_the_denied_file():
    """Planted control: the PRE-FIX text, which is what r162's lane was given."""
    pre_fix = ("registered+implemented endpoints answer 404/405 — the routes are not "
               "actually mounted. Wire them in app/backend/main.py (include_router / "
               "the @app.<method> path) so each declared path responds.")
    assert "app/backend/main.py" in pre_fix
    assert "custom_routes" not in pre_fix, (
        "the control was supposed to point only at the unwritable file; if it does not, "
        "this fix is unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
