"""#1202vl — a docstring promised one shared list; the body re-listed it, and it drifted.

`registryhub._framework_auth_surface_1202gr` ended with: "Same net as
`lifecycle.is_business`'s auth exclusion, asked from the other side; imported rather than
re-listed so the two cannot drift (#906)." The body re-listed the prefixes, and #1202ov had
already added `/.well-known/` on the lifecycle side only — so the guard that suppresses a
false "auth was added to a framework surface" breaking change (147 such P0s across 29 runs,
every one filed at a lane that does not own the endpoint) still reported one for an OAuth
discovery document.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.lifecycle import (
    FRAMEWORK_AUTH_SURFACE_PREFIXES_1202vl as PREFIXES,
)
from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    _framework_auth_surface_1202gr as is_auth_surface,
)

_RH = pathlib.Path(
    __file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/registryhub.py")
_LC = pathlib.Path(
    __file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/lifecycle.py")


@pytest.mark.parametrize("path", [
    "/auth/login", "/auth/register", "/oauth/token", "/oauth/authorize",
    "/api/auth/login", "/api/oauth/token",
])
def test_the_auth_surface_is_recognised(path):
    assert is_auth_surface(path) is True


@pytest.mark.parametrize("path", [
    "/.well-known/jwks.json", "/.well-known/oauth-authorization-server",
])
def test_the_discovery_documents_are_on_it_now(path):
    """The drift itself. #1202ov put these beside /oauth/ in `is_business` because they
    were classifying as BUSINESS and blocking delivery in 9 runs; the other copy of the
    same net never got them."""
    assert is_auth_surface(path) is True


@pytest.mark.parametrize("path", [
    "/api/videos", "/api/users/{id}", "/authors", "/oauthclients",
])
def test_a_business_route_is_not_the_auth_surface(path):
    assert is_auth_surface(path) is False


def test_health_stays_off_the_list():
    """Framework-served, but not the AUTH surface. #1202gr is narrow on purpose (#647),
    and `is_business` excludes /health by its own separate clause."""
    assert "/health" not in PREFIXES
    assert is_auth_surface("/health") is False


def test_the_control_surface_is_not_folded_in():
    """`is_business` consults `is_control_surface_path` separately. Folding it in here
    would widen a breaking-change SUPPRESSION past what #1202gr measured."""
    assert not any("tenant" in p or "admin" in p for p in PREFIXES)
    assert is_auth_surface("/api/v1/tenants") is False


def test_registryhub_imports_the_list_rather_than_re_listing_it():
    """The whole ticket: make the docstring's promise true. A future edit that inlines the
    tuple again recreates the drift this closed."""
    src = _RH.read_text()
    body = src[src.index("def _framework_auth_surface_1202gr"):]
    body = body[:body.index("def _resolved_auth_1202gr")]
    assert "FRAMEWORK_AUTH_SURFACE_PREFIXES_1202vl" in body
    # the only literal prefixes allowed here are the fail-closed fallback, which must NOT
    # be the full net (that would silently become a second copy again)
    assert body.count('"/auth/"') <= 1
    assert '"/.well-known/"' not in body, (
        "the discovery prefix must come from the shared list, not a second literal")


def test_lifecycle_uses_the_same_constant():
    src = _LC.read_text()
    assert "FRAMEWORK_AUTH_SURFACE_PREFIXES_1202vl)" in src
    # and does not keep its own inline copy beside it
    assert '"/api/oauth/", "/.well-known/"))' not in src


def test_the_fallback_fails_closed_to_the_old_net(monkeypatch):
    """If the import ever fails, answering True would SUPPRESS a breaking-change report —
    the one answer indistinguishable from "nothing to report". It falls back to the
    pre-#1202vl net instead."""
    src = _RH.read_text()
    body = src[src.index("def _framework_auth_surface_1202gr"):]
    body = body[:body.index("def _resolved_auth_1202gr")]
    assert "except Exception:" in body
    assert "return True" not in body


def test_the_chain_hint_derives_its_namespaces_from_the_same_list():
    """#1202vc asks the same membership question from a third place. Deriving keeps its
    stricter MATCHING (first path segment, case-folded, `/api/` stripped — so
    `/api/oauth_clients` stays a business route) while the SET comes from one place."""
    from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
        _as_namespaces_1202vl as namespaces,
        _is_authorization_server_path_1202vc as is_as_path,
    )
    derived = set(namespaces())
    # exactly what the shared prefixes reduce to today
    assert derived == {"auth", "oauth", ".well-known"}
    # and every prefix on the shared list reaches it
    for pref in PREFIXES:
        seg = pref.strip("/")
        if seg.startswith("api/"):
            seg = seg[4:]
        assert seg.split("/", 1)[0].lower() in derived, pref
    # the stricter matching is preserved, not replaced by a prefix test
    assert is_as_path("/api/oauth_clients") is False
    assert is_as_path("/AUTH/Login") is True


def test_a_prefix_added_to_the_shared_list_reaches_the_chain_hint(monkeypatch):
    """The point of deriving: one edit, both readers. Without it the third copy drifts the
    way the second one already did."""
    import env_generator.llm_generator.multi_agent.runtime.lifecycle as lc
    from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
        _as_namespaces_1202vl as namespaces,
    )
    monkeypatch.setattr(lc, "FRAMEWORK_AUTH_SURFACE_PREFIXES_1202vl",
                        tuple(PREFIXES) + ("/idp/",))
    assert "idp" in namespaces()
