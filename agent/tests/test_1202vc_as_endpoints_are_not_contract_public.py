"""#1202vc — the "CONTRACT SAYS PUBLIC" hint must not fire on the framework's own AS.

Live netflix-r30 (2026-09-25), run through the framework's own `run_chains`: POST
/auth/login answered 200 to a WRONG password and to an email that was never registered,
and both failing chain steps carried the framework-authored sentence "this probe is
probably mis-authored. If the endpoint really must deny, change the CONTRACT first."
The only signal that caught a disabled password check arrived with instructions to
dismiss it.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    _is_authorization_server_path_1202vc as is_as,
    _contract_public_note_1202ib as note,
)


@pytest.mark.parametrize("path", [
    "/auth/login", "/auth/register", "/auth/signup", "/auth/logout", "/auth/me",
    "/oauth/token", "/oauth/authorize", "/oauth/register",
    "/api/auth/login", "/api/oauth/token",          # frontends that mount everything under /api
    "/auth/login/", "/auth/login?next=/", "/AUTH/Login",
    "/.well-known/jwks.json",
])
def test_the_authorization_server_namespace_is_recognised(path):
    assert is_as(path) is True


@pytest.mark.parametrize("path", [
    "/api/videos/feed", "/api/feed/foryou", "/api/notifications", "/api/users/65",
    "/api/video_saves", "/api/videos/39/comments",   # every endpoint the hint has EVER
    "/health", "/api/authors", "/api/oauth_clients",  # fired on in the corpus logs
])
def test_business_routes_are_not_mistaken_for_the_as(path):
    """`/api/authors` and `/api/oauth_clients` start with the same letters — matching on
    a prefix instead of the first path SEGMENT would swallow real business routes and
    silently disarm the hint where it is correct."""
    assert is_as(path) is False


def test_the_note_inverts_on_a_login_denial_probe():
    """The r30 reading: a registered, contract-public POST /auth/login."""
    eps = [{"method": "POST", "path": "/auth/login", "auth_required": False,
            "schema": {"auth_required": False}, "_updated_by": "backend"}]
    out = note("POST", "/auth/login", eps)
    assert "mis-authored" not in out
    assert "change the CONTRACT" not in out
    assert "DEFINITIONAL" in out
    assert "auth_password_is_checked" in out


def test_a_contract_public_business_route_still_gets_the_original_note():
    """#1202ib's own evidence — 12 of 14 denial-probe failures were projected business
    routes whose contract really did say public. Narrowing must not disarm that."""
    eps = [{"method": "GET", "path": "/api/videos/feed", "auth_required": False,
            "schema": {"auth_required": False}, "_updated_by": "backend"}]
    out = note("GET", "/api/videos/feed", eps)
    assert "CONTRACT SAYS PUBLIC" in out
    assert "probably mis-authored" in out


def test_an_as_path_needs_no_registered_endpoint_to_get_the_corrected_note():
    """The correction must not depend on the contract carrying the AS endpoint at all —
    /auth/login is framework-owned and a lane may simply never have registered it."""
    out = note("POST", "/auth/login", [])
    assert "DEFINITIONAL" in out


def test_the_premise_is_stated_where_the_next_reader_will_look():
    """#647: the reason this narrowing is correct is that the AS is not projected. If
    that sentence is gone, the next person cannot tell this from an arbitrary waiver."""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "env_generator/llm_generator/multi_agent/runtime/chain_executor.py").read_text()
    start = src.index("def _is_authorization_server_path_1202vc")
    block = src[start:src.index("def _denial_scope_verdict_663", start)]
    assert "oauth_routes.py" in block          # who really serves these paths
    assert "registered contract" in block       # and that they do not come from it
