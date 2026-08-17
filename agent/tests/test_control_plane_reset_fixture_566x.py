r"""#566x (netflix r130): a verifier-authored chain step that POSTs the FIXED control-plane
reset endpoint takes its FACTORY branch -- the contract is "scoped (X-Tenant-Id -> that
tenant's business rows) or factory (NO header)" -- and DELETEs every business row, including
the seeded catalog that every OTHER chain reads its ${...} ids from.

The step itself PASSES (200 is the correct answer), so the damage is invisible at the point of
harm and resurfaces as misleading application-level 404s in every chain that runs after it:
  GET /api/titles          -> 200 {"items": []}   save FAILED: titleId<-items.0.id
  POST /api/my-list        -> 404 "referenced resource not found"   (ladder filled a foreign id)
  POST /api/titles/41/rating -> 404 "parent resource not found"

Live r130 ground truth (agent/generated/netflix-web-r130/.../registryhub_verification_chains.json):
reset chain at index 20 of 49; failing chain indices [24,25,27,28,29,30,31,39,40,41] -- ZERO
before the reset, ALL ten after it. Deterministic every pass, so the delivery gate can never
see all chains green in ONE eval -> business_chain_failing -> wedge (0 tags, rc=1). The lane is
then dispatched to "fix" endpoints that were never broken.

Fix: send the reset TENANT-SCOPED (_scoped_reset_header) -- a tenant the chain created, else its
registered tenant, else a deterministic synthetic id that owns nothing. The endpoint stays
covered and reachable; the shared fixture survives.
"""
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
from env_generator.llm_generator.multi_agent.runtime.validation_runner import _http

# Snapshot at import: the pre-#566x simulation empties ce._CONTROL_PLANE_RESET (that set IS
# the guard), and the fake app must keep serving the reset path regardless of the guard.
_RESET_PATHS = frozenset(ce._CONTROL_PLANE_RESET)


# --------------------------------------------------------------------------- units

def test_factory_reset_detected_from_the_fixed_surface_only():
    assert ce._CONTROL_PLANE_RESET, "control surface must expose a reset path"
    reset_path = sorted(ce._CONTROL_PLANE_RESET)[0]
    assert ce._is_factory_reset("POST", reset_path)
    assert ce._is_factory_reset("post", reset_path + "/")
    assert ce._is_factory_reset("POST", reset_path + "?x=1")
    # not the reset: wrong verb, a business path, a look-alike suffix
    assert not ce._is_factory_reset("GET", reset_path)
    assert not ce._is_factory_reset("POST", "/api/my-list")
    assert not ce._is_factory_reset("POST", "/api/v1/resets")
    assert not ce._is_factory_reset("POST", "/api/password/reset")


def test_scope_prefers_a_tenant_the_chain_created_then_its_own_then_synthetic():
    hdr = ce._TENANT_SCOPE_HEADER
    # 1. a tenant THIS chain created wins
    assert ce._scoped_reset_header("c", "verif_9", {"tenant_id": "reg_t"})[hdr] == "verif_9"
    # 2. else the chain user's registered tenant
    assert ce._scoped_reset_header("c", None, {"tenant_id": "reg_t"})[hdr] == "reg_t"
    # 3. else a deterministic synthetic scope that owns nothing
    got = ce._scoped_reset_header("tenant_and_infra_coverage", None, {})[hdr]
    assert got == "_fwscope_tenant_and_infra_coverage"
    assert got == ce._scoped_reset_header("tenant_and_infra_coverage", None, None)[hdr]
    # never empty, never unsanitised, never the literal 'default' (which owns the seed)
    weird = ce._scoped_reset_header("a b/c;drop", None, {"tenant_id": "  "})[hdr]
    assert weird and re.fullmatch(r"[A-Za-z0-9_-]+", weird) and weird != "default"


def test_http_sends_custom_headers_and_is_unchanged_without_them():
    sent = {}

    class _Resp:
        status = 200

        def read(self, _n=None):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request as _u
    real = _u.urlopen
    try:
        _u.urlopen = lambda req, timeout=10: (sent.update(dict(req.header_items())), _Resp())[1]
        _http("POST", "http://x/api/v1/reset", headers={"X-Tenant-Id": "t1"})
        assert sent.get("X-tenant-id") == "t1"  # urllib capitalises header keys
        sent.clear()
        _http("POST", "http://x/api/v1/reset")
        assert not any(k.lower() == "x-tenant-id" for k in sent)
    finally:
        _u.urlopen = real


# ------------------------------------------------------- r130 replay (the real test)

