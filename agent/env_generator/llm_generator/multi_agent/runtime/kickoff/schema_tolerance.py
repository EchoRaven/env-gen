"""Round 8h — kickoff schema tolerance.

Centralizes the closed-by-construction tolerances the kickoff
pipeline accumulated from real-LLM smoke runs through smokes
#9 through #9-septodecimus (2026-06-02 / 2026-06-03). Each
helper here was originally a one-line band-aid inside
``cross_check_suite``, ``run_kickoff``, or ``facilitate``; this
module collects them with consistent docstrings + the smoke
post-mortem that motivated each one, so a future agent (human or
machine) reading the kickoff stack doesn't have to read 12
sibling commits to understand WHY the synthesizer is permissive
about real-LLM shape drift.

What "schema tolerance" means here:

  The kickoff protocol publishes a JSON contract shape to each
  attendee via the v3 prompts. LLM authors occasionally drift from
  that exact shape — they rename keys (``endpoints`` vs
  ``api_endpoints``), invent action tokens (``accept_revision_and_
  recenter`` instead of canonical ``consensus``), or under-author
  collections (verifier writes ONE predicate when 4 critical
  flows need coverage). The original synthesizer was strict about
  every drift, which forced revision rounds that the LLMs couldn't
  reliably converge in 3 rounds — escalating to
  synthesize_fallback (the "no-fallback" design invariant the user
  has explicitly pinned: 用户原话 "fallback对系统不好").

  Each function below is forgiving along ONE axis of drift —
  enough to recover the LLM's evident intent without compromising
  the closed-by-construction contract the runtime needs.

API surface (kept narrow; call sites in cross_check_suite + run_kickoff +
facilitate import what they need):

  extract_backend_endpoints(backend)        # Fix #J: api_endpoints OR endpoints
  extract_frontend_screens(frontend)        # Fix #J: screens OR ui_pages
  api_call_key(call)                        # Fix #J: endpoint_id OR method+path
  coerce_facilitator_action(action)         # Fix #O: keyword recovery
  pick_feature_inventory(frontend, backend) # Fix #N: validator-shape preferred
  synthesize_task_tree(contract)            # Fix #N: from endpoints + tables
  ensure_critical_flow_coverage(preds, fl)  # Fix #P: stub for missing critical flows
  augment_drafts_for_coverage(drafts)       # Fix #P-bis: drafts-level wrap of the above
  is_protocol_decision(d, attendee_sections=None)  # Fix #H: stray-section filter
  endpoint_key(method, path)                # canonical "METHOD PATH" joiner

None of these functions perform I/O, hub calls, or LLM calls. All
take plain Mappings and return plain dicts / lists / strings.
Testable in isolation; the module ships its own test suite at
``agent/tests/test_kickoff_schema_tolerance.py``.

Naming: every helper is module-private in spirit (the call sites
should import the names they need), but no leading-underscore
prefix because tests + sibling kickoff modules both import them.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional

__all__ = [
    "PROTOCOL_FIXED_SECTIONS",
    "FACILITATOR_ACTIONS",
    "api_call_key",
    "augment_drafts_for_coverage",
    "coerce_facilitator_action",
    "endpoint_key",
    "ensure_critical_flow_coverage",
    "extract_backend_endpoints",
    "extract_frontend_screens",
    "is_critical_flow",
    "is_protocol_decision",
    "normalize_auth_shape",
    "normalize_feature_inventory",
    "normalize_task_entries",
    "pick_feature_inventory",
    "synthesize_task_tree",
]


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

# The 3 sections whose presence in a meeting page advances the
# protocol state regardless of attendee identity. Fix #H ignores
# decisions whose section is anything else for round-counting +
# phase-detection purposes — they're treated as metadata noise.
# (Attendee section names like "backend"/"frontend"/"verifier" are
# also protocol-relevant but are looked up dynamically from the
# meeting's attendee list via :func:`is_protocol_decision`.)
PROTOCOL_FIXED_SECTIONS: FrozenSet[str] = frozenset({
    "phase_ack",
    "comment",
    "facilitator_note",
})

# The 3 actions :func:`coerce_facilitator_action` may return. Fix #O
# maps invented LLM action strings to one of these via keyword
# inspection; anything genuinely unmappable defaults to ``escalate``.
FACILITATOR_ACTIONS = ("consensus", "request_revision", "escalate")


# Keyword sets used by :func:`coerce_facilitator_action`. Order
# matters: precedence is escalate > consensus > revision so that an
# LLM string mixing tokens picks the conservative-failure interpretation.
_ESCALATE_KEYWORDS = ("escalat", "abandon", "abort", "fail")
_CONSENSUS_KEYWORDS = (
    "accept", "approve", "consensus", "proceed",
    "ready", "finalize", "confirm", "recenter", "align",
)
_REVISION_KEYWORDS = ("revis", "rework", "amend", "redo")


# Kinds whose presence on a decision counts as "protocol vocabulary"
# even when the ``section`` field is empty / odd. Used by
# :func:`is_protocol_decision` as the final defensive fallback.
_PROTOCOL_KINDS: FrozenSet[str] = frozenset({
    "draft_section",
    "comment_phase_done",
    "reply_phase_done",
    "facilitator_decision",
})


# ---------------------------------------------------------------------------
# Endpoint / API call key helpers (Fix #J)
# ---------------------------------------------------------------------------


def endpoint_key(method: Any, path: Any) -> str:
    """Canonical ``METHOD PATH`` join (method uppercased; path stripped).

    The cross_check + finalize paths use this as the lookup key when
    matching frontend api_calls against backend endpoint declarations.
    Both sides MUST canonicalize identically — that's what this helper
    guarantees.
    """
    return f"{str(method).upper().strip()} {str(path).strip()}"


def api_call_key(call: Mapping[str, Any]) -> str:
    """Canonical lookup key for a frontend ``api_calls[*]`` entry.

    Round 8h Fix #J: real-LLM frontend writes api_calls entries in
    TWO shapes (sometimes both in the same section):

    1. Canonical pair: ``{method: "GET", path: "/api/posts"}``
    2. Shorthand id:   ``{endpoint_id: "GET /api/posts", purpose: ...}``

    Both forms canonicalize to the same ``METHOD PATH`` key here so
    the cross-check ``api_vs_frontend`` doesn't false-positive when
    a single section happens to mix them.

    Falls back to method+path if endpoint_id can't be parsed as
    ``"METHOD PATH"`` (single token, empty, etc.).
    """
    if not isinstance(call, Mapping):
        return endpoint_key(None, None)
    eid = call.get("endpoint_id")
    if isinstance(eid, str) and eid.strip():
        parts = eid.strip().split(None, 1)
        if len(parts) == 2:
            return endpoint_key(parts[0], parts[1])
    return endpoint_key(call.get("method"), call.get("path"))


def extract_backend_endpoints(backend: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Return the endpoint list from a backend section, accepting either
    ``api_endpoints`` or ``endpoints`` (Round 8h Fix #J).

    The kickoff_response_prompt's example shows ``api_endpoints`` but
    real-LLM backends frequently write ``endpoints`` (smoke #9-octavus
    + smoke #9-undecimus, 2026-06-02 / 2026-06-03). The strict
    extractor returned []; cross-checks then reported every frontend
    api_call as "undefined endpoint"; facilitator escalated. Both
    keys accepted now; ``api_endpoints`` preferred for back-compat
    with tests / pre-real-LLM fixtures.
    """
    if not isinstance(backend, Mapping):
        return []
    raw = backend.get("api_endpoints") or backend.get("endpoints") or []
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, Mapping)]


