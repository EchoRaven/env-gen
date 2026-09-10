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
    "FIXED_ENDPOINT_KINDS",
    "is_control_surface_path",
    "control_surface_kind_for_path",
]


# ---------------------------------------------------------------------------
# Shared FIXED (runtime-owned) endpoint-kind surface — the ONE definition.
# ---------------------------------------------------------------------------
# The runtime-owned contract surface (registered by the orchestrator, served by
# the AS / control plane — NOT by lane business code). Every gate that "audits
# only business endpoints" MUST skip exactly this set, or it false-demotes /
# re-implements the fixed surface. Historically the definition had DIVERGED
# across files — ``backend_audit`` carried {auth,oauth,spine,control,health}
# (no ``infra``) while ``lifecycle`` / ``database_scaffold`` /
# ``cross_check_suite`` carried {auth,oauth,infra,spine} (no ``control``/
# ``health``). The control surface registers as ``kind='infra'``
# (see ``control_plane.CONTROL_SURFACE_ENDPOINTS``), so the ``backend_audit``
# variant (lacking ``infra``) repeatedly demoted the tenant/health control
# endpoints to ``regressed`` and hand-reimplemented them.
#
# This is now the single source of truth: a UNION covering BOTH naming
# conventions in use anywhere in the runtime (``infra`` is the kind the control
# plane actually carries today; ``control``/``control_plane``/``health`` are the
# forward-looking control-surface tags applied by ``control_surface_kind_for_path``
# and the reserved-path guard). All gates point here instead of redefining it.
# ``contract.py`` is a pure, import-safe leaf (no hub/runtime coupling), so every
# gate can import this without a cycle.
FIXED_ENDPOINT_KINDS: frozenset = frozenset({
    "auth", "oauth", "infra", "spine", "control", "control_plane", "health",
})


# Control-surface path classification — the deterministic tenant/health/admin
# surface the harness drives. Used to AUTO-TAG ``kind='control'`` at registration
# (part A) so a control endpoint can never be mistaken for a lane business
# endpoint, AND as a behavior-based skip net in the gates (path, not just the
# tag). Mirrors the reserved-path guard in ``registryhub.register_endpoint``.
def is_control_surface_path(path: Any) -> bool:
    """True iff ``path`` is part of the FIXED tenant/health/admin control plane.

    Matches (after canonicalization): ``/health``, ``/api/v1/admin/*`` (incl. the
    init-tenant endpoint ``/api/v1/admin/init-tenant``), ``/api/v1/reset``, and
    ``/api/v1/tenants*`` (collection + ``/api/v1/tenants/{tenant_id}``). Path-based
    (behavior), not kind-based — so it holds even when the ``kind`` tag is absent
    or wrong."""
    p = str(path or "").strip()
    if p:
        if not p.startswith("/"):
            p = "/" + p
        if len(p) > 1 and p.endswith("/"):
            p = p.rstrip("/") or "/"
    return (
        p in ("/health", "/api/v1/reset", "/api/v1/init-tenant")
        or p.startswith("/api/v1/admin/")
        or p == "/api/v1/admin"
        or p.startswith("/api/v1/tenants/")
        or p == "/api/v1/tenants"
    )


