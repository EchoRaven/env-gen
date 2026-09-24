"""Convention-tolerant oracle helpers for north-star measurement.

Source: R2 round-5 delivery (verbatim). Update with care — these
helpers are the oracle's calibration anchor.

Per R2 round-5: the make-or-break for north-star is decoupling
"transport convention" (cookie vs Bearer auth, /api prefix presence,
status code families like 200 vs 201, error envelope shapes) from
"behavior" (the post must really appear in the listing; unauthorized
must really be rejected). This file lets oracles assert behavior
strictly while tolerating convention differences between the
reference_impl (FastAPI/cookie) and pipeline output (likely
Bearer/Express//api).

The best source of truth for what convention an app uses is its own
spec.api.json conventions block (project_structure.py:152 declares
base_url, auth method, error format, response_wrapper). When the spec
is available we drive the oracle from it; otherwise we fall back to
probing.

Principle: tolerate the CONVENTION, never the BEHAVIOR. Over-loosening
behavior assertions makes the oracle blind and misses real bugs.

Required for the §9.1.5 cross-stack calibration arm — without
convention-tolerance the oracle systematically false-fails any correct
pipeline-generated app that ships a different convention than the
FastAPI/cookie reference. False-fails on improvements would poison
the north-star metric (making improvement look like regression).
"""

import json
import os
from pathlib import Path
from typing import Optional

import requests


# ---- 1. auth: cookie OR Bearer token both accepted ----

def authenticate(session, base, email, password):
    """Login then return session carrying auth.

    Tolerates two conventions:
      - cookie auth (reference_impl FastAPI): requests.Session
        automatically persists Set-Cookie, so nothing extra to do.
      - Bearer auth (pipeline-generated Express/Node): pull token
        from response body and pin it as the session's Authorization
        header.

    Behavior assertion stays strict: login MUST succeed (200/201/204).
    """
    r = session.post(
        f"{base}/login", json={"email": email, "password": password},
    )
    assert r.status_code in (200, 201, 204), f"login failed: {r.status_code}"
    token = _extract_token(r)
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    # Cookie stack: requests.Session has already persisted Set-Cookie
    return session


def _extract_token(resp):
    """Pull an auth token out of a login response body, tolerating
    common key names + 1-level nesting. Returns None if none found
    (in which case the caller falls back to cookie-only)."""
    try:
        body = resp.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    for key in ("token", "access_token", "accessToken", "jwt", "id_token"):
        if body.get(key):
            return body[key]
        for parent in ("data", "user", "result"):
            sub = body.get(parent)
            if isinstance(sub, dict) and sub.get(key):
                return sub[key]
    return None


# ---- 2. path: bare OR /api prefix both accepted (resolved once per app) ----

def resolve_base(api_url, app_path: Optional[str] = None):
    """Determine the API base URL for an app under test.

    Priority order:
      1. Read spec.api.json conventions.base_url if app_path is supplied
         (this is the authoritative declaration from the generator).
      2. Probe /health (and /api/health) for a 2xx/3xx/4xx (anything
         non-404).
      3. Default to bare (no prefix).
    """
    pref = _prefix_from_spec(app_path)
    if pref is not None:
        return f"{api_url}{pref}"
    for pref in ("", "/api"):
        try:
            r = requests.get(f"{api_url}{pref}/health", timeout=5)
            if r.status_code != 404:
                return f"{api_url}{pref}"
        except Exception:
            pass
    return api_url


def _prefix_from_spec(app_path: Optional[str]) -> Optional[str]:
    """Read base_url prefix from <app_path>/design/spec.api.json
    conventions block. Returns None if unavailable."""
    if not app_path:
        return None
    try:
        spec_path = Path(app_path) / "design" / "spec.api.json"
        if not spec_path.is_file():
            return None
        spec = json.loads(spec_path.read_text())
        conv = spec.get("conventions") or {}
        base_url = conv.get("base_url")
        if not isinstance(base_url, str):
            return None
        # base_url may be "/api" or "http://..." — only use the path part.
        if base_url.startswith("/"):
            return base_url.rstrip("/")
        # Absolute URL — try to extract its path component.
        from urllib.parse import urlparse
        path = urlparse(base_url).path or ""
        return path.rstrip("/") or None
    except Exception:
        return None