def _fake_app():
    """A minimal app with the two behaviours that matter: a seeded catalog every chain
    reads ids from, and a control-plane reset whose FACTORY branch wipes it."""
    state = {"titles": [{"id": 29}, {"id": 30}], "log": []}

    def _fake_http(method, url, *, token=None, body=None, timeout=10, form=False,
                   headers=None):
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        path = "/" + path.split("?", 1)[0]
        state["log"].append((method.upper(), path, dict(headers or {})))
        if path == "/auth/register":
            return {"status": 201, "body_text": '{"access_token":"tok","user":{"id":1}}',
                    "error": None}
        if path == "/api/v1/tenants" and method.upper() == "POST":
            return {"status": 201, "body_text": '{"ok":true}', "error": None}
        if path.rstrip("/") in _RESET_PATHS and method.upper() == "POST":
            if not (headers or {}).get(ce._TENANT_SCOPE_HEADER):
                state["titles"] = []            # FACTORY branch: wipe the fixture
            return {"status": 200, "body_text": '{"ok":true}', "error": None}
        if path == "/api/titles":
            rows = ",".join('{"id":%s}' % t["id"] for t in state["titles"])
            return {"status": 200,
                    "body_text": '{"items":[%s],"total":%d}' % (rows, len(state["titles"])),
                    "error": None}
        if path == "/api/my-list" and method.upper() == "POST":
            ids = {str(t["id"]) for t in state["titles"]}
            if str((body or {}).get("title_id")) in ids:
                return {"status": 201, "body_text": '{"item":{"id":7}}', "error": None}
            return {"status": 404, "body_text": '{"detail":"referenced resource not found"}',
                    "error": None}
        return {"status": 200, "body_text": '{"items":[]}', "error": None}

    return state, _fake_http


_RESET_CHAIN = {
    "name": "tenant_and_infra_coverage",
    "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "chain_${rand}@example.com", "password": "Chain123!x"},
         "save": {"token": "access_token"}},
        {"method": "POST", "path": "/api/v1/reset"},
    ],
}

# r130's my_list_add_and_readback, verbatim in shape.
_BUSINESS_CHAIN = {
    "name": "my_list_add_and_readback",
    "steps": [
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "mladd_${rand}@example.com", "password": "Password123!"},
         "save": {"token": "access_token"}},
        {"method": "GET", "path": "/api/titles", "save": {"titleId": "items.0.id"}},
        {"method": "POST", "path": "/api/my-list", "body": {"title_id": "${titleId}"},
         "expect": [200, 201]},
    ],
}


def _run_pass(monkeypatch, *, guard_enabled):
    state, fake = _fake_app()
    monkeypatch.setattr(ce, "_http", fake)
    if not guard_enabled:                      # simulate the PRE-#566x framework
        monkeypatch.setattr(ce, "_CONTROL_PLANE_RESET", frozenset())
    first = ce.execute_chain("http://app", dict(_RESET_CHAIN))
    second = ce.execute_chain("http://app", dict(_BUSINESS_CHAIN))
    return state, first, second


def test_r130_repro_without_the_guard_the_reset_starves_every_later_chain(monkeypatch):
    """The bug, reproduced: the reset chain PASSES and the next chain dies on a 404 that
    looks like an application defect."""
    state, first, second = _run_pass(monkeypatch, guard_enabled=False)
    assert not first["broken"], "the reset step itself passes — that is what hides the damage"
    assert state["titles"] == [], "factory branch wiped the shared fixture"
    notes = " ".join(str(s.get("note") or "") for s in second["steps"])
    assert "save FAILED" in notes and "titleId" in notes
    assert second["broken"], "downstream chain must break — this is the r130 signature"
    assert any("referenced resource not found" in str(b) for b in second["broken"])


def test_the_guard_scopes_the_reset_so_the_fixture_and_later_chains_survive(monkeypatch):
    state, first, second = _run_pass(monkeypatch, guard_enabled=True)
    # the reset is still EXERCISED (covered + 200) — only its blast radius changed
    reset_calls = [c for c in state["log"] if c[1].rstrip("/") in _RESET_PATHS]
    assert len(reset_calls) == 1
    assert reset_calls[0][2].get(ce._TENANT_SCOPE_HEADER) == "_fwscope_tenant_and_infra_coverage"
    assert not first["broken"]
    # and the fixture — plus every chain that depends on it — survives
    assert state["titles"] == [{"id": 29}, {"id": 30}]
    assert not second["broken"], f"downstream chain must pass, got {second['broken']}"
    notes = " ".join(str(s.get("note") or "") for s in second["steps"])
    assert "save FAILED" not in notes


def test_the_scoping_is_recorded_never_silent(monkeypatch):
    """A framework-adjusted request must SAY so in the step record — a silent rewrite is
    undiagnosable when it is the wrong call."""
    _state, first, _second = _run_pass(monkeypatch, guard_enabled=True)
    reset_step = first["steps"][-1]
    assert any(str(a).startswith("reset-scoped->") for a in (reset_step.get("autofilled") or [])), \
        reset_step


def test_an_app_with_no_control_plane_is_untouched(monkeypatch):
    """Derived-from-the-surface, not a literal: no control plane → the guard is inert."""
    monkeypatch.setattr(ce, "_CONTROL_PLANE_RESET", frozenset())
    assert not ce._is_factory_reset("POST", "/api/v1/reset")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
