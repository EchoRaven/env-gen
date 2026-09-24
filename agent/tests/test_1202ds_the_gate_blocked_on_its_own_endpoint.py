r"""#1202ds: the response_key gate blocked delivery on an endpoint the FRAMEWORK registered.

netflix-r44 ended without delivering. One of its two final blockers was
`business_response_key_noncanonical`. Run the check against that run's own
`registryhub_endpoints.json` (37 entries) and exactly one endpoint is flagged:

    GET /__noop_orchestrator_state_check__   response_key = 'state'
    {"provider": "orchestrator", "status": "deprecated", "metadata": {}, ...}

The orchestrator's own deprecated state probe. No lane wrote it, no lane can fix it.

The backend agent was RIGHT every time it said otherwise. Its reports are in the log:

    "business_response_key_noncanonical no longer reproduces in inspected RegistryHub
     entries (all business endpoints use item/items)"
    "Backend contract audit ... All business endpoints expose canonical envelopes only"

It audited business endpoints — correctly all canonical — while the culprit was a framework
endpoint it had no reason to inspect, because THE GATE NEVER NAMED IT. The check appends
`business_response_key_noncanonical` to `failed_checks` and logs nothing, even though the
comment twenty lines above it in the same file diagnoses precisely this:

    Same class as #973/#978/#981/#983 — the report names the failure and not the instance
    — on the one check that now decides delivery.

...and applies the per-instance logging to `incomplete_required_tasks` and not to this one.

Two exemptions already exist and both miss it: `metadata.kind` is EMPTY (so the kind test
does not fire) and the path is not `/auth/`, `/oauth` or `/.well-known` (so #251's path test
does not fire). #251 wrote the rule this re-learns:

    exemption must not depend on a metadata field the LANE has to remember ... NO lane could
    fix it (the handlers are ours) ... an unwinnable hard gate is the opt-5 lesson we keep
    re-learning.
"""
import json
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    noncanonical_business_response_keys,
)


def _hubs(endpoints):
    class RH:
        def get_endpoints(self):
            return endpoints

    class Hubs:
        registryhub = RH()

    return Hubs()


# r44's entry, verbatim from its registryhub_endpoints.json
NOOP = {
    "GET /__noop_orchestrator_state_check__": {
        "id": "GET /__noop_orchestrator_state_check__",
        "method": "GET", "path": "/__noop_orchestrator_state_check__",
        "status": "deprecated", "provider": "orchestrator",
        "schema": {"response_key": "state", "auth_required": False},
        "metadata": {}, "_updated_by": "orchestrator",
    }
}


def test_the_framework_probe_that_blocked_r44_is_exempt():
    assert noncanonical_business_response_keys(_hubs(NOOP)) == []


def test_exemption_does_not_rely_on_metadata_the_lane_must_set():
    """#251's rule: `metadata` is empty here, so a kind-based test can never save it."""
    assert NOOP["GET /__noop_orchestrator_state_check__"]["metadata"] == {}
    assert noncanonical_business_response_keys(_hubs(NOOP)) == []


def test_a_real_lane_endpoint_is_still_flagged():
    """The blank-page defect this gate exists for must still be caught."""
    bad = noncanonical_business_response_keys(_hubs({
        "GET /api/games": {
            "method": "GET", "path": "/api/games", "provider": "backend",
            "schema": {"response_key": "games"}, "metadata": {},
        }
    }))
    assert len(bad) == 1, bad
    assert bad[0]["endpoint"] == "GET /api/games"
    assert bad[0]["response_key"] == "games"


def test_canonical_keys_pass():
    for key in ("items", "item"):
        assert noncanonical_business_response_keys(_hubs({
            "GET /api/titles": {
                "method": "GET", "path": "/api/titles", "provider": "backend",
                "schema": {"response_key": key}, "metadata": {},
            }
        })) == []


def test_a_lane_cannot_exempt_itself_by_claiming_a_framework_path():
    """The exemption is a framework naming convention (`/__`), not an opt-out for /api/."""
    bad = noncanonical_business_response_keys(_hubs({
        "GET /api/__games": {
            "method": "GET", "path": "/api/__games", "provider": "backend",
            "schema": {"response_key": "games"}, "metadata": {},
        }
    }))
    assert len(bad) == 1, bad


def test_the_gate_names_the_instance_when_it_fails():
    """The whole reason r44's backend could not fix this: the failure had no instance.

    Landmark-anchored on the check, not a byte window.
    """
    import inspect
    from multi_agent.runtime import delivery_gate as dg

    src = inspect.getsource(dg)
    at = src.index('failed_checks.append("business_response_key_noncanonical")')
    before = src[src.index("noncanonical_response_keys = ", 0):at]
    assert "logger" in before and "1202ds" in before, (
        "the check still appends a failure name with no instance — the shape #973/#978/"
        "#981/#983/#1009 all fixed elsewhere in this same file")