# ---- 3. unauthorized: 401 OR 403 both count as "rejection" ----

def assert_unauthorized(resp):
    """Auth-required endpoint without credentials → must reject."""
    assert resp.status_code in (401, 403), \
        f"expected auth rejection (401/403), got {resp.status_code}"


# ---- 4. client error: 4xx with machine-readable body ----

def assert_client_error(resp, expect=None):
    """4xx response with JSON body (not HTML app shell).

    If expect == 400 or 422, accepts either (treated as synonymous
    validation rejections). Otherwise insists on exactly `expect` if
    given, else any 4xx.

    Always insists on JSON content-type — catches the
    "200 with HTML app shell" anti-pattern where the SPA routes
    unknown URLs back to the shell, defeating the oracle's HTTP
    assertion.
    """
    if expect in (400, 422):
        assert resp.status_code in (400, 422), \
            f"expected 400/422 client error, got {resp.status_code}"
    elif expect is not None:
        assert resp.status_code == expect, \
            f"expected {expect}, got {resp.status_code}"
    else:
        assert 400 <= resp.status_code < 500, \
            f"expected 4xx client error, got {resp.status_code}"
    ctype = resp.headers.get("content-type", "")
    assert "json" in ctype.lower(), \
        f"error response not machine-readable JSON (HTML app shell?): {ctype}"


# ---- 5. create: 200 OR 201 accepted; id tolerates multiple keys ----

def assert_created(resp):
    """POST to create endpoint must return 200 or 201 with a body
    containing the new resource's id. Returns the id.

    R2 round-6 correction: raise AssertionError when no id is recoverable.
    The previous implementation silently returned None on missing id —
    exactly the over-tolerance bug this helper exists to guard against
    (a "created but no id" response is a real product bug; oracles must
    surface it, not silently accept it). The id extractor (``_id_of``)
    stays composable and returns None on missing — this assertion is
    the surfacing layer."""
    assert resp.status_code in (200, 201), \
        f"create expected 200/201, got {resp.status_code}"
    try:
        body = resp.json()
    except Exception as e:
        raise AssertionError(f"create response not JSON: {e}")
    id_value = _id_of(body)
    if id_value is None:
        body_keys = (list(body.keys()) if isinstance(body, dict)
                     else type(body).__name__)
        raise AssertionError(
            "create response missing id field (tried id/_id/uuid/pk + "
            f"data/result/post/item wrappers); body shape: {body_keys}. "
            "An app that returns 201 without an id is broken — the "
            "oracle MUST NOT silently accept it (R2 round-6 fix)."
        )
    return id_value


def _id_of(obj):
    """Extract the resource id from a body, tolerating common key
    names + 1-level wrapper conventions.

    Returns None if no recognizable id field present. Callers (e.g.
    ``assert_created``) MUST check the return value and raise on None;
    this extractor itself does not raise so it remains composable.
    R2 round-6 separation of concerns: extractor stays pure; the
    assertion layer surfaces the absent-id case as the real bug it is."""
    if not isinstance(obj, dict):
        return None
    for k in ("id", "_id", "uuid", "pk"):
        if obj.get(k) is not None:
            return obj[k]
    for parent in ("data", "result", "post", "item"):
        sub = obj.get(parent)
        if isinstance(sub, dict):
            inner = _id_of(sub)
            if inner is not None:
                return inner
    return None


# ---- 6. list envelope tolerance ----

def items_of(listing):
    """Extract the items array from a list response, tolerating common
    envelope conventions: {posts: []}, {items: []}, {data: []}, or a
    bare [].

    Returns empty ``[]`` if no recognizable list envelope. Callers
    performing existence assertions (e.g. "post must appear in list")
    MUST NOT silently accept ``[]`` — explicit existence check + assert
    is required at the caller. R2 round-6 separation of concerns
    (matches ``_id_of`` pattern)."""
    if isinstance(listing, list):
        return listing
    if not isinstance(listing, dict):
        return []
    for k in ("posts", "items", "data", "results"):
        v = listing.get(k)
        if isinstance(v, list):
            return v
    return []
