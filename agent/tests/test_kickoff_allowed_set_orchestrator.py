"""Round-8d Fix #4 regression: registryhub.register_endpoint +
schema_hub.register_table must accept actor='orchestrator' so the
kickoff coordinator (run_kickoff.finalize_kickoff) can register the
M{n} contract during the kickoff-finalize phase.

Background (round-8d smoke surfaced this AFTER Fix #2-bis was identified
as the immediate dispatch break):

- Round-8a finalize_kickoff partial-failure hardening tests all used
  mock hubs, so the actual role-gate ``allowed_set`` was never tested.
  Unit-green ≠ runtime-engaged — the same lesson the whole arc has
  taught us repeatedly.
- finalize_kickoff calls ``registryhub.register_endpoint(agent="orchestrator", ...)``
  and ``schema_hub.register_table(agent="orchestrator", ...)``.
- The legacy ``allowed_set`` was ``{"backend"}`` for register_endpoint and
  ``{"backend", "database_worker"}`` for register_table — exactly the
  set that role-gated design's rejection loop in round-8b (32 rejections).
  orchestrator was NOT in either set, so even if Fix #2-bis lets the
  kickoff reach finalize, the very first register_endpoint call would
  partial_failure and the driver would raise.

Fix #4 adds ``"orchestrator"`` to both allowed_sets. The semantic
justification: orchestrator IS the authoritative contract registrar in
the kickoff finalize phase (charter §6.D — contract must register
BEFORE any task_ready dispatch, and the kickoff coordinator is the
single registrar). Legacy actors (backend / database_worker) stay
allowed for non-kickoff remediation paths. Design / frontend / verifier
remain BLOCKED — they produce sections, not registrations.

These tests are closed-by-construction:
- orchestrator can register (the round-8d positive case)
- backend can register (legacy path still works — no regression)
- database_worker can register tables (legacy spawn path still works)
- design / frontend / verifier still get rejected (round-8b
  closed-by-construction guard against re-introducing the legacy
  "design owns contract" pattern; if those branches re-open silently
  the round-8b rejection-loop bug returns)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402  (source-pin only)


# ---------------------------------------------------------------------------
# Helpers: build real RegistryHub instances via HubRegistry. We need REAL
# hubs (not mocks) because the bug we're catching is exactly the gap
# between mock-only tests and runtime behavior.
# ---------------------------------------------------------------------------


@pytest.fixture
def hubs(tmp_path):
    return HubRegistry(tmp_path)


def _registryhub(hubs):
    return hubs.registryhub


def _schema_hub(hubs):
    return hubs.schema_hub


# ---------------------------------------------------------------------------
# registryhub.register_endpoint allowed_set: orchestrator + backend OK; other
# actors rejected.
# ---------------------------------------------------------------------------


def test_registryhub_register_endpoint_accepts_orchestrator(hubs):
    """The round-8d positive case: kickoff coordinator (actor='orchestrator')
    must be able to register endpoints during finalize_kickoff."""
    hub = _registryhub(hubs)
    result = hub.register_endpoint(
        method="POST",
        path="/api/auth/register",
        schema={"request": {}, "response": {}},
        provider="backend",
        agent="orchestrator",
        status="defined",
    )
    # On success, register_endpoint returns the endpoint dict.
    assert isinstance(result, dict)
    assert result.get("id") or result.get("method") == "POST"


def test_registryhub_register_endpoint_accepts_backend_legacy_path(hubs):
    """Legacy path must still work — backend (and its spawns) register
    endpoints when the legacy task_ready flow runs (e.g. remediation
    tasks routed via the debugger)."""
    hub = _registryhub(hubs)
    result = hub.register_endpoint(
        method="GET",
        path="/api/posts",
        schema={},
        provider="backend",
        agent="backend",
        status="defined",
    )
    assert isinstance(result, dict)


@pytest.mark.parametrize("actor", ["design", "frontend", "verifier", "debugger", "knowledge"])
def test_registryhub_register_endpoint_rejects_non_allowed_actors(hubs, actor):
    """Closed-by-construction guard against the round-8b regression:
    design / frontend / verifier / debugger / knowledge MUST NOT be able
    to register endpoints. The kickoff flow has design contribute the
    ui_pages section and backend contribute the api_endpoints section;
    orchestrator does the actual registration during finalize. If a
    future edit silently re-opens any of these actors, the round-8b
    rejection loop returns."""
    hub = _registryhub(hubs)
    with pytest.raises(Exception) as exc_info:
        hub.register_endpoint(
            method="POST",
            path="/api/foo",
            schema={},
            provider="backend",
            agent=actor,
            status="defined",
        )
    msg = str(exc_info.value).lower()
    assert "register_endpoint" in msg
    assert actor in msg or "restricted" in msg


# ---------------------------------------------------------------------------
# schema_hub.register_table allowed_set: orchestrator + backend +
# database_worker OK; other actors rejected.
# ---------------------------------------------------------------------------


def test_schema_hub_register_table_accepts_orchestrator(hubs):
    """Kickoff finalize registers each data-model table under
    actor='orchestrator'. This is the round-8d positive case."""
    hub = _schema_hub(hubs)
    result = hub.register_table(
        name="posts",
        schema={"columns": []},
        provider="backend",
        agent="orchestrator",
        status="defined",
    )
    assert isinstance(result, dict)
    assert result.get("name") == "posts" or result.get("id") == "posts"


def test_schema_hub_register_table_accepts_backend_legacy_path(hubs):
    hub = _schema_hub(hubs)
    result = hub.register_table(
        name="users",
        schema={},
        provider="backend",
        agent="backend",
        status="defined",
    )
    assert isinstance(result, dict)


def test_schema_hub_register_table_accepts_database_worker_spawn_path(hubs):
    """Backend's database_worker spawns also legitimately register
    tables; preserved from the legacy allowed_set."""
    hub = _schema_hub(hubs)
    result = hub.register_table(
        name="comments",
        schema={},
        provider="backend",
        agent="database_worker",
        status="defined",
    )
    assert isinstance(result, dict)


@pytest.mark.parametrize("actor", ["design", "frontend", "verifier", "debugger", "knowledge"])
def test_schema_hub_register_table_rejects_non_allowed_actors(hubs, actor):
    """Closed-by-construction guard: design / frontend / verifier /
    debugger / knowledge MUST NOT register tables. Same regression
    surface as the registryhub test above."""
    hub = _schema_hub(hubs)
    with pytest.raises(Exception) as exc_info:
        hub.register_table(
            name="foo",
            schema={},
            provider="backend",
            agent=actor,
            status="defined",
        )
    msg = str(exc_info.value).lower()
    assert "register_table" in msg
    assert actor in msg or "restricted" in msg


# ---------------------------------------------------------------------------
# Closed-by-construction integration check: finalize_kickoff calls
# register_endpoint and register_table with agent='orchestrator' — these
# must work end-to-end against real hubs (no mocks). This is the test
# that would have caught the round-8d allowed_set gap if round-8a had
# included it.
# ---------------------------------------------------------------------------


def test_finalize_kickoff_registers_under_orchestrator_actor_against_real_hubs(hubs):
    """Round-8d-blocker test: simulate the call shape finalize_kickoff
    uses and assert both hubs accept it. If round-8a's hardening had
    used REAL hubs instead of mocks, this is the test that would have
    caught the allowed_set gap before it shipped to round-8b smoke."""
    registryhub = _registryhub(hubs)
    schema_hub = _schema_hub(hubs)

    # The exact call shape finalize_kickoff uses
    # (run_kickoff.py:862 + 898 — agent='orchestrator', provider read
    # from the endpoint dict; for the test we use 'backend' as provider
    # since that's what the kickoff backend section would emit).
    ep = registryhub.register_endpoint(
        method="POST",
        path="/api/posts",
        schema={"request": {}, "response": {}},
        provider="backend",
        agent="orchestrator",  # <- the key assertion
        status="defined",
    )
    assert isinstance(ep, dict)

    tbl = schema_hub.register_table(
        name="posts",
        schema={"columns": []},
        provider="backend",
        agent="orchestrator",  # <- the key assertion
        status="defined",
    )
    assert isinstance(tbl, dict)


# ---------------------------------------------------------------------------
# Sanity: the allowed_set IS the closed-by-construction guard. Pin the
# exact contents so a future edit that drops orchestrator silently
# (re-creating the round-8d break) fails here.
# ---------------------------------------------------------------------------


def test_registryhub_register_endpoint_source_pins_allowed_set():
    """Source-inspection guard: the allowed_set literal in registryhub.py
    MUST contain both 'backend' and 'orchestrator'."""
    import inspect
    src = inspect.getsource(RegistryHub.register_endpoint)
    assert '"backend"' in src or "'backend'" in src
    assert (
        '"orchestrator"' in src or "'orchestrator'" in src
    ), (
        "round-8d Fix #4: registryhub.register_endpoint MUST allow "
        "actor='orchestrator' so the kickoff coordinator can register "
        "the contract during finalize_kickoff. Dropping orchestrator "
        "from allowed_set re-opens the round-8d break: finalize "
        "partial_failure → kickoff_failed → driver raises before any "
        "smoke can succeed."
    )


def test_schema_hub_register_table_source_pins_allowed_set():
    import inspect
    src = inspect.getsource(RegistryHub.register_table)
    assert '"backend"' in src or "'backend'" in src
    assert '"database_worker"' in src or "'database_worker'" in src
    assert (
        '"orchestrator"' in src or "'orchestrator'" in src
    ), (
        "registryhub.register_table MUST allow actor='orchestrator' "
        "(kickoff coordinator)."
    )
