"""Canonical ``KickoffEndpoint`` shape + RegistryHub-storage normalizer.

WHY
---
Round-7 reviewer-blocker: the kickoff-time validators
(``roadmap_validator.py`` + ``cross_check_suite.py``) and the
RegistryHub storage layer (``registryhub.register_endpoint``) had drifted
into two DIFFERENT endpoint shapes:

* kickoff-time validators expect a FLAT endpoint dict with
  top-level keys ``{method, path, response_key, auth_required}``
  (per ``roadmap_validator`` docstring §59) and an additional
  ``response.tables`` sub-mapping consumed by
  ``cross_check_suite.api_vs_data_model``.
* RegistryHub stores a NESTED dict with ``method/path/schema``
  top-level but with ``response_key`` and ``auth_required``
  buried inside ``metadata`` (per ``registryhub.register_endpoint``
  lines 167-178).

If both layers each tried to read the other's shape, the
contract-drift bug class would re-enter through the back door.
This module is the single source of truth for the
**kickoff-time** shape; normalization to the RegistryHub-storage
shape happens at ``register_endpoint`` call-time only — never
the other way around. Validators NEVER touch the RegistryHub-storage
shape; RegistryHub NEVER speaks ``KickoffEndpoint`` directly.

Contract (closed-by-construction — no fallback, no back-compat):

  * The kickoff shape is the producer-side shape (what backend
    drafts during the meeting). It is what every validator
    consumes.
  * The RegistryHub-storage shape is the system-of-record-side shape
    (what ``registryhub._endpoints[endpoint_id]`` actually stores).
    Only ``normalize_to_registryhub_endpoint`` produces it.
  * The two shapes are not interchangeable. No phantom
    defaults; any missing required field surfaces as a
    validation finding (NOT a silent fill-in).

Pure-function: no I/O, no hub coupling, no LLM. Safe for
``roadmap_validator`` or the kickoff orchestrator to import
without side effects.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping


__all__ = [
    "KickoffEndpoint",
    "KickoffDataModel",
    "KickoffAuth",
    "ValidationFinding",
    "endpoint_id",
    "normalize_to_registryhub_endpoint",
    "validate_kickoff_endpoint",
    "REQUIRED_ENDPOINT_KEYS",
]


# ---------------------------------------------------------------------------
# Type aliases (sibling-module convention: plain ``Dict[str, Any]`` aliases
# — see ``roadmap_validator.py`` line 100 — so we don't take on a
# python-version-coupled ``TypedDict`` dependency for what is fundamentally
# a free-form drafting shape).
# ---------------------------------------------------------------------------

# KickoffEndpoint dict shape (drafted by backend during kickoff):
#
#     {
#         "id":            str,   # canonical, derived via endpoint_id(method, path)
#         "method":        str,   # HTTP verb, MUST be non-empty
#         "path":          str,   # URL path, MUST be non-empty
#         "response_key":  str,   # top-level JSON key returned, MUST be non-empty
#         "auth_required": bool,  # True iff endpoint requires an auth token
#         "response": {           # response-shape sketch (cross-check fodder)
#             "tables": [str, ...],  # data_model table names this endpoint reads/writes
#             "shape":  dict,         # free-form, e.g. {"type": "list", "items": "Post"}
#         },
#         "request": {            # request-shape sketch
#             "body":  dict,          # free-form JSON-body schema
#             "query": [str, ...],   # query-string parameter names
#         },
#     }
KickoffEndpoint = Dict[str, Any]

# KickoffDataModel dict shape:
#
#     {"tables": [{"name": str, "columns": [{"name": str, "type": str, ...}, ...]}, ...]}
KickoffDataModel = Dict[str, Any]

# KickoffAuth dict shape (note: kickoff-time auth carries a free-form
# ``details`` sub-mapping, separate from ``registryhub.register_endpoint``'s
# per-endpoint ``auth_required`` bool):
#
#     {"model": str, "details": dict}
KickoffAuth = Dict[str, Any]

# Sibling-module convention: findings are plain dicts (see
# ``roadmap_validator.Finding``).
ValidationFinding = Dict[str, Any]


# Required top-level keys on a KickoffEndpoint. Matches the v1 vocabulary
# enforced by ``roadmap_validator._check_contract`` line 152 verbatim —
# the two MUST stay in sync.
REQUIRED_ENDPOINT_KEYS: tuple = ("method", "path", "response_key", "auth_required")


def _is_nonempty_str(value: Any) -> bool:
    """Sibling-module-style check (mirrors ``roadmap_validator._is_nonempty_str``).

    Whitespace-only strings are treated as missing.
    """
    return isinstance(value, str) and value.strip() != ""


def endpoint_id(method: str, path: str) -> str:
    """Derive the canonical endpoint id from ``(method, path)``.

    MUST stay byte-identical with ``registryhub.RegistryHub.endpoint_id`` (lines
    121-143 of ``registryhub.py``) so that an id minted at kickoff time
    matches the id ``register_endpoint`` mints at storage time. If the
    rule there changes, change it here too — there is intentionally no
    cross-import to keep this module hub-free.

    Rules:
      * ``method`` → upper-case, trimmed.
      * ``path``   → trimmed; ensure exactly one leading ``/`` if path
                     is non-empty; strip trailing ``/`` (except for the
                     bare root ``/`` which stays as-is); Express ``:param``
                     → FastAPI ``{param}`` (PROPOSAL #29, slash-anchored).
    """
    m = str(method or "").upper().strip()
    p = str(path or "").strip()
    if p:
        if not p.startswith("/"):
            p = "/" + p
        if len(p) > 1 and p.endswith("/"):
            p = p.rstrip("/") or "/"
        p = re.sub(r"(?<=/):([A-Za-z_][A-Za-z0-9_]*)", r"{\1}", p)
    return f"{m} {p}"


def normalize_to_registryhub_endpoint(ke: KickoffEndpoint) -> Dict[str, Any]:
    """Translate a ``KickoffEndpoint`` into ``register_endpoint`` kwargs.

    The return value is a **dict of keyword arguments** the caller
    splats into ``registryhub.register_endpoint``. Concretely::

        kwargs = normalize_to_registryhub_endpoint(ke)
        registryhub.register_endpoint(agent="backend", **kwargs)

    Returned keys::

        {
            "method": str,        # passes through as positional-or-kw
            "path":   str,        # passes through as positional-or-kw
            "schema": {           # registryhub stores this verbatim
                "request":  ke["request"],   # body + query
                "response": ke["response"],  # tables + shape
            },
            "provider":      "backend",        # gated by registryhub._role_gate
            "response_key":  ke["response_key"],   # → registryhub metadata
            "auth_required": ke["auth_required"],  # → registryhub metadata
        }

    Why ``provider="backend"``: ``registryhub.register_endpoint`` enforces
    ``allowed_set={"backend"}`` via ``_role_gate.require_allowed_actor``
    (lines 150-162). The kickoff endpoint MUST be registered by the
    backend lane, so we pin it here. Caller may override by editing the
    returned dict before splatting if a future lane ever earns the
    registration right — but the default is the only currently-legal
    value.

    Why ``response_key`` / ``auth_required`` come out at TOP LEVEL of
    the returned kwargs (not nested): ``register_endpoint`` has a
    ``**metadata`` catch-all (line 145) that vacuums any unknown kwargs
    into ``endpoint['metadata']``. So splatting ``response_key`` and
    ``auth_required`` puts them exactly where ``registryhub`` reads them
    (lines 183-184, 190-191): inside the stored ``metadata`` dict.

    Args:
        ke: A well-formed ``KickoffEndpoint`` dict. Call
            :func:`validate_kickoff_endpoint` first if the source is
            untrusted — this normalizer trusts its input.

    Raises:
        TypeError: ``ke`` is not a Mapping.
        KeyError:  ``ke`` is missing one of ``REQUIRED_ENDPOINT_KEYS``.
                   No phantom defaults — caller MUST validate first.
    """
    if not isinstance(ke, Mapping):
        raise TypeError(
            f"KickoffEndpoint MUST be a mapping, got {type(ke).__name__}"
        )
    for key in REQUIRED_ENDPOINT_KEYS:
        if key not in ke:
            raise KeyError(
                f"KickoffEndpoint missing required key '{key}'. "
                "Call validate_kickoff_endpoint() before normalizing."
            )

    request_sub = ke.get("request") or {}
    response_sub = ke.get("response") or {}

    return {
        "method": ke["method"],
        "path": ke["path"],
        "schema": {
            "request": dict(request_sub) if isinstance(request_sub, Mapping) else {},
            "response": dict(response_sub) if isinstance(response_sub, Mapping) else {},
        },
        "provider": "backend",
        # response_key + auth_required ride the **metadata catch-all into
        # registryhub's endpoint['metadata'] — DO NOT nest them here.
        "response_key": ke["response_key"],
        "auth_required": ke["auth_required"],
    }


def validate_kickoff_endpoint(ke: Any) -> List[ValidationFinding]:
    """Shape-check a single ``KickoffEndpoint``.

    Returns a list of findings (NOT raises) so the caller can aggregate
    findings across a whole batch of endpoints (mirrors the
    ``roadmap_validator`` aggregation pattern). Empty list ⇒ shape OK.

    Each finding shape matches the ``Finding`` alias used by
    ``roadmap_validator`` (``{section, id, severity, message}``) so
    findings from this module can be appended to a
    ``ValidationResult.findings`` list without translation. ``section``
    is fixed to ``"kickoff_endpoint"``.

    Checks (mirrors ``roadmap_validator._check_contract`` lines 152-189
    verbatim so the two layers can't drift):
      * ``ke`` is a Mapping
      * each of ``REQUIRED_ENDPOINT_KEYS`` is present
      * ``method`` / ``path`` / ``response_key`` are non-empty strings
      * ``auth_required`` is a Python bool

    Args:
        ke: Candidate KickoffEndpoint. Any type accepted; non-Mappings
            produce a single shape error.

    Returns:
        List of ``ValidationFinding`` dicts. Empty list iff shape OK.
    """
    findings: List[ValidationFinding] = []

    if not isinstance(ke, Mapping):
        findings.append({
            "section": "kickoff_endpoint",
            "id": "endpoint_shape",
            "severity": "error",
            "message": "kickoff_endpoint MUST be a mapping",
        })
        return findings

    # Presence checks first (mirrors roadmap_validator line 161-167).
    missing: List[str] = []
    for key in REQUIRED_ENDPOINT_KEYS:
        if key not in ke:
            missing.append(key)
            findings.append({
                "section": "kickoff_endpoint",
                "id": f"missing.{key}",
                "severity": "error",
                "message": f"kickoff_endpoint MUST have '{key}'",
            })

    # Type checks only when every required key is present (mirrors
    # roadmap_validator line 169 — the `all(...)` gate).
    if not missing:
        if not _is_nonempty_str(ke["method"]):
            findings.append({
                "section": "kickoff_endpoint",
                "id": "type.method",
                "severity": "error",
                "message": "kickoff_endpoint.method MUST be a non-empty string",
            })
        if not _is_nonempty_str(ke["path"]):
            findings.append({
                "section": "kickoff_endpoint",
                "id": "type.path",
                "severity": "error",
                "message": "kickoff_endpoint.path MUST be a non-empty string",
            })
        if not _is_nonempty_str(ke["response_key"]):
            findings.append({
                "section": "kickoff_endpoint",
                "id": "type.response_key",
                "severity": "error",
                "message": "kickoff_endpoint.response_key MUST be a non-empty string",
            })
        if not isinstance(ke["auth_required"], bool):
            findings.append({
                "section": "kickoff_endpoint",
                "id": "type.auth_required",
                "severity": "error",
                "message": "kickoff_endpoint.auth_required MUST be a bool",
            })

    return findings