def extract_frontend_screens(frontend: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Return the screen list from a frontend section, accepting either
    ``screens`` or ``ui_pages`` (Round 8h Fix #J).

    Both keys exist in v3 frontend output depending on the prompt
    branch. Same forgiving posture as :func:`extract_backend_endpoints`.
    """
    if not isinstance(frontend, Mapping):
        return []
    raw = frontend.get("screens") or frontend.get("ui_pages") or []
    if not isinstance(raw, list):
        return []
    return [s for s in raw if isinstance(s, Mapping)]


# ---------------------------------------------------------------------------
# Feature inventory shape picker (Fix #N)
# ---------------------------------------------------------------------------


def pick_feature_inventory(
    frontend: Mapping[str, Any],
    backend: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the ``feature_inventory`` dict whose shape matches the
    roadmap validator's expectation ({entities, flows}).

    Round 8h Fix #N: frontend's v3 prompt sometimes emits a per-feature
    map (``{auth_login: {...}, post_compose: {...}}``) instead of the
    validator-shaped ``{entities, flows}`` pair. Backend writes the
    validator shape under its own ``feature_inventory``. This picker:

    1. Prefer frontend (charter §5 ownership) when its shape has
       ``entities`` or ``flows`` at top level.
    2. Otherwise prefer backend if its shape matches.
    3. Otherwise return frontend's wrong-shaped dict verbatim so the
       validator can surface a specific shape error against the
       canonical author (rather than silently dropping content).
    4. Fall through to {} only when neither side authored anything.
    """
    fe = frontend.get("feature_inventory") if isinstance(frontend, Mapping) else None
    if isinstance(fe, Mapping) and ("entities" in fe or "flows" in fe):
        return dict(fe)
    be = backend.get("feature_inventory") if isinstance(backend, Mapping) else None
    if isinstance(be, Mapping) and ("entities" in be or "flows" in be):
        return dict(be)
    if isinstance(fe, Mapping):
        return dict(fe)
    return {}


# ---------------------------------------------------------------------------
# Task tree synthesis (Fix #N)
# ---------------------------------------------------------------------------


def synthesize_task_tree(contract: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Build a minimum-viable task_tree from the contract.

    Round 8h Fix #N: frontend's v3 prompt suggests authoring a
    task_tree but doesn't enforce it; real-LLM frontends frequently
    leave it empty. The roadmap_validator then reports ``task_tree
    missing`` and the facilitator dispatches a frontend revision
    that just writes a task_tree from the contract — exactly what
    this synthesis would do. Synthesize from the upstream signals
    (endpoints + tables) at the synthesizer entrypoint so the LLM
    doesn't have to spend a round on derivable boilerplate.

    Tasks emitted:

      * one ``implement_endpoint`` task per declared contract endpoint,
        owner=backend, summary=``"Implement METHOD PATH"``,
        depends_on=[…linked-table-tasks…], status="pending"
      * one ``implement_table`` task per declared data_model table,
        owner=backend, summary=``"Implement table <name>"``,
        depends_on=[], status="pending"

    Tasks also carry validator-required ``depends_on`` (list) and
    ``status`` (str) fields per Round 8h Fix #R — roadmap_validator
    rejects entries lacking either. Endpoints that consume specific
    tables (per ``response.tables``) get those tables as their
    ``depends_on`` upstream — better DAG hint for downstream lane
    planning.

    Deterministic + idempotent: same contract → same task list.
    Malformed entries are skipped (not promoted to "garbage" tasks).
    """
    tasks: List[Dict[str, Any]] = []
    seen_ids: set = set()

    endpoints_raw = (
        contract.get("endpoints") if isinstance(contract, Mapping) else None
    ) or []
    # Round 8h adversarial-review follow-up: dedup endpoints by the
    # canonical (method, path) tuple BEFORE assigning task IDs. The
    # earlier impl used a munged id-string for dedup, which:
    #   1. silently dropped a SECOND endpoint whose raw path happened
    #      to munge to the same id ("/api/v1/users" + "/api_v1_users"
    #      both → "impl.endpoint.get._api_v1_users");
    #   2. when the same (method, path) was authored twice with
    #      different response.tables, the linking loop's `break` could
    #      bind to the first occurrence (no tables) and miss the second's
    #      tables — depends_on would end up empty.
    # We now collapse same-(method,path) duplicates by MERGING their
    # response.tables (last-writer-wins for other fields is fine; the
    # interesting signal is "what does this endpoint consume"), and
    # then disambiguate any post-munge id collision across DISTINCT
    # paths by appending a numeric suffix.
    seen_keys: Dict[tuple, Dict[str, Any]] = {}
    ordered_keys: List[tuple] = []
    for ep in endpoints_raw:
        if not isinstance(ep, Mapping):
            continue
        method = str(ep.get("method") or "").upper().strip()
        path = str(ep.get("path") or "").strip()
        if not method or not path:
            continue
        key = (method, path)
        response = ep.get("response") or {}
        tables_consumed: List[str] = []
        if isinstance(response, Mapping):
            raw_tables = response.get("tables") or []
            if isinstance(raw_tables, (list, tuple)):
                tables_consumed = [
                    str(t).strip() for t in raw_tables if str(t).strip()
                ]
        if key in seen_keys:
            for t in tables_consumed:
                if t not in seen_keys[key]["tables"]:
                    seen_keys[key]["tables"].append(t)
        else:
            seen_keys[key] = {"method": method, "path": path, "tables": list(tables_consumed)}
            ordered_keys.append(key)

    def _munge_path(method: str, path: str) -> str:
        return (
            f"impl.endpoint.{method.lower()}.{path}"
            .replace("/", "_")
            .replace("__", "_")
            .strip("_")
        )

    endpoint_table_links: Dict[str, List[str]] = {}
    for key in ordered_keys:
        rec = seen_keys[key]
        method, path = rec["method"], rec["path"]
        base = _munge_path(method, path)
        tid = base
        # Disambiguate munge collisions across DISTINCT (method, path)
        # pairs. Two different paths that munge to the same id get
        # `__2`, `__3`, ... suffixes — distinct tasks, distinct IDs.
        suffix = 2
        while tid in seen_ids:
            tid = f"{base}__{suffix}"
            suffix += 1
        seen_ids.add(tid)
        endpoint_table_links[tid] = rec["tables"]
        tasks.append({
            "id": tid,
            "owner": "backend",
            "kind": "implement_endpoint",
            "summary": f"Implement {method} {path}",
            "endpoint": {"method": method, "path": path},
            "depends_on": [],
            "status": "pending",
        })

    data_model = (contract.get("data_model") if isinstance(contract, Mapping) else None) or {}
    tables = data_model.get("tables") if isinstance(data_model, Mapping) else None
    table_task_ids: set = set()
    for t in tables or []:
        if not isinstance(t, Mapping):
            continue
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        tid = f"impl.table.{name}"
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        table_task_ids.add(tid)
        tasks.append({
            "id": tid,
            "owner": "backend",
            "kind": "implement_table",
            "summary": f"Implement table {name}",
            "table": name,
            "depends_on": [],
            "status": "pending",
        })

    # Round 8h Fix #R: link endpoint tasks to their consumed tables
    # via depends_on when the endpoint's response.tables names a known
    # table. We use the per-task ``endpoint_table_links`` we already
    # collected during dedup so collision-disambiguated tasks and
    # merged-across-duplicates table lists both reach the linker.
    for task in tasks:
        if task.get("kind") != "implement_endpoint":
            continue
        tid = task["id"]
        for tname in endpoint_table_links.get(tid, []):
            dep_tid = f"impl.table.{tname}"
            if dep_tid in table_task_ids and dep_tid not in task["depends_on"]:
                task["depends_on"].append(dep_tid)

    # Validation tasks for the verifier lane. Smoke #40-#42 surfaced
    # that the verifier had zero assigned tasks after kickoff — it
    # idled waiting for an explicit task_ready that the orchestrator
    # often forgot to send. Closing the gap structurally: emit one
    # validation task per concrete deliverable (endpoint smoke,
    # critical UI page smoke, critical flow journey).
    impl_endpoint_ids = {t["id"] for t in tasks if t.get("kind") == "implement_endpoint"}
    for key in ordered_keys:
        rec = seen_keys[key]
        method, path = rec["method"], rec["path"]
        impl_tid = _munge_path(method, path)
        # If munge collided we use the same disambiguation suffix;
        # find the actual impl task id by scanning.
        impl_match = next(
            (t for t in tasks
             if t.get("kind") == "implement_endpoint"
             and t.get("endpoint", {}).get("method") == method
             and t.get("endpoint", {}).get("path") == path),
            None,
        )
        depends = [impl_match["id"]] if impl_match else []
        vtid = f"validate.api_smoke.{method.lower()}.{path}".replace("/", "_").replace("__", "_").strip("_")
        suffix = 2
        base_vtid = vtid
        while vtid in seen_ids:
            vtid = f"{base_vtid}__{suffix}"
            suffix += 1
        seen_ids.add(vtid)
        tasks.append({
            "id": vtid,
            "owner": "verifier",
            "kind": "validate_api_smoke",
            "summary": f"Validate {method} {path} (api_smoke)",
            "endpoint": {"method": method, "path": path},
            "depends_on": depends,
            "status": "pending",
        })

    # Mechanism #52 (user decision: components DO get tasks — counts are
    # small): one impl.component.<id> task per declared ui_component; page
    # tasks depend on their referenced components' tasks, so "components
    # first, then the page" is STRUCTURAL (depends_on), not prose.
    ui_components_raw = (contract.get("ui_components") if isinstance(contract, Mapping) else None) or []
    component_task_ids: set = set()
    for c in ui_components_raw:
        if not isinstance(c, Mapping):
            continue
        cid = str(c.get("id") or "").strip()
        if not cid:
            continue
        ctid = f"impl.component.{cid}"
        if ctid in seen_ids:
            continue
        seen_ids.add(ctid)
        component_task_ids.add(ctid)
        tasks.append({
            "id": ctid,
            "owner": "frontend",
            "kind": "implement_component",
            "summary": f"Implement UI component `{cid}`",
            "ui_component": cid,
            "metadata": {
                "component": str(c.get("component") or ""),
                "apis_used": [str(a) for a in (c.get("apis_used") or [])],
                "children": [str(x) for x in (c.get("children") or [])],
            },
            "depends_on": [],
            "status": "pending",
        })

    ui_pages_raw = (contract.get("ui_pages") if isinstance(contract, Mapping) else None) or []
    # Mechanism #50 (user design 2026-06-11): the frontend mirrors the
    # backend's by-construction lifecycle — every declared ui_page gets an
    # ``impl.page.<name>`` task (kind=implement_page) carrying its declared
    # route/component/apis_used; the page registry entry starts ``defined``
    # and a deterministic auditor flips it to ``implemented`` (file exists +
    # route wired + declared APIs called + controls bound), which completes
    # this task via cross-hub sync — exactly how impl.table.* works.
    for p in ui_pages_raw:
        if not isinstance(p, Mapping):
            continue
        name = str(p.get("id") or p.get("name") or "").strip()
        if not name:
            continue
        ptid = f"impl.page.{name}"
        if ptid not in seen_ids:
            seen_ids.add(ptid)
            _page_deps = [f"impl.component.{str(r)}" for r in (p.get("components") or [])
                          if f"impl.component.{str(r)}" in component_task_ids]
            tasks.append({
                "id": ptid,
                "owner": "frontend",
                "kind": "implement_page",
                "summary": f"Implement UI page `{name}`",
                "description": (
                    "Build order: implement the page's declared COMPONENTS "
                    "first (each flips defined->implemented as the framework "
                    "audits the code), then compose the page, wire its route "
                    "and page-level APIs. The page reaches implemented (and "
                    "this task completes) only when its route is wired, its "
                    "APIs are referenced, controls are bound, AND every "
                    "referenced component is implemented."),
                "ui_page": name,
                "metadata": {
                    "route": str(p.get("route") or ""),
                    "component": str(p.get("component") or ""),
                    "apis_used": [str(a) for a in (p.get("apis_used")
                                                   or p.get("apis") or [])],
                    # carry the child-component references so the registered
                    # ui_page has them — frontend_audit's rollup (every
                    # referenced component must be implemented) is a no-op
                    # without this (silent failure, found in the round-37
                    # data-flow audit).
                    "components": [str(r) for r in (p.get("components") or [])],
                },
                "depends_on": _page_deps,
                "status": "pending",
            })
    for p in ui_pages_raw:
        if not isinstance(p, Mapping):
            continue
        if not p.get("critical"):
            continue
        name = str(p.get("id") or p.get("name") or "").strip()
        if not name:
            continue
        vtid = f"validate.ui_smoke.{name}"
        if vtid in seen_ids:
            continue
        seen_ids.add(vtid)
        tasks.append({
            "id": vtid,
            "owner": "verifier",
            "kind": "validate_ui_smoke",
            "summary": f"Validate UI page `{name}` (ui_smoke)",
            "ui_page": name,
            "depends_on": [],
            "status": "pending",
        })

    user_flows_raw = (contract.get("user_flows") if isinstance(contract, Mapping) else None) or []
    for f in user_flows_raw:
        if not isinstance(f, Mapping):
            continue
        if not is_critical_flow(f):
            continue
        name = str(f.get("id") or f.get("name") or "").strip()
        if not name:
            continue
        vtid = f"validate.ui_flow.{name}"
        if vtid in seen_ids:
            continue
        seen_ids.add(vtid)
        tasks.append({
            "id": vtid,
            "owner": "verifier",
            "kind": "validate_ui_flow",
            "summary": f"Validate critical flow `{name}` (ui_flow)",
            "user_flow": name,
            "depends_on": [],
            "status": "pending",
        })

    return tasks


# ---------------------------------------------------------------------------
# Predicate coverage synthesis (Fix #P + #P-bis)
# ---------------------------------------------------------------------------


_CRITICAL_TRUTHY_STRS = frozenset({"true", "yes", "1", "y", "t", "critical"})
_CRITICAL_FALSY_STRS = frozenset({"false", "no", "0", "n", "f", "", "null", "none"})
_CRITICAL_FIELD_ALIASES = ("critical", "is_critical", "priority", "importance")


def is_critical_flow(flow: Mapping[str, Any]) -> bool:
    """Round 8h adversarial-review follow-up: decide whether a
    user_flow entry should be treated as critical.

    Real-LLM authors drift across multiple axes for this one field:

      * key name: ``critical`` (canonical) | ``is_critical`` | ``priority`` |
        ``importance``
      * value type: bool | string ("true"/"yes"/"critical"/"false"/...) |
        int (1/0)
      * missing entirely (= not critical)

    Pre-fix, the kickoff path used a bare ``flow.get("critical")`` truthy
    check, which silently dropped any drifted shape. ``priority: "critical"``
    or ``is_critical: true`` both returned None → falsy → flow skipped → no
    coverage stub auto-written → cross_check ``test_strategy_coverage``
    failed → revision dispatched against the verifier when the real bug was
    upstream key-name drift. This helper paves over all four shapes so
    ``ensure_critical_flow_coverage`` and ``test_strategy_coverage`` (when
    routed through it) make the same call.

    Bias: when the value is an unrecognized string, treat as TRUTHY
    (matching ``runtime/flow_coverage.py``'s ``_is_truthy_critical``).
    "More flows required" is a louder, more triageable failure mode than
    "silently skipped critical flow".
    """
    if not isinstance(flow, Mapping):
        return False
    for key in _CRITICAL_FIELD_ALIASES:
        if key not in flow:
            continue
        value = flow[key]
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _CRITICAL_FALSY_STRS:
                return False
            if lowered in _CRITICAL_TRUTHY_STRS:
                return True
            # Unknown string → treat as truthy. priority="P0" / "must" /
            # "must-have" all read as critical-by-intent.
            return bool(lowered)
        # Non-string/non-bool/non-numeric (e.g. nested dict) → coerce.
        if value is None:
            continue
        return bool(value)
    return False


def ensure_critical_flow_coverage(
    predicates: Iterable[Mapping[str, Any]],
    user_flows: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Append stub ``api_smoke`` predicates for every critical
    ``user_flow.id`` that lacks coverage in ``predicates``.

    Round 8h Fix #P: real-LLM verifiers consistently under-author
    predicates (writing 1 when the requirements name 4 critical flows).
    test_strategy_coverage flagged each gap; facilitator dispatched
    verifier-only revisions; verifier added one more predicate per
    round; round budget exhausted; escalate. Even at
    reasoning_effort="high" (Fix #M) + prompt-level enumeration
    nudges (Fix #K), the LLM under-covers reliably.

    Stub shape: ``{id: "pred.<flow_id>.auto_coverage", flow: <id>,
    form: {kind: "api_smoke", body: {flow: <id>, auto: True}},
    source: "auto_coverage"}``. ``source="auto_coverage"`` is the
    audit marker — a code review of the contract can see which
    predicates were author-written vs synthesized and replace stubs
    with concrete checks during implementation.

    Idempotent: re-running the function on its own output is a no-op.
    """
    out: List[Dict[str, Any]] = []
    covered: set = set()
    for p in predicates or []:
        if not isinstance(p, Mapping):
            continue
        out.append(dict(p))
        flow = str(p.get("flow") or "").strip()
        if flow:
            covered.add(flow)
    for flow in user_flows or []:
        if not isinstance(flow, Mapping):
            continue
        if not is_critical_flow(flow):
            continue
        fid = str(flow.get("id") or "").strip()
        if not fid or fid in covered:
            continue
        out.append({
            "id": f"pred.{fid}.auto_coverage",
            "flow": fid,
            "form": {
                "kind": "api_smoke",
                "body": {"flow": fid, "auto": True},
            },
            "source": "auto_coverage",
        })
        covered.add(fid)
    return out


def augment_drafts_for_coverage(
    drafts: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Return a NEW drafts mapping where verifier predicates are
    augmented via :func:`ensure_critical_flow_coverage`. Other
    sections pass through verbatim.

    Round 8h Fix #P-bis: the cross_check_suite extractor reads
    ``drafts["verifier"]["predicates"]`` directly to run
    ``test_strategy_coverage``. If we only augmented in
    ``_build_roadmap`` (Fix #P's original landing spot), the
    cross-check still saw the raw predicates and failed. Augmenting
    drafts at the synthesizer entry makes BOTH consumers (cross-check
    + roadmap builder) see the same coverage-enriched view.

    Idempotent: re-augmenting an already-augmented drafts is a no-op.
    No mutation of the input mapping.
    """
    if not isinstance(drafts, Mapping):
        return {}
    out: Dict[str, Dict[str, Any]] = {
        section: dict(content) if isinstance(content, Mapping) else content
        for section, content in drafts.items()
    }
    verifier = out.get("verifier") or {}
    frontend = out.get("frontend") or {}
    if not isinstance(verifier, Mapping):
        return out
    # Round 8h adversarial-review follow-up: coerce a wrong-shape
    # ``verifier.predicates`` (dict, scalar, etc.) to a list BEFORE
    # passing to ensure_critical_flow_coverage. The downstream helper
    # tolerates ``predicates or []`` but iterates it — a dict iterates
    # its keys (strings), which then all fail the ``isinstance(p, Mapping)``
    # filter, silently dropping any LLM-authored predicate intent.
    # By coercing here we preserve as much of the LLM's intent as we
    # can recover: dict-shape predicates (keyed by flow id) are
    # converted to a list with the key plumbed back in as ``flow``.
    raw_predicates = verifier.get("predicates")
    coerced_predicates = _coerce_predicates_to_list(raw_predicates)
    augmented = ensure_critical_flow_coverage(
        coerced_predicates,
        frontend.get("user_flows") or [],
    )
    out["verifier"] = {**verifier, "predicates": augmented}
    return out


def _coerce_predicates_to_list(
    raw: Any,
) -> List[Dict[str, Any]]:
    """Best-effort coercion of a ``verifier.predicates`` value to a
    canonical ``List[Mapping]``.

    Round 8h adversarial-review follow-up: real-LLM verifier blocks
    occasionally write predicates as a dict keyed by flow id
    (``{"flow_a": {...}, "flow_b": {...}}``) instead of the contract's
    list shape. ``ensure_critical_flow_coverage`` defensively iterates
    on Mapping items, so a dict-shape input silently dropped every
    LLM-authored predicate. Here we:

      * pass list / tuple through, keeping only Mapping items
      * convert a dict to a list of its values, lifting the key into
        the value's ``flow`` field when the value lacks one
      * coerce a single Mapping to a one-element list
      * return ``[]`` for any other shape (scalars, strings, None)
    """
    if raw is None:
        return []
    if isinstance(raw, list) or isinstance(raw, tuple):
        return [dict(p) for p in raw if isinstance(p, Mapping)]
    if isinstance(raw, Mapping):
        # Dict-as-collection shape. The conventional shape is keyed by
        # flow id, so plumb the key into ``flow`` if the value didn't
        # already declare one.
        out: List[Dict[str, Any]] = []
        for key, value in raw.items():
            if not isinstance(value, Mapping):
                continue
            entry = dict(value)
            if not entry.get("flow"):
                entry["flow"] = str(key)
            out.append(entry)
        return out
    return []


# ---------------------------------------------------------------------------
# Roadmap-shape normalizers (Fix #R) — pre-validator hardening
# ---------------------------------------------------------------------------


def normalize_endpoint_response_shapes(
    endpoints: Iterable[Any],
) -> List[Any]:
    """Mechanism #38 (round 31, M3 死因): roadmap_validator requires
    ``endpoint.response.tables`` to be a list of non-empty strings, but a
    real-LLM draft wrote another shape — the reconcile cannot repair a
    contract finding, so the kickoff sat in status=conflict to the 1200s
    abort. Shape is FRAMEWORK territory: coerce deterministically here.

      * response not a Mapping            → drop the ``response`` key
      * tables str "users"                → ["users"]
      * tables Mapping {"users": …}       → its keys
      * tables list                       → keep non-empty strings only
      * coercion yields nothing           → drop ``tables`` (absent is
                                            vacuously aligned)
    """
    out: List[Any] = []
    for ep in endpoints:
        if not isinstance(ep, Mapping) or "response" not in ep:
            out.append(ep)
            continue
        ep = dict(ep)
        response = ep.get("response")
        if not isinstance(response, Mapping):
            ep.pop("response", None)
            out.append(ep)
            continue
        response = dict(response)
        if "tables" in response:
            tables = response["tables"]
            if isinstance(tables, str):
                tables = [tables]
            elif isinstance(tables, Mapping):
                tables = list(tables.keys())
            elif not isinstance(tables, list):
                tables = []
            tables = [t for t in tables if isinstance(t, str) and t.strip()]
            if tables:
                response["tables"] = tables
            else:
                response.pop("tables", None)
        ep["response"] = response
        out.append(ep)
    return out


def normalize_auth_shape(
    auth: Mapping[str, Any],
    endpoints: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Round 8h Fix #R: ensure ``contract.auth.required`` is a literal
    boolean.

    Real-LLM auth blocks variously omit ``required`` or write it as a
    string. roadmap_validator wants a strict bool. Coercion rules:

      * bool ``required``       → pass through
      * str ``required``        → coerce truthy (case-insensitive
                                  "true"/"yes"/"y"/"1") → True; else False
      * absent ``required``     → infer from endpoints: True iff ANY
                                  endpoint declares auth_required=True;
                                  else True (conservative default for
                                  any auth block that named a model)

    FRAMEWORK-OWNED AUTH FLOOR (youtube 2026-06-16): an empty/model-less
    auth block is floored to ``model="jwt"`` rather than returned empty.
    The generated stack ALWAYS embeds an OAuth2 AS minting JWTs (target
    arch), so a missing auth declaration is descriptive drift, not a real
    "no auth" signal — and ``roadmap_validator`` HARD-REQUIRES a non-empty
    ``contract.auth.model`` + bool ``required``. The old "return empty {}
    unchanged" behavior directly contradicted that gate: lanes that declared
    endpoints via the typed ``kickoff_declare_*`` tools (which carry no auth
    block) left ``contract.auth = {}`` → validate_roadmap failed every
    synthesis → kickoff looped to its 1200s timeout with zero recovery
    (the frontend-draft backstop only runs on the reconcile path, not the
    polling-synthesis path that ``_build_contract`` drives). Flooring here —
    the single point every contract flows through — makes the contract.auth
    shape valid by construction on BOTH paths. ``none`` is not used as the
    default because the framework provides JWT auth regardless of the spec.
    """
    out: Dict[str, Any] = dict(auth) if isinstance(auth, Mapping) else {}
    if not (isinstance(out.get("model"), str) and out["model"].strip()):
        out["model"] = "jwt"
    req = out.get("required")
    if isinstance(req, bool):
        return out
    if isinstance(req, str):
        out["required"] = req.strip().lower() in ("true", "yes", "y", "1")
        return out
    any_auth_required = False
    for ep in endpoints or []:
        if isinstance(ep, Mapping) and ep.get("auth_required") is True:
            any_auth_required = True
            break
    out["required"] = bool(any_auth_required) if any_auth_required else True
    return out


def normalize_task_entries(
    task_tree: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Round 8h Fix #R: ensure every task entry has the validator-
    required ``depends_on`` (list) and ``status`` (str) fields.

    Defaults: ``[]`` and ``"pending"``. Idempotent for already-valid
    tasks. Non-Mapping entries are skipped (not promoted to garbage).
    """
    out: List[Dict[str, Any]] = []
    for t in task_tree or []:
        if not isinstance(t, Mapping):
            continue
        normalized = dict(t)
        if not isinstance(normalized.get("depends_on"), list):
            normalized["depends_on"] = []
        status = normalized.get("status")
        if not isinstance(status, str) or not status.strip():
            normalized["status"] = "pending"
        out.append(normalized)
    return out


def normalize_feature_inventory(
    fi: Mapping[str, Any],
    contract: Mapping[str, Any],
    frontend: Mapping[str, Any],
) -> Dict[str, Any]:
    """Round 8h Fix #R: ensure ``feature_inventory`` has non-empty
    ``entities`` and ``flows`` lists.

    Picker semantics (see :func:`pick_feature_inventory`) determine
    the starting point; this function fills the canonical fields if
    they're empty/wrong-typed by deriving from upstream:

      * entities ← prefer ``fi.entities``; else
        ``contract.data_model.tables[*].name`` (each declared backend
        table is a feature-level entity)
      * flows ← prefer ``fi.flows``; else
        ``frontend.user_flows[*].id`` (each declared frontend flow is
        a feature-level flow)

    Any other keys in ``fi`` (e.g. the per-feature map the LLM wrote
    instead of the validator-shape) are preserved unchanged so the
    audit trail keeps the LLM's intent.
    """
    out: Dict[str, Any] = dict(fi) if isinstance(fi, Mapping) else {}
    entities = out.get("entities")
    if not isinstance(entities, list) or not entities:
        data_model = (contract.get("data_model") if isinstance(contract, Mapping) else None) or {}
        tables = data_model.get("tables") if isinstance(data_model, Mapping) else None
        derived: List[str] = []
        for t in tables or []:
            if isinstance(t, Mapping):
                name = str(t.get("name") or "").strip()
                if name and name not in derived:
                    derived.append(name)
        out["entities"] = derived
    flows = out.get("flows")
    if not isinstance(flows, list) or not flows:
        user_flows = frontend.get("user_flows") if isinstance(frontend, Mapping) else None
        derived: List[str] = []
        for fl in user_flows or []:
            if isinstance(fl, Mapping):
                fid = str(fl.get("id") or "").strip()
                if fid and fid not in derived:
                    derived.append(fid)
        out["flows"] = derived
    return out


# ---------------------------------------------------------------------------
# Facilitator action coercion (Fix #O)
# ---------------------------------------------------------------------------


_NEGATION_TOKENS = frozenset({"not", "no", "non", "dont", "don't", "doesn't", "without"})


def _tokenize_action(s: str) -> List[str]:
    """Split an action string on underscores / dashes / whitespace,
    keep non-empty lowercase tokens. ``"accept_revision_and_recenter"``
    → ``["accept", "revision", "and", "recenter"]``."""
    out: List[str] = []
    buf: List[str] = []
    for ch in s.lower():
        if ch.isalnum() or ch == "'":
            buf.append(ch)
        else:
            if buf:
                out.append("".join(buf))
                buf = []
    if buf:
        out.append("".join(buf))
    return out


def _token_matches_keyword(tokens: List[str], keywords: tuple) -> bool:
    """A keyword matches a token iff the token STARTS WITH the keyword
    prefix AND the immediately-preceding token is not a negation marker.

    Token-prefix (not substring) matching avoids ``escalat`` being seen
    inside ``deescalation`` or ``not_escalate``-style negations. The
    "preceding token isn't a negation" guard avoids
    ``not_escalate`` / ``don't escalate`` flipping into the escalate
    bucket when the author clearly meant the opposite.
    """
    for i, tok in enumerate(tokens):
        if not any(tok.startswith(k) for k in keywords):
            continue
        prev = tokens[i - 1] if i > 0 else ""
        if prev in _NEGATION_TOKENS:
            continue
        return True
    return False


def coerce_facilitator_action(action: Any) -> str:
    """Map an LLM-invented action string to a canonical
    :data:`FACILITATOR_ACTIONS` value via keyword inspection.

    Round 8h Fix #O: the kickoff_facilitation_prompt enumerates the
    3 valid actions, but real-LLM runs (smoke #9-duodecimus, 2026-06-03)
    occasionally invent variants like ``accept_revision_and_recenter``
    whose rationale matches consensus semantics. Strict matching forced
    those through ``escalate`` → ``synthesize_fallback`` → loud abort,
    which breaks the no-fallback design invariant.

    Precedence: escalate > consensus > revision.

      * escalate kws:  escalat, abandon, abort, fail
      * consensus kws: accept, approve, consensus, proceed, ready,
                       finalize, confirm, recenter, align
      * revision kws:  revis, rework, amend, redo

    Round 8h adversarial-review follow-up: matching is now
    token-prefix (not substring) and respects a one-token negation
    look-behind. ``not_escalate`` / ``do_not_escalate`` are not
    misclassified as escalate; ``de-escalation`` is no longer a
    spurious escalate match either (its leading token is ``de``,
    not ``escalat``).

    Consensus beats revision because tokens like
    ``accept_revision_and_recenter`` contain BOTH ``accept`` and
    ``revis`` — the dominant intent is acceptance of a prior revision,
    not a request for another. Escalate beats consensus because
    failure-signals (``fail_and_revise``) dominate any positive token
    in the same phrase.

    Canonical inputs (already in FACILITATOR_ACTIONS) pass through
    unchanged. Empty / non-string / undecipherable inputs default to
    ``escalate`` (the conservative fallback).
    """
    s = str(action or "").strip().lower()
    if not s:
        return "escalate"
    if s in FACILITATOR_ACTIONS:
        return s
    tokens = _tokenize_action(s)
    if _token_matches_keyword(tokens, _ESCALATE_KEYWORDS):
        return "escalate"
    if _token_matches_keyword(tokens, _CONSENSUS_KEYWORDS):
        return "consensus"
    if _token_matches_keyword(tokens, _REVISION_KEYWORDS):
        return "request_revision"
    return "escalate"


# ---------------------------------------------------------------------------
# Protocol decision filter (Fix #H)
# ---------------------------------------------------------------------------


def is_protocol_decision(
    d: Mapping[str, Any],
    attendee_sections: Optional[FrozenSet[str]] = None,
) -> bool:
    """A decision counts toward round/phase state iff its section
    is part of the protocol vocabulary.

    Round 8h Fix #H: smoke #9-septimus (2026-06-03 01:08) caught the
    orchestrator's facilitator LLM writing
    ``section="orchestrator" round=2`` off-script (a "summary" log
    entry the prompt didn't ask for). The original ``current_round``
    counted ALL decisions' round fields → returned 2 prematurely →
    driver skipped the request_revisions dispatch → meeting hung.

    Protocol vocabulary:

      * Fixed: phase_ack, comment, facilitator_note
      * Dynamic: any attendee section name (passed via
        ``attendee_sections`` — typically ``{"backend", "frontend",
        "verifier"}`` per the meeting's expected_attendees)
      * Defensive: any decision whose ``kind`` is in the kickoff vocab
        (draft_section / *_phase_done / facilitator_decision) — covers
        the edge case where an LLM wrote section="" but a sensible
        kind, which would otherwise orphan its phase_ack/section
    """
    if not isinstance(d, Mapping):
        return False
    sec = d.get("section") or (lambda _i: _i.get("section") if isinstance(_i, Mapping) else None)(d.get("decision"))
    if sec in PROTOCOL_FIXED_SECTIONS:
        return True
    if attendee_sections is not None and sec in attendee_sections:
        return True
    kind = d.get("kind") or (d.get("content") or {}).get("kind") or ""
    return kind in _PROTOCOL_KINDS
