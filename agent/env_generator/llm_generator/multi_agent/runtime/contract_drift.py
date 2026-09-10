"""Detect drift between an endpoint's declared response schema and the
actual response shape returned by its implementing code.

Pure functions. Heuristic by design — covers the dominant ``res.json`` /
``return jsonify`` / ``return JSONResponse`` patterns across Express,
Flask, FastAPI. Agents call this after writing/updating a route to
catch silent contract drift before downstream consumers break on it.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# Express/Node.js: ``res.json({...})``, ``res.send({...})``, and the
# chained form ``res.status(200).json({...})``. We match the ``.json(`` /
# ``.send(`` invocation anywhere (the ``\.`` anchor + the JSON.parse
# rejection via the trailing ``\{`` keeps false positives low).
_EXPRESS_RES_JSON = re.compile(
    r"\.(?:json|send)\s*\(\s*\{\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*:",
)
# return { "key": ... }  or  return {key: ...}  in arrow fns / express handlers
_RETURN_OBJECT = re.compile(
    r"\breturn\s*\{\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*:",
)
# Flask: return jsonify({"key": ...})  /  return jsonify(key=..., ...)
_FLASK_JSONIFY = re.compile(
    r"\bjsonify\s*\(\s*\{?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*[:=]",
)
# FastAPI: return JSONResponse({"key": ...})  /  return ORJSONResponse(content={"key": ...})
_FASTAPI_RESP = re.compile(
    r"\b(?:JSON|ORJSON)Response\s*\(\s*(?:content\s*=\s*)?\{\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*:",
)

_PATTERNS = (
    _EXPRESS_RES_JSON,
    _RETURN_OBJECT,
    _FLASK_JSONIFY,
    _FASTAPI_RESP,
)

# Common envelope keys we don't want to falsely flag. ``error`` / ``status``
# are legitimate alongside the response key, not contract drift.
_BENIGN_KEYS = {"error", "status", "ok", "success", "code", "errors", "detail"}


def extract_response_keys(file_content: str) -> List[str]:
    """Return every top-level response key the file appears to use.

    Order-preserved, deduplicated. Benign envelope keys (``error``,
    ``status``) are filtered out so a route that does
    ``res.status(400).json({error: "bad"})`` doesn't get reported as
    drift away from its happy-path response_key.
    """
    found: List[str] = []
    seen: set = set()
    for pattern in _PATTERNS:
        for match in pattern.finditer(file_content):
            key = match.group(1)
            if key in _BENIGN_KEYS:
                continue
            if key not in seen:
                seen.add(key)
                found.append(key)
    return found


def detect_endpoint_drift(
    *,
    endpoint: Dict[str, Any],
    file_content: str,
) -> Optional[Dict[str, Any]]:
    """Compare an endpoint's declared ``response_key`` to the keys
    actually used in ``file_content``.

    Returns ``None`` when no drift detected (declared key is among the
    keys used in the file, or no declared key to compare against).
    Returns a drift report dict otherwise.

    Drift report shape:
        {
            "endpoint_id": "...",
            "expected_key": "...",
            "found_keys": [...],
            "hint": "..."
        }
    """
    if not endpoint or not isinstance(endpoint, dict):
        return None
    metadata = endpoint.get("metadata") or {}
    schema = endpoint.get("schema") or {}
    # Prefer explicit metadata.response_key; fall back to schema.response_key
    # (some agents put it under schema).
    expected = metadata.get("response_key") or schema.get("response_key")
    if not expected:
        return None
    expected = str(expected).strip()
    if not expected:
        return None

    found = extract_response_keys(file_content or "")
    if not found:
        # File doesn't use any of the recognised patterns — could be a
        # middleware, a static file handler, or a route style we don't
        # parse. Don't report drift on absence — too many false positives.
        return None

    if expected in found:
        return None

    return {
        "endpoint_id": endpoint.get("id"),
        "expected_key": expected,
        "found_keys": found,
        "hint": (
            f"Route file returns {found!r} but the registered endpoint "
            f"schema declares response_key={expected!r}. Either fix the "
            f"code to return {{{expected}: ...}} or update the schema "
            f"via registryhub_update_schema."
        ),
    }


# A path segment that is purely an API version marker: v1, v2, V3, ...
_VERSION_SEGMENT = re.compile(r"^v\d+$", re.IGNORECASE)


def _strip_version_segments(path: str) -> str:
    """Normalise a route path by dropping empty and ``/vN/`` version segments so
    ``/api/v1/directions`` and ``/api/directions`` collapse to the same key."""
    segs = [s for s in str(path).strip("/").split("/")
            if s and not _VERSION_SEGMENT.match(s)]
    return "/" + "/".join(segs)


def _iter_method_path(endpoints: Any):
    """Yield ``(method, path)`` from a registryhub endpoints map (keyed
    ``"METHOD /path"``) or a list of endpoint dicts; skips ``_meta`` / non-endpoint
    entries (anything without both a method and a path)."""
    if isinstance(endpoints, dict):
        vals = endpoints.values()
    elif isinstance(endpoints, (list, tuple)):
        vals = endpoints
    else:
        return
    for e in vals:
        if not isinstance(e, dict):
            continue
        method, path = e.get("method"), e.get("path")
        if method and path:
            yield str(method), str(path)


def version_variant_duplicate_routes(endpoints: Any) -> List[Dict[str, Any]]:
    """Detect endpoints registered under VERSION-VARIANT DUPLICATE paths — the same
    METHOD at paths that are identical modulo a ``/vN/`` version segment, e.g.
    ``GET /api/directions`` AND ``GET /api/v1/directions``.

    This is the run-13 no-convergence-abort root cause: the contract fragmented one
    logical endpoint across two paths, the lane implemented one and left the other a
    projected empty stub, and the frontend client called the stub. Which path the lane
    fills is LLM-nondeterministic, so it is a flaky-abort source. A SOFT gate uses this
    to route a precise "consolidate to a single path" remediation to the backend lane
    instead of the generic "query the table" (which can't fix a path mismatch).

    Only flags a group when >1 distinct path collapses to the same normalised key AND at
    least one variant actually carries a version segment (so genuinely-distinct non-version
    paths are never flagged). Pure; best-effort — ``[]`` on a non-map/list input.
    """
    from collections import defaultdict
    groups: Dict[tuple, List[str]] = defaultdict(list)
    for method, path in _iter_method_path(endpoints):
        groups[(method.upper(), _strip_version_segments(path))].append(path)

    blockers: List[Dict[str, Any]] = []
    for (method, norm), paths in groups.items():
        distinct = sorted(set(paths))
        if len(distinct) < 2:
            continue
        # genuine version-variant: the differentiator is a /vN/ segment, not something else.
        has_version = any(_VERSION_SEGMENT.match(s)
                          for p in distinct for s in p.strip("/").split("/"))
        if not has_version:
            continue
        blockers.append({
            "method": method,
            "paths": distinct,
            "normalized": norm,
            "hint": (
                f"{method} is registered at {len(distinct)} version-variant paths "
                f"{distinct} — the SAME logical endpoint. A client calls only ONE of them; "
                f"the other(s) are left as unimplemented projected stubs that return empty "
                f"responses, so their page can never render real data (run-13 aborted on "
                f"exactly this for directions). CONSOLIDATE to a SINGLE path — match what the "
                f"frontend api client actually calls — and remove the duplicate registration."
            ),
        })
    return blockers


def logged_out_screens_needing_auth_1202jx(screens: Any, ui_pages: Any,
                                           endpoints: Any) -> List[Dict[str, Any]]:
    """Screens the design system declares reachable LOGGED OUT whose page calls an endpoint
    the contract marks auth_required.

    Such a screen can never render: the capture arrives without a token, the projected handler
    answers 401, and the page shows its error or empty state. The lane then reads "the logged
    out feed is blank" and looks at the frontend, where nothing is wrong.

    Measured over 35 recent runs (googlemaps-r16 excluded — #1202jw: its references are two
    environments merged): 32 of 98 screens declared `requires_auth: False` depend on at least
    one auth-required endpoint. The names say it outright — tiktok's `fyp_feed_logged_out` at
    `/` calling `GET /api/videos`, netflix's `landing` at `/` calling `GET /api/titles`.

    THE SIGNAL IS DECLARED, NOT SNIFFED: `requires_auth` comes from the design system's own
    screen record and the auth flag through #1202hi's single reader, so this needs no guess
    about which routes "look" public — the mistake I made on the first pass here, when I
    treated `/browse` as a logged-out surface and netflix's login-walled browse page counted
    as a finding.

    REPORTS BOTH REPAIRS AND PICKS NEITHER. Either the endpoint should be public or the screen
    should not be marked logged-out, and only the contract's author knows which; flipping
    `auth_required` here would open an endpoint on a guess. Pure function, no I/O.
    """
    out: List[Dict[str, Any]] = []
    try:
        auth: Dict[str, bool] = {}
        for ep in _iter_endpoint_records_1202jx(endpoints):
            a = _stated_auth_1202jx(ep)
            if a is None:
                continue
            m = str(ep.get("method") or "GET").upper()
            p = str(ep.get("path") or "")
            if p:
                auth[f"{m} {p}"] = bool(a)
        by_route: Dict[str, Any] = {}
        for pg in _iter_endpoint_records_1202jx(ui_pages):
            r = str(pg.get("route") or "")
            if r:
                by_route.setdefault(r, pg)
        for sc in (screens or []):
            if not isinstance(sc, dict) or sc.get("requires_auth") is not False:
                continue
            pg = by_route.get(str(sc.get("route") or ""))
            if not pg:
                continue
            guarded = [str(u) for u in (pg.get("apis_used") or [])
                       if auth.get(str(u)) is True or auth.get("GET " + str(u)) is True]
            if guarded:
                out.append({"screen": str(sc.get("name") or ""),
                            "route": str(sc.get("route") or ""),
                            "page": str(pg.get("name") or ""),
                            "auth_endpoints": sorted(guarded)})
    except Exception:
        return []
    return out


def _iter_endpoint_records_1202jx(coll: Any):
    """RegistryHub hands these back as {id: record}; a list is tolerated too."""
    if isinstance(coll, dict):
        return [v for k, v in coll.items() if k != "_meta" and isinstance(v, dict)]
    if isinstance(coll, (list, tuple)):
        return [v for v in coll if isinstance(v, dict)]
    return []


def _stated_auth_1202jx(ep: Any) -> Optional[bool]:
    """#1202hi's precedence, imported so this cannot become a fourth reading of the flag."""
    try:
        from .route_projector import _stated_auth_1202hi
        return _stated_auth_1202hi(ep)
    except Exception:
        return None
