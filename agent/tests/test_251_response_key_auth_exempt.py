"""#251 — the response_key gate must never fire on the auth/oauth control surface.

r50 (live) was green except for this ONE check, burned both convergence graces and
aborted. The two "offending" endpoints were POST /auth/signup (response_key='signup')
and POST /auth/logout — framework-owned AS-router endpoints the projector never touches.
The gate's own docstring lists auth/oauth as exempt, but the exemption only consulted
``metadata.kind``, which the lane had not set — so the check flagged endpoints NO lane
could fix (the handlers are the framework's). That is an unwinnable hard gate: the
opt-5 FALSE-BLOCK lesson recurring.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (  # noqa: E402
    noncanonical_business_response_keys,
)


class _Hubs:
    def __init__(self, endpoints):
        self.registryhub = self
        self._eps = endpoints

    def get_endpoints(self):
        return self._eps


def _ep(path, key, kind=None, method="POST"):
    md = {"response_key": key}
    if kind:
        md["kind"] = kind
    return {"path": path, "metadata": md, "method": method}


def test_r50_regression_auth_endpoints_never_flagged():
    """The exact pair that aborted r50 — no metadata.kind, non-canonical key."""
    hubs = _Hubs({
        "POST /auth/signup": _ep("/auth/signup", "signup"),
        "POST /auth/logout": _ep("/auth/logout", "logout"),
    })
    assert noncanonical_business_response_keys(hubs) == []


def test_all_control_surface_prefixes_exempt():
    hubs = _Hubs({
        "POST /api/auth/login": _ep("/api/auth/login", "login"),
        "GET /oauth/authorize": _ep("/oauth/authorize", "authorize", method="GET"),
        "POST /api/oauth/token": _ep("/api/oauth/token", "token"),
        "GET /.well-known/openid": _ep("/.well-known/openid", "config", method="GET"),
    })
    assert noncanonical_business_response_keys(hubs) == []


def test_real_business_endpoint_still_flagged():
    """The gate must keep its teeth: a projected business endpoint reading data.games
    against a {items:[...]} body is the blank-page class this check exists for."""
    hubs = _Hubs({"GET /api/games": _ep("/api/games", "games", method="GET")})
    bad = noncanonical_business_response_keys(hubs)
    assert len(bad) == 1 and bad[0]["response_key"] == "games"


def test_canonical_and_absent_keys_pass():
    hubs = _Hubs({
        "GET /api/videos": _ep("/api/videos", "items", method="GET"),
        "GET /api/videos/{id}": _ep("/api/videos/{id}", "item", method="GET"),
        "GET /api/x": {"path": "/api/x", "metadata": {}, "method": "GET"},   # absent key
    })
    assert noncanonical_business_response_keys(hubs) == []


def test_metadata_kind_exemption_still_works():
    hubs = _Hubs({"POST /api/thing": _ep("/api/thing", "thing", kind="infra")})
    assert noncanonical_business_response_keys(hubs) == []