def control_surface_kind_for_path(path: Any) -> str:
    """Return ``"control"`` for a control-surface path (part A auto-tag), else ``""``.

    Helper so the registration/projection site can stamp ``metadata.kind='control'``
    for ``/api/v1/admin/*`` / ``/api/v1/reset`` / ``/api/v1/tenants*`` / init-tenant
    without re-deriving the path rule. ``"control"`` is a member of
    :data:`FIXED_ENDPOINT_KINDS`, so every gate that points there skips it."""
    return "control" if is_control_surface_path(path) else ""


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
                     → FastAPI ``{param}`` (PROPOSAL #29, slash-anchored); then every
                     ``{param}`` → ``{}`` so the id is param-NAME-agnostic (PROPOSAL #39 #1:
                     ``/notes/{id}`` ≡ ``/notes/{note_id}`` — one endpoint, not a phantom).
    """
    m = str(method or "").upper().strip()
    # Strip any QUERY STRING before identity (byte-identical with
    # registryhub.endpoint_id): ``/api/notes?tag=x`` ≡ the registered ``/api/notes``.
    p = str(path or "").split("?", 1)[0].strip()
    if p:
        if not p.startswith("/"):
            p = "/" + p
        if len(p) > 1 and p.endswith("/"):
            p = p.rstrip("/") or "/"
        p = re.sub(r"(?<=/):([A-Za-z_][A-Za-z0-9_]*)", r"{\1}", p)
    # PROPOSAL #39 (#1): param-NAME-agnostic identity — collapse {param}->{} so the same
    # route under a different param name resolves to ONE id (see registryhub.endpoint_id).
    p = re.sub(r"\{[^}]+\}", "{}", p)
    return f"{m} {p}"


_FIXED_SURFACE_CACHE_1202KE: Dict[tuple, Mapping[str, Any]] = {}


def fixed_surface_1202ke() -> Dict[tuple, Mapping[str, Any]]:
    """The endpoints the FRAMEWORK itself fixes, keyed ``(METHOD, path)``.

    Derived from the framework's own two declarations — never a literal copy — so a build
    that drops the OAuth AS or the control plane simply contributes nothing here, the same
    discipline `_CONTROL_PLANE_PUBLIC` follows in chain_executor.
    """
    if _FIXED_SURFACE_CACHE_1202KE:
        return _FIXED_SURFACE_CACHE_1202KE
    # Resolved on FIRST USE, not at import: this module is imported from the runtime package
    # that owns `oauth_scaffold`, and an import-time resolution would make that cycle load-order
    # dependent. The two declarations are literals, so the answer cannot change within a run.
    out: Dict[tuple, Mapping[str, Any]] = {}
    for mod, name in (("..oauth_scaffold", "AS_CONTRACT_ENDPOINTS"),
                      ("..control_plane", "CONTROL_SURFACE_ENDPOINTS")):
        try:
            import importlib
            eps = getattr(importlib.import_module(mod, __package__), name, None) or []
        except Exception:  # pragma: no cover - a partial build must not break kickoff
            continue
        for ep in eps:
            if not isinstance(ep, Mapping):
                continue
            m, path = ep.get("method"), ep.get("path")
            if isinstance(m, str) and isinstance(path, str):
                out[(m.upper(), path.rstrip("/") or "/")] = ep
    _FIXED_SURFACE_CACHE_1202KE.update(out)
    return out


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

    kwargs: Dict[str, Any] = {
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
    # #1202ke: the FUNNEL half of the rule. `_normalize_backend_endpoints_for_reconcile`
    # applies the same authority to the DRAFT, but only on the reconcile path -- a draft that
    # states `auth_required: true` for `/auth/login` outright is valid to `roadmap_validator`,
    # never reaches reconcile, and would sail through. Every kickoff endpoint passes HERE, so
    # this is where the ledger is actually protected; both call `fixed_surface_1202ke()` so
    # there is one implementation of the rule, not two that can drift (#1202gt/gu/gw).
    _fx = fixed_surface_1202ke().get(
        (str(ke["method"]).upper(), str(ke["path"]).rstrip("/") or "/"))
    if _fx is not None:
        kwargs["auth_required"] = bool(_fx.get("auth_required", False))
    # Part A: AUTO-TAG the fixed tenant/health/admin control surface as
    # ``kind='control'`` (a member of FIXED_ENDPOINT_KINDS) so it can never be
    # audited as a lane business endpoint and get demoted/hand-reimplemented.
    # Path-based (behavior), so it holds regardless of what the drafter put in
    # ``kind``. An EXPLICIT fixed-surface kind already on the KickoffEndpoint
    # (auth/oauth/infra/spine/...) is preserved verbatim — only an untagged /
    # business-looking control-path endpoint is reclassified.
    _ctrl_kind = control_surface_kind_for_path(ke["path"])
    if _ctrl_kind:
        _existing_kind = str(ke.get("kind") or "").strip().lower()
        if _existing_kind not in FIXED_ENDPOINT_KINDS:
            kwargs["kind"] = _ctrl_kind
        elif _existing_kind:
            kwargs["kind"] = _existing_kind
    elif _is_nonempty_str(ke.get("kind")):
        # Pass through any caller-declared kind unchanged (no silent drop).
        kwargs["kind"] = str(ke["kind"]).strip().lower()
    return kwargs


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
