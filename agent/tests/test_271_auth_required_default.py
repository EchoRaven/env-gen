"""#271 — an endpoint with no declared auth_required must not default to WIDE OPEN.

r58 (opus-4.7), live: GET /api/me, GET /api/feed/following, and the video
like/save/share/comment routes all returned 200 without a token (expected 401). The
registryhub contract carried ``auth_required=None`` for every one of them — the field was
never authored — and the projector read it as

    bool(ep.get("auth_required", meta.get("auth_required", True)))

``.get("auth_required", True)`` only supplies True when the KEY IS ABSENT; the key was
PRESENT with value None, so this returned None and ``bool(None)`` is False. Every
unauthored endpoint projected WITHOUT ``Depends(get_current_user)``. The custom_routes
versions of these routes require auth, but the anonymous projected handler shadowed them.

Two things are wrong and both are fixed here:

  1. None must be treated as "unstated", not as "public". ``.get`` with a default cannot do
     that; an explicit ``is None`` check must.

  2. When auth is genuinely unstated, defaulting to WIDE OPEN is the unsafe direction — it
     silently ships an authz hole. But defaulting every endpoint to auth would break public
     reads (a video feed, an explore grid). The env-agnostic call: a WRITE (POST/PUT/PATCH/
     DELETE) or a SELF / PERSONALISED read (/me, /feed/following|friends, anything scoped to
     "the current user") needs auth; a plain public GET does not.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.route_projector import (  # noqa: E402
    resolve_endpoint_auth,
)


def test_r58_regression_none_is_not_public():
    """The exact contract shape that leaked: key present, value None."""
    assert resolve_endpoint_auth("GET", "/api/me", {"auth_required": None}) is True
    assert resolve_endpoint_auth("GET", "/api/feed/following", {"auth_required": None}) is True


def test_an_explicit_false_is_honoured():
    """A deliberate public endpoint stays public — the fix must not force auth everywhere."""
    assert resolve_endpoint_auth("GET", "/api/videos/{id}", {"auth_required": False}) is False


def test_an_explicit_true_is_honoured():
    assert resolve_endpoint_auth("GET", "/api/explore", {"auth_required": True}) is True


def test_writes_default_to_auth_when_unstated():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert resolve_endpoint_auth(method, "/api/videos/{id}/like", {}) is True, method


def test_self_and_personalised_reads_default_to_auth():
    for path in ("/api/me", "/api/users/me", "/api/feed/following",
                 "/api/feed/friends", "/api/notifications"):
        assert resolve_endpoint_auth("GET", path, {}) is True, path


def test_plain_public_reads_stay_open_when_unstated():
    for path in ("/api/videos", "/api/videos/{id}", "/api/explore",
                 "/api/search", "/api/sounds/{id}"):
        assert resolve_endpoint_auth("GET", path, {}) is False, path


def test_metadata_fallback_still_works():
    assert resolve_endpoint_auth("GET", "/api/x", {}, meta={"auth_required": True}) is True
    assert resolve_endpoint_auth("GET", "/api/x", {}, meta={"auth_required": None}) is False


def test_auth_control_surface_is_not_forced_to_auth():
    """login/register must stay anonymous — they MINT the token."""
    for path in ("/auth/login", "/auth/register", "/api/auth/login", "/oauth/token"):
        assert resolve_endpoint_auth("POST", path, {}) is False, path
