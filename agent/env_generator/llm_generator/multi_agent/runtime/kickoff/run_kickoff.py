"""Kickoff coordinator — three pure-orchestration entry points.

WHY
---
Charter §5 + §8 + ``docs/plan_kickoff_refactor.md`` require the
orchestrator's lane to wake up on a ``kickoff_complete`` event rather
than to hand-roll the kickoff meeting itself. This module is the
single ``runtime.kickoff`` package entry point that owns the
mechanics, so ``orchestrator.py`` stays at one call site (charter §8
"orchestrator wire is ONE call site, ideally a single import + one
function call").

Three pure-orchestration functions wire the package's existing
helpers (``ready_set``, ``cross_check_suite``, ``arbitration_table``,
``roadmap_validator``, ``contract``) to the live ``hubs`` registry::

    start_kickoff(...)     -> opens the meeting + fans-out kickoff_request
    try_synthesize(...)    -> polled by orchestrator; returns
                              awaiting / conflict / validation_failed / ready
    finalize_kickoff(...)  -> registers endpoints + tables + tasks,
                              persists predicates, closes the meeting,
                              and emits the kickoff_complete event

Closed-by-construction discipline (mirrors sibling kickoff helpers):
  * Required arguments are validated at the function boundary —
    empty values raise ``ValueError`` with no phantom defaults.
  * Each helper short-circuits on the first failure and returns a
    structured ``SynthesisResult`` / handle / receipt dict the caller
    can pattern-match without re-parsing free-form strings.
  * No LLM call, no file I/O, no hidden state — every external
    coupling is an explicit ``hubs.<name>.<method>`` call so a unit
    test can mock the hub registry wholesale.

The decision shape that ``try_synthesize`` reads from
``meeting.metadata["decisions"]`` is the contract this module pins:

    {
      "section":  "backend" | "frontend" | "verifier",
      "agent":    str,        # the recording agent_id
      "content":  Mapping,    # section-specific structured draft
      "recorded_by": str,     # injected by workhub.add_meeting_decision
      "recorded_at": float,   # injected by workhub.add_meeting_decision
      # ...extra fields preserved + ignored
    }

The ``content`` sub-mapping shape per section mirrors
``cross_check_suite``'s extractors (it is the SAME shape — by
construction those extractors stay decoupled from this synthesizer).
Round 8e.1: design merged into frontend, so frontend now owns the
former design fields (user_flows, feature_inventory, done_def, auth,
ui_pages) IN ADDITION to its native screens field.

  * "backend":   {"api_endpoints": [KickoffEndpoint, ...],
                  "data_model": {"tables": [...]}}
  * "frontend":  {"ui_pages": [...], "user_flows": [...],
                  "feature_inventory": {...}, "done_def": [...],
                  "auth": {...}, "screens": [...],
                  "reference_image_manifest": [...]}
  * "verifier":  {"predicates": [...]}

Any agent may submit MULTIPLE decisions during the meeting; the
synthesizer uses the LAST decision per (section, agent) pair so
revisions arbitrated via ``arbitration_table.resolve_conflict``
overwrite the original draft.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .arbitration_table import resolve_conflict
from .contract import normalize_to_registryhub_endpoint
from .cross_check_suite import (
    run_cross_checks,
    reconcile_check_registry,
    _param_agnostic,
)
from .roadmap_validator import validate_roadmap
# Round 8h refactor: schema-tolerance helpers consolidated; aliases
# preserve the private names this module's call sites have used.
from .schema_tolerance import (
    api_call_key as _api_call_key,
    augment_drafts_for_coverage as _augment_drafts_for_coverage,
    endpoint_key as _endpoint_key,
    ensure_critical_flow_coverage as _ensure_critical_flow_coverage,
    extract_backend_endpoints as _extract_backend_endpoints,
    extract_frontend_screens as _extract_frontend_screens,
    normalize_auth_shape as _normalize_auth_shape,
    normalize_endpoint_response_shapes as _normalize_endpoint_response_shapes,
    normalize_feature_inventory as _normalize_feature_inventory,
    normalize_task_entries as _normalize_task_entries,
    pick_feature_inventory as _pick_feature_inventory,
    synthesize_predicates_from_contract as _synthesize_predicates_from_contract,
    synthesize_task_tree as _synthesize_task_tree,
)

__all__ = [
    "EXPECTED_SECTIONS",
    "SynthesisResult",
    "KICKOFF_POLL_INTERVAL_SEC",
    "KICKOFF_TIMEOUT_SEC",
    "start_kickoff",
    "try_synthesize",
    "finalize_kickoff",
    "synthesize_fallback",
]


# Driver constants — the Python coordinator on the orchestrator side
# polls try_synthesize on this cadence and aborts the run with a
# kickoff_failed event if T=KICKOFF_TIMEOUT_SEC elapses without a ready
# synthesis. These are module-level so tests can monkey-patch them
# without touching orchestrator.py.
KICKOFF_POLL_INTERVAL_SEC: float = 5.0
KICKOFF_TIMEOUT_SEC: float = 1200.0
# PROPOSAL #28 (C-recovery): a FAST stall escape so a lane that can never emit a
# clean section (e.g. Gemini re-mangling its draft to {auth:-1}) does not pin the
# whole run in phase=initial for the full 1200s. When NO new attendee records a
# substantive section for KICKOFF_INITIAL_STALL_POLLS consecutive polls AND at
# least KICKOFF_INITIAL_STALL_MIN_SEC has elapsed, the driver finalizes via the
# EXISTING _kickoff_fallback_or_reconcile (which synthesizes from whatever WAS
# recorded). Grace before the first stall-check leaves honest-but-slow kickoffs
# alone; the no-progress window distinguishes "stuck" from "still trickling in".
KICKOFF_INITIAL_STALL_MIN_SEC: float = 240.0
KICKOFF_INITIAL_STALL_POLLS: int = 24  # × 5s poll = 120s of no new substantive section


# v2 vocabulary (round 8e.1) — every kickoff meeting expects ONE
# decision per section from the agent that owns it. Round 8e.1 merged
# design into frontend, so the section count dropped 4 → 3 and the
# ui_pages_vs_user_flows cross-check disappeared (both fields now
# live in frontend, intra-section). Keep this tuple in sync with the
# three remaining cross-check extractors in cross_check_suite.py
# (_extract_api_vs_frontend, _extract_api_vs_data_model,
# _extract_test_strategy_coverage).
EXPECTED_SECTIONS: tuple = ("backend", "frontend", "verifier")


# SynthesisResult is a plain dict (mirrors sibling-module convention
# in contract.py + roadmap_validator.py — no TypedDict / dataclass
# dependency for a free-form return shape):
#
#   {
#     "status":     "awaiting" | "conflict" | "validation_failed" | "ready",
#     # populated per status:
#     "missing":    [str, ...],                  # status="awaiting"
#     "findings":   [Mapping, ...],              # status in {conflict,
#                                                #            validation_failed}
#     "revisers":   {agent_id: [finding, ...]},  # status="conflict"
#     "contract":   Mapping,                     # status="ready"
#     "task_tree":  [Mapping, ...],              # status="ready"
#     "predicates": [Mapping, ...],              # status="ready"
#     "milestone_index": int,                    # always
#   }
SynthesisResult = Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers — small, pure, each enforcing one input rule.
# ---------------------------------------------------------------------------


def _require_nonempty_str(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"start_kickoff/finalize_kickoff: '{field}' MUST be a non-empty "
            f"string (no phantom default); got {value!r}"
        )


def _require_milestone_index(milestone_index: Any) -> None:
    if (
        not isinstance(milestone_index, int)
        or isinstance(milestone_index, bool)
        or milestone_index < 1
    ):
        raise ValueError(
            "milestone_index MUST be an int >= 1 "
            "(M1 is the walking skeleton, M2+ are vertical slices); "
            f"got {milestone_index!r}"
        )


def _require_attendees(attendees: Any) -> List[str]:
    if not isinstance(attendees, (list, tuple)) or not attendees:
        raise ValueError(
            "attendees MUST be a non-empty list of agent_ids "
            "(no phantom default)"
        )
    out: List[str] = []
    for idx, a in enumerate(attendees):
        if not isinstance(a, str) or not a.strip():
            raise ValueError(
                f"attendees[{idx}] MUST be a non-empty string; got {a!r}"
            )
        out.append(a)
    return out


def _summarise_requirements(requirements: Any) -> str:
    """Short, deterministic agenda blurb. Empty input -> empty string.

    The full requirements list is also persisted in metadata; this
    summary is just for the page title.
    """
    if isinstance(requirements, str):
        text = requirements.strip()
        return text[:200] + ("..." if len(text) > 200 else "")
    if isinstance(requirements, (list, tuple)):
        joined = " ; ".join(str(r).strip() for r in requirements if str(r).strip())
        return joined[:200] + ("..." if len(joined) > 200 else "")
    return ""


def _collect_drafts(
    decisions: List[Mapping[str, Any]],
    expected_sections: tuple = EXPECTED_SECTIONS,
) -> Dict[str, Mapping[str, Any]]:
    """Bucket decisions into the per-section drafts mapping.

    Last-write-wins per (section, recording_agent): a revising
    decision overwrites the original draft. Returns a mapping suitable
    for ``cross_check_suite.run_cross_checks`` (agent_id -> draft).

    Decisions whose ``section`` is outside the v1 vocabulary are
    skipped (they may be ad-hoc decisions unrelated to kickoff
    synthesis — e.g. tooling notes — and silently ignoring them is
    safer than dropping them on the floor with an error).
    """
    drafts: Dict[str, Mapping[str, Any]] = {}
    for d in decisions:
        if not isinstance(d, Mapping):
            continue
        section = d.get("section")
        if section not in expected_sections:
            continue
        content = d.get("content")
        if not isinstance(content, Mapping) or not content:
            # SHAPE TOLERANCE (2026-06-10): file-first authoring lands FLAT
            # decisions ({"section": "frontend", "ui_pages": [...]}) with no
            # "content" wrapper — a real gemini-authored section was read as
            # {} here and the facilitator escalated on a "missing" section
            # that was actually present and good. Treat the decision row's own
            # fields (minus bookkeeping keys) as the content.
            content = {k: v for k, v in d.items()
                       if k not in ("section", "kind", "recorded_by", "agent",
                                    "recorded_at", "milestone_index", "round")}
        # MERGE semantics (2026-06-11): a section may arrive in SEVERAL SMALL
        # decisions (gemini cannot reliably emit one giant structured payload —
        # measured: tiny calls succeed where big ones starve; round 16 died in
        # an 18-min reject loop). Lists CONCATENATE (deduped by id/whole-value),
        # scalars/dicts: later non-empty wins. Authoring in parts is now the
        # RECOMMENDED path, not an error.
        prev = drafts.get(section)
        if not isinstance(prev, dict):
            drafts[section] = dict(content)
            continue
        drafts[section] = _merge_section(dict(prev), content)
    return drafts


def _merge_section(merged: Dict[str, Any], content: Mapping[str, Any]) -> Dict[str, Any]:
    """One-level-deep section merge: lists concatenate (deduped via json_key),
    dicts recurse one level (so data_model.tables accumulates), scalars —
    later NON-EMPTY wins."""
    for k, v in content.items():
        pv = merged.get(k)
        if isinstance(v, list) and isinstance(pv, list):
            seen = {json_key(x) for x in pv}
            merged[k] = pv + [x for x in v if json_key(x) not in seen]
        elif isinstance(v, Mapping) and isinstance(pv, Mapping):
            merged[k] = _merge_section(dict(pv), v)
        elif v not in (None, "", [], {}):
            merged[k] = v
        elif k not in merged:
            merged[k] = v
    return merged


def json_key(x: Any) -> str:
    """Stable dedup key for merged list items (id field preferred)."""
    import json as _json
    if isinstance(x, Mapping) and x.get("id") is not None:
        return f"id:{x.get('id')}"
    try:
        return _json.dumps(x, sort_keys=True, default=str)
    except Exception:
        return str(x)


def _missing_attendees(
    decisions: List[Mapping[str, Any]],
    expected_attendees: List[str],
) -> List[str]:
    """Return attendees that have not yet recorded any decision.

    Quorum rule: every expected attendee must submit AT LEAST ONE
    decision (regardless of which section). Empty input ⇒ everyone
    missing.
    """
    submitted: set = set()
    for d in decisions:
        if not isinstance(d, Mapping):
            continue
        # Prefer ``agent`` (the original author) over ``recorded_by``
        # (which workhub fills in even for system-injected decisions).
        a = d.get("agent") or d.get("recorded_by")
        if isinstance(a, str) and a.strip():
            submitted.add(a)
    return [a for a in expected_attendees if a not in submitted]


def _read_meeting_decisions(hubs: Any, meeting_id: str) -> List[Mapping[str, Any]]:
    """Read decisions off the meeting page's metadata.

    ``workhub`` doesn't ship a dedicated ``get_meeting_decisions``
    helper; decisions are persisted on
    ``page.metadata["decisions"]`` by
    ``add_meeting_decision``. Read them straight off the store —
    that's the single source of truth, and re-reading guarantees we
    see the latest write.
    """
    workhub = hubs.workhub
    # Two callable shapes are tolerated so tests can mock either:
    # (a) ``workhub.get_meeting_decisions(meeting_id) -> list`` —
    #     preferred (gives the test author an obvious mock point),
    # (b) ``workhub.stores.documents.value()[meeting_id]`` — the live
    #     persistence path.
    getter = getattr(workhub, "get_meeting_decisions", None)
    if callable(getter):
        decisions = getter(meeting_id) or []
        return list(decisions)
    documents = workhub.stores.documents.value()
    document = documents.get(meeting_id) or {}
    meta = document.get("metadata") or {}
    return list(meta.get("decisions") or [])


# FIX #42 (#1 — guaranteed kickoff contract): the kickoff is the one place the
# LLM lanes NEGOTIATE the contract, and that negotiation occasionally produces
# NOTHING (a backend lane that drafts no endpoints/data_model → empty contract →
# roadmap_validator fails → 20-min timeout → abort). The user's spec (the
# ``--description``) already LISTS the endpoints + data-model deterministically, so
# extract them as a LAST-RESORT backstop: the contract can then never be empty,
# turning the kickoff from "negotiate from scratch" into "negotiate, else fall back
# to the spec". Pure-regex on the structured spec format; best-effort.
_DESC_ENDPOINT_RE = re.compile(
    r"^\s*[-*]?\s*(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s)]+)", re.IGNORECASE | re.MULTILINE
)
# #773: the description writes `- table: NAME: cols`; this expected `- NAME: cols`. With the
# optional `table:` prefix absent from the pattern, group(1) captured the literal word "table"
# and group(2) became "users: id, email, ..." — whose first column parses as `users:`, is not an
# identifier, and is dropped. The whole extraction then yields ZERO tables while endpoints (a
# separate regex) yield 17.
#
# r150's own milestone slice is the proof:
#
#     - table: my_list: id, profile_id, title_id
#     - table: ratings: id, profile_id, title_id, value
#     - table: continue_watching: id, profile_id, title_id, progress_seconds
#
#     extract_contract_from_description(slice) -> endpoints: 17, tables: 0
#
# The consumer is `_derive_missing_essential_sections`, whose docstring says "the milestone slice
# already LISTS the endpoints/tables ... so extract them" and which salvages a stalled BACKEND
# lane. It could never have salvaged a schema — only the endpoints — and nothing said so,
# because `tables: []` is indistinguishable from "the spec had no tables".
#
# Both forms accepted: the `table:` prefix is optional and non-capturing.
_DESC_TABLE_RE = re.compile(
    r"^\s*[-*]\s+(?:table\s*:\s*)?([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.+)$", re.MULTILINE
)


def _infer_sql_type(col: str) -> str:
    n = col.lower()
    if n == "id":
        return "serial primary key"
    if n.endswith("_id"):
        return "integer"
    if n.endswith("_at") or n in ("created_at", "updated_at", "timestamp"):
        return "timestamptz default now()"
    if n.startswith("is_") or n.endswith("_flag") or n in ("active", "enabled"):
        return "boolean default false"
    if n.endswith("_count") or n in ("count", "quantity", "amount", "price"):
        return "integer"
    return "text"


def _canonical_response_key(method: Any, path: Any) -> str:
    """PROPOSAL #46: the CANONICAL response envelope key the route_projector
    actually emits — ``item`` (single) or ``items`` (collection).

    The projector hardcodes ``{"items": [...]}`` for collection reads and
    ``{"item": {...}}`` for single/mutating routes and IGNORES any other declared
    key; the delivery gate ``noncanonical_business_response_keys`` then HARD-BLOCKS
    a business endpoint whose declared ``response_key`` isn't ``item``/``items``.
    The legacy ``_derive_response_key*`` returned the last PATH SEGMENT
    (``/api/notes/{id}`` → ``"notes"``) — a resource name no consumer reads, which
    the gate rightly rejected → a permanent, remediation-less delivery block
    (smoke-notes 2026-06-19: ``GET/PUT/DELETE /api/notes/{id}`` got
    ``response_key="notes"`` → never delivered).

    Single (``item``) when the route is NOT a plain collection read: a non-GET
    (create/update/delete return the affected row), a ``/me`` route, or a path
    whose last segment is a parameter (``/{id}`` / ``:id``). Otherwise it's a
    collection GET → ``items``. Mirrors the reconciler heuristic + the projector's
    own emit, so the metadata matches the body BY CONSTRUCTION."""
    m = str(method or "GET").upper().strip()
    last = next((p for p in reversed(str(path or "").strip("/").split("/")) if p), "")
    is_param = (last.startswith("{") and last.endswith("}")) or last.startswith(":")
    single = m != "GET" or last == "me" or is_param
    return "item" if single else "items"


def _derive_response_key_from_path(path: str) -> str:
    parts = [p for p in str(path).strip("/").split("/")
             if p and not p.startswith("{") and not p.startswith(":")]
    return parts[-1] if parts else "data"


def extract_contract_from_description(description: str) -> Dict[str, Any]:
    """Deterministically extract ``{endpoints, tables}`` from the structured spec
    (``- METHOD /path`` lines + ``- table: col, col (constraint), ...`` lines).
    Best-effort; returns empty lists when the spec isn't in this shape."""
    desc = str(description or "")
    endpoints: List[Dict[str, Any]] = []
    seen_ep = set()
    for m in _DESC_ENDPOINT_RE.finditer(desc):
        method = m.group(1).upper()
        path = m.group(2).rstrip(".,;)")
        if (method, path) in seen_ep:
            continue
        seen_ep.add((method, path))
        endpoints.append({
            "method": method, "path": path,
            # PROPOSAL #46: canonical item/items for business (/api/); legacy
            # resource-name for control-plane (kind-exempt, must not be clobbered).
            "response_key": (_canonical_response_key(method, path)
                             if str(path).startswith("/api/")
                             else _derive_response_key_from_path(path)),
            "auth_required": True,
        })
    tables: List[Dict[str, Any]] = []
    seen_t = set()
    for m in _DESC_TABLE_RE.finditer(desc):
        name = m.group(1).strip().lower()
        cols: List[Dict[str, str]] = []
        for raw in m.group(2).split(","):
            cname = re.split(r"[\s(]", raw.strip(), 1)[0].strip().rstrip(".")
            if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", cname or ""):
                cols.append({"name": cname, "type": _infer_sql_type(cname)})
        # require a plausible table: >=2 columns and an 'id' (filters prose lines)
        if name in seen_t or len(cols) < 2 or not any(c["name"] == "id" for c in cols):
            continue
        seen_t.add(name)
        tables.append({"name": name, "columns": cols})
    return {"endpoints": endpoints, "tables": tables}


