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
