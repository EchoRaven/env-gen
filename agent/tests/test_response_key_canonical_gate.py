"""PROMPT-C1 — response_key by-construction: a projected business endpoint may
only declare the canonical envelope key (``items`` / ``item``).

``route_projector`` hardcodes ``{"items": [...], "total": N}`` (list) and
``{"item": {...}}`` (single) for every business endpoint and IGNORES any other
``response_key``. The prompts used to ALSO teach custom keys ("response_key=
'games' -> {games: [...]}"), so a contract could register ``response_key='games'``
while the projector still shipped ``{items}`` — the frontend read ``data.games``
against an ``{items}`` body and rendered blank. This is the single biggest
blank-page source (review backlog #4 / PROMPT-C1).

``_noncanonical_business_response_keys`` flags the non-canonical key at the
delivery gate. Calibrated on the released generated/instagram round47:

  * business endpoints (``metadata.kind`` unset) all used ``items`` / ``item`` —
    0 flagged;
  * the 3 endpoints with ``response_key='message'`` are all ``kind=infra``
    (control-plane: init-tenant / reset / delete-tenant) — NOT projector-owned,
    so exempt;
  * single-object GETs that don't end in ``/me`` or ``/{id}`` (``/insights``,
    ``/limit``, ``/business_discovery``) correctly declare ``item`` — the gate
    checks only the KEY VOCABULARY ({items,item}), NOT which of the two, so these
    are not falsely flagged.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.orchestrator import Orchestrator  # noqa: E402


def _ep(method, path, response_key=None, kind=None, status="implemented", custom=False):
    md = {}
    if response_key is not None:
        md["response_key"] = response_key
    if kind is not None:
        md["kind"] = kind
    if custom:
        md["custom"] = True
    return {"method": method, "path": path, "status": status, "metadata": md}


def _flag(endpoints):
    stub = types.SimpleNamespace(hubs=types.SimpleNamespace(
        registryhub=types.SimpleNamespace(get_endpoints=lambda: endpoints)))
    return Orchestrator._noncanonical_business_response_keys(stub)


def _ids(rows):
    return {r["endpoint"] for r in rows}


# ── canonical keys pass ───────────────────────────────────────────────────────

def test_canonical_items_and_item_not_flagged():
    eps = {
        "GET /api/posts": _ep("GET", "/api/posts", "items"),
        "POST /api/posts": _ep("POST", "/api/posts", "item"),
    }
    assert _flag(eps) == []


def test_single_object_get_registered_item_not_flagged():
    """round47: GET /api/users/{u}/insights returns ONE object → response_key
    'item'. The gate checks the key vocabulary, not the (heuristic) shape, so a
    legit single-object GET registered 'item' must NOT be a false positive."""
    eps = {
        "GET /api/users/{username}/insights": _ep("GET", "/api/users/{username}/insights", "item"),
        "GET /api/publishing/limit": _ep("GET", "/api/publishing/limit", "item"),
    }
    assert _flag(eps) == []


def test_absent_response_key_not_flagged():
    # absent is a separate "lane forgot to set it" concern, not a wrong-key blank page
    eps = {"GET /api/feed": _ep("GET", "/api/feed", None)}
    assert _flag(eps) == []


# ── non-canonical business key is flagged ─────────────────────────────────────

def test_custom_business_response_key_is_flagged():
    eps = {"GET /api/games": _ep("GET", "/api/games", "games")}
    rows = _flag(eps)
    assert _ids(rows) == {"GET /api/games"}
    assert rows[0]["response_key"] == "games"
    assert "blank" in rows[0]["reason"]


def test_multiple_custom_keys_all_flagged():
    eps = {
        "GET /api/games": _ep("GET", "/api/games", "games"),
        "GET /api/posts": _ep("GET", "/api/posts", "items"),       # ok
        "GET /api/results": _ep("GET", "/api/results", "results"),  # bad
    }
    assert _ids(_flag(eps)) == {"GET /api/games", "GET /api/results"}


# ── exemptions: control-plane / custom_routes are not projector-owned ─────────

def test_infra_message_endpoints_exempt():
    """round47's 3 'message' keys are all kind=infra (control-plane). They ship
    their own handlers and the frontend skips them — must NOT be flagged."""
    eps = {
        "POST /api/v1/admin/init-tenant": _ep("POST", "/api/v1/admin/init-tenant", "message", kind="infra"),
        "POST /api/v1/reset": _ep("POST", "/api/v1/reset", "message", kind="infra"),
        "DELETE /api/v1/tenants/{tenant_id}": _ep("DELETE", "/api/v1/tenants/{tenant_id}", "message", kind="infra"),
    }
    assert _flag(eps) == []


def test_auth_oauth_spine_kinds_exempt():
    eps = {
        "POST /auth/register": _ep("POST", "/auth/register", "access_token", kind="auth"),
        "GET /oauth/authorize": _ep("GET", "/oauth/authorize", "redirect", kind="oauth"),
        "GET /api/v1/tenants": _ep("GET", "/api/v1/tenants", "tenants", kind="spine"),
    }
    assert _flag(eps) == []


def test_custom_route_flagged_endpoint_exempt():
    eps = {"GET /api/report": _ep("GET", "/api/report", "report", custom=True)}
    assert _flag(eps) == []


# ── round47 shape: many canonical + infra 'message' → zero flags ──────────────

def test_round47_shape_zero_false_flags():
    eps = {"_meta": {"version": 1}}
    for path in ("/api/feed", "/api/posts", "/api/stories"):
        eps[f"GET {path}"] = _ep("GET", path, "items")
    for path in ("/api/users/{username}/insights", "/api/publishing/limit"):
        eps[f"GET {path}"] = _ep("GET", path, "item")        # single-object GET
    eps["POST /api/posts/media"] = _ep("POST", "/api/posts/media", "item")
    # control-plane 'message' (kind=infra) — exempt
    eps["POST /api/v1/reset"] = _ep("POST", "/api/v1/reset", "message", kind="infra")
    # None response_key business endpoint — not flagged
    eps["GET /api/conversations"] = _ep("GET", "/api/conversations", None)
    assert _flag(eps) == []


# ── resilience ────────────────────────────────────────────────────────────────

def test_missing_registryhub_returns_empty():
    stub = types.SimpleNamespace(hubs=types.SimpleNamespace())
    assert Orchestrator._noncanonical_business_response_keys(stub) == []


def test_meta_key_and_non_dict_values_skipped():
    eps = {"_meta": {"version": 9}, "bogus": "not-a-dict",
           "GET /api/x": _ep("GET", "/api/x", "items")}
    assert _flag(eps) == []
