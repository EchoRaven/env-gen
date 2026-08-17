"""#561 — THIN-SLICE KICKOFF WEDGE fix (unblocks multi-milestone runs).

ROOT CAUSE (verified): in a multi-milestone run, a LATER milestone (M2+) that adds
NO NEW backend endpoints leaves the backend + verifier lanes with nothing to author.
``roadmap_validator`` treated an EMPTY ``contract.endpoints`` as an UNCONDITIONAL
error (unlike ``data_model`` / ``data_model.tables``, which #96/#108 already gated to
M1-only), so the deterministic kickoff reconcile could not derive a valid section for
a no-new-endpoint slice → the 1200s ``KICKOFF_TIMEOUT_SEC`` HARD-ABORTED the whole run
(instagram_v4: M1 nearly delivered, M2 kickoff timed out ``Missing=['backend',
'verifier']``). Also M2 kickoff could run CONCURRENTLY with unfinished M1 delivery.
This is why ``ENVGEN_SINGLE_MILESTONE=1`` was forced.

FIX (two parts, mirroring the existing M2+ tolerances so it stays consistent):
  1. Empty-slice kickoff tolerance — ``roadmap_validator`` gates an empty
     ``contract.endpoints`` to error@M1 / warning@M2+ (exact mirror of the #96/#108
     ``data_model`` gating), and ``_build_roadmap`` SYNTHESIZES verifier predicates
     from the CUMULATIVE registered contract (the endpoints M1..M(i-1) built) for a
     no-net-new-predicate M2+ slice instead of requiring net-new predicates.
  2. Serialize milestone kickoff — ``Orchestrator._await_prior_milestone_delivery_
     drained`` blocks M(i>=2) advance until the prior milestone's delivery is fully
     drained (``_project_delivered_event`` set + release cut).

Tests below cover:
  (a) a no-new-backend-endpoint slice → reconcile derives a valid empty backend
      section + synthesizes verifier predicates from the cumulative contract →
      validation PASSES (not Missing=[backend,verifier]).
  (b) a slice WITH new endpoints → still fully validated (not weakened); a slice
      whose lanes recorded NOTHING still gates on quorum (the fix does not blanket-
      pass an empty meeting).
  (c) single-milestone / M1 path byte-identical.
  (d) the serialize guard waits for the prior milestone's delivered-event + release.

Run from agent/:
    PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_thin_slice_kickoff_561.py -q
"""

import asyncio
import logging
import types

import pytest

from env_generator.llm_generator.multi_agent.runtime.kickoff.roadmap_validator import (
    validate_roadmap,
)
from env_generator.llm_generator.multi_agent.runtime.kickoff.schema_tolerance import (
    synthesize_predicates_from_contract,
)
from env_generator.llm_generator.multi_agent.runtime.kickoff import run_kickoff
from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_ATTENDEES = ["backend", "frontend", "verifier"]


def _base_roadmap(milestone_index, endpoints, tables):
    """A structurally-complete roadmap snapshot, parameterized on the two fields
    #561 gates (endpoints + tables). Everything else is valid by construction."""
    roadmap = {
        "milestone_index": milestone_index,
        "contract": {
            "endpoints": endpoints,
            "data_model": {"tables": tables},
            "auth": {"model": "jwt", "required": True},
        },
        "task_tree": [
            {"id": "impl.page.p", "owner": "frontend", "depends_on": [],
             "kind": "implement_page", "status": "pending"},
        ],
        "acceptance_predicates": [
            {"id": "p1", "flow": "f1", "form": {"kind": "api_smoke"}},
        ],
        "done_def": ["App boots cleanly in Docker"],
    }
    if milestone_index == 1:
        roadmap["feature_inventory"] = {"entities": ["e"], "flows": ["f1"]}
    return roadmap


class _Store:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _Stores:
    def __init__(self, documents):
        self.documents = _Store(documents)


