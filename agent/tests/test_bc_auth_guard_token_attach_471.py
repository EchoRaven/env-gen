"""#471 — THE final part-B delivery blocker (r47: #470 fixed the seed → r47 reached
deliver_project 6× with 15/16 endpoints, but create_release=0, blocked on
deliverability_ui_flow_missing). ROOT: 7 screens bounced to /login because the app made
protected /api/ calls WITHOUT the (valid, backend-issued, stored) token on a cold boot —
its api-layer read the token only from React context (empty on reload), so /api/ → 401 →
the framework global guard (_BC_AUTH_GUARD_JS) redirected. This tanked BOTH fidelity
capture (verdict 0.223 artifact) AND ui_flow delivery. FIX: extend the guard to ATTACH the
stored bearer token to same-origin /api/ requests that lack an Authorization header (cold-
boot session restore), for BOTH fetch and XHR (axios). Additive + guarded (never double-
adds; same-origin /api/ only) so a lane that already attaches the token is unaffected.
Generalizable to every app. (JS syntax separately verified with `node --check`.)"""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _BC_AUTH_GUARD_JS)


def test_attaches_stored_token_to_api_requests():
    g = _BC_AUTH_GUARD_JS
    assert "_bcTok" in g and "Bearer ' + tok" in g, "attaches a Bearer token"
    # reads the standard storage aliases (same set FIX #103 pre-sets)
    for alias in ("access_token", "token", "authToken", "accessToken", "jwt"):
        assert f"'{alias}'" in g, f"reads the {alias} storage alias"
    assert "localStorage.getItem" in g and "sessionStorage.getItem" in g, "both storages"


def test_only_same_origin_api_and_no_double_add():
    g = _BC_AUTH_GUARD_JS
    assert "_bcIsApi" in g and "/api/" in g, "scopes to /api/"
    assert "u.origin === window.location.origin" in g, "same-origin only (no cross-origin leak)"
    # fetch: don't overwrite an existing Authorization header
    assert "h.has('Authorization')" in g, "fetch guards against double-add"
    # xhr: track whether the app already set Authorization
    assert "_bcAuthSet" in g and "authorization" in g.lower(), "xhr guards against double-add"


def test_preserves_401_redirect_guard():
    g = _BC_AUTH_GUARD_JS
    assert "_bcOn401" in g and "window.location.assign('/login')" in g, "401→/login preserved"
    assert "res.status === 401" in g and "this.status === 401" in g, "both fetch + xhr 401 handled"


def test_patches_both_fetch_and_xhr():
    g = _BC_AUTH_GUARD_JS
    assert "window.fetch =" in g, "patches fetch"
    assert "XMLHttpRequest.prototype.send" in g and "XMLHttpRequest.prototype.open" in g, "patches XHR"
    assert "XMLHttpRequest.prototype.setRequestHeader" in g, "tracks XHR Authorization for no-double-add"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
