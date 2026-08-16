"""Artifact lifecycle vocabulary + state queries (Phase B1).

Single source of truth for the contract-artifact lifecycles
(pipeline_process_design.md §1) and the read-only queries the verify/delivery
triggers key off (§6/§7: "is the milestone's implementation complete?" is a hub
QUERY, not a lane-finish-notify heuristic — that was the fragile ⚠2 path).

Pure functions: the state machine is plain data; the query helpers take the
already-loaded endpoints map (``registryhub.get_endpoints()``), never a hub handle.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping


# ── lifecycle state machines (§1): state -> legal next states ──────────────────
ENDPOINT_STATES: Dict[str, frozenset] = {
    "defined":      frozenset({"implementing", "deprecated"}),
    "implementing": frozenset({"implemented", "defined", "deprecated"}),
    "implemented":  frozenset({"revising", "deprecated"}),
    "revising":     frozenset({"implemented", "deprecated"}),
    "deprecated":   frozenset(),
}
TABLE_STATES: Dict[str, frozenset] = {
    "defined":     frozenset({"implemented", "deprecated"}),
    "implemented": frozenset({"revising", "deprecated"}),
    "revising":    frozenset({"implemented", "deprecated"}),
    "deprecated":  frozenset(),
}
PAGE_STATES: Dict[str, frozenset] = {
    "defined":      frozenset({"implementing", "deprecated"}),
    "implementing": frozenset({"implemented", "deprecated"}),
    "implemented":  frozenset({"revising", "deprecated"}),
    "revising":     frozenset({"implemented", "deprecated"}),
    "deprecated":   frozenset(),
}
PREDICATE_STATES: Dict[str, frozenset] = {
    "defined":  frozenset({"covered"}),
    "covered":  frozenset({"passing", "failing", "revising"}),
    "passing":  frozenset({"failing", "revising"}),
    "failing":  frozenset({"passing", "revising"}),
    "revising": frozenset({"covered", "passing", "failing"}),
}

_MACHINES: Dict[str, Dict[str, frozenset]] = {
    "endpoint": ENDPOINT_STATES,
    "table": TABLE_STATES,
    "page": PAGE_STATES,
    "predicate": PREDICATE_STATES,
}


def is_valid_transition(artifact: str, frm: str, to: str) -> bool:
    """True if ``frm -> to`` is a legal transition for ``artifact`` (one of
    endpoint/table/page/predicate). An idempotent re-assert (``frm == to``) is
    always allowed (registration is a merge-upsert)."""
    machine = _MACHINES.get(str(artifact).lower())
    if machine is None:
        return False
    frm = str(frm or "").lower().strip()
    to = str(to or "").lower().strip()
    if frm == to:
        return True
    return to in machine.get(frm, frozenset())


# ── endpoint kind (business vs the runtime-owned fixed surface) ────────────────
# #853: was a hand-listed copy of the same set, missing `control`/`control_plane`/`health`.
# Six modules re-listed this surface and all six omitted the same three. Imported, not re-listed.
from .kickoff.contract import FIXED_ENDPOINT_KINDS as _FIXED_KINDS


def endpoint_kind(rec: Mapping[str, Any]) -> str:
    """The endpoint's ``kind`` wherever it landed (top-level or under metadata)."""
    if not isinstance(rec, Mapping):
        return ""
    if rec.get("kind"):
        return str(rec["kind"]).lower()
    md = rec.get("metadata")
    if isinstance(md, Mapping) and md.get("kind"):
        return str(md["kind"]).lower()
    return ""


def is_business(rec: Mapping[str, Any]) -> bool:
    """A business endpoint is one NOT on the fixed surface (kind unset/business) AND not a
    framework-owned control-surface / auth / oauth PATH.

    The kind tag alone is not enough: a lane routinely DECLARES a control-surface endpoint
    (``/api/v1/tenants``, ``/api/v1/reset``, ``/api/v1/admin/init-tenant``) in its contract
    with NO kind, so it mis-classifies as business and gets REQUIRED — for implementation
    AND for business_chain COVERAGE — even though it is served by the control plane and the
    verifier can never chain it. outlook M2 wedged on exactly this: business_chain_api_coverage
    listed the spine endpoints as uncovered → 7 stuck cycles → abort. The path net excludes
    them regardless of the (missing) kind tag — it only ever REMOVES a framework-owned path
    from the business set, never adds one, so no check can start requiring something new."""
    if endpoint_kind(rec) in _FIXED_KINDS:
        return False
    p = str(rec.get("path") or "")
    if p.startswith(("/auth/", "/oauth/", "/api/auth/", "/api/oauth/")) or p == "/health":
        return False
    try:
        from .kickoff.contract import is_control_surface_path
        if is_control_surface_path(p):
            return False
    except Exception:
        pass
    return True


def _status(rec: Mapping[str, Any]) -> str:
    return str((rec or {}).get("status") or "defined").lower()


# ── queries (the substrate for §6/§7 hub-query triggers) ──────────────────────
def business_endpoints(endpoints: Mapping[str, Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Non-deprecated BUSINESS endpoints from an ``registryhub.get_endpoints()`` map.

    Skips non-endpoint records: a real endpoint always has a ``path``. The
    json_store ``_meta`` bookkeeping key (version/last_modified_*) and any
    malformed/phantom record have no path — and since they carry no ``kind``,
    ``is_business`` would treat them as a business endpoint stuck at the default
    ``defined`` status, making ``all_business_endpoints_implemented`` False
    FOREVER (it would block the §6 validation_ready trigger). get_endpoints()
    strips _meta today, but every other consumer (delivery_gate, chain_executor,
    heal_pipeline) defends against it independently — this query must too, so a
    raw-dict caller can never silently wedge the validation trigger."""
    return [
        ep for ep in (endpoints or {}).values()
        if isinstance(ep, Mapping) and str(ep.get("path") or "").strip()
        and is_business(ep) and _status(ep) != "deprecated"
    ]


def endpoints_by_state(endpoints: Mapping[str, Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    """Group all endpoints by lifecycle state."""
    out: Dict[str, List[Mapping[str, Any]]] = {}
    for ep in (endpoints or {}).values():
        if isinstance(ep, Mapping):
            out.setdefault(_status(ep), []).append(ep)
    return out


def all_business_endpoints_implemented(endpoints: Mapping[str, Mapping[str, Any]]) -> bool:
    """True iff there is at least one business endpoint and EVERY business
    endpoint is ``implemented``. The core "backend implementation complete"
    signal for the §6 validation_ready trigger. Empty business contract → False
    (don't fire validation on nothing)."""
    biz = business_endpoints(endpoints)
    if not biz:
        return False
    return all(_status(ep) == "implemented" for ep in biz)


__all__ = [
    "ENDPOINT_STATES", "TABLE_STATES", "PAGE_STATES", "PREDICATE_STATES",
    "is_valid_transition", "endpoint_kind", "is_business",
    "business_endpoints", "endpoints_by_state", "all_business_endpoints_implemented",
]