class _FakeWorkhub:
    def __init__(self, meeting_id, decisions, attendees):
        self._decisions = list(decisions)
        self.stores = _Stores({
            meeting_id: {"metadata": {
                "decisions": list(decisions),
                "expected_attendees": list(attendees),
            }},
        })

    def get_meeting_decisions(self, meeting_id):
        return list(self._decisions)


class _FakeRegistryhub:
    def __init__(self, endpoints):
        self._endpoints = dict(endpoints)

    def get_endpoints(self):
        return dict(self._endpoints)


class _FakeHubs:
    """Minimal hubs surface try_synthesize touches: workhub decisions +
    registryhub cumulative contract."""

    def __init__(self, meeting_id, decisions, attendees, endpoints):
        self.workhub = _FakeWorkhub(meeting_id, decisions, attendees)
        self.registryhub = _FakeRegistryhub(endpoints)


def _cumulative_contract():
    """The endpoints M1 already registered (the cumulative contract at M2)."""
    return {
        "GET /api/posts": {"method": "GET", "path": "/api/posts",
                           "response_key": "items", "auth_required": True},
        "POST /api/posts": {"method": "POST", "path": "/api/posts",
                            "response_key": "item", "auth_required": True},
        # control-plane endpoint — must NOT yield a business acceptance predicate
        "POST /auth/login": {"method": "POST", "path": "/auth/login",
                             "response_key": "item", "auth_required": False},
    }


# ---------------------------------------------------------------------------
# (a) no-new-endpoint slice → validation PASSES
# ---------------------------------------------------------------------------


def test_empty_endpoints_is_warning_not_error_at_m2plus():
    """Mirror of #96/#108: an empty contract.endpoints is a WARNING at M2+, so a
    no-new-endpoint slice validates cleanly on the cumulative contract."""
    roadmap = _base_roadmap(2, endpoints=[], tables=[])
    result = validate_roadmap(roadmap, 2)
    assert result["ok"] is True
    sev = [f["severity"] for f in result["findings"]
           if f["id"] == "endpoints_missing"]
    assert sev == ["warning"], f"expected a warning finding, got {sev}"


def test_synthesize_predicates_from_cumulative_contract():
    """Verifier predicates are DERIVED from the cumulative registered contract
    (one api_smoke predicate per BUSINESS endpoint; control-plane excluded)."""
    preds = synthesize_predicates_from_contract(_cumulative_contract().values())
    assert len(preds) == 2, "one predicate per /api business endpoint (auth excluded)"
    assert {p["source"] for p in preds} == {"auto_cumulative_contract"}
    assert all(p["form"]["kind"] == "api_smoke" for p in preds)
    # deterministic + idempotent
    again = synthesize_predicates_from_contract(_cumulative_contract().values())
    assert preds == again
    # empty-in → empty-out (caller keeps its generic floor)
    assert synthesize_predicates_from_contract([]) == []


def test_build_roadmap_m2_derives_predicates_from_cumulative_contract():
    """_build_roadmap on a no-verifier-predicate M2 slice pulls acceptance
    predicates from the CUMULATIVE contract instead of the single generic floor."""
    drafts = {
        "backend": {"endpoints": [], "deferred": True},
        "frontend": {"ui_pages": [
            {"id": "settings_page", "route": "/settings", "component": "SettingsPage"}]},
        "verifier": {"deferred": True},
    }
    roadmap = run_kickoff._build_roadmap(
        drafts, 2, "Add a settings page.",
        registered_endpoints=list(_cumulative_contract().values()),
    )
    preds = roadmap["acceptance_predicates"]
    assert preds, "predicates must be non-empty"
    assert {p.get("source") for p in preds} == {"auto_cumulative_contract"}
    # not the generic single-floor fallback
    assert [p.get("id") for p in preds] != ["auto_default_api_smoke"]


