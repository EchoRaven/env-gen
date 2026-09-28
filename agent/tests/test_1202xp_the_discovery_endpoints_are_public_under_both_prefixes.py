"""#1202xp: a JWKS endpoint that answers 401 is self-contradictory.

The embedded AS router is mounted twice -- bare and `include_router(prefix="/api")` -- so
every one of its paths answers on both spellings. The generated app's auth middleware made
only the BARE spelling public.

MEASURED on four delivered stacks, identical in all four (tiktok r135, r132, r126 and
netflix-local-r30):

    /.well-known/jwks.json                     200
    /api/.well-known/jwks.json                 401
    /.well-known/oauth-authorization-server    200
    /api/.well-known/oauth-authorization-server 401

RFC 7517 and 8414 have a client fetch these BEFORE it holds any token, so requiring one is a
contradiction -- and both spellings appear in the app's public `openapi.json`, so the app
advertises an endpoint it then refuses.

This is the fourth time in one session that a guard covered one spelling of a thing that has
two (#1202xf, #1202xl, #1202xm). Here the argument for the fix was already written six lines
below it: #64 widened the auth ENTRY points to `/api/auth/...` because "the frontend's api.js
prefixes EVERY call with /api ... must be public under BOTH prefixes". `/.well-known` and
`/oauth` were not given the same treatment.

No consumer was found on the `/api` spelling -- the delivered MCP server builds
`{API_BASE_URL}/.well-known/jwks.json` from the bare form and the frontend bundle references
neither -- so this is a published-surface correctness fix rather than an outage. Additive and
in the safe direction: these paths are public by specification and their bare twins already
are.
"""
import os
import re
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

_SCAFFOLD = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                         "backend_scaffold.py")


def _public_predicate_src():
    with open(_SCAFFOLD, encoding="utf-8") as fh:      # #1202eu
        src = fh.read()
    i = src.index("    public = (")
    return src[i:src.index("\n    )", i)]


def _is_public(path):
    """Evaluate the emitted predicate the way the generated app does."""
    body = _public_predicate_src()
    expr = body.split("public = (", 1)[1]
    expr = "(" + re.sub(r"^\s*#.*$", "", expr, flags=re.M) + ")"
    return bool(eval(expr, {"__builtins__": {}}, {"p": path}))  # noqa: S307


@pytest.mark.parametrize("path", [
    "/.well-known/jwks.json",
    "/api/.well-known/jwks.json",
    "/.well-known/oauth-authorization-server",
    "/api/.well-known/oauth-authorization-server",
    "/oauth/token",
    "/api/oauth/token",
    "/oauth/authorize",
    "/api/oauth/authorize",
])
def test_discovery_and_oauth_are_public_under_both_prefixes(path):
    """★ The defect: only the bare half was public, on four delivered stacks."""
    assert _is_public(path), path


@pytest.mark.parametrize("path", [
    "/api/videos",
    "/api/feed/foryou",
    "/api/users/1/followers",
    "/api/auth/me",
])
def test_business_paths_stay_guarded(path):
    """★ The widening must not open anything else. `/api/auth/me` is named because #64's own
    comment carves it out: it 'stays guarded by its own Depends(get_current_user)'."""
    assert not _is_public(path), path


@pytest.mark.parametrize("path", [
    "/auth/login", "/api/auth/login", "/auth/register", "/api/auth/signup",
    "/health", "/openapi.json", "/api/v1/tenants",
])
def test_what_was_already_public_still_is(path):
    assert _is_public(path), path


def test_the_predicate_was_actually_found():
    """A parametrised guard over an expression the parser failed to locate is vacuous."""
    body = _public_predicate_src()
    assert "startswith" in body and len(body) > 200, body[:120]
