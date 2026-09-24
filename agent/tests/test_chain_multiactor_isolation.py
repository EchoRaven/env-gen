"""normalize_steps MULTI-ACTOR isolation auto-fix.

A cross-user isolation probe (GET/PUT/DELETE /api/<res>/{id} expecting 403/404 —
"user B must NOT reach A's row") authored WITHOUT per-step auth defaults to the
canonical "token" = the resource OWNER → reads its OWN row → 200 ≠ 404 → false-fail
(smoke-notes exp7/exp9, ~2/3 of private-app runs failed this way though the app was
correctly scoped). normalize_steps routes such a step to a dedicated INTRUDER user
(owns nothing) so the app's real 404 is observed. SAFE: explicit distinct actors are
untouched, deletion-checks keep the owner (no masking of failed deletes), 401-only
auth-roundtrips are not denials.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.chain_executor import normalize_steps  # noqa: E402

_INTRUDER = "__chain_intruder_token"


def _norm(steps):
    out, _ = normalize_steps(steps)
    return out


def _find(out, method, path, expect_has=None, expect_eq=None):
    for s in out:
        if str(s.get("method", "")).upper() != method.upper():
            continue
        if str(s.get("path", "")).rstrip("/") != path.rstrip("/"):
            continue
        codes = [int(c) for c in (s.get("expect") or []) if str(c).lstrip("-").isdigit()]
        if expect_has is not None and expect_has not in codes:
            continue
        if expect_eq is not None and set(codes) != set(expect_eq):
            continue
        return s
    return None


def _has_intruder_register(out):
    return any(_INTRUDER in (s.get("save") or {}) for s in out)


def _authored_step_routed_to_intruder(out):
    """True iff the intruder-ROUTING block rewrote an ORIGINALLY-AUTHORED step to the
    intruder token. Excludes the FIX #192a framework-injected isolation probe (a NEW
    synthesized step, separately covered by test_isolation_probe_injection.py) — that
    probe legitimately registers + authenticates as the intruder even when no authored
    step was routed, so a global _has_intruder_register no longer isolates the routing."""
    return any(s.get("auth") == _INTRUDER
               and not str(s.get("action", "")).startswith("framework_isolation_probe")
               for s in out)


# ---- the core fix: unset-auth cross-user denial → intruder -----------------

def test_cross_user_read_routed_to_intruder():
    out = _norm([
        {"method": "POST", "path": "/auth/register", "save": {"tokenA": "access_token"}},
        {"method": "POST", "path": "/api/notes", "save": {"note_id": "id"}},
        {"method": "POST", "path": "/auth/register", "save": {"tokenB": "access_token"}},
        {"method": "GET", "path": "/api/notes/${note_id}", "expect": [404]},
    ])
    probe = _find(out, "GET", "/api/notes/${note_id}")
    assert probe is not None and probe.get("auth") == _INTRUDER
    assert _has_intruder_register(out)


def test_cross_user_put_and_delete_routed():
    out = _norm([
        {"method": "POST", "path": "/auth/register", "save": {"tokenA": "access_token"}},
        {"method": "POST", "path": "/api/notes", "save": {"note_id": "id"}},
        {"method": "PUT", "path": "/api/notes/${note_id}", "expect": [403, 404]},
        {"method": "DELETE", "path": "/api/notes/${note_id}", "expect": [403, 404]},
    ])
    assert _find(out, "PUT", "/api/notes/${note_id}").get("auth") == _INTRUDER
    assert _find(out, "DELETE", "/api/notes/${note_id}").get("auth") == _INTRUDER


# ---- safety: explicit distinct actor is NOT overridden ---------------------

def test_explicit_actor_auth_untouched():
    out = _norm([
        {"method": "POST", "path": "/auth/register", "save": {"tokenA": "access_token"}},
        {"method": "POST", "path": "/api/notes", "auth": "tokenA", "save": {"note_id": "id"}},
        {"method": "POST", "path": "/auth/register", "save": {"tokenB": "access_token"}},
        {"method": "GET", "path": "/api/notes/${note_id}", "auth": "tokenB", "expect": [404]},
    ])
    probe = _find(out, "GET", "/api/notes/${note_id}")
    assert probe.get("auth") == "tokenB"      # verifier authored it correctly → keep
    assert not _authored_step_routed_to_intruder(out)   # routing block left the explicit actor alone


# ---- safety: deletion-check keeps the owner (no masking) -------------------

def test_deletion_check_keeps_owner_not_intruder():
    out = _norm([
        {"method": "POST", "path": "/auth/register", "save": {"tokenA": "access_token"}},
        {"method": "POST", "path": "/api/notes", "save": {"note_id": "id"}},
        {"method": "GET", "path": "/api/notes/${note_id}", "expect": [403, 404]},  # cross-user
        {"method": "DELETE", "path": "/api/notes/${note_id}", "expect": [200]},    # owner delete
        {"method": "GET", "path": "/api/notes/${note_id}", "expect": [404]},       # deletion check
    ])
    cross = _find(out, "GET", "/api/notes/${note_id}", expect_has=403)
    deleted = _find(out, "GET", "/api/notes/${note_id}", expect_eq=[404])
    assert cross.get("auth") == _INTRUDER          # cross-user (before delete) → intruder
    assert deleted.get("auth") == "token"          # deletion check → stays owner (no masking)


def test_cross_user_read_of_different_resource_than_deleted_is_routed():
    out = _norm([
        {"method": "POST", "path": "/auth/register", "save": {"tokenA": "access_token"}},
        {"method": "POST", "path": "/api/notes", "save": {"nid_a": "id"}},
        {"method": "DELETE", "path": "/api/notes/${nid_a}", "expect": [200]},   # delete A's
        {"method": "GET", "path": "/api/posts/${pid_b}", "expect": [404]},      # cross-user on a DIFFERENT var
    ])
    assert _find(out, "GET", "/api/posts/${pid_b}").get("auth") == _INTRUDER


# ---- safety: non-denial / 401-only / collection are untouched --------------

def test_owner_success_step_untouched():
    out = _norm([
        {"method": "POST", "path": "/auth/register", "save": {"tokenA": "access_token"}},
        {"method": "POST", "path": "/api/notes", "save": {"note_id": "id"}},
        {"method": "GET", "path": "/api/notes/${note_id}", "expect": [200]},
    ])
    assert _find(out, "GET", "/api/notes/${note_id}").get("auth") == "token"
    assert not _authored_step_routed_to_intruder(out)   # a 200 success read is never routed to intruder


def test_unauthenticated_401_probe_untouched():
    out = _norm([
        {"method": "POST", "path": "/auth/register", "save": {"tokenA": "access_token"}},
        {"method": "GET", "path": "/api/notes/${note_id}", "expect": [401]},
    ])
    # 401-only = auth-roundtrip (no token), NOT a cross-user denial → not the intruder
    assert _find(out, "GET", "/api/notes/${note_id}").get("auth") != _INTRUDER
    assert not _has_intruder_register(out)


def test_no_intruder_when_no_qualifying_step():
    out = _norm([
        {"method": "POST", "path": "/auth/register", "save": {"token": "access_token"}},
        {"method": "POST", "path": "/api/notes", "save": {"note_id": "id"}},
        {"method": "GET", "path": "/api/notes/${note_id}", "expect": [200]},
        {"method": "DELETE", "path": "/api/notes/${note_id}", "expect": [200]},
    ])
    # no cross-user DENIAL step → the routing block never fires. (FIX #192a still appends its
    # own framework probe here because a bare authed create is present — covered separately.)
    assert not _authored_step_routed_to_intruder(out)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