def test_try_synthesize_no_new_endpoint_slice_is_ready():
    """End-to-end: an M2 slice whose lanes recorded EMPTY/reuse sections (the exact
    state the reconcile derive produces) synthesizes to READY — not Missing=[...]."""
    mid = "m-561-a"
    decisions = [
        {"section": "backend", "agent": "backend",
         "content": {"endpoints": [], "note": "reuse existing", "deferred": True}},
        {"section": "frontend", "agent": "frontend",
         "content": {"ui_pages": [
             {"id": "settings_page", "route": "/settings", "component": "SettingsPage"}]}},
        {"section": "verifier", "agent": "verifier", "content": {"deferred": True}},
    ]
    handle = {"meeting_id": mid, "milestone_index": 2,
              "expected_attendees": _ATTENDEES, "description": "Add a settings page."}
    hubs = _FakeHubs(mid, decisions, _ATTENDEES, _cumulative_contract())

    res = run_kickoff.try_synthesize(hubs, handle)
    assert res["status"] == "ready", res
    # a no-new-endpoint slice legitimately registers zero net-new endpoints
    assert res["contract"]["endpoints"] == []
    # verifier predicates came from the cumulative contract
    assert {p.get("source") for p in res["predicates"]} == {"auto_cumulative_contract"}

    # the reconcile path (what the driver actually invokes at a stall) also readies
    res_r = run_kickoff.try_synthesize(hubs, handle, reconcile=True)
    assert res_r["status"] == "ready", res_r


# ---------------------------------------------------------------------------
# (b) a slice WITH new endpoints is NOT weakened
# ---------------------------------------------------------------------------


def test_empty_endpoints_still_error_at_m1():
    """M1 (walking skeleton) still HARD-requires endpoints — a real-endpoint
    contract is mandatory for the first milestone."""
    roadmap = _base_roadmap(1, endpoints=[], tables=[{"name": "t",
              "columns": [{"name": "id", "type": "integer"}]}])
    result = validate_roadmap(roadmap, 1)
    assert result["ok"] is False
    sev = [f["severity"] for f in result["findings"]
           if f["id"] == "endpoints_missing"]
    assert sev == ["error"]


def test_declared_endpoints_still_fully_shape_validated_at_m2plus():
    """A slice that DOES declare endpoints is still fully shape-validated at M2+ —
    the tolerance only excuses an EMPTY list, never a malformed present one."""
    bad_endpoints = [{"method": "GET", "path": "/api/notes"}]  # missing response_key/auth
    roadmap = _base_roadmap(2, endpoints=bad_endpoints, tables=[])
    result = validate_roadmap(roadmap, 2)
    assert result["ok"] is False, "malformed endpoint at M2+ must still fail"
    ids = {f["id"] for f in result["findings"] if f["severity"] == "error"}
    assert any("response_key" in i for i in ids), ids
    assert any("auth_required" in i for i in ids), ids


def test_try_synthesize_unrecorded_lanes_still_gate_on_quorum():
    """The fix does NOT weaken quorum: a meeting where backend+verifier recorded
    NOTHING still returns awaiting (the driver's reconcile derive is what authors
    the empty sections — synthesis never blanket-passes an empty meeting)."""
    mid = "m-561-b"
    decisions = [
        {"section": "frontend", "agent": "frontend",
         "content": {"ui_pages": [{"id": "n", "route": "/n", "component": "N"}]}},
    ]
    handle = {"meeting_id": mid, "milestone_index": 2,
              "expected_attendees": _ATTENDEES, "description": "x"}
    hubs = _FakeHubs(mid, decisions, _ATTENDEES, _cumulative_contract())
    res = run_kickoff.try_synthesize(hubs, handle)
    assert res["status"] == "awaiting"
    assert set(res["missing"]) == {"backend", "verifier"}


# ---------------------------------------------------------------------------
# (c) single-milestone / M1 path byte-identical
# ---------------------------------------------------------------------------


