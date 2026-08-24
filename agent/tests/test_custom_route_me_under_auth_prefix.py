"""A custom /me route under the auth/oauth control surface is KEPT, not dropped (outlook
run-27 M3, 2026-07-01, live-reproduced).

The generated main.py filters custom_routes' router: a custom route is KEPT only when
`_custom_route_overrides_projected(method, path)` is True; otherwise it is dropped so the
"safe" projected handler serves that path. The projector emits a /me handler (it special-
cases `path.endswith("/me")`) — BUT ONLY for endpoints it receives, and business_endpoints()
EXCLUDES the auth/oauth control surface (/auth/*, /api/auth/*, /oauth/*). So the canonical
`GET /api/auth/me` ("current user") is never projected; dropping the custom one left the
endpoint NOWHERE → 404 (live: openapi missing /api/auth/me, curl → 404), wedging the
business_chain auth step + the frontend's user-load → M3 no-convergence. Fix: keep the custom
/me route when it sits under an auth/oauth prefix; elsewhere (/api/users/me, bare /me) the
projector DID emit a handler so projected still wins. ENV-AGNOSTIC + LOCAL-ONLY (gitignored).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import _CUSTOM_ROUTES_INCLUDE  # noqa: E402


def _load_fn(nested=("tasks", "comments"), owner_scoped=()):
    """Exec the include template (the `from custom_routes import` raises ImportError, which
    the template's own `except ImportError: pass` swallows) and return the decision fn.
    ``owner_scoped`` fills #77's _OWNER_SCOPED_RESOURCES set (empty by default → the flip is
    inert, so pre-#77 scenarios are unchanged)."""
    tmpl = _CUSTOM_ROUTES_INCLUDE.replace(
        "__NESTED_CHILD_RESOURCES__", repr(list(nested))
    ).replace(
        "__OWNER_SCOPED_RESOURCES__", repr(list(owner_scoped))
    # The template gained __DEGENERATE_RESOURCES__ after this test was written;
    # exec'ing it then died with NameError before reaching a single assertion.
    ).replace("__DEGENERATE_RESOURCES__", "[]")
    _left = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]*__", tmpl)))
    assert not _left, f"unsubstituted template placeholders: {_left}"
    ns: dict = {}
    exec(compile(tmpl, "custom_include.py", "exec"), ns)
    return ns["_custom_route_overrides_projected"]


def test_auth_me_is_kept_custom_wins():
    f = _load_fn()
    # THE FIX: /api/auth/me + /auth/me must be KEPT (True = custom wins) — no projected handler
    assert f("GET", "/api/auth/me") is True
    assert f("GET", "/auth/me") is True


def test_non_auth_me_still_projected_wins():
    f = _load_fn()
    # a MULTI-segment /me the projector DOES emit → projected wins (custom dropped): the `me`
    # branch is only reached here (len(segs) >= 2, non-param tail), and users != auth/oauth.
    assert f("GET", "/api/users/me") is False
    assert f("GET", "/api/profile/me") is False
    # a BARE /me (single segment) is classified as a collection-GET one branch earlier, so it
    # returns True (custom wins) — pre-existing behaviour, NOT the `me` branch. Assert it stays.
    assert f("GET", "/me") is True
    assert f("GET", "/api/me") is True


def test_oauth_prefixed_me_also_kept():
    f = _load_fn()
    assert f("GET", "/oauth/me") is True
    assert f("GET", "/api/oauth/me") is True


def test_standard_crud_shapes_unchanged():
    """Regression guard: the fix only touches the /me branch."""
    f = _load_fn()
    # GET collection + GET by-id → custom wins (owner-scope remediation, run-9)
    assert f("GET", "/api/messages") is True
    assert f("GET", "/api/messages/{messageId}") is True
    # writes stay projected (safe CRUD)
    assert f("POST", "/api/messages") is False
    assert f("DELETE", "/api/messages/{messageId}") is False
    assert f("PATCH", "/api/messages/{messageId}") is False
    # a nested ACTION verb (rsvp not a registered child resource) → custom wins
    assert f("POST", "/api/events/{eventId}/rsvp") is True
    # a nested child-RESOURCE CRUD → projected wins
    assert f("GET", "/api/projects/{pid}/tasks") is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
