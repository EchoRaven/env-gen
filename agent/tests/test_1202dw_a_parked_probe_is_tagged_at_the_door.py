r"""#1202dw: tag a parked `__`-probe as infra where it is REGISTERED, not at each gate.

An agent parks probe registrations in RegistryHub. `validation_runner` recorded it in
netflix-local-r6 — "an agent parked `GET /__noop__` at status=deprecated" — and noted the
part that makes it structural: "Both delivered artifacts still carry that registration, so
this is not a one-run accident."

netflix-r44 carried two, and they were the ONLY two of its 37 registered endpoints that were
not `implemented`:

    GET  /__noop__                          status=deprecated  provider=orchestrator-monitor
    POST /__noop_orchestrator_state_check__ status=defined     provider=orchestrator

They can never become implemented, because nobody should implement them. So every gate that
looks for "registered but not implemented" flags them forever, and r44 shows what that cost:

  * the response_key gate blocked delivery on one of them (fixed at that gate by #1202ds)
  * the seed audit flagged the matching probe TABLE (fixed at that gate by #1202du)
  * the orchestrator agent authored a P0 telling backend to "add a real FastAPI handler ...
    with real DB-backed state/check logic" for `GET /__noop_orchestrator_state_check__`
  * the backend lane then grepped `app/backend` for it, repeatedly, across runs

Three gates, three patches, one cause. The cause is that the registration carries no `kind`,
so the kind-based exemption every gate ALREADY has cannot fire: `FIXED_ENDPOINT_KINDS` is
{auth, control, control_plane, health, infra, oauth, spine} and r44's probe had `metadata: {}`.

Tagging it `infra` at the door makes the exemption those gates already implement start
working, and any gate added later inherits it for free. #1202ds's path check stays as defence
in depth; this removes the reason it was needed.

The convention is the DOUBLE underscore, which app endpoints do not use — a lane cannot
exempt its own `/api/...` surface by adopting it.
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.kickoff.contract import (
    FIXED_ENDPOINT_KINDS,
)
from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


def _hub(d):
    return RegistryHub(Path(d))


def _meta(hub, key):
    return (hub.get_endpoints().get(key) or {}).get("metadata") or {}


@pytest.mark.parametrize("method,path", [
    ("GET", "/__noop__"),
    ("POST", "/__noop_orchestrator_state_check__"),
    ("GET", "/__noop_orchestrator_probe__"),
])
def test_a_parked_probe_is_tagged_infra(tmp_path, method, path):
    hub = _hub(tmp_path)
    hub.register_endpoint(method, path, status="defined")
    assert _meta(hub, f"{method} {path}").get("kind") == "infra"


def test_infra_is_a_kind_the_gates_already_exempt():
    """The whole point: reuse the exemption, do not invent a new one."""
    assert "infra" in FIXED_ENDPOINT_KINDS


def test_a_real_endpoint_is_untouched(tmp_path):
    hub = _hub(tmp_path)
    hub.register_endpoint("GET", "/api/titles", status="implemented")
    assert "kind" not in _meta(hub, "GET /api/titles")


def test_a_lane_cannot_exempt_its_own_surface_with_the_convention(tmp_path):
    """`/api/__x` is app surface; only a leading `__` segment is the framework convention."""
    hub = _hub(tmp_path)
    hub.register_endpoint("GET", "/api/__titles", status="defined")
    assert _meta(hub, "GET /api/__titles").get("kind") != "infra"


def test_an_explicit_kind_is_not_overwritten(tmp_path):
    """A caller that states its own kind keeps it."""
    hub = _hub(tmp_path)
    hub.register_endpoint("GET", "/__noop__", status="defined", kind="control")
    assert _meta(hub, "GET /__noop__").get("kind") == "control"


def test_the_response_key_gate_now_skips_it_by_kind(tmp_path):
    """#1202ds patched this at the gate; with the kind set, the gate's OWN exemption fires."""
    from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
        noncanonical_business_response_keys,
    )
    hub = _hub(tmp_path)
    hub.register_endpoint("GET", "/__noop_orchestrator_state_check__",
                          schema={"response_key": "state"}, status="defined")

    class _H:
        registryhub = hub

    assert noncanonical_business_response_keys(_H()) == []