# Infra/spine tables that aren't user-facing list pages.
_FRONTEND_SKIP_TABLES = {
    "users", "user", "tenants", "tenant", "sessions", "session", "tokens", "token",
    "oauth_clients", "oauth_codes", "oauth_tokens", "auth", "migrations", "alembic_version",
}


def _frontend_page_from_resource(resource: str, apis_used: Optional[List[str]] = None) -> Dict[str, Any]:
    comp = "".join(w.capitalize() for w in re.split(r"[_\-]", resource) if w) + "Page"
    page: Dict[str, Any] = {
        "id": f"{resource}_page", "route": "/" + resource,
        "component": comp, "purpose": f"List and manage {resource}.",
    }
    if apis_used:
        page["apis_used"] = apis_used
    return page


def derive_frontend_pages_from_endpoints(
    endpoints: List[Mapping[str, Any]],
    tables: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Domain-agnostic ui_pages: a login page + one list page per collection-GET
    business endpoint (``GET /api/<resource>``, last segment not a param and not
    ``me``). Used to SALVAGE a kickoff whose frontend lane never authored a section
    in time (slow Gemini) — the synthesis only needs a frontend decision to clear
    quorum, and the implementation lane then builds these declared pages properly.
    When NO endpoints are extractable (e.g. a prose spec the line-regex can't parse),
    fall back to one page per business ``tables`` entry (skipping infra/spine tables)
    so the salvage isn't login-only. Empty-in → just the login page; no app-specific
    names."""
    pages: List[Dict[str, Any]] = [{
        "id": "login_page", "route": "/login", "component": "LoginPage",
        "purpose": "Authenticate the user (framework-owned auth surface).",
    }, {
        "id": "signup_page", "route": "/signup", "component": "SignupPage",
        "purpose": "Register a new user (framework-owned auth surface).",
    }]
    seen_routes = {"/login", "/signup"}
    _baseline = len(pages)  # auth pages; resource pages are appended past this
    for ep in endpoints or []:
        # tolerate both {method, path} dicts and "METHOD /path" strings (a lane's
        # declared backend draft may store endpoints in either shape).
        if isinstance(ep, str):
            parts = ep.strip().split(None, 1)
            if len(parts) != 2:
                continue
            method, path = parts[0].upper(), parts[1]
        elif isinstance(ep, Mapping):
            method = str(ep.get("method") or "GET").upper()
            path = str(ep.get("path") or "")
        else:
            continue
        if method != "GET":
            continue
        if not path.startswith("/api/"):
            continue
        segs = [p for p in path.strip("/").split("/") if p]
        last = segs[-1] if segs else ""
        is_param = (last.startswith("{") and last.endswith("}")) or last.startswith(":") or last == "me"
        if is_param or len(segs) < 2:  # /api/<resource> collection only
            continue
        resource = segs[-1]
        route = "/" + resource
        if route in seen_routes:
            continue
        seen_routes.add(route)
        pages.append(_frontend_page_from_resource(resource, [f"GET {path}"]))
    # Fallback: no endpoint-derived pages (prose spec) → one page per business table.
    if len(pages) == _baseline and tables:
        for t in tables:
            name = (t.get("name") if isinstance(t, Mapping) else str(t or "")).strip().lower()
            if (not name or name in _FRONTEND_SKIP_TABLES
                    or ("/" + name) in seen_routes):
                continue
            seen_routes.add("/" + name)
            pages.append(_frontend_page_from_resource(name, [f"GET /api/{name}"]))
    return pages


# Columns that attribute a row to the authenticated caller — a table carrying one
# is "owned per user" (route_projector uses the same notion to authorize writes).
_OWNER_FK_COL_NAMES = frozenset({
    "user_id", "author_id", "owner_id", "creator_id", "created_by",
    "sender_id", "uploaded_by", "posted_by", "account_id", "from_user_id",
})

# HIGH-PRECISION phrases that signal per-user-PRIVATE reads (each user sees only
# their OWN rows). Deliberately excludes bare "your X" — public-feed UI copy uses
# it too. A public-feed goal ("see everyone's posts", "a shared/public feed")
# matches NONE of these.
_PRIVATE_GOAL_PHRASES = (
    "only see their own", "only sees their own", "see only their own",
    "only view their own", "only their own", "only see your own",
    "only sees your own", "see only your own", "scoped to the authenticated user",
    "scoped to the current user", "scoped to the logged-in user", "scoped per user",
    "owned per user", "owned by the user", "private to each user",
    "private to the user", "each user only sees", "each user can only see",
    "users can only see their", "users only see their", "per-user private",
    "only the owner can", "visible only to the owner",
)
_PRIVATE_GOAL_RE = re.compile(
    r"each\s+user[^.\n]{0,40}\b(own|only)\b"
    r"|users?\s+can\s+only\s+(see|view|access)[^.\n]{0,30}\bown\b"
    r"|only\s+(see|view|access)\s+(their|your|his|her|its)\s+own",
    re.IGNORECASE,
)


def _goal_implies_per_user_private(description: Any) -> bool:
    """True when the GOAL explicitly states per-user-PRIVATE reads (each user sees
    only their OWN rows). High-precision: a public-feed goal does NOT match. Used
    ONLY as a deterministic BACKSTOP when the lane did not author owner_scoped_reads
    (which is LLM-authored and demonstrably inconsistent run-to-run)."""
    text = description if isinstance(description, str) else ""
    if not text and description:
        try:
            text = " ".join(str(x) for x in description)
        except Exception:
            return False
    low = text.lower()
    if any(p in low for p in _PRIVATE_GOAL_PHRASES):
        return True
    return bool(_PRIVATE_GOAL_RE.search(low))


def _table_has_owner_fk(table: Mapping[str, Any]) -> bool:
    """The table is owned-per-user: a column names the actor (user_id/author_id/…)
    or FKs to ``users``. The SAME signal route_projector keys row-ownership on."""
    cols = table.get("columns") if isinstance(table, Mapping) else None
    for c in (cols or []):
        if not isinstance(c, Mapping):
            continue
        if str(c.get("name") or "").strip().lower() in _OWNER_FK_COL_NAMES:
            return True
        ref = str(c.get("references") or c.get("fk") or c.get("foreign_key") or "").strip().lower()
        if ref == "users" or ref.startswith("users.") or ref.startswith("users("):
            return True
    return False


def _build_contract(
    drafts: Mapping[str, Mapping[str, Any]], description: str = "",
) -> Dict[str, Any]:
    """Synthesize the contract block roadmap_validator expects.

    Pulls endpoints + data_model from backend's draft and auth from
    frontend's draft (round 8e.1: design merged into frontend; frontend
    is now the auth authority since it owns user_flows that auth-gate
    against). Backend's draft may still carry an auth sketch for
    endpoint-level annotations — kept as fallback so a partial frontend
    section can still produce a complete contract.

    FIX #42: if the lanes drafted no endpoints/data_model (kickoff variance),
    backstop from the deterministic spec extraction so the contract is NEVER empty.
    """
    backend = drafts.get("backend") or {}
    frontend = drafts.get("frontend") or {}
    # Round 8h Fix #N: real-LLM backend writes the list under
    # ``endpoints`` (sibling: smoke #9-octavus / #9-undecimus) while
    # this synthesizer historically only read ``api_endpoints``. The
    # extractor silently returned [] → roadmap_validator reported
    # "contract.endpoints malformed/missing" → facilitator escalated
    # (smoke #9-undecimus round-2 verdict 2026-06-03 03:31). Accept
    # both keys here, matching cross_check_suite._extract_backend_endpoints
    # (round 8h Fix #J).
    endpoints = list(backend.get("api_endpoints") or backend.get("endpoints") or [])
    data_model = backend.get("data_model") or {}
    # FIX #42: deterministic spec backstop when the lanes produced an empty contract.
    _dm_tables = data_model.get("tables") if isinstance(data_model, Mapping) else None
    if description and ((not endpoints) or not _dm_tables):
        _extracted = extract_contract_from_description(description)
        if not endpoints and _extracted["endpoints"]:
            endpoints = _extracted["endpoints"]
        if not _dm_tables and _extracted["tables"]:
            data_model = {"tables": _extracted["tables"]}
    # Mechanism #38: coerce endpoint.response/response.tables to the
    # validator's canonical shape — malformed shapes are framework-repairable
    # and must never wedge the meeting in status=conflict (round 31 M3).
    endpoints = _normalize_endpoint_response_shapes(endpoints)
    ui_components = list(frontend.get("ui_components") or [])
    # Mechanism #54 (round 34 found the gap): the frontend's declared
    # ui_pages/user_flows never reached the CONTRACT — so synthesize_task_tree
    # never emitted impl.page/impl.component/validate.ui_* tasks in any real
    # run (unit tests passed by constructing the contract directly).
    ui_pages = list(frontend.get("ui_pages") or frontend.get("screens") or [])
    user_flows = list(frontend.get("user_flows") or [])
    # UI-LAYER CLOSURE (user design 2026-06-11): pages must compose REGISTERED
    # components; components must call REGISTERED APIs. Enforced by
    # AUTO-ENROLLMENT (not rejection — rejection would wedge the meeting):
    #   a. a page referencing an undeclared component id → register a stub
    #      ui_component (defined, empty) so the reference resolves and the
    #      lifecycle rollup has a real node to audit;
    #   b. an api in any apis_used that is NOT in the contract → APPEND it
    #      (source=auto_from_ui_declaration) — the skeleton generates it,
    #      exactly like the dangling-frontend-call reconcile.
    declared_ids = {str(c.get("id") or "").strip()
                    for c in ui_components if isinstance(c, Mapping)}
    # FIELD-SEMANTICS GUARD (round 36 found this): `component` (singular) is the
    # page's ROOT component (src/pages/<Name>.jsx); `components` (plural) lists
    # REUSABLE child components (src/components/<Name>.jsx). The frontend often
    # conflates them — declaring component='' and components=['LoginPage'] where
    # LoginPage IS the root. A single `components` entry with no `component` is
    # the root, not a child: promote it so the audit looks in src/pages/ and the
    # monitor doesn't show a phantom "unregistered component".
    for pg in ui_pages:
        if isinstance(pg, Mapping):
            comps = [str(c).strip() for c in (pg.get("components") or []) if str(c).strip()]
            if not str(pg.get("component") or "").strip() and len(comps) == 1:
                pg["component"] = comps[0]
                pg["components"] = []
    for pg in ui_pages:
        if not isinstance(pg, Mapping):
            continue
        for ref in (pg.get("components") or []):
            ref_s = str(ref).strip()
            if ref_s and ref_s not in declared_ids:
                declared_ids.add(ref_s)
                ui_components.append({"id": ref_s,
                                      "source": "auto_from_page_reference"})
    def _known_eps():
        out = set()
        for ep in endpoints:
            if isinstance(ep, Mapping):
                m = str(ep.get("method") or "GET").upper()
                pth = str(ep.get("path") or "")
                out.add((m, pth.rstrip("/")))
        return out
    _known = _known_eps()
    for src_list in (ui_pages, ui_components):
        for item in src_list:
            if not isinstance(item, Mapping):
                continue
            for a in (item.get("apis_used") or []):
                parts = str(a).strip().split()
                if len(parts) == 2:
                    m, pth = parts[0].upper(), parts[1].rstrip("/")
                elif len(parts) == 1 and parts[0].startswith("/"):
                    m, pth = "GET", parts[0].rstrip("/")
                else:
                    continue
                if not pth.startswith("/api/") or (m, pth) in _known:
                    continue
                _known.add((m, pth))
                endpoints.append({"method": m, "path": pth,
                                  "auth_required": True,
                                  "response_key": _canonical_response_key(m, pth),
                                  "source": "auto_from_ui_declaration"})
    auth = frontend.get("auth") or backend.get("auth") or {}
    auth_dict = dict(auth) if isinstance(auth, Mapping) else {}
    # Round 8h Fix #R: roadmap_validator requires contract.auth.required
    # to be a literal boolean. Real-LLM auth dicts sometimes write the
    # field as a string ("true"/"yes") or omit it entirely. Coerce
    # here so the validator passes; defaults to True for any auth
    # block that names a model (the safer default for protected
    # endpoints — if the LLM meant "no auth", it wouldn't have written
    # an auth block in the first place).
    auth_dict = _normalize_auth_shape(auth_dict, endpoints)
    # CONTRACT-SHAPE FLOOR (round 37 death): roadmap_validator hard-fails on
    # any endpoint missing response_key/auth_required and the reconcile could
    # not converge (1200s timeout). response_key is fully derivable from the
    # path and auth defaults True — coerce EVERY endpoint here so the validator
    # never blocks on a recoverable shape gap, regardless of source (backend
    # inline decision, typed declare, or UI auto-enrollment).
    for _ep in endpoints:
        if isinstance(_ep, Mapping):
            # PROPOSAL #46: for BUSINESS endpoints (/api/, the only ones the projector
            # projects + the gate checks) override ABSENT *and* non-canonical
            # response_keys with the projector's canonical envelope key (item/items) —
            # a resource-name key like "notes" no consumer reads and the gate
            # hard-blocks. Control-plane (/auth,/oauth,/health) is kind-exempt from the
            # gate and clobbering its key would cause false contract-drift, so it keeps
            # the legacy fill-when-absent (never overridden).
            _rk = _ep.get("response_key")
            _epath = str(_ep.get("path") or "")
            if _epath.startswith("/api/"):
                if not (isinstance(_rk, str) and _rk in ("item", "items")):
                    _ep["response_key"] = _canonical_response_key(_ep.get("method"), _epath)
            elif not (isinstance(_rk, str) and _rk.strip()):
                _ep["response_key"] = _derive_response_key_from_path(_epath)
            if not isinstance(_ep.get("auth_required"), bool):
                _ep["auth_required"] = True
    # TABLE-COLUMNS FLOOR (round 38 systematic pass): roadmap_validator hard-
    # fails on a table with empty columns. An inline-declared table can omit
    # columns; every table has at least an id PK, so floor it (recoverable
    # shape gap). A table with NO name is meaningless → drop it rather than
    # invent one (don't manufacture phantom tables).
    _dm = data_model if isinstance(data_model, Mapping) else {}
    _tbls = _dm.get("tables") if isinstance(_dm.get("tables"), list) else None
    if _tbls is not None:
        _kept = []
        for _t in _tbls:
            if not (isinstance(_t, Mapping) and str(_t.get("name") or "").strip()):
                continue  # nameless table → drop, never floor a phantom
            _cols = _t.get("columns")
            if not (isinstance(_cols, list) and any(
                    isinstance(c, Mapping) and str(c.get("name") or "").strip()
                    for c in _cols)):
                _t = dict(_t)
                _t["columns"] = [{"name": "id", "type": "integer", "pk": True}]
            # READ-VISIBILITY BACKSTOP (deterministic; fills a GAP only). The per-table
            # owner_scoped_reads flag is LLM-authored at kickoff and demonstrably
            # INCONSISTENT across runs of the SAME app (smoke-notes: set in exp3, FORGOTTEN
            # in exp1/exp5 → a per-user-private app ships with leaking reads). When the lane
            # did NOT decide it AND the table is owned-per-user (owner FK to users) AND the
            # GOAL explicitly states per-user privacy, set it deterministically here. An
            # EXPLICIT lane decision (true OR false) is always respected — this never
            # overrides, only fills the gap. High-precision goal match → no public-feed
            # false-positive (a public feed's goal matches none of the private phrases).
            if ("owner_scoped_reads" not in _t
                    and _table_has_owner_fk(_t)
                    and _goal_implies_per_user_private(description)):
                _t = dict(_t)
                _t["owner_scoped_reads"] = True
            _kept.append(_t)
        data_model = {**_dm, "tables": _kept}
    return {
        "endpoints": endpoints,
        "data_model": dict(data_model) if isinstance(data_model, Mapping) else {},
        "auth": auth_dict,
        "ui_components": ui_components,
        "ui_pages": ui_pages,
        "user_flows": user_flows,
    }


# Round 8h refactor: _normalize_task_entries / _normalize_feature_
# inventory / _normalize_auth_shape moved to schema_tolerance. The
# import aliases at the top of this module preserve the private names.


def _build_roadmap(
    drafts: Mapping[str, Mapping[str, Any]],
    milestone_index: int,
    description: str = "",
    registered_endpoints: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble the validator-shaped roadmap snapshot from agent drafts.

    Round 8e.1: design+frontend merged — frontend owns task_tree,
    done_def, feature_inventory (formerly design's responsibility).

    Round 8h Fix #N: real-LLM kickoffs reveal the documented-vs-actual
    shape drift this used to assume away:
      * Frontend's prompt-emitted ``feature_inventory`` is a flat
        per-feature dict ``{auth_login: {...}, post_compose: {...}}``
        rather than the validator-shaped ``{entities, flows}`` dict.
        Backend writes the validator shape under its OWN
        feature_inventory. Prefer whichever source has the
        validator-shape keys (smoke #9-undecimus, 2026-06-03 03:31).
      * Frontend frequently emits an empty ``task_tree`` (prompt
        suggests it but doesn't enforce). Synthesize a minimal
        task_tree from the contract endpoints + data_model tables
        when frontend's is empty so finalize_kickoff has dispatchable
        work — same closed-by-construction principle as Fix #A/C/D.
    """
    backend = drafts.get("backend") or {}
    frontend = drafts.get("frontend") or {}
    verifier = drafts.get("verifier") or {}
    contract = _build_contract(drafts, description)
    task_tree = list(frontend.get("task_tree") or [])
    if not task_tree:
        task_tree = _synthesize_task_tree(contract)
    # Round 8h Fix #R (extended): normalize EVERY task entry — whether
    # author-written or synthesized — to have the validator-required
    # ``depends_on`` (list) and ``status`` (str) fields. Real-LLM
    # frontends author tasks with various missing-field shapes that
    # roadmap_validator rejects as "task entries missing required
    # depends_on and status fields" (smoke #9-quindecimus / #17).
    task_tree = _normalize_task_entries(task_tree)
    predicates = list(verifier.get("predicates") or [])
    # Round 8h Fix #P: smoke #9-tertius-decimus (2026-06-03 05:08)
    # caught verifier consistently authoring 1 predicate while there
    # were 4 critical user_flows in the requirements. test_strategy_
    # coverage flagged the gap, facilitator dispatched verifier-only
    # revisions, verifier added 1 more predicate per round, escalated
    # at round 3. Closed-by-construction: append stub api_smoke
    # predicates for every critical user_flow that lacks coverage,
    # marking them ``source="auto_coverage"`` so the audit trail
    # surfaces under-authoring without blocking finalize.
    predicates = _ensure_critical_flow_coverage(
        predicates, frontend.get("user_flows") or [],
    )
    # PREDICATE FLOOR (2026-06-11, round 24 M4 abort): roadmap_validator hard-
    # requires non-empty acceptance_predicates, but a milestone where the
    # verifier under-authors AND the frontend declares no user_flows (small
    # slices: follow/DM milestones) left predicates=[] → synthesis
    # validation_failed in an unwinnable loop → 1200s timeout → run abort.
    # The floor is the criterion the runtime ALREADY enforces deterministically.
    if not predicates:
        # FIX #561: at MILESTONE 2+, a no-net-new-predicate slice EXERCISES the
        # cumulative contract (the endpoints M1..M(i-1) already registered).
        # Synthesize an api_smoke predicate per registered BUSINESS endpoint —
        # the acceptance criteria assert the reused cumulative surface still
        # passes — instead of the single generic floor. Milestone 1 (the walking
        # skeleton) has no cumulative contract yet, so it keeps the generic floor
        # → the single-milestone / M1 path stays byte-identical.
        _cumulative_preds = (
            _synthesize_predicates_from_contract(registered_endpoints)
            if int(milestone_index or 1) >= 2 else []
        )
        if _cumulative_preds:
            predicates = _cumulative_preds
        else:
            predicates = [{
                "id": "auto_default_api_smoke",
                "kind": "api_smoke",
                "description": ("every registered business endpoint passes the "
                                "deterministic api_smoke suite (boot, auth, "
                                "reachability, response shapes, write persistence)"),
                "source": "auto_default",
            }]
    # PREDICATE NORMALIZATION (2026-06-11 round 26): roadmap_validator's
    # canonical shape is {"id", "flow": str, "form": {"kind": <vocab>}} — but
    # the authoring surfaces (declare tools, chunked decisions, the floor
    # above) produce {"id", "kind", "flow_id"/none, "description"}. Coerce
    # EVERY predicate to the canonical shape here so the synthesis never
    # dies on shape drift (round 26: 'predicate.flow MUST be a non-empty
    # string' looped M1 to abort).
    _flow_ids = [str(f.get("id")) for f in (frontend.get("user_flows") or [])
                 if isinstance(f, Mapping) and f.get("id")]
    _default_flow = _flow_ids[0] if _flow_ids else "general"
    _VOCAB = {"api_smoke", "ui_flow", "sql_check", "predicate_dsl"}
    _normed = []
    for i, pred in enumerate(predicates):
        if not isinstance(pred, Mapping):
            continue
        q = dict(pred)
        q.setdefault("id", f"predicate_{i}")
        flow = q.get("flow") or q.get("flow_id") or _default_flow
        q["flow"] = str(flow)
        form = q.get("form") if isinstance(q.get("form"), Mapping) else {}
        kind = (form.get("kind") or q.get("kind") or "api_smoke")
        if kind not in _VOCAB:
            kind = "api_smoke"
        q["form"] = {**form, "kind": kind}
        _normed.append(q)
    predicates = _normed
    # CONTRACT-SHAPE FLOOR (round 38 death): roadmap_validator hard-fails on an
    # empty done_def → validation_failed → 1200s kickoff timeout when reconcile
    # didn't run in time. done_def is a recoverable shape gap (generic done-
    # criteria apply to every app) — floor it HERE in the main synthesis path
    # so the FIRST validation passes, instead of relying on the late reconcile.
    # Mirrors the response_key floor in _build_contract. Same default text as
    # _normalize_roadmap_shape_for_reconcile so the two paths agree.
    done_def = [x for x in (frontend.get("done_def") or [])
                if isinstance(x, str) and x.strip()]
    if not done_def:
        done_def = [
            "All business endpoints implemented and reachable",
            "App boots cleanly in Docker",
            "Auth + core user flows pass smoke validation",
        ]
    roadmap: Dict[str, Any] = {
        "milestone_index": milestone_index,
        "contract": contract,
        "task_tree": task_tree,
        "acceptance_predicates": predicates,
        "done_def": done_def,
    }
    if milestone_index == 1:
        # M1 requires the feature inventory (charter §5 item 5).
        fi = _pick_feature_inventory(frontend, backend)
        # Round 8h Fix #R: synthesize entities + flows from upstream
        # signals when the picked feature_inventory is empty / wrong-
        # shaped. roadmap_validator demands non-empty entities + flows
        # at M1; real-LLM feature_inventories rarely satisfy that
        # exactly, so derive from contract.data_model.tables (entities)
        # and frontend.user_flows[*].id (flows).
        roadmap["feature_inventory"] = _normalize_feature_inventory(
            fi, contract, frontend,
        )
    return roadmap


# Round 8h refactor: _pick_feature_inventory / _synthesize_task_tree /
# _augment_drafts_for_coverage / _ensure_critical_flow_coverage moved
# to schema_tolerance. Aliases at top of module preserve private names.



def _conflict_from_finding(
    finding: Mapping[str, Any],
) -> Dict[str, Any]:
    """Translate one cross-check item into the arbitration conflict shape.

    ``cross_check_suite.run_cross_checks`` items look like::

        {"id": "api_vs_frontend", "status": "fail", "blockers": [...],
         "severity": "error", "offending_field": ...}

    The arbitration table needs::

        {"id": "<conflict_id>", "kind": "<check_id>",
         "agents": ["<agent_a>", "<agent_b>"]}

    We pin ``agents`` to the two principals from the matching
    ARBITRATION_TABLE row (backend/frontend for api_vs_frontend, etc).
    For unknown kinds the tiebreak fallback in resolve_conflict picks
    the alphabetically-first agent_id, so we pass every expected
    section as a candidate.
    """
    check_id = finding.get("id") or "unknown_check"
    # Map check_id -> agents to put on the conflict.
    # Round-8e.1: ui_pages_vs_user_flows dropped — both fields live
    # in frontend's section now, so cross-section consistency is
    # implicit (intra-section LLM coherence is design's job, not
    # the cross_check_suite's).
    section_for_check = {
        "api_vs_frontend": ["backend", "frontend"],
        "api_vs_data_model": ["backend"],
        "test_strategy_coverage": ["verifier"],
    }
    agents = section_for_check.get(
        check_id, list(EXPECTED_SECTIONS)
    )
    return {
        "id": f"conflict::{check_id}",
        "kind": check_id,
        "agents": agents,
        "detail": finding.get("blockers") or [],
        "offending_field": finding.get("offending_field"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def author_milestone_detail(
    hubs: Any,
    orch_agent: Any,
    milestone_index: int,
    *,
    raw_req: str = "",
    timeout_s: float = 240.0,
) -> str:
    """Run the orchestrator's KICKOFF-DETAIL turn for ``milestone_index``, returning
    the authored detail (or ``""`` to fall back to the rough slice).

    Fires a ``kickoff_detail_request`` to the orchestrator AGENT (it reviews the
    roadmap, may revise FUTURE phases, and sets THIS phase's detailed detail via the
    ``milestone_*`` tools — with its full system prompt + hub context), then AWAITS
    (bounded) until ``hubs.milestones`` reports the kickoff-detail TURN COMPLETE
    (``is_detail_authored``). Waiting for turn COMPLETION (not the first non-empty
    write) closes the double-author race: the handler may set the detail then refine
    it within the same turn, and only marks ``detail_authored`` in its finally block.
    NEVER hangs the run — the timeout is a hard safety cap; on timeout returns ``""``
    and the caller falls back to the rough slice."""
    import asyncio
    ms = getattr(hubs, "milestones", None)
    if ms is None or orch_agent is None:
        return ""  # no store / no orchestrator agent to author — caller uses the slice
    try:
        cur = ms.get_by_index(milestone_index) or ms.get_current()
    except Exception:
        cur = None
    if not isinstance(cur, dict):
        return ""
    mid = cur.get("id")
    if ms.is_detail_authored(mid):
        return str(cur.get("detail") or "")  # already authored (resume) — reuse
    try:
        hubs.eventhub.publish_event(
            source_hub="orchestrator",
            event_type="kickoff_detail_request",
            payload={"milestone_index": milestone_index, "milestone_id": mid,
                     "raw_requirements": str(raw_req or "")},
            recipients=["orchestrator"], priority="high", caller="orchestrator")
    except Exception:
        return ""
    # Bounded poll: the orchestrator handler (separate task) authors the detail +
    # may revise future phases, then marks the TURN complete (detail_authored) in its
    # finally block. This resolves on turn COMPLETION — not on the first non-empty
    # write — so a refined second write within the turn is never missed. asyncio.sleep
    # yields so the orchestrator task runs concurrently.
    waited, step = 0.0, 3.0
    while waited < timeout_s:
        await asyncio.sleep(step)
        waited += step
        try:
            if ms.is_detail_authored(mid):
                c = ms.get(mid)
                return str(c.get("detail") or "") if isinstance(c, dict) else ""
        except Exception:
            pass
    return ""  # timed out → caller falls back to the rough slice


def start_kickoff(
    hubs: Any,
    milestone_index: int,
    requirements: Any,
    attendees: List[str],
    agent: str = "orchestrator",
) -> Dict[str, Any]:
    """Open the meeting and fan-out the ``kickoff_request`` event.

    Returns a ``kickoff_handle`` dict the orchestrator polls with
    :func:`try_synthesize` until quorum + cross-checks are clean.

    Args:
        hubs: hub registry exposing ``hubs.workhub.create_meeting``
              and ``hubs.eventhub.publish_event``.
        milestone_index: 1-based milestone counter.
        requirements: list[str] | str — the raw requirement bundle to
                      ship in the kickoff_request event payload.
        attendees: list[str] of agent_ids that MUST attend.
        agent: caller identity (defaults to "orchestrator" since this
               is the orchestrator's entry point — no phantom default
               at lower layers).

    Returns:
        ``{meeting_id, milestone_index, expected_attendees,
            started_at, phase}``.

    Raises:
        ValueError: on missing/empty agent, attendees, or a malformed
            milestone_index.
    """
    _require_nonempty_str(agent, "agent")
    _require_milestone_index(milestone_index)
    expected_attendees = _require_attendees(attendees)

    requirements_summary = _summarise_requirements(requirements)
    if isinstance(requirements, (list, tuple)):
        requirements_list = list(requirements)
    elif isinstance(requirements, str):
        requirements_list = [requirements] if requirements.strip() else []
    else:
        requirements_list = []

    # Step 1: create the meeting page.
    agenda = f"M{milestone_index} kickoff: {requirements_summary}".strip(": ")
    meeting = hubs.workhub.create_meeting(
        agenda=agenda,
        attendees=expected_attendees,
        kind="kickoff",
        milestone_index=milestone_index,
        metadata={
            "requirements": requirements_list,
            "phase": "open",
        },
        agent=agent,
    )
    if not isinstance(meeting, Mapping) or "id" not in meeting:
        # workhub.create_meeting raises on bad input; an error dict
        # here would be a hub bug — surface it as a ValueError so the
        # orchestrator doesn't silently proceed with a broken handle.
        raise ValueError(
            f"create_meeting returned an unexpected payload: {meeting!r}"
        )
    meeting_id = meeting["id"]

    # Step 2: broadcast the kickoff_request event.
    hubs.eventhub.publish_event(
        source_hub="orchestrator",
        event_type="kickoff_request",
        payload={
            "meeting_id": meeting_id,
            "milestone_index": milestone_index,
            "requirements": requirements_list,
            "expected_sections": list(EXPECTED_SECTIONS),
        },
        recipients=expected_attendees,
        priority="high",
        caller=agent,
    )

    started_at = time.time()
    return {
        "meeting_id": meeting_id,
        "milestone_index": milestone_index,
        "expected_attendees": expected_attendees,
        "started_at": started_at,
        "phase": "awaiting_decisions",
        # FIX #95: carried so a timeout retry can re-broadcast the SAME request
        # without re-deriving the requirement bundle.
        "requirements": requirements_list,
    }


def rebroadcast_kickoff_request(
    hubs: Any,
    kickoff_handle: Mapping[str, Any],
    only: Optional[List[str]] = None,
    agent: str = "orchestrator",
) -> None:
    """FIX #95 (runs 4/10/13, live): Gemini MALFORMED storms come in 20-50min BURSTS;
    a milestone kickoff landing in one times out with ZERO drafts to reconcile and the
    run hard-aborts — twice discarding runs that had ALREADY delivered milestones. Before
    aborting, the orchestrator re-broadcasts the kickoff_request to the MISSING lanes
    (``only``) and drives one more window: if the burst passed, the run continues. Reuses
    the handle's meeting + requirements — no duplicate meeting, roadmap intact."""
    recipients = list(only or kickoff_handle.get("expected_attendees") or [])
    if not recipients:
        return
    hubs.eventhub.publish_event(
        source_hub="orchestrator",
        event_type="kickoff_request",
        payload={
            "meeting_id": kickoff_handle.get("meeting_id"),
            "milestone_index": kickoff_handle.get("milestone_index"),
            "requirements": list(kickoff_handle.get("requirements") or []),
            "expected_sections": list(EXPECTED_SECTIONS),
        },
        recipients=recipients,
        priority="high",
        caller=agent,
    )


def _derive_response_key(path: Any) -> str:
    """Best-effort response_key from a path: last non-parameter segment.

    ``/api/posts`` → ``posts``; ``/api/posts/{id}`` → ``posts``;
    ``/api/posts/{id}/comments`` → ``comments``; ``/api/auth/login`` →
    ``login``. Falls back to ``"data"`` when nothing usable remains.
    """
    if not isinstance(path, str):
        return "data"
    segs = [s for s in path.strip("/").split("/")
            if s and not (s.startswith("{") or s.startswith(":"))]
    return segs[-1] if segs else "data"


def _normalize_backend_endpoints_for_reconcile(
    drafts: Mapping[str, Mapping[str, Any]],
) -> "tuple[Dict[str, Mapping[str, Any]], List[str]]":
    """Deterministic LAST-RESORT endpoint-shape normalization (FIX #20).

    A large LLM-authored contract often has a few endpoints missing the
    roadmap_validator-required ``response_key`` / ``auth_required`` (Instagram
    run #3: 6 such shape errors → ``validation_failed`` → abort even after the
    cross-checks reconciled). At the last resort, default the shape by
    construction rather than aborting the whole run:

      * ``auth_required`` missing or non-bool → ``True`` (safer default for a
        protected business surface — the LLM only omits it, never means "public");
      * ``response_key`` missing/empty → derived from the path
        (``/api/posts`` → ``posts``), else ``"data"``;
      * an endpoint missing ``method`` OR ``path`` is un-implementable junk →
        dropped (a frontend call to it was already pruned as "undefined").

    Returns ``(normalized_drafts, notes)`` — ``notes`` lists the changes
    (empty → drafts unchanged). data_model / task_tree / predicate shape is
    NOT touched here (those carry semantics the framework can't safely invent;
    they surface honestly in the residual-findings log instead).
    """
    backend = drafts.get("backend") or {}
    key = "api_endpoints" if "api_endpoints" in backend else (
        "endpoints" if "endpoints" in backend else None)
    if key is None:
        return dict(drafts), []
    raw = backend.get(key) or []
    if not isinstance(raw, list):
        return dict(drafts), []

    notes: List[str] = []
    new_eps: List[Any] = []
    changed = False
    for ep in raw:
        if not isinstance(ep, Mapping):
            notes.append("dropped non-mapping endpoint")
            changed = True
            continue
        method = ep.get("method")
        path = ep.get("path")
        if not (isinstance(method, str) and method.strip()) or \
           not (isinstance(path, str) and path.strip()):
            notes.append(f"dropped endpoint missing method/path: {method} {path}")
            changed = True
            continue
        ep2 = dict(ep)
        if not isinstance(ep2.get("auth_required"), bool):
            ep2["auth_required"] = True
            notes.append(f"defaulted auth_required=True for {method} {path}")
            changed = True
        rk = ep2.get("response_key")
        # PROPOSAL #46: BUSINESS endpoints (/api/) get the canonical projector envelope
        # key (item/items) — override absent OR non-canonical (e.g. "notes" the gate
        # rejects). Control-plane is kind-exempt + would false-drift if clobbered, so it
        # keeps the legacy fill-when-absent.
        if str(path).startswith("/api/"):
            if not (isinstance(rk, str) and rk in ("item", "items")):
                ep2["response_key"] = _canonical_response_key(method, path)
                notes.append(
                    f"derived response_key={ep2['response_key']!r} for {method} {path}")
                changed = True
        elif not (isinstance(rk, str) and rk.strip()):
            ep2["response_key"] = _derive_response_key_from_path(path)
            notes.append(
                f"derived response_key={ep2['response_key']!r} for {method} {path}")
            changed = True
        new_eps.append(ep2)

    if not changed:
        return dict(drafts), []
    new_backend = dict(backend)
    new_backend[key] = new_eps
    new_drafts = dict(drafts)
    new_drafts["backend"] = new_backend
    return new_drafts, notes


def _normalize_roadmap_shape_for_reconcile(
    drafts: Mapping[str, Mapping[str, Any]],
) -> "tuple[Dict[str, Mapping[str, Any]], List[str]]":
    """Default the non-runtime-fatal roadmap METADATA the LLM frequently leaves
    empty so a last-resort reconcile can finalize instead of aborting on
    ``validate_roadmap`` (FIX #20b — Instagram run #7: reconcile cleared the
    cross-checks but validation_failed on ``done_def MUST be a non-empty list``
    + ``feature_inventory.flows MUST be a non-empty list``).

    ``done_def`` (done-criteria) and ``feature_inventory`` (entity/flow list)
    are descriptive metadata — they don't affect whether the generated app WORKS
    at runtime — so defaulting them is safe (charter §8 by-construction). Entities
    are derived from the data_model tables, flows from the declared user_flows /
    screens. Returns ``(drafts, notes)``.
    """
    frontend = dict(drafts.get("frontend") or {})
    backend = drafts.get("backend") or {}
    notes: List[str] = []
    changed = False

    dd = frontend.get("done_def")
    if not (isinstance(dd, list) and any(
            isinstance(x, str) and x.strip() for x in dd)):
        frontend["done_def"] = [
            "All business endpoints implemented and reachable",
            "App boots cleanly in Docker",
            "Auth + core user flows pass smoke validation",
        ]
        notes.append("defaulted done_def")
        changed = True

    # Default auth metadata: validate_roadmap requires a non-empty
    # ``auth.model`` string, but the REAL auth is framework-owned by construction
    # (embedded OAuth2 AS minting JWTs) regardless of what the section says — so a
    # missing/empty declaration is descriptive drift, not a runtime risk
    # (instagram M3 2026-06-10 03:21 aborted on exactly this residual).
    auth = frontend.get("auth")
    if not (isinstance(auth, Mapping) and str(auth.get("model", "")).strip()):
        frontend["auth"] = {"model": "jwt", "required": True}
        notes.append("defaulted auth.model=jwt")
        changed = True

    # Normalize user_flows SHAPE: the LLM writes entries as bare strings or
    # mappings without an id, and ``test_strategy_coverage`` then errors with
    # "flow entry is not a mapping" / "critical flow is missing an id" —
    # offending_field=user_flows[j] — which the reconcile could NOT clear
    # (instagram 2026-06-10 01:56: residual=['user_flows[0]'] aborted the run).
    # Shape is mechanical, not semantic: coerce instead of failing.
    uf = frontend.get("user_flows")
    if isinstance(uf, list) and uf:
        fixed_flows: List[Any] = []
        uf_changed = False
        for j, f in enumerate(uf):
            if isinstance(f, Mapping):
                if not str(f.get("id", "")).strip():
                    f = {**f, "id": f"flow_{j}"}
                    uf_changed = True
                fixed_flows.append(f)
            elif isinstance(f, str) and f.strip():
                fixed_flows.append({"id": f.strip(), "critical": False})
                uf_changed = True
            else:
                uf_changed = True  # drop junk entries (None/numbers)
        if uf_changed:
            frontend["user_flows"] = fixed_flows
            notes.append(f"normalized user_flows shape ({len(fixed_flows)} flow(s))")
            changed = True

    def _valid_fi(x: Any) -> bool:
        return (
            isinstance(x, Mapping)
            and isinstance(x.get("entities"), list) and len(x.get("entities")) > 0
            and isinstance(x.get("flows"), list) and len(x.get("flows")) > 0
        )

    fi = frontend.get("feature_inventory")
    be_fi = backend.get("feature_inventory") if isinstance(backend, Mapping) else None
    if not _valid_fi(fi) and not _valid_fi(be_fi):
        tables = []
        if isinstance(backend, Mapping):
            tables = (backend.get("data_model") or {}).get("tables") or []
        entities = [
            t.get("name") for t in tables
            if isinstance(t, Mapping) and t.get("name")
        ]
        flows = [
            f.get("id") for f in (frontend.get("user_flows") or [])
            if isinstance(f, Mapping) and f.get("id")
        ]
        if not flows:
            flows = [
                s.get("id")
                for s in (frontend.get("screens") or frontend.get("ui_pages") or [])
                if isinstance(s, Mapping) and s.get("id")
            ]
        entities = entities or ["app"]
        flows = flows or ["core"]
        frontend["feature_inventory"] = {"entities": entities, "flows": flows}
        notes.append(
            f"defaulted feature_inventory(entities={len(entities)},flows={len(flows)})")
        changed = True

    if not changed:
        return dict(drafts), []
    new_drafts = dict(drafts)
    new_drafts["frontend"] = frontend
    return new_drafts, notes


# PROPOSAL #43: the whole framework implements *business* endpoints under the
# ``/api`` prefix — the frontend baseline client (`_BASELINE_API_JS`: nginx proxies
# ``/api,/auth,/oauth``), the backend skeleton (`render_skeleton_main` skips any path
# not ``startswith("/api/")``) and the gap-filling route projector
# (`project_missing_routes`, same guard). But the kickoff LLM authors business
# endpoint paths free-form, so it routinely emits a bare ``/notes``. That bare path is
# structurally un-implementable by the machinery above, while the frontend's
# ``/api/notes`` call gets AUTO-REGISTERED as a *separate* endpoint by
# `_reconcile_dangling_frontend_calls` (its ``known`` set is param-name-agnostic but
# NOT prefix-agnostic) — leaving ``/notes`` a permanent ``defined`` orphan that fails
# ``business_endpoints_implemented`` forever (observed: smoke-notes run, 2026-06-19).
#
# Fix: canonicalize business endpoint paths to ``/api`` at synthesis, BEFORE the
# contract / task_tree / reconcile-known-set are derived. We do NOT use a hardcoded
# control-plane path blocklist (the architecture deliberately avoids that —
# control_plane.py: "needs no hardcoded exemption list"). Instead the pre-registered
# fixed surface (spine/auth/control, kind-tagged, registered before the meeting) is the
# oracle: a draft path that matches a registered fixed-surface endpoint is owned
# elsewhere and left verbatim; everything else the LLM authored is business and gets
# the prefix. Already-``/api`` paths are left untouched (no ``/api/api`` double-prefix).
_API_PREFIX = "/api"


def _control_plane_keys(
    registered_endpoints: Optional[Iterable[Mapping[str, Any]]],
) -> set:
    """Param-agnostic keys of the pre-registered fixed surface (kind-tagged
    spine/auth/control). At synthesis time only the fixed surface is registered, so
    any draft endpoint matching one of these is control-plane, owned elsewhere."""
    keys: set = set()
    for rec in (registered_endpoints or []):
        if isinstance(rec, Mapping) and rec.get("method") and rec.get("path"):
            keys.add(_param_agnostic(_endpoint_key(rec.get("method"), rec.get("path"))))
    return keys


def _ensure_business_api_prefix(method: Any, path: Any, control_plane_keys: set) -> Any:
    """Return ``path`` carrying the ``/api`` business convention, unless it already
    has it, is unparseable, or matches a registered control-plane endpoint."""
    p = str(path or "").strip()
    if not p.startswith("/"):
        return path  # unparseable / relative — leave alone
    if p == _API_PREFIX or p.startswith(_API_PREFIX + "/"):
        return path  # already conventional → no double-prefix
    if _param_agnostic(_endpoint_key(method, p)) in control_plane_keys:
        return path  # control-plane / fixed surface — owned elsewhere
    return _API_PREFIX + p


def _canonicalize_business_endpoint_paths(
    drafts: Mapping[str, Mapping[str, Any]],
    registered_endpoints: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Mapping[str, Mapping[str, Any]]:
    """Rewrite bare business endpoint paths in the backend draft to the ``/api``
    convention (PROPOSAL #43). Idempotent; returns drafts unchanged if nothing moved."""
    backend = drafts.get("backend") or {}
    cp_keys = _control_plane_keys(registered_endpoints)
    new_backend = dict(backend)
    changed = False
    for key in ("endpoints", "api_endpoints"):
        eps = new_backend.get(key)
        if not isinstance(eps, list):
            continue
        out: List[Any] = []
        for ep in eps:
            if isinstance(ep, Mapping) and ep.get("path"):
                canon = _ensure_business_api_prefix(ep.get("method"), ep.get("path"), cp_keys)
                if canon != ep.get("path"):
                    ep = {**ep, "path": canon}
                    changed = True
            out.append(ep)
        new_backend[key] = out
    if not changed:
        return drafts
    new_drafts = dict(drafts)
    new_drafts["backend"] = new_backend
    return new_drafts


def _reconcile_dangling_frontend_calls(
    drafts: Mapping[str, Mapping[str, Any]],
    registered_endpoints: Optional[Iterable[Mapping[str, Any]]] = None,
) -> "tuple[Dict[str, Mapping[str, Any]], List[str]]":
    """Deterministic LAST-RESORT kickoff reconciliation (charter §8: converge by
    construction, don't abort a whole run on an unresolvable negotiation).

    A frontend ``api_call`` to an endpoint the backend never declared is the
    classic backend↔frontend gap (Instagram run #1: frontend invented
    ``GET /api/stories``, escalate→abort). Rather than PRUNE the call, AUTO-REGISTER
    the missing endpoint onto the backend contract — the frontend's NEED becomes the
    contract, which the skeleton then generates a handler for. This is the
    by-construction posture: the framework reconciles deterministically instead of
    blocking forever on a negotiation the lanes won't complete. The frontend calls
    are kept untouched (they now resolve against a real registered endpoint); each
    synthesised endpoint is stamped ``source="auto_from_frontend_call"`` for audit.

    Returns ``(reconciled_drafts, added)`` where ``added`` is the list of
    ``"METHOD PATH"`` endpoints auto-registered (empty → nothing dangling, drafts
    returned unchanged).
    """
    backend = drafts.get("backend") or {}
    frontend = drafts.get("frontend") or {}

    known: set = set()
    for ep in _extract_backend_endpoints(backend):
        known.add(_param_agnostic(_endpoint_key(ep.get("method"), ep.get("path"))))
    for rec in (registered_endpoints or []):
        if isinstance(rec, Mapping) and rec.get("method") and rec.get("path"):
            known.add(_param_agnostic(_endpoint_key(rec.get("method"), rec.get("path"))))

    # PROPOSAL #43: same control-plane oracle as the synthesis-time canonicalizer, so a
    # genuinely-new business call the frontend makes is auto-registered under ``/api``
    # (matching the rest of the contract) rather than as a bare orphan.
    cp_keys = _control_plane_keys(registered_endpoints)
    added: List[str] = []
    new_endpoints: List[Dict[str, Any]] = []
    for screen in _extract_frontend_screens(frontend):
        for call in (screen.get("api_calls") or []):
            if not isinstance(call, Mapping):
                continue
            disp = _api_call_key(call)                       # normalised "METHOD PATH"
            if _param_agnostic(disp) in known:
                continue                                     # already declared
            parts = disp.split(" ", 1)
            if len(parts) != 2 or not parts[1].startswith("/"):
                continue                                     # unparseable → leave alone
            method, path = parts[0].upper(), parts[1].strip()
            path = _ensure_business_api_prefix(method, path, cp_keys)
            known.add(_param_agnostic(_endpoint_key(method, path)))
            last = next((s for s in reversed(path.split("/")) if s), "")
            single = method != "GET" or last == "me" or (last.startswith("{") and last.endswith("}"))
            new_endpoints.append({
                "method": method,
                "path": path,
                "response_key": "item" if single else "items",
                "auth_required": True,
                "source": "auto_from_frontend_call",
            })
            added.append(f"{method} {path}")

    if not new_endpoints:
        return dict(drafts), []

    new_backend = dict(backend)
    eps_key = "endpoints" if ("endpoints" in new_backend and "api_endpoints" not in new_backend) else "api_endpoints"
    new_backend[eps_key] = list(new_backend.get(eps_key) or []) + new_endpoints
    new_drafts = dict(drafts)
    new_drafts["backend"] = new_backend
    return new_drafts, added


def try_synthesize(
    hubs: Any,
    kickoff_handle: Mapping[str, Any],
    reconcile: bool = False,
) -> SynthesisResult:
    """Attempt to synthesize the contract from the meeting's decisions.

    Polled by the orchestrator on every tick. Returns one of four
    structured statuses:

      * ``awaiting`` — not every expected attendee has recorded a
                       decision yet (``missing`` carries the gap).
      * ``conflict`` — quorum reached but ``cross_check_suite`` found
                       at least one error-severity finding;
                       ``revisers`` carries the per-agent reviser
                       map computed via ``arbitration_table.resolve_conflict``.
      * ``validation_failed`` — quorum + cross-checks clean, but
                       ``roadmap_validator.validate_roadmap`` flagged
                       a shape error.
      * ``ready`` — every gate passed; ``contract``, ``task_tree``,
                       and ``predicates`` carry the synthesized
                       artifacts the orchestrator hands to
                       :func:`finalize_kickoff`.
    """
    if not isinstance(kickoff_handle, Mapping):
        raise ValueError(
            "kickoff_handle MUST be a Mapping returned by start_kickoff; "
            f"got {type(kickoff_handle).__name__}"
        )
    meeting_id = kickoff_handle.get("meeting_id")
    _require_nonempty_str(meeting_id, "kickoff_handle.meeting_id")
    milestone_index = kickoff_handle.get("milestone_index")
    _require_milestone_index(milestone_index)
    # FIX #42: the orchestrator stows the project ``--description`` on the handle so
    # the synthesizer can deterministically backstop an empty LLM-drafted contract.
    _kickoff_description = str(kickoff_handle.get("description") or "")
    expected_attendees = list(kickoff_handle.get("expected_attendees") or [])
    if not expected_attendees:
        raise ValueError(
            "kickoff_handle.expected_attendees MUST be a non-empty list"
        )

    decisions = _read_meeting_decisions(hubs, meeting_id)

    # 1. Quorum check. In revision rounds (N>=2) ONLY the revisers named by the prior
    # round's facilitator_note are expected to re-author — counting the FULL attendee set
    # wedges synthesis in 'awaiting' forever on non-revisers who were correctly never
    # woken (Round 8h Fix #G already filters facilitate.current_phase this way; the
    # quorum check here must match or revision rounds never reach 'ready'). Round 1 uses
    # the full set, and any error falls back to it, so round-1 behavior is unchanged.
    _quorum_attendees = expected_attendees
    try:
        from . import facilitate as _facilitate
        _round_n = _facilitate.current_round(hubs, meeting_id)
        if _round_n and _round_n >= 2:
            _quorum_attendees = _facilitate.expected_attendees_for_round(
                decisions, _round_n, expected_attendees) or expected_attendees
    except Exception:
        _quorum_attendees = expected_attendees
    missing = _missing_attendees(decisions, _quorum_attendees)
    if missing:
        return {
            "status": "awaiting",
            "missing": missing,
            "milestone_index": milestone_index,
        }

    # 2. Bucket decisions into per-section drafts.
    drafts = _collect_drafts(decisions)
    # Round 8h Fix #P-bis: augment verifier predicates with stubs for
    # any critical user_flow that lacks coverage BEFORE running
    # cross-checks (the test_strategy_coverage extractor reads
    # drafts["verifier"]["predicates"] directly, so augmenting in
    # _build_roadmap only would still let the cross-check fail).
    # Same augmentation is later applied (idempotently) inside
    # _build_roadmap as a defensive safety net.
    drafts = _augment_drafts_for_coverage(drafts)
    # §4 D4.2: resolve cross-checks against the registered contract (the fixed
    # surface — spine/AS/auth/control — is registered BEFORE the meeting), so a
    # frontend screen that calls /auth/login resolves to a real kind=auth
    # endpoint and the "needs a UI consumer" rule is exempted by `kind`, never by
    # a hardcoded path list. At synthesis time only the fixed surface is
    # registered (business registers at finalize_kickoff).
    try:
        registered = list((hubs.registryhub.get_endpoints() or {}).values())
    except Exception:
        registered = []
    # PROPOSAL #43: canonicalize bare business endpoint paths to the framework's
    # ``/api`` convention BEFORE the contract, task_tree and reconcile-known-set are
    # derived from drafts — so the LLM's ``/notes`` becomes ``/api/notes`` (which the
    # skeleton/projector can implement and the frontend baseline already calls),
    # instead of orphaning as a permanent ``defined`` endpoint. Runs unconditionally
    # (not just on the reconcile path) so the normal happy-path contract is canonical
    # too. Control-plane / fixed-surface endpoints (matched against the pre-registered
    # kind-tagged surface) are left verbatim.
    drafts = _canonicalize_business_endpoint_paths(drafts, registered_endpoints=registered)
    # Last-resort deterministic reconciliation (only when the caller is about to
    # abort the kickoff): prune frontend api_calls to undefined endpoints so the
    # contract converges by construction instead of failing the whole run.
    added_endpoints: List[str] = []
    normalized_notes: List[str] = []
    if reconcile:
        # 1. Normalize endpoint shape (default response_key/auth_required, drop
        #    method/path-less junk) so a slightly-malformed big contract still
        #    passes validate_roadmap (FIX #20). Done BEFORE pruning so dangling
        #    frontend calls resolve against the cleaned endpoint set.
        drafts, normalized_notes = _normalize_backend_endpoints_for_reconcile(
            drafts,
        )
        # 1b. Default non-runtime-fatal roadmap metadata (done_def,
        #     feature_inventory) the LLM left empty (FIX #20b).
        drafts, _shape_notes = _normalize_roadmap_shape_for_reconcile(drafts)
        normalized_notes = list(normalized_notes) + _shape_notes
        # 2. Auto-register endpoints for frontend calls the backend didn't declare —
        #    the frontend's need becomes the contract (the skeleton generates them).
        drafts, added_endpoints = _reconcile_dangling_frontend_calls(
            drafts, registered_endpoints=registered,
        )
        # 3. Lenient registry: dead-endpoint (tightness) downgraded to
        #    non-blocking; runtime-fatal checks (undefined-endpoint,
        #    api↔data_model) stay enforced.
        cross = run_cross_checks(
            drafts,
            checks=reconcile_check_registry(),
            registered_endpoints=registered,
        )
    else:
        cross = run_cross_checks(drafts, registered_endpoints=registered)
    if not cross.get("ok", False):
        # Conflict — translate each non-pass item into a reviser
        # assignment via arbitration_table.resolve_conflict.
        findings: List[Mapping[str, Any]] = []
        revisers: Dict[str, List[Mapping[str, Any]]] = {}
        for item in cross.get("items", []):
            if item.get("status") == "pass":
                continue
            findings.append(item)
            conflict = _conflict_from_finding(item)
            try:
                reviser = resolve_conflict(conflict)
            except ValueError:
                # Malformed conflict — surface as a generic reviser
                # ("orchestrator") rather than re-raising, so the
                # orchestrator can decide to escalate to human.
                reviser = "orchestrator"
            revisers.setdefault(reviser, []).append(item)
        return {
            "status": "conflict",
            "findings": findings,
            "revisers": revisers,
            "milestone_index": milestone_index,
        }

    # 3. Roadmap shape validation.
    # FIX #561: pass the CUMULATIVE registered contract so a no-new-endpoint M2+
    # slice with no net-new verifier predicates derives its acceptance predicates
    # from the endpoints M1..M(i-1) already built (see _build_roadmap).
    roadmap = _build_roadmap(
        drafts, milestone_index, _kickoff_description,
        registered_endpoints=registered,
    )
    validation = validate_roadmap(roadmap, milestone_index)
    if not validation.get("ok", False):
        return {
            "status": "validation_failed",
            "findings": list(validation.get("findings", [])),
            "milestone_index": milestone_index,
        }

    # 4. Ready — return the synthesized artifacts.
    return {
        "status": "ready",
        "contract": roadmap["contract"],
        "task_tree": roadmap["task_tree"],
        "predicates": roadmap["acceptance_predicates"],
        "milestone_index": milestone_index,
        # Surface the full roadmap snapshot too so finalize_kickoff
        # has everything it needs without rebuilding.
        "roadmap": roadmap,
        # Non-empty only when the reconcile path auto-registered endpoints for
        # frontend calls the backend didn't declare — orchestrator logs these.
        "reconciled_added": added_endpoints,
        # Endpoint-shape normalizations applied in the reconcile path (FIX #20).
        "reconciled_normalized": normalized_notes,
    }


# ---------------------------------------------------------------------------
# Phase state machine helpers (charter §5/§8 closed-by-construction):
#
# A finalize_kickoff run progresses the meeting through:
#
#   "open"           -> set by start_kickoff at create_meeting time
#   "synthesizing"   -> (reserved for try_synthesize; not driven here)
#   "finalizing"     -> set on entry to finalize_kickoff
#   "finalized"      -> set after all hub writes + meeting close succeed
#   "partial_failure"-> set on the first hub-write rejection inside finalize
#
# Persistence: the phase is recorded as a ``phase_transition`` decision
# via ``workhub.add_meeting_decision`` (no new hub method required —
# decisions are already the meeting page's append-only audit trail).
# The CURRENT phase is the most recent ``phase_transition`` decision's
# ``content["phase"]``; if none exist, the create_meeting initial
# metadata phase ("open") wins.
#
# Idempotency: on re-entry, ``_current_phase`` reads the latest
# transition; if it is "finalized", finalize_kickoff short-circuits and
# returns the cached receipt that was recorded alongside the last
# transition. If "partial_failure", finalize_kickoff resumes: registers
# are merge-upserts (safe to re-run), and create_task skips any task_id
# that already exists in workhub.get_task / list_tasks.
# ---------------------------------------------------------------------------


_TASK_SKIP_STATUSES = ("done", "in_progress", "claimed", "ready", "pending", "completed")


def _read_phase_transitions(
    hubs: Any, meeting_id: str
) -> List[Mapping[str, Any]]:
    """Return phase_transition decisions in append order (oldest first)."""
    decisions = _read_meeting_decisions(hubs, meeting_id)
    return [
        d for d in decisions
        if isinstance(d, Mapping) and d.get("section") == "phase_transition"
    ]


def _current_phase(hubs: Any, meeting_id: str) -> str:
    """Return the meeting's current phase.

    Source of truth: the LAST ``phase_transition`` decision in the
    meeting metadata. Falls back to the page's ``metadata["phase"]``
    (set at create_meeting time) and finally to ``"open"`` so a
    pristine meeting always reports a phase.
    """
    transitions = _read_phase_transitions(hubs, meeting_id)
    if transitions:
        last = transitions[-1]
        content = last.get("content")
        if isinstance(content, Mapping):
            phase = content.get("phase")
            if isinstance(phase, str) and phase.strip():
                return phase
    # Fall back to the page's initial metadata phase.
    pages_getter = getattr(getattr(hubs.workhub, "stores", None), "pages", None)
    if pages_getter is not None:
        try:
            page = pages_getter.value().get(meeting_id) or {}
        except Exception:
            page = {}
        meta = page.get("metadata") or {}
        phase = meta.get("phase")
        if isinstance(phase, str) and phase.strip():
            return phase
    return "open"


def _last_finalized_receipt(
    hubs: Any, meeting_id: str
) -> Optional[Dict[str, Any]]:
    """Return the receipt persisted with the last 'finalized' transition.

    On idempotent re-entry we replay the exact receipt the first
    successful run published, so the caller can't tell the difference
    between the initial success and a no-op re-call.
    """
    for d in reversed(_read_phase_transitions(hubs, meeting_id)):
        content = d.get("content") if isinstance(d, Mapping) else None
        if not isinstance(content, Mapping):
            continue
        if content.get("phase") != "finalized":
            continue
        receipt = content.get("receipt")
        if isinstance(receipt, Mapping):
            return dict(receipt)
    return None


def _record_phase(
    hubs: Any,
    *,
    meeting_id: str,
    milestone_index: int,
    agent: str,
    phase: str,
    receipt: Optional[Mapping[str, Any]] = None,
    failures: Optional[List[Mapping[str, Any]]] = None,
) -> None:
    """Persist a phase_transition decision on the meeting page."""
    content: Dict[str, Any] = {"phase": phase}
    if receipt is not None:
        content["receipt"] = dict(receipt)
    if failures:
        content["failures"] = list(failures)
    hubs.workhub.add_meeting_decision(
        meeting_id=meeting_id,
        decision={
            "section": "phase_transition",
            "agent": agent,
            "content": content,
            "kind": "kickoff_phase_transition",
        },
        agent=agent,
        milestone_index=milestone_index,
    )


def _task_already_present(hubs: Any, task_id: Optional[str]) -> bool:
    """Return True if a task with this id is already registered and live.

    Used to make recovery from partial_failure idempotent: a second
    finalize_kickoff run skips create_task for any task_id that
    already lives in workhub with a non-failed status.
    """
    if not task_id:
        return False
    workhub = hubs.workhub
    getter = getattr(workhub, "get_task", None)
    task: Optional[Mapping[str, Any]] = None
    if callable(getter):
        try:
            task = getter(task_id)
        except Exception:
            task = None
    if task is None:
        lister = getattr(workhub, "list_tasks", None)
        if callable(lister):
            try:
                rows = lister() or []
            except Exception:
                rows = []
            for row in rows:
                if isinstance(row, Mapping) and row.get("id") == task_id:
                    task = row
                    break
    if not isinstance(task, Mapping):
        return False
    status = task.get("status")
    return status in _TASK_SKIP_STATUSES


def finalize_kickoff(
    hubs: Any,
    kickoff_handle: Mapping[str, Any],
    synthesis: Mapping[str, Any],
    agent: str = "orchestrator",
) -> Dict[str, Any]:
    """Register synthesized artifacts and close the kickoff meeting.

    Caller MUST first verify ``synthesis["status"] == "ready"``; this
    function raises ``ValueError`` otherwise so a half-baked synthesis
    can't slip past the gate.

    Steps (in order — each is one explicit hub call, each wrapped in
    a try/except that converts a raised exception or an
    ``{"error": ...}`` return into a structured failure entry):

      0. Phase guard: if the meeting is already ``finalized``,
         short-circuit and return the persisted receipt. Otherwise
         record ``phase=finalizing`` before the first write.
      1. ``registryhub.register_endpoint`` per canonical endpoint
         (fail-fast — if any endpoint fails, do not proceed to
         tables/tasks).
      2. ``schema_hub.register_table`` per declared table
         (fail-fast — if any table fails, do not proceed to tasks).
      3. ``workhub.create_task`` per task_tree entry. Idempotent
         re-entry skips tasks whose ``task_id`` already lives in
         workhub with a non-failed status.
      4. Persist predicates onto the meeting page via
         ``workhub.add_meeting_decision``.
      5. ``workhub.close_meeting`` with the artifact list
         (only if all prior steps succeeded).
      6. ``eventhub.publish_event`` with type ``kickoff_complete``
         (only if all prior steps succeeded).
      7. Record ``phase=finalized`` (with cached receipt) so
         re-entry is a no-op.

    On the first failure: record ``phase=partial_failure`` plus the
    captured ``failures`` list, DO NOT close the meeting, DO NOT
    emit ``kickoff_complete``, and return the structured receipt with
    ``phase="partial_failure"`` so the caller (or the orchestrator's
    lane) can wake on either ``kickoff_complete`` OR the receipt's
    explicit failure state.

    Returns a receipt dict::

        {"finalized": bool,
         "endpoints_registered": int,
         "endpoints_failed":     int,
         "tables_registered":    int,
         "tables_failed":        int,
         "tasks_created":        int,
         "tasks_already_existing": int,
         "tasks_failed":         int,
         "predicates_persisted": int,
         "failures": [{"hub":..., "item":..., "error":...}],
         "meeting_id":           str,
         "milestone_index":      int,
         "phase":                "finalized" | "partial_failure"}
    """
    _require_nonempty_str(agent, "agent")
    if not isinstance(kickoff_handle, Mapping):
        raise ValueError(
            "kickoff_handle MUST be a Mapping returned by start_kickoff"
        )
    if not isinstance(synthesis, Mapping):
        raise ValueError(
            "synthesis MUST be a Mapping returned by try_synthesize"
        )
    if synthesis.get("status") != "ready":
        raise ValueError(
            "finalize_kickoff requires synthesis.status == 'ready'; "
            f"got {synthesis.get('status')!r}"
        )

    meeting_id = kickoff_handle.get("meeting_id")
    _require_nonempty_str(meeting_id, "kickoff_handle.meeting_id")
    milestone_index = kickoff_handle.get("milestone_index")
    _require_milestone_index(milestone_index)
    expected_attendees = list(kickoff_handle.get("expected_attendees") or [])

    # Step 0a: phase guard — idempotent re-call short-circuit.
    current_phase = _current_phase(hubs, meeting_id)
    if current_phase == "finalized":
        cached = _last_finalized_receipt(hubs, meeting_id)
        if cached is not None:
            return cached
        # Defensive: phase is finalized but no receipt was persisted
        # — fall through and replay (registers are upserts so the
        # second pass is safe).
    # "partial_failure" -> continue; register_endpoint/register_table
    # are merge-upserts and create_task skips already-present ids.
    # "open" / "synthesizing" / "finalizing" -> normal flow.

    contract = synthesis.get("contract") or {}
    # Mechanism #52: register declared ui_components as ``defined`` — the
    # API-owning layer of the UI model (page → components → apis). Pages
    # roll up: a page can only reach ``implemented`` once every component
    # it references is implemented (frontend_audit enforces this).
    try:
        for _c in (contract.get("ui_components") or []):
            if isinstance(_c, Mapping) and str(_c.get("id") or "").strip():
                hubs.workhub.update_ui_component(
                    str(_c["id"]).strip(), {
                        "status": "defined",
                        "component": str(_c.get("component") or ""),
                        "comp_kind": str(_c.get("kind") or ""),
                        "apis_used": [str(a) for a in (_c.get("apis_used") or [])],
                        "children": [str(c) for c in (_c.get("children") or [])],
                    }, agent="orchestrator")
    except Exception:
        pass
    task_tree = list(synthesis.get("task_tree") or [])
    predicates = list(synthesis.get("predicates") or [])
    endpoints = list(contract.get("endpoints") or [])
    data_model = contract.get("data_model") or {}
    tables = list(data_model.get("tables") or [])

    # Step 0b: mark the meeting as finalizing before any hub write.
    _record_phase(
        hubs,
        meeting_id=meeting_id,
        milestone_index=milestone_index,
        agent=agent,
        phase="finalizing",
    )

    failures: List[Dict[str, Any]] = []
    n_endpoints = 0
    n_endpoints_failed = 0
    n_tables = 0
    n_tables_failed = 0
    n_tasks = 0
    n_tasks_existing = 0
    n_tasks_failed = 0
    n_predicates = 0

    def _emit_partial_failure() -> Dict[str, Any]:
        receipt = {
            "finalized": False,
            "endpoints_registered": n_endpoints,
            "endpoints_failed": n_endpoints_failed,
            "tables_registered": n_tables,
            "tables_failed": n_tables_failed,
            "tasks_created": n_tasks,
            "tasks_already_existing": n_tasks_existing,
            "tasks_failed": n_tasks_failed,
            "predicates_persisted": n_predicates,
            "failures": list(failures),
            "meeting_id": meeting_id,
            "milestone_index": milestone_index,
            "phase": "partial_failure",
        }
        _record_phase(
            hubs,
            meeting_id=meeting_id,
            milestone_index=milestone_index,
            agent=agent,
            phase="partial_failure",
            receipt=receipt,
            failures=failures,
        )
        # Emit a kickoff_failed event so the orchestrator's lane can
        # wake on either kickoff_complete OR kickoff_failed.
        try:
            hubs.eventhub.publish_event(
                source_hub="orchestrator",
                event_type="kickoff_failed",
                payload={
                    "meeting_id": meeting_id,
                    "milestone_index": milestone_index,
                    "failures": list(failures),
                    "endpoints_registered": n_endpoints,
                    "tables_registered": n_tables,
                    "tasks_created": n_tasks,
                },
                recipients=expected_attendees,
                priority="high",
                caller=agent,
            )
        except Exception:
            # Eventhub failure during partial-failure reporting must
            # not mask the underlying hub failure — the receipt is
            # the source of truth.
            pass
        return receipt

    # Step 1: register each canonical endpoint via registryhub. Fail-fast:
    # tasks reference endpoints, so a missing endpoint means tasks
    # would land against a contract that isn't there yet.
    for ep in endpoints:
        try:
            kwargs = normalize_to_registryhub_endpoint(ep)
            provider = kwargs.pop("provider", "backend")
            result = hubs.registryhub.register_endpoint(
                agent=agent,
                provider=provider,
                status="defined",
                **kwargs,
            )
        except Exception as exc:
            n_endpoints_failed += 1
            failures.append({
                "hub": "registryhub",
                "item": ep,
                "error": repr(exc),
            })
            return _emit_partial_failure()
        # registryhub.register_endpoint returns the endpoint dict on
        # success; defensively check for an error-dict shape in case
        # a future revision starts returning one.
        if isinstance(result, Mapping) and result.get("error"):
            n_endpoints_failed += 1
            failures.append({
                "hub": "registryhub",
                "item": ep,
                "error": str(result.get("error")),
            })
            return _emit_partial_failure()
        n_endpoints += 1

    # Step 2: register each declared table via schema_hub. Fail-fast.
    for tbl in tables:
        if not isinstance(tbl, Mapping):
            continue
        name = tbl.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        # owner_scoped_reads (a.k.a private/private_reads): per-user-PRIVATE table —
        # every read is owner-scoped, like writes. It's a TABLE PROPERTY, not a
        # column, so lift it into metadata (the projector reads it from there);
        # leaving it in ``schema`` would make normalize_table_schema drop it.
        _read_flag_keys = ("owner_scoped_reads", "private_reads", "private")
        schema = {k: v for k, v in tbl.items()
                  if k != "name" and k not in _read_flag_keys}
        _osr = next((tbl[k] for k in _read_flag_keys if k in tbl), None)
        table_meta: Dict[str, Any] = {}
        if _osr is not None:
            table_meta["owner_scoped_reads"] = (
                _osr if isinstance(_osr, bool)
                else str(_osr).strip().lower() in {"true", "1", "yes", "y", "on"})
        try:
            result = hubs.schema_hub.register_table(
                name=name,
                schema=schema,
                provider="backend",
                agent=agent,
                **table_meta,
            )
        except Exception as exc:
            n_tables_failed += 1
            failures.append({
                "hub": "schema_hub",
                "item": name,
                "error": repr(exc),
            })
            return _emit_partial_failure()
        if isinstance(result, Mapping) and result.get("error"):
            n_tables_failed += 1
            failures.append({
                "hub": "schema_hub",
                "item": name,
                "error": str(result.get("error")),
            })
            return _emit_partial_failure()
        n_tables += 1

    # Step 3: spawn each task in the synthesized task_tree.
    # workhub.create_task returns {"error": ...} on invalid input (it
    # does NOT raise) — we MUST inspect the return value.
    for task in task_tree:
        if not isinstance(task, Mapping):
            continue
        title = task.get("title") or task.get("id") or "kickoff_task"
        description = task.get("description") or ""
        assignee = task.get("owner") or task.get("assignee")
        depends_on = list(task.get("depends_on") or [])
        task_id = task.get("id")
        kind = task.get("kind")
        metadata: Dict[str, Any] = {}
        if kind:
            metadata["kind"] = kind
        # GATE-C2/C3 (delivery task-completeness): carry the structural
        # identity into metadata so the delivery gate can map a pending
        # implement_endpoint / implement_table / validate_api_smoke task back
        # to its registry evidence (endpoint contract-test record / table impl
        # status) without lossy task-id parsing. create_task(**metadata) stashes
        # these under task["metadata"].
        ep = task.get("endpoint")
        if isinstance(ep, Mapping) and ep.get("path"):
            metadata.setdefault(
                "endpoint",
                {"method": ep.get("method"), "path": ep.get("path")},
            )
        tbl = task.get("table")
        if tbl:
            metadata.setdefault("table", tbl)
        extras = task.get("metadata")
        if isinstance(extras, Mapping):
            for k, v in extras.items():
                metadata.setdefault(k, v)
        # Idempotency: a recovery re-run skips tasks that already
        # landed during the prior run (workhub.create_task does NOT
        # guard duplicate ids on its own — discovery confirmed it
        # silently overwrites).
        if _task_already_present(hubs, task_id):
            n_tasks_existing += 1
            continue
        try:
            result = hubs.workhub.create_task(
                title=title,
                description=description,
                assignee=assignee,
                depends_on=depends_on,
                agent=agent,
                task_id=task_id,
                **metadata,
            )
        except Exception as exc:
            n_tasks_failed += 1
            failures.append({
                "hub": "workhub",
                "item": task_id or title,
                "error": repr(exc),
            })
            return _emit_partial_failure()
        if isinstance(result, Mapping) and result.get("error"):
            n_tasks_failed += 1
            failures.append({
                "hub": "workhub",
                "item": task_id or title,
                "error": str(result.get("error")),
            })
            return _emit_partial_failure()
        n_tasks += 1
        # Mechanism #50: an implement_page task ALSO registers its ui_page in
        # the workhub registry as ``defined`` (route/component/apis_used from
        # the kickoff declaration) — the frontend lifecycle mirrors tables.
        if kind == "implement_page":
            try:
                _pname = str(task.get("ui_page") or "").strip()
                _pmeta = task.get("metadata") if isinstance(task.get("metadata"), Mapping) else {}
                if _pname:
                    hubs.workhub.update_ui_page(_pname, {
                        "status": "defined",
                        "route": _pmeta.get("route") or "",
                        "component": _pmeta.get("component") or "",
                        "apis_used": list(_pmeta.get("apis_used") or []),
                        "components": list(_pmeta.get("components") or []),
                    }, agent="orchestrator")
            except Exception:
                pass

    # Step 4: persist predicates alongside the meeting page.
    if predicates:
        try:
            result = hubs.workhub.add_meeting_decision(
                meeting_id=meeting_id,
                decision={
                    "section": "acceptance_predicates",
                    "agent": agent,
                    "content": {"predicates": predicates},
                    "kind": "acceptance_predicate_set",
                },
                agent=agent,
                milestone_index=milestone_index,
            )
        except Exception as exc:
            failures.append({
                "hub": "workhub",
                "item": "acceptance_predicates",
                "error": repr(exc),
            })
            return _emit_partial_failure()
        if isinstance(result, Mapping) and result.get("error"):
            failures.append({
                "hub": "workhub",
                "item": "acceptance_predicates",
                "error": str(result.get("error")),
            })
            return _emit_partial_failure()
        n_predicates = len(predicates)
        # VERIFIER PREDICATES → DELIVERABILITY GATES (2026-06-10, user
        # direction: "verifier 写的测试也得添加在 gate 里面"). Each named
        # acceptance predicate becomes an individually-evaluated gate in the
        # same store the reference-spec gates use — enforced and visible in
        # the deliverability report, instead of being advisory text that
        # successive leniency knobs quietly drop. Best-effort: a gate-write
        # failure must not fail the finalize.
        try:
            base = getattr(hubs, "base_dir", None)
            if base is not None:
                gates = []
                for pred in predicates:
                    if not isinstance(pred, Mapping):
                        continue
                    desc = str(pred.get("description") or pred.get("id") or "").strip()
                    if not desc:
                        continue
                    gates.append({
                        "type": "predicate",
                        "name": f"verifier: {str(pred.get('id') or desc)[:60]}",
                        "params": {"description": desc},
                        "source": "verifier_predicates",
                    })
                if gates:
                    # de-dup by name within this batch; merge keeps the
                    # user's own gates and the reference-spec gates intact.
                    seen = set()
                    gates = [g for g in gates
                             if not (g["name"] in seen or seen.add(g["name"]))]
                    _merged = _merge_predicate_gates(base, gates)
        except Exception:
            pass

    # Step 5: close the meeting with the produced-artifact summary.
    try:
        result = hubs.workhub.close_meeting(
            meeting_id=meeting_id,
            produced_artifacts=["contract", "task_tree", "predicates"],
            milestone_index=milestone_index,
            agent=agent,
        )
    except Exception as exc:
        failures.append({
            "hub": "workhub",
            "item": "close_meeting",
            "error": repr(exc),
        })
        return _emit_partial_failure()
    if isinstance(result, Mapping) and result.get("error"):
        failures.append({
            "hub": "workhub",
            "item": "close_meeting",
            "error": str(result.get("error")),
        })
        return _emit_partial_failure()

    # Step 6: emit kickoff_complete — orchestrator lane subscribes via
    # agent_subscriptions and wakes on this event (NOT on send_task).
    hubs.eventhub.publish_event(
        source_hub="orchestrator",
        event_type="kickoff_complete",
        payload={
            "meeting_id": meeting_id,
            "milestone_index": milestone_index,
            "endpoints_registered": n_endpoints,
            "tables_registered": n_tables,
            "tasks_created": n_tasks,
            "tasks_already_existing": n_tasks_existing,
            "predicates_persisted": n_predicates,
        },
        recipients=expected_attendees,
        priority="normal",
        caller=agent,
    )

    receipt = {
        "finalized": True,
        "endpoints_registered": n_endpoints,
        "endpoints_failed": n_endpoints_failed,
        "tables_registered": n_tables,
        "tables_failed": n_tables_failed,
        "tasks_created": n_tasks,
        "tasks_already_existing": n_tasks_existing,
        "tasks_failed": n_tasks_failed,
        "predicates_persisted": n_predicates,
        "failures": [],
        "meeting_id": meeting_id,
        "milestone_index": milestone_index,
        "phase": "finalized",
    }
    # Step 7: stamp phase=finalized + cache the receipt for
    # idempotent re-entry.
    _record_phase(
        hubs,
        meeting_id=meeting_id,
        milestone_index=milestone_index,
        agent=agent,
        phase="finalized",
        receipt=receipt,
    )
    return receipt


# ---------------------------------------------------------------------------
# Timeout / fallback path — round-8a reviewer's "T=1200s circuit-breaker"
# folded into the round-8c Python driver. If the orchestrator's driver
# polls past KICKOFF_TIMEOUT_SEC without a ready synthesis, it calls this
# helper to emit a kickoff_failed event so attendees can stop and the
# run loop can abort cleanly. We deliberately do NOT manufacture stub
# drafts for missing sections — synthesising a fake contract from a
# partial kickoff is exactly the "silently degraded run" the round-8b
# break exposed. The fallback marks `kickoff_fallback_used=True` on the
# emitted event so anyone watching the eventhub knows this run is dead.
# ---------------------------------------------------------------------------


def synthesize_fallback(
    hubs: Any,
    kickoff_handle: Mapping[str, Any],
    last_synthesis: Mapping[str, Any],
    agent: str = "orchestrator",
) -> Dict[str, Any]:
    """Emit ``kickoff_failed`` for a timeout-bound kickoff + return receipt.

    Called by the orchestrator's Python driver when ``try_synthesize`` has
    not produced a ``ready`` status within :data:`KICKOFF_TIMEOUT_SEC`
    seconds of ``start_kickoff``'s ``started_at``.

    Args:
        hubs:           hub registry — needs ``hubs.eventhub.publish_event``.
        kickoff_handle: the handle returned by :func:`start_kickoff`.
        last_synthesis: the most recent ``try_synthesize`` result; its
                        ``missing`` / ``findings`` are surfaced on the
                        emitted event so attendees + the run loop see why
                        the kickoff timed out.
        agent:          caller identity (default "orchestrator" since this
                        is the orchestrator-driver entry point).

    Returns:
        ``{"phase": "timeout_fallback", "kickoff_fallback_used": True,
            "meeting_id": str, "milestone_index": int, "missing": [...],
            "findings": [...]}``

    The returned phase is intentionally NOT "finalized" — the orchestrator
    driver inspects ``phase == "timeout_fallback"`` and aborts the run
    with a clear error rather than continuing into delivery checks.
    """
    _require_nonempty_str(agent, "agent")
    if not isinstance(kickoff_handle, Mapping):
        raise ValueError(
            "kickoff_handle MUST be a Mapping returned by start_kickoff"
        )
    if not isinstance(last_synthesis, Mapping):
        raise ValueError(
            "last_synthesis MUST be a Mapping returned by try_synthesize"
        )
    meeting_id = kickoff_handle.get("meeting_id")
    _require_nonempty_str(meeting_id, "kickoff_handle.meeting_id")
    milestone_index = kickoff_handle.get("milestone_index")
    _require_milestone_index(milestone_index)
    expected_attendees = list(kickoff_handle.get("expected_attendees") or [])

    missing = list(last_synthesis.get("missing") or [])
    findings = list(last_synthesis.get("findings") or [])
    last_status = last_synthesis.get("status", "unknown")

    # Mark the meeting as fallback-used via a phase_transition decision so
    # the persisted artifacts also reflect the timeout (not only the
    # in-flight event). _record_phase is a closed-by-construction guard
    # against silently degraded runs slipping past observers.
    try:
        _record_phase(
            hubs,
            meeting_id=meeting_id,
            milestone_index=milestone_index,
            agent=agent,
            phase="timeout_fallback",
        )
    except Exception:
        # workhub failure here MUST NOT mask the underlying timeout —
        # the event below is the source of truth for the driver.
        pass

    # Emit kickoff_failed so attendees and any subscribed observers can
    # stop work + so the orchestrator driver itself sees the explicit
    # event (in addition to the receipt below).
    try:
        hubs.eventhub.publish_event(
            source_hub="orchestrator",
            event_type="kickoff_failed",
            payload={
                "meeting_id": meeting_id,
                "milestone_index": milestone_index,
                "reason": "timeout",
                "last_status": last_status,
                "missing": missing,
                "findings": findings,
                "kickoff_fallback_used": True,
                "timeout_sec": KICKOFF_TIMEOUT_SEC,
            },
            recipients=expected_attendees,
            priority="high",
            caller=agent,
        )
    except Exception:
        # Eventhub failure here is also non-fatal — the receipt the
        # driver inspects is the source of truth.
        pass

    return {
        "phase": "timeout_fallback",
        "kickoff_fallback_used": True,
        "meeting_id": meeting_id,
        "milestone_index": milestone_index,
        "last_status": last_status,
        "missing": missing,
        "findings": findings,
    }


def _merge_predicate_gates(workspace: Any, new_gates: List[Dict[str, Any]]) -> int:
    """Append verifier-predicate gates into ``.user_gates.json``, replacing
    earlier gates of source=verifier_predicates (re-finalize never accretes
    stale predicates) while preserving user-authored and reference-spec gates."""
    import json as _json
    from pathlib import Path as _Path
    path = _Path(workspace) / ".user_gates.json"
    try:
        existing = _json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except Exception:
        existing = []
    kept = [g for g in existing
            if not (isinstance(g, Mapping) and g.get("source") == "verifier_predicates")]
    names = {g.get("name") for g in kept if isinstance(g, Mapping)}
    added = [g for g in new_gates if g.get("name") not in names]
    path.write_text(_json.dumps(kept + added, indent=2) + "\n", encoding="utf-8")
    return len(added)