def test_m1_predicate_floor_byte_identical():
    """M1 has no cumulative contract, so an empty-verifier slice keeps the exact
    legacy generic floor (auto_default_api_smoke) — single-milestone unchanged."""
    drafts = {
        "backend": {"endpoints": [
            {"method": "GET", "path": "/api/x", "response_key": "items",
             "auth_required": True}]},
        "frontend": {"ui_pages": [{"id": "p", "route": "/p", "component": "P"}]},
        "verifier": {},
    }
    roadmap = run_kickoff._build_roadmap(drafts, 1, "")
    assert [p.get("id") for p in roadmap["acceptance_predicates"]] == [
        "auto_default_api_smoke"]


def test_m1_with_cumulative_arg_still_uses_generic_floor():
    """Even if registered_endpoints are passed, M1 keeps the generic floor (the
    cumulative-predicate branch is gated to milestone_index >= 2)."""
    drafts = {
        "backend": {"endpoints": [
            {"method": "GET", "path": "/api/x", "response_key": "items",
             "auth_required": True}]},
        "frontend": {"ui_pages": [{"id": "p", "route": "/p", "component": "P"}]},
        "verifier": {},
    }
    roadmap = run_kickoff._build_roadmap(
        drafts, 1, "", registered_endpoints=list(_cumulative_contract().values()))
    assert [p.get("id") for p in roadmap["acceptance_predicates"]] == [
        "auto_default_api_smoke"]


def test_m1_valid_contract_unaffected():
    """A well-formed M1 contract validates exactly as before the fix."""
    roadmap = _base_roadmap(1, endpoints=[
        {"method": "GET", "path": "/api/posts", "response_key": "items",
         "auth_required": True}], tables=[
        {"name": "posts", "columns": [{"name": "id", "type": "integer"}]}])
    result = validate_roadmap(roadmap, 1)
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# (d) serialize guard: M(i) kickoff waits for M(i-1) delivered-event + release
# ---------------------------------------------------------------------------


def _fake_orch(delivered, event_set):
    lane = types.SimpleNamespace(_project_delivered_event=asyncio.Event())
    if event_set:
        lane._project_delivered_event.set()
    self = types.SimpleNamespace(
        _agents={"orchestrator": lane},
        _project_delivered=delivered,
        _logger=logging.getLogger("test_561"),
    )
    return self, lane


def test_drain_guard_returns_immediately_when_already_drained():
    async def run():
        self, lane = _fake_orch(delivered=True, event_set=True)
        calls = {"n": 0}

        async def _deliver():
            calls["n"] += 1
        self._maybe_framework_deliver = _deliver
        ok = await Orchestrator._await_prior_milestone_delivery_drained(
            self, 2, timeout_s=5.0, poll_s=0.01)
        assert ok is True
        # already drained → never needs to (re-)cut a release
        assert calls["n"] == 0
    asyncio.run(run())


def test_drain_guard_waits_then_cuts_release_and_converges():
    """The prior milestone set only the LANE event (LLM deliver_project) without a
    release cut; the guard idempotently drives _maybe_framework_deliver until the
    release is cut AND the event is set, then returns True."""
    async def run():
        self, lane = _fake_orch(delivered=False, event_set=False)
        calls = {"n": 0}

        async def _deliver():
            calls["n"] += 1
            if calls["n"] >= 2:  # framework deliver cuts the release + sets event
                self._project_delivered = True
                lane._project_delivered_event.set()
        self._maybe_framework_deliver = _deliver
        ok = await Orchestrator._await_prior_milestone_delivery_drained(
            self, 2, timeout_s=5.0, poll_s=0.01)
        assert ok is True
        assert self._project_delivered is True
        assert lane._project_delivered_event.is_set()
        assert calls["n"] >= 2
    asyncio.run(run())


def test_drain_guard_bounded_returns_false_on_timeout():
    """A prior delivery that never drains does not hang the run — the guard is
    bounded and returns False (logged) so the loop proceeds rather than deadlock."""
    async def run():
        self, lane = _fake_orch(delivered=False, event_set=False)

        async def _deliver():
            pass  # never converges
        self._maybe_framework_deliver = _deliver
        ok = await Orchestrator._await_prior_milestone_delivery_drained(
            self, 2, timeout_s=0.05, poll_s=0.01)
        assert ok is False
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
