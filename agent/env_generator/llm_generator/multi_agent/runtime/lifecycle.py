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
_FIXED_KINDS = frozenset({"auth", "oauth", "infra", "spine"})


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
    """A business endpoint is one NOT on the fixed surface (kind unset/business)."""
    return endpoint_kind(rec) not in _FIXED_KINDS


def _status(rec: Mapping[str, Any]) -> str:
    return str((rec or {}).get("status") or "defined").lower()


# ── queries (the substrate for §6/§7 hub-query triggers) ──────────────────────
def business_endpoints(endpoints: Mapping[str, Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Non-deprecated BUSINESS endpoints from an ``registryhub.get_endpoints()`` map."""
    return [
        ep for ep in (endpoints or {}).values()
        if isinstance(ep, Mapping) and is_business(ep) and _status(ep) != "deprecated"
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
