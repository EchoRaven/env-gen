"""DeliveryGate — delivery-gate logic extracted from Orchestrator (PROPOSAL #8 Tier-1a).

The gate is the read-only check that decides whether a generated env may be released
(contract alignment, build evidence, validation evidence, required files/dirs, hub
counts). It holds NO mutable orchestrator state — it reads output_dir + the hubs.

Slice 1 (this commit): the two PURE report formatters — `format_delivery_gate_report`
and `delivery_gate_suggestions` are pure functions of the gate dict (no `self`), so they
move verbatim as module-level functions. Orchestrator keeps thin shims so every caller
(run(), _maybe_framework_deliver, the coordination tick, tests) is unchanged.
Following slices move the validators (_validate_delivery_gate / _validate_contract_alignment
/ _incomplete_required_tasks / _extract_* / _validate_build_evidence) into a DeliveryGate
class constructed with (output_dir, hubs, logger) + the 3 cross-group callbacks
(get_validation_results / get_validation_summary / scaffold_design_readme).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def _norm_gate_path(p: Any) -> str:
    """Param-agnostic path key for milestone-scope matching: '/api/notes/{id}' ≡ '/api/notes/{}'."""
    s = str(p or "").split("?", 1)[0]
    s = re.sub(r"\{[^}]+\}|:[A-Za-z_][\w]*", "{}", s)
    return s.rstrip("/") or "/"


def scope_filter_incomplete(incomplete_tasks: List[Dict[str, Any]], scope_paths) -> List[Dict[str, Any]]:
    """§4 milestone-scoped gate: keep only incomplete structural tasks whose endpoint is in
    THIS milestone's slice; defer (drop) tasks for a clearly out-of-slice endpoint (a later
    milestone's surface). A task with NO identifiable endpoint is KEPT (never wrongly deferred).
    ``scope_paths`` empty/None ⇒ no filtering (full-app gate, byte-identical). PURE."""
    if not scope_paths:
        return incomplete_tasks
    keep_keys = {_norm_gate_path(p) for p in scope_paths}
    out: List[Dict[str, Any]] = []
    for t in incomplete_tasks:
        ep = (t.get("metadata") or {}).get("endpoint") or t.get("endpoint")
        path = ep.get("path") if isinstance(ep, dict) else (ep if isinstance(ep, str) else None)
        if path and _norm_gate_path(path) not in keep_keys:
            continue  # out-of-slice structural task → deferred to its own milestone
        out.append(t)
    return out

from .. import delivery as _contract


def delivery_gate_suggestions(gate: Dict[str, Any]) -> List[str]:
    """Map gate failures to concrete remediation suggestions."""
    suggestions: List[str] = []

    missing_files = set(gate.get("missing_files", []))
    missing_dirs = set(gate.get("missing_dirs", []))
    invalid_json = set(gate.get("invalid_json", []))
    failed_checks = set(gate.get("failed_checks", []))

    if "docker/docker-compose.yml" in missing_files:
        suggestions.append("Regenerate `docker/docker-compose.yml` and verify service ports/paths.")
    if "design/README.md" in missing_files:
        suggestions.append("Recreate `design/README.md` (kickoff-coordinator-authored).")

    if "app/backend" in missing_dirs or "backend_code_missing" in failed_checks:
        suggestions.append("Generate backend implementation files under `app/backend` before delivery.")
    if "app/frontend" in missing_dirs or "frontend_code_missing" in failed_checks:
        suggestions.append("Generate frontend implementation files under `app/frontend` before delivery.")
    if "app/database" in missing_dirs or "database_sql_missing" in failed_checks:
        suggestions.append("Create database SQL artifacts under `app/database` (e.g., schema/seed SQL).")

    if "no_endpoints_in_hub" in failed_checks:
        suggestions.append("Register API endpoints in hub using `update_endpoint(...)`.")
    if "no_tables_in_hub" in failed_checks:
        suggestions.append("Register DB tables in hub using `update_table(...)`.")
    if "no_pages_in_hub" in failed_checks:
        suggestions.append("Register UI pages via `workhub.update_ui_page(...)`.")
    if "no_implemented_endpoints" in failed_checks:
        suggestions.append("Mark at least one endpoint as implemented via `update_endpoint(key=..., status='implemented')`.")
    if "no_implemented_tables" in failed_checks:
        suggestions.append("Mark at least one table as implemented via `update_table(name=..., status='implemented')`.")
    if "verification_checklist_not_ready" in failed_checks:
        suggestions.append("Run and record verification/build checks until checklist is ready for delivery.")
    if "business_chain_missing" in failed_checks:
        suggestions.append(
            "Verifier: register real business-flow verification chains via "
            "`registryhub_register_verification_chain` (auth round-trip + one chain "
            "per critical flow: create -> read-back -> cross-user). The synthesized "
            "default does NOT satisfy delivery.")
    if "business_chain_failing" in failed_checks:
        suggestions.append(
            "Verifier: a registered verification chain is not passing — run_validation "
            "must show business_chain green. Fix the broken step or the endpoint, then re-run.")
    if "business_chain_api_coverage" in failed_checks:
        suggestions.append(
            "Verifier: every registered API endpoint must be exercised by at least one "
            "verification chain step. Add steps (or a new chain) until the union of all "
            "chains covers the whole API surface.")
    if "business_chain_coverage" in failed_checks:
        suggestions.append(
            "Verifier: author one business-flow verification chain per declared critical "
            "flow so every critical flow is covered (not just a subset).")
    if "validation_retry_pending" in failed_checks:
        suggestions.append(
            "Automatic smoke retry is still pending. Wait for retry completion and rerun delivery gate."
        )
    if "validation_api_smoke_missing" in failed_checks:
        suggestions.append(
            "Record at least one passed API smoke check via `record_validation_result(..., metadata={'check': 'api_smoke'})`."
        )
    if "validation_ui_smoke_missing" in failed_checks:
        suggestions.append(
            "Record at least one passed UI smoke check via `record_validation_result(..., metadata={'check': 'ui_smoke'})`."
        )
    if "contract_alignment_failed" in failed_checks:
        suggestions.append(
            "Resolve hub/code drift: align RegistryHub-registered endpoints + SchemaHub-registered tables with SQL schema and backend route definitions before delivery."
        )
    if "semantic_projection_errors" in failed_checks:
        suggestions.append(
            "Fix semantic projection errors recorded in hub, usually invalid or unsupported design/task spec structure."
        )
    if "frontend_build_not_recorded" in failed_checks:
        suggestions.append(
            "Run frontend build (`npm install && npm run build` in `app/frontend`) and record a passed `frontend_build` validation result."
        )
    if "deliverability_ui_flow_missing" in failed_checks:
        suggestions.append(
            "Each critical UI flow in WorkHub (explicit `critical_flows[]` "
            "or `pages` with `critical: true`) needs a passing `validation:ui_flow` "
            "record. Spawn a UI-flow tester worker (config_profile='verifier'); have "
            "it drive `browser_navigate` + at least one mutating step "
            "(`browser_click`/`browser_fill`) + `browser_screenshot`, then call "
            "`record_validation_result(task_id='ui_flow_<name>', status='passed', "
            "metadata={'check': 'ui_flow', 'flow': '<name>'})`."
        )
    if "deliverability_ui_flow_failed" in failed_checks:
        suggestions.append(
            "One or more critical UI flow tests failed. Inspect the failure evidence "
            "(`browser_console`, `browser_network_errors`, screenshot), file a bug "
            "via `bug_create(...)`, route to the owning agent, and re-run the flow "
            "test once fixed."
        )
    if "deliverability_critical_flows_invalid" in failed_checks:
        suggestions.append(
            "WorkHub `critical_flows[]` is present but every entry is "
            "unparseable (each entry must be either a `{\"name\": \"<slug>\", ...}` "
            "dict or a bare slug string). Fix the entries via frontend's "
            "kickoff section re-emit."
        )

    # Deduplicate while preserving order
    deduped: List[str] = []
    seen = set()
    for s in suggestions:
        if s not in seen:
            deduped.append(s)
            seen.add(s)
    return deduped


def format_delivery_gate_report(gate: Dict[str, Any]) -> str:
    """Format delivery gate result as a readable report."""
    if gate.get("ok", False):
        counts = gate.get("hub_counts", {})
        return (
            "Delivery gate passed.\n"
            f"- Endpoints: {counts.get('endpoints', 0)} "
            f"(implemented/tested: {counts.get('implemented_endpoints', 0)})\n"
            f"- Tables: {counts.get('tables', 0)} "
            f"(implemented/tested: {counts.get('implemented_tables', 0)})\n"
            f"- Pages: {counts.get('pages', 0)}"
        )

    state = gate.get("state", "failed")
    if state == "waiting_for_retry":
        lines = ["Delivery gate waiting for automatic retries:"]
    else:
        lines = ["Delivery gate failed:"]

    missing_files = gate.get("missing_files", [])
    if missing_files:
        lines.append(f"- Missing files: {', '.join(missing_files)}")

    missing_dirs = gate.get("missing_dirs", [])
    if missing_dirs:
        lines.append(f"- Missing directories: {', '.join(missing_dirs)}")

    invalid_json = gate.get("invalid_json", [])
    if invalid_json:
        lines.append(f"- Invalid JSON specs: {', '.join(invalid_json)}")

    failed_checks = gate.get("failed_checks", [])
    if failed_checks:
        lines.append(f"- Failed checks: {', '.join(failed_checks)}")

    contract_alignment = gate.get("contract_alignment", {})
    if contract_alignment:
        lines.append(
            "- Contract alignment: "
            f"expected_tables={contract_alignment.get('expected_tables', 0)}, "
            f"sql_tables={contract_alignment.get('sql_tables', 0)}, "
            f"declared_endpoints={contract_alignment.get('declared_endpoints', 0)}, "
            f"implemented_endpoints={contract_alignment.get('implemented_endpoints', 0)}"
        )
        for item in contract_alignment.get("errors", [])[:5]:
            lines.append(f"  • ERROR: {item}")
        for item in contract_alignment.get("warnings", [])[:5]:
            lines.append(f"  • WARN: {item}")

    semantic_drift = gate.get("semantic_hub_drift", {})
    if semantic_drift:
        lines.append(
            "- Semantic hub drift: "
            f"spec_endpoints={semantic_drift.get('spec_endpoints', 0)}, "
            f"hub_endpoints={semantic_drift.get('hub_endpoints', 0)}, "
            f"spec_tables={semantic_drift.get('spec_tables', 0)}, "
            f"hub_tables={semantic_drift.get('hub_tables', 0)}, "
            f"spec_pages={semantic_drift.get('spec_pages', 0)}, "
            f"hub_pages={semantic_drift.get('hub_pages', 0)}"
        )
        for item in semantic_drift.get("errors", [])[:5]:
            lines.append(f"  • ERROR: {item}")
        for item in semantic_drift.get("warnings", [])[:5]:
            lines.append(f"  • WARN: {item}")

    projection_errors = gate.get("projection_errors", {})
    if projection_errors:
        lines.append(f"- Projection errors: {len(projection_errors)}")
        for path, item in list(projection_errors.items())[:5]:
            lines.append(f"  • {path}: {item.get('error') if isinstance(item, dict) else item}")

    build_evidence = gate.get("build_evidence", {})
    if build_evidence:
        lines.append(
            "- Build evidence: "
            f"frontend_package={build_evidence.get('frontend_package', False)}, "
            f"frontend_build_recorded={build_evidence.get('frontend_build_recorded', False)}"
        )

    counts = gate.get("hub_counts", {})
    lines.append(
        "- hub counts: "
        f"endpoints={counts.get('endpoints', 0)} "
        f"(implemented={counts.get('implemented_endpoints', 0)}), "
        f"tables={counts.get('tables', 0)} "
        f"(implemented={counts.get('implemented_tables', 0)}), "
        f"pages={counts.get('pages', 0)}"
    )

    verification = gate.get("verification", {})
    checklist = verification.get("checklist", {}) if isinstance(verification, dict) else {}
    if checklist:
        status_pairs = []
        for key, item in checklist.items():
            status = item.get("status", "pending") if isinstance(item, dict) else "pending"
            status_pairs.append(f"{key}={status}")
        lines.append(f"- Verification checklist: {', '.join(status_pairs)}")

    runtime_validation = gate.get("validation_runtime", {})
    if runtime_validation:
        lines.append(
            "- Runtime validation: "
            f"task_suite={runtime_validation.get('task_suite_exists', False)}, "
            f"total_results={runtime_validation.get('total_results', 0)}, "
            f"api_smoke_pass={runtime_validation.get('api_smoke_pass', False)}, "
            f"ui_smoke_pass={runtime_validation.get('ui_smoke_pass', False)}, "
            f"retries_used_total={runtime_validation.get('retries_used_total', 0)}, "
            f"retry_pending={runtime_validation.get('retry_pending_count', 0)}, "
            f"retry_exhausted={runtime_validation.get('retry_exhausted_count', 0)}"
        )
        failed_top = runtime_validation.get("failed_top", [])
        if failed_top:
            lines.append("- Failed validation tasks (top):")
            for item in failed_top:
                lines.append(
                    "  • "
                    f"{item.get('task_id')} [{item.get('status')}] "
                    f"(domain_hint={item.get('domain_hint')}, mode={item.get('execution_mode')}) "
                    f"- {item.get('summary') or 'no summary'}"
                )

    suggestions = delivery_gate_suggestions(gate)
    if suggestions:
        lines.append("- Suggested fixes:")
        for s in suggestions:
            lines.append(f"  • {s}")

    return "\n".join(lines)


def incomplete_required_tasks(hubs) -> List[Dict[str, Any]]:
    """GATE-C2/C3: kickoff-synthesized STRUCTURAL tasks that are still
    pending/in_progress AND not satisfied by registry evidence.

    The delivery gate is an "evidence exists" model — it never checked
    whether the assigned work is DONE, so dozens of per-endpoint
    ``validate_api_smoke`` tasks (and any ``implement_*`` task) could linger
    pending while a release cut anyway (the user's "task not finished, why
    release" root cause).

    This is COVERAGE-AWARE, not status-naive — verified on the released
    generated/instagram round47: 24 ``validate_api_smoke`` tasks sat pending
    only because the verifier ran one ``run_validation()`` covering every
    endpoint instead of closing each per-endpoint task. Blocking on raw
    pending status would falsely block that good release. So a pending task
    blocks ONLY when its registry evidence is missing:

      * ``implement_endpoint``  → endpoint not registered implemented/tested
      * ``implement_table``     → table not registered implemented/tested
      * ``validate_api_smoke``  → endpoint has no passing contract-test record

    Ad-hoc ``task_*`` (visual / breaking-change / merge-conflict / chain-
    authoring remediation) are NOT structural kickoff kinds — they are
    governed by their own gates (visual deferral, deliverability) and are
    deliberately excluded here so this gate never double-blocks them.
    """
    wh = getattr(hubs, "workhub", None)
    if wh is None or not hasattr(wh, "list_tasks"):
        return []
    rh = getattr(hubs, "registryhub", None)
    sh = getattr(hubs, "schema_hub", None)
    try:
        tasks = wh.list_tasks() or []
    except Exception:
        return []

    def _norm(s: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

    # Registry endpoint identity → (clean_id, implemented?) keyed by the
    # normalized form so a task's metadata.endpoint OR its munged id both map.
    endpoints: Dict[str, Any] = {}
    try:
        endpoints = (rh.get_endpoints() if rh is not None else {}) or {}
    except Exception:
        endpoints = {}
    reg_clean: Dict[str, str] = {}
    impl_ep: set = set()
    for k, v in endpoints.items():
        if k == "_meta" or not isinstance(v, dict):
            continue
        # Deprecated endpoints are retired from the contract — do NOT count them as
        # "required" here. lifecycle.business_endpoints (and validation_ready) already
        # filter them out, so counting them only here makes delivery block on an
        # endpoint validation considers done (the deprecated-asymmetry: ready-yet-blocked).
        if v.get("status") == "deprecated":
            continue
        clean = (
            f"{(v.get('method') or '').upper()} {v.get('path') or ''}".strip()
            if v.get("method") else str(k)
        )
        nk = _norm(clean)
        reg_clean[nk] = clean
        if v.get("status") in {"implemented", "tested"}:
            impl_ep.add(nk)

    tables: Dict[str, Any] = {}
    try:
        tables = (sh.list_tables() if sh is not None else {}) or {}
    except Exception:
        tables = {}
    impl_tbl: set = {
        _norm(v.get("name") or k)
        for k, v in tables.items()
        if k != "_meta" and isinstance(v, dict)
        and v.get("status") in {"implemented", "tested"}
    }

    _METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

    def _endpoint_norm(t: Dict[str, Any]) -> str:
        ep = (t.get("metadata") or {}).get("endpoint") or t.get("endpoint")
        if isinstance(ep, dict) and ep.get("path"):
            return _norm(f"{(ep.get('method') or '').upper()} {ep['path']}")
        parts = str(t.get("id") or "").split(".")
        for i, p in enumerate(parts):
            if p.lower() in _METHODS and i + 1 < len(parts):
                return _norm(p + " " + ".".join(parts[i + 1:]))
        return _norm(t.get("id"))

    def _table_norm(t: Dict[str, Any]) -> str:
        name = (t.get("metadata") or {}).get("table") or t.get("table")
        if name:
            return _norm(name)
        tid = str(t.get("id") or "")
        return _norm(tid[len("impl.table."):] if tid.startswith("impl.table.") else tid)

    def _endpoint_validated(nk: str) -> bool:
        if rh is None:
            return False
        clean = reg_clean.get(nk)
        if not clean:  # endpoint not even registered → cannot be validated
            return False
        try:
            recs = rh.get_contract_test_results(clean) or []
            # PROPOSAL #44: contract-test records are stored under the
            # param-NAME-agnostic endpoint_id (``GET /api/notes/{}`` — the same
            # canonicalization as registryhub.endpoint_id / PROPOSAL #1/#29), but
            # ``clean`` carries the registry path form (``GET /api/notes/{id}``).
            # An exact-match lookup misses a PASSING test for an ``{id}`` endpoint,
            # so validate_api_smoke.*_{id} tasks are falsely "incomplete" and the
            # delivery gate (incomplete_required_tasks) blocks forever even though
            # the smoke test passed (smoke-notes run 2026-06-19). Fall back to the
            # canonical form so the passing record resolves.
            if not recs:
                canon = re.sub(r"\{[^}]+\}", "{}", clean)
                if canon != clean:
                    recs = rh.get_contract_test_results(canon) or []
        except Exception:
            return False
        return any(
            isinstance(r, dict)
            and ((r.get("result") or {}).get("passed") is True
                 or (r.get("result") or {}).get("verdict") == "pass")
            for r in recs
        )

    incomplete: List[Dict[str, Any]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("status") not in {"pending", "in_progress"}:
            continue
        kind = (t.get("metadata") or {}).get("kind") or t.get("kind")
        if kind == "implement_endpoint":
            _nk = _endpoint_norm(t)
            # Covered if the lane flipped the registry status, OR if api_smoke
            # PROVED the endpoint works — a passing contract-test record from
            # run_validation's live HTTP probe (the same evidence the
            # validate_api_smoke branch below trusts). The framework PROJECTS a
            # working handler for every registered endpoint and api_smoke probes
            # all of them, but the lane often never calls
            # register_endpoint(status='implemented'); without this, those
            # api_smoke-validated endpoints' impl tasks block delivery FOREVER
            # while the idle lanes can't self-heal (youtube run #19 deadlock:
            # 32 'defined' endpoints all passed api_smoke, gate wedged anyway).
            if _nk in impl_ep or _endpoint_validated(_nk):
                continue
            reason = "endpoint not implemented in registry and no passing contract-test record"
        elif kind == "implement_table":
            if _table_norm(t) in impl_tbl:
                continue
            reason = "table not implemented in registry"
        elif kind == "validate_api_smoke":
            if _endpoint_validated(_endpoint_norm(t)):
                continue
            reason = "endpoint has no passing contract-test record"
        else:
            continue  # not a structural kickoff task — governed elsewhere
        incomplete.append({
            "id": t.get("id"),
            "kind": kind,
            "status": t.get("status"),
            "assignee": t.get("assignee"),
            "reason": reason,
        })
    return incomplete


def _declared_critical_flows(hubs) -> List[str]:
    """Names of the DECLARED critical flows (the authoritative set the verifier
    must cover). Reuses ``compute_flow_coverage``'s inventory. Returns [] on any
    error so the coverage check degrades to a no-op rather than wedging the gate."""
    try:
        from .flow_coverage import compute_flow_coverage
        rep = compute_flow_coverage(hubs, None)
        return list(getattr(rep, "required", []) or [])
    except Exception:
        return []


def _uncovered_business_endpoints(rh, authored_chains: List[Dict[str, Any]]) -> List[str]:
    """Business endpoints (``METHOD /path``) NOT exercised by ANY authored chain
    step. Reuses ``registryhub.endpoint_id`` + the ``${var}``->``{x}`` collapse
    that ``register_verification_chain`` validates steps with, so a chain step
    ``/api/posts/${id}`` matches the registered ``/api/posts/{post_id}``
    (param-name-agnostic). Returns [] on any error so the check degrades to a
    no-op rather than wedging the gate."""
    try:
        from .lifecycle import business_endpoints
        required: Dict[str, str] = {}  # endpoint_id -> readable "METHOD /path"
        for ep in business_endpoints(rh.get_endpoints() or {}):
            m = str(ep.get("method") or "").upper()
            p = str(ep.get("path") or "")
            if m and p:
                required[rh.endpoint_id(m, p)] = f"{m} {p}"
        if not required:
            return []
        covered = set()
        for ch in authored_chains:
            for st in (ch.get("steps") or []):
                p = str(st.get("path") or "")
                if not p:
                    continue
                p = re.sub(r"\$\{[^}]+\}", "{x}", p)
                covered.add(rh.endpoint_id(str(st.get("method") or "GET"), p))
        return sorted(lbl for eid, lbl in required.items() if eid not in covered)
    except Exception:
        return []


def business_chain_blockers(hubs) -> Dict[str, Any]:
    """DELIVERY-QUALITY GATE (user 2026-06-24): what ships must be verified by a
    REAL business-flow verification chain, not just per-endpoint api_smoke. The
    verifier MUST author chains (``registryhub_register_verification_chain``) that
    exercise the business flows end-to-end. The framework's synthesized DEFAULT
    chain is a ``run_validation`` deadlock-breaker only — it is NEVER stored in the
    chain registry, so an empty ``get_verification_chains()`` proves the verifier
    authored none, and the default can never satisfy this gate.

    Returns ``{}`` when satisfied, else ``{"reason": <check>, "detail": <msg>, ...}``.
    Strictest tier (user choice): three blocking conditions —
      * ``business_chain_missing``  — verifier authored NO chain (registry empty)
      * ``business_chain_failing``  — an authored chain has not PASSED (never run,
                                      or last run left steps broken)
      * ``business_chain_coverage`` — fewer authored chains than declared critical
                                      flows (must cover every critical flow)
    """
    rh = getattr(hubs, "registryhub", None)
    if rh is None or not hasattr(rh, "get_verification_chains"):
        return {}
    try:
        chains = rh.get_verification_chains() or {}
    except Exception:
        return {}
    authored = [
        rec for name, rec in chains.items()
        if name != "_meta" and isinstance(rec, dict) and rec.get("steps")
    ]
    if not authored:
        return {
            "reason": "business_chain_missing", "authored": 0,
            "detail": ("no verifier-authored verification chain is registered — the "
                       "synthesized default does NOT satisfy delivery. The verifier "
                       "must register business-flow chains via "
                       "registryhub_register_verification_chain."),
        }
    not_passing = [
        str(rec.get("name") or rec.get("id"))
        for rec in authored
        if rec.get("status") != "passing"
        or (rec.get("last_result") or {}).get("broken")
    ]
    if not_passing:
        return {
            "reason": "business_chain_failing", "authored": len(authored),
            "chains": not_passing,
            "detail": (f"{len(not_passing)} verification chain(s) have NOT passed: "
                       + ", ".join(not_passing[:8]) + ". run_validation must show "
                       "business_chain green (re-author the broken step or fix the "
                       "endpoint) before delivery."),
        }
    # HARD RULE (user 2026-06-24): the UNION of all authored chains must exercise
    # EVERY business API endpoint at least once — the chains collectively cover the
    # whole API surface, not just happy-path flows. A registered endpoint that no
    # chain step touches is unverified and blocks delivery.
    uncovered = _uncovered_business_endpoints(rh, authored)
    if uncovered:
        return {
            "reason": "business_chain_api_coverage", "authored": len(authored),
            "uncovered": uncovered,
            "detail": (f"{len(uncovered)} registered API endpoint(s) are NOT exercised by "
                       "ANY verification chain — every business endpoint must appear in at "
                       "least one chain step: " + ", ".join(uncovered[:12])
                       + ("" if len(uncovered) <= 12 else f" (+{len(uncovered) - 12} more)")
                       + ". Add steps to existing chains or author a new chain to cover them."),
        }
    # NOTE: the per-flow chain-COUNT check was retired alongside the user_flow
    # migration (2026-06-22) — critical flows are now page-derived, so a count proxy
    # (chains >= flows) is no longer meaningful. The per-API coverage above is the
    # robust, concrete coverage guarantee (every endpoint exercised); authored+passing
    # + full API coverage is what delivery requires.
    return {}


def noncanonical_business_response_keys(hubs) -> List[Dict[str, Any]]:
    """PROMPT-C1 (response_key by-construction): a route_projector-projected
    business endpoint MUST declare a response_key inside the canonical envelope
    the projector actually emits — ``items`` (collection) or ``item`` (single).
    The projector hardcodes that envelope and IGNORES any other key, so a
    registered ``response_key='games'`` leaves the frontend reading
    ``data.games`` against a ``{"items": [...]}`` body → the single biggest
    blank-page source. Flag the non-canonical key at build time instead.

    Only the KEY VOCABULARY is enforced ({items, item}); WHICH of the two an
    endpoint should use (single vs collection) is the runtime
    ``business_endpoints_correct_shape`` gate's job — and is deliberately NOT
    re-derived here, because the method/path heuristic mis-classifies legit
    single-object GETs that don't end in ``/me`` or ``/{id}`` (round47's
    ``GET /api/.../insights`` / ``/limit`` / ``/business_discovery`` correctly
    return ``item``; demanding ``items`` for them would be a false positive).

    Scope = projector-owned BUSINESS endpoints only. Control-plane / infra /
    auth / oauth / spine endpoints carry a ``metadata.kind`` and ship their own
    handlers (e.g. ``{"message": ...}``) — NOT projected, frontend already skips
    them, exempt (round47's 3 ``message`` keys are all ``kind=infra``).
    custom_routes are hand-authored, exempt. An ABSENT response_key is a
    separate "lane forgot to set it" concern, not a wrong-key blank page, so it
    is not flagged here."""
    rh = getattr(hubs, "registryhub", None)
    if rh is None:
        return []
    try:
        endpoints = rh.get_endpoints() or {}
    except Exception:
        return []
    _CANONICAL = {"items", "item"}
    _EXEMPT_KINDS = {"auth", "oauth", "infra", "spine", "control_plane", "custom"}
    bad: List[Dict[str, Any]] = []
    for k, v in endpoints.items():
        if k == "_meta" or not isinstance(v, dict):
            continue
        md = v.get("metadata") or {}
        if str(md.get("kind") or "").strip().lower() in _EXEMPT_KINDS:
            continue  # not projector-owned (orchestrator/spine/custom handlers)
        if md.get("custom") or md.get("custom_route"):
            continue  # custom_routes are hand-authored, not projected
        rk = md.get("response_key") or (v.get("schema") or {}).get("response_key")
        if rk is None or rk in _CANONICAL:
            continue
        bad.append({
            "endpoint": k,
            "response_key": rk,
            "reason": (
                f"projected business endpoint declares non-canonical "
                f"response_key={rk!r} — the projector emits {{items/item}}, so the "
                f"frontend reading data.{rk} renders blank. Use 'items' or 'item'."
            ),
        })
    return bad


def extract_spec_tables(spec: Dict[str, Any]) -> Dict[str, set]:
    tables = spec.get("tables", {})
    out: Dict[str, set] = {}
    if isinstance(tables, dict):
        iterable = tables.items()
    elif isinstance(tables, list):
        iterable = ((t.get("name"), t) for t in tables if isinstance(t, dict))
    else:
        iterable = []
    for raw_name, table in iterable:
        name = str(raw_name or "").strip()
        if not name or not isinstance(table, dict):
            continue
        columns = table.get("columns", {})
        if isinstance(columns, dict):
            out[name] = {str(c) for c in columns.keys()}
        elif isinstance(columns, list):
            out[name] = {
                str(c.get("name"))
                for c in columns
                if isinstance(c, dict) and c.get("name")
            }
    return out

# Contract extraction lives in multi_agent/delivery/contract_extract.py. It is
# now STACK-PLUGGABLE (FastAPI + Express auto-detected) — see that module.


def validate_contract_alignment(output_dir, hubs) -> Dict[str, Any]:
    """Run lightweight static checks for design/DB/backend/API drift."""
    errors: List[str] = []
    warnings: List[str] = []

    # Sources of truth: RegistryHub for endpoints, SchemaHub for tables.
    hub_endpoints = hubs.registryhub.get_endpoints() or {}
    hub_tables = hubs.schema_hub.list_tables() or {}
    api_spec = {
        "endpoints": [
            {"method": ep.get("method"), "path": ep.get("path")}
            for ep in hub_endpoints.values()
            if isinstance(ep, dict) and ep.get("status") != "deprecated"
        ],
    }
    db_spec = {"tables": list(hub_tables.values())}

    expected_tables = extract_spec_tables(db_spec)
    sql_tables = _contract.extract_sql_tables(output_dir / "app/database")
    backend_sql_refs = _contract.extract_backend_sql_refs(output_dir / "app/backend")

    from .database_scaffold import _SPINE_OWNED_TABLES
    for table, expected_columns in sorted(expected_tables.items()):
        if str(table).lower() in _SPINE_OWNED_TABLES:
            # tenants/users/oauth_* are owned deterministically by the
            # tenancy spine (database_scaffold), not the contract — skip
            # column alignment so a contract-declared users table (which
            # the spine intentionally replaces) doesn't false-error.
            continue
        if not expected_columns:
            # Hub knows of the table but hasn't registered columns
            # yet (early/minimal state). Skip column-level alignment.
            continue
        actual_columns = sql_tables.get(table)
        if actual_columns is None:
            errors.append(f"SQL schema missing registered table: {table}")
            continue
        missing_columns = sorted(expected_columns - actual_columns)
        if missing_columns:
            errors.append(f"SQL table `{table}` missing registered columns: {', '.join(missing_columns[:8])}")

    for table, referenced_columns in sorted(backend_sql_refs.items()):
        actual_columns = sql_tables.get(table)
        if not actual_columns:
            warnings.append(f"Backend references table `{table}` but SQL schema did not define it.")
            continue
        missing_columns = sorted(referenced_columns - actual_columns)
        if missing_columns:
            errors.append(f"Backend references missing SQL columns on `{table}`: {', '.join(missing_columns[:8])}")

    declared_endpoints = _contract.extract_api_endpoints(api_spec)
    implemented_endpoints = _contract.extract_backend_routes(output_dir / "app/backend")
    # Param-agnostic match so {id}/:id/${id} + stack differences don't false-flag.
    declared_keys = {_contract.param_agnostic(e): e for e in declared_endpoints}
    impl_keys = {_contract.param_agnostic(r) for r in implemented_endpoints}
    if declared_endpoints and implemented_endpoints:
        missing_endpoints = sorted(e for k, e in declared_keys.items() if k not in impl_keys)
        if missing_endpoints:
            warnings.append(
                "Backend route coverage missing declared endpoints: "
                + ", ".join(missing_endpoints[:10])
            )

    # Code-derived consumer gate (P0, contract_enforcement_and_lifecycle_design §A2):
    # every BUSINESS API call in the generated frontend MUST hit a registered
    # endpoint. Phase 3b.6: the auth/oauth surface (oauth_scaffold), the spine
    # tables (database_scaffold) and the tenant/health control plane
    # (control_plane) are now REGISTERED in RegistryHub by _register_contract_surface
    # — so a frontend call to /auth/login or /api/v1/reset matches a real
    # declared endpoint and needs no hardcoded path exemption (consistency-by-
    # construction replaces the old _INFRA prefix list). The only residual
    # exemption is the EXTERNAL central IdP (/idp) used by the google-idp env
    # variant — it is a foreign service, never an endpoint of THIS env.
    frontend_calls = _contract.extract_frontend_calls(output_dir / "app/frontend")
    _EXTERNAL = ("/idp",)
    # Match on PATH (param-agnostic), METHOD-tolerant. A static scan can't
    # reliably tell a fetch's method from a React-Router route path (a `/auth/
    # login` *page* route looks like `GET /auth/login`), so requiring a
    # method-exact match false-flags registered endpoints as "unregistered".
    # The api_smoke gate (authoritative — it boots the app and probes every
    # registered endpoint with its real method) already validated the surface,
    # so here flag only a call whose PATH has NO registered endpoint at all —
    # that is the genuine frontend↔contract drift this gate exists to catch.
    def _pa_path(mp: str) -> str:
        pa = _contract.param_agnostic(mp)
        return pa.split(" ", 1)[1] if " " in pa else pa
    declared_path_keys = {_pa_path(e) for e in declared_endpoints}
    unregistered_calls = []
    for call in sorted(frontend_calls):
        path = call.split(" ", 1)[1] if " " in call else call
        if any(path == pre or path.startswith(pre + "/") for pre in _EXTERNAL):
            continue
        if declared_path_keys and _pa_path(call) not in declared_path_keys:
            unregistered_calls.append(call)
    if unregistered_calls:
        errors.append(
            "Frontend calls unregistered endpoint(s) (register in RegistryHub): "
            + ", ".join(unregistered_calls[:10])
        )

    return {
        "errors": errors[:20],
        "warnings": warnings[:20],
        "expected_tables": len(expected_tables),
        "sql_tables": len(sql_tables),
        "declared_endpoints": len(declared_endpoints),
        "implemented_endpoints": len(implemented_endpoints),
        "frontend_calls": len(frontend_calls),
        "frontend_call_unregistered": len(unregistered_calls),
    }


def validate_build_evidence(output_dir, get_validation_results) -> Dict[str, Any]:
    """Check whether generated projects have recorded build validation."""
    frontend_package = output_dir / "app/frontend/package.json"
    validation_results = get_validation_results(limit=200) or []
    frontend_build_recorded = any(
        isinstance(r, dict)
        and r.get("status") == "passed"
        and (
            r.get("metadata", {}).get("check") == "frontend_build"
            or "npm run build" in str(r.get("summary", "")).lower()
        )
        for r in validation_results
    )
    return {
        "frontend_package": frontend_package.exists(),
        "frontend_build_recorded": frontend_build_recorded,
    }


def validate_delivery_gate(output_dir, hubs, session_start_ts, logger, *,
                           scaffold_design_readme, get_validation_results,
                           get_validation_summary,
                           milestone_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Validate objective delivery readiness.

    Gate design:
    1) Required artifacts must exist (compose + README).
    2) Generated code footprint must exist for backend/frontend/database.
    3) RegistryHub / SchemaHub / WorkHub must contain registered contract entries.
    4) Contract alignment: registered endpoints/tables match implemented code.
    5) If build checklist has recorded results, it must be ready_for_delivery.
    """
    # Guarantee the required design doc exists before checking (also scaffolded
    # each heal tick; this covers the resumed-complete checkpoint path).
    scaffold_design_readme()
    required_files = [
        "docker/docker-compose.yml",
        "design/README.md",
    ]
    required_dirs = [
        "app/backend",
        "app/frontend",
        "app/database",
    ]

    missing_files: List[str] = []
    invalid_json: List[str] = []
    missing_dirs: List[str] = []
    failed_checks: List[str] = []

    for rel in required_files:
        p = output_dir / rel
        if not p.exists():
            missing_files.append(rel)

    for rel in required_dirs:
        p = output_dir / rel
        if not p.exists() or not p.is_dir():
            missing_dirs.append(rel)

    # Basic code footprint checks
    backend_has_code = any((output_dir / "app/backend").glob("**/*.*"))
    frontend_has_code = any((output_dir / "app/frontend").glob("**/*.*"))
    database_has_sql = any((output_dir / "app/database").glob("**/*.sql"))
    if not backend_has_code:
        failed_checks.append("backend_code_missing")
    if not frontend_has_code:
        failed_checks.append("frontend_code_missing")
    if not database_has_sql:
        failed_checks.append("database_sql_missing")

    # A deterministically functionally-validated app — a successful in-session
    # RunHub run (the framework's api_smoke: clean docker boot that BUILT the
    # frontend+backend, then probed every endpoint) — has already PROVEN both
    # contract alignment and the frontend build at runtime. So the static
    # contract-alignment check and the frontend_build RECORD (verifier
    # bookkeeping the LLM drifts on) become warnings, not hard delivery
    # blockers. They still block when the app is NOT functionally validated.
    _session_ts = session_start_ts or 0.0
    _runhub = getattr(hubs, "runhub", None)
    functionally_validated = bool(
        _runhub is not None
        and hasattr(_runhub, "last_successful_run_since")
        and _runhub.last_successful_run_since(_session_ts)
    )

    contract_report = validate_contract_alignment(output_dir, hubs)
    if contract_report.get("errors") and not functionally_validated:
        failed_checks.append("contract_alignment_failed")

    build_report = validate_build_evidence(output_dir, get_validation_results)
    if (build_report.get("frontend_package")
            and not build_report.get("frontend_build_recorded")
            and not functionally_validated):
        failed_checks.append("frontend_build_not_recorded")

    # hub topology checks
    endpoints = hubs.registryhub.get_endpoints() or {}
    tables = hubs.schema_hub.list_tables() or {}
    pages = hubs.registryhub.list_ui_pages() or {}
    projection_errors = {}  # file-coordination CRDT removed in Cutover 4 (replaced by git worktree)
    semantic_drift = {"errors": [], "warnings": []}  # vestigial — specs no longer exist as independent source.

    if not endpoints:
        failed_checks.append("no_endpoints_in_hub")
    if not tables:
        failed_checks.append("no_tables_in_hub")
    if not pages:
        failed_checks.append("no_pages_in_hub")
    if semantic_drift.get("errors"):
        failed_checks.append("semantic_hub_drift")
    if projection_errors:
        failed_checks.append("semantic_projection_errors")

    implemented_endpoints = sum(
        1 for v in endpoints.values()
        if isinstance(v, dict) and v.get("status") in {"implemented", "tested"}
    )
    implemented_tables = sum(
        1 for v in tables.values()
        if isinstance(v, dict) and v.get("status") in {"implemented", "tested"}
    )
    if implemented_endpoints == 0:
        failed_checks.append("no_implemented_endpoints")
    if implemented_tables == 0:
        failed_checks.append("no_implemented_tables")

    # Build verification checklist from CodeHub.checks directly (hubs.get_verification_checklist removed)
    try:
        build_checks = [
            c for c in hubs.codehub.list_checks()
            if c.get("name", "").startswith("build:")
        ]
        by_component: dict = {}
        for c in build_checks:
            comp = c.get("name", "").removeprefix("build:")
            prev = by_component.get(comp)
            if prev is None or c.get("updated_at", 0) > prev.get("updated_at", 0):
                by_component[comp] = c.get("status", "pending")
        checklist_statuses_map = {
            "sql_syntax": by_component.get("database", "pending"),
            "docker_build": by_component.get("docker", "pending"),
            "npm_install": by_component.get("frontend", "pending"),
            "backend_start": by_component.get("backend", "pending"),
        }
        all_passing = all(s == "success" for s in checklist_statuses_map.values())
        checklist = {
            "checklist": {k: {"status": v} for k, v in checklist_statuses_map.items()},
            "all_required_passing": all_passing,
            "ready_for_delivery": all_passing,
        }
    except Exception:
        checklist = {"checklist": {}, "all_required_passing": False, "ready_for_delivery": False}
    checklist_items = checklist.get("checklist", {})
    statuses = [
        item.get("status", "pending")
        for item in checklist_items.values()
        if isinstance(item, dict)
    ]
    any_recorded = any(s != "pending" for s in statuses)
    if any_recorded and not checklist.get("ready_for_delivery", False):
        failed_checks.append("verification_checklist_not_ready")

    # Runtime validation matrix (if task suite exists):
    # require at least one API smoke pass and one UI smoke pass.
    task_suite_exists = (output_dir / "tasks" / "tasks.yaml").exists()
    validation_summary = get_validation_summary() or {}
    validation_results = get_validation_results(limit=200) or []
    retry_pending_count = int(validation_summary.get("retry_pending_count", 0) or 0)
    api_smoke_pass = any(
        isinstance(r, dict)
        and r.get("status") == "passed"
        and r.get("metadata", {}).get("check") in {"api_smoke", "api_health"}
        for r in validation_results
    )
    ui_smoke_pass = any(
        isinstance(r, dict)
        and r.get("status") == "passed"
        and r.get("metadata", {}).get("check") in {"ui_smoke", "ui_page_reachable"}
        for r in validation_results
    )
    failed_validation_top = [
        {
            "task_id": r.get("task_id"),
            "status": r.get("status"),
            "summary": r.get("summary", ""),
            "domain_hint": (
                (r.get("metadata", {}) or {}).get("domain")
                or (r.get("evidence", {}) or {}).get("domain")
                or "any"
            ),
            "execution_mode": r.get("execution_mode", "auto"),
        }
        for r in validation_results
        if isinstance(r, dict) and r.get("status") in {"failed", "error"}
    ][:5]
    if task_suite_exists:
        if retry_pending_count > 0:
            # Soft-fail: auto-retry loop is still in progress.
            failed_checks.append("validation_retry_pending")
        else:
            if not api_smoke_pass:
                failed_checks.append("validation_api_smoke_missing")
            if not ui_smoke_pass:
                failed_checks.append("validation_ui_smoke_missing")

    # PR 6 review (2026-05-30) follow-up: fold the
    # deliverability aggregator into the autonomous hard gate.
    # ``compute_deliverability`` was previously only consumed by
    # the UI-driven deliver path (``deliver_project_call`` in
    # live_monitor_server). The autonomous / LLM-driven deliver
    # path enforced retro (via ``RetroBeforeDeliverPolicy``) and
    # the topology/build checks above, but NOT visual-critical
    # approval, seed data, RunHub-successful-run-since-session,
    # or coverage dead-artifact detection. The original in-tool
    # gates in ``DeliverProjectTool.execute`` intended to enforce
    # those four — but were dead-wired (``self.agent.hub_registry``
    # vs the real ``self.agent._hubs``); the 2026-05-30 cleanup
    # commit deleted them. Folding here closes the
    # autonomous-vs-UI enforcement asymmetry by reusing the SAME
    # aggregator both paths now share. Single enforcement point,
    # consistent with the architectural pattern from the
    # two-pass dispatcher and GateRegistry extraction.
    deliverability_failed_checks: List[str] = []
    try:
        from .deliverability import compute_deliverability
        session_start_ts = session_start_ts or 0.0
        app_root = output_dir / "app"
        if not app_root.exists():
            app_root = output_dir
        deliverability_report = compute_deliverability(
            hubs, app_root, session_start_ts=session_start_ts,
        )
        for blocker in (deliverability_report.blockers or []):
            # Canonicalize: blocker strings are human prose; map
            # them onto stable check tokens the test surface
            # can assert against. Each token names the failed
            # dimension; the full prose remains in
            # ``deliverability_report`` returned below for the
            # operator-facing log.
            low = blocker.lower()
            if "no successful runhub run" in low:
                deliverability_failed_checks.append("deliverability_no_successful_run")
            elif "failed endpoint probe" in low:
                deliverability_failed_checks.append("deliverability_failed_endpoint_probes")
            elif "failed mcp probe" in low:
                deliverability_failed_checks.append("deliverability_failed_mcp_probes")
            elif "dead artifact" in low:
                deliverability_failed_checks.append("deliverability_dead_artifacts")
            elif "missing seed" in low:
                deliverability_failed_checks.append("deliverability_missing_seed")
            elif "low row count" in low or "placeholder seed" in low:
                deliverability_failed_checks.append("deliverability_seed_quality")
            elif "critical visual review" in low and "pending" in low:
                deliverability_failed_checks.append("deliverability_critical_visuals_pending")
            elif "critical visual review" in low and "need revision" in low:
                deliverability_failed_checks.append("deliverability_critical_visuals_needs_revision")
            elif "critical_flows" in low and "unparseable" in low:
                deliverability_failed_checks.append("deliverability_critical_flows_invalid")
            elif "ui flow(s) failed" in low:
                # Anchor on the FULL prefix emitted by
                # ``_flow_coverage_summary`` (``"N critical UI
                # flow(s) failed:"``) so a flow whose NAME
                # contains the substring "missing" (e.g.
                # ``recover_missing_password``) doesn't collide
                # with the missing-branch elif. Check failed
                # FIRST: ``ui flow(s) failed`` doesn't appear in
                # the missing-branch prose; ``missing`` can
                # appear in the failed-branch prose if a flow
                # name has it.
                deliverability_failed_checks.append("deliverability_ui_flow_failed")
            elif "ui flow(s) missing" in low:
                deliverability_failed_checks.append("deliverability_ui_flow_missing")
            elif "declared but unusable" in low:
                # B1: a declared ui_page whose route isn't wired in App.jsx
                # or whose component file is absent (round 44 blank-screen
                # class). Deterministic, NOT relaxed on functionally_validated.
                deliverability_failed_checks.append("deliverability_ui_page_unwired")
            else:
                # Unmapped blocker — surface verbatim under a
                # catch-all so the operator sees it instead of
                # silently dropping; future canonicalization
                # work can move it into a named token.
                deliverability_failed_checks.append(
                    f"deliverability_other:{blocker[:80]}"
                )
    except Exception as deliv_err:
        # Defense in depth: a malformed aggregator call must
        # never crash the gate. Surface the exception as its
        # own failure so the gap stays visible.
        try:
            logger.warning(
                f"compute_deliverability raised inside delivery gate: {deliv_err}"
            )
        except Exception:
            pass
        deliverability_failed_checks.append("deliverability_compute_failed")
        deliverability_report = None

    failed_checks.extend(deliverability_failed_checks)

    # GATE-C2/C3 (2026-06-12): task-completeness HARD check. The gate above
    # proves "evidence exists"; this proves "the assigned structural work is
    # DONE". Coverage-aware (see _incomplete_required_tasks) so it never
    # blocks a run_validation-covered endpoint whose per-endpoint task was
    # left open. NOT relaxed by functionally_validated — an un-evidenced
    # implement_*/validate task is genuine incomplete work, not bookkeeping.
    incomplete_tasks = incomplete_required_tasks(hubs)
    # §4: when a milestone slice is provided (intermediate milestone), defer structural tasks
    # for a clearly out-of-slice endpoint — an intermediate milestone is gated on ITS OWN
    # surface, not the whole app. Empty/None scope ⇒ no filtering (full-app, byte-identical).
    if milestone_scope:
        _before = len(incomplete_tasks)
        incomplete_tasks = scope_filter_incomplete(
            incomplete_tasks, (milestone_scope or {}).get("endpoint_paths"))
        if logger and len(incomplete_tasks) != _before:
            logger.warning("milestone-scoped delivery gate: deferred %d out-of-slice structural task(s)",
                           _before - len(incomplete_tasks))
    if incomplete_tasks:
        failed_checks.append("incomplete_required_tasks")

    # PROMPT-C1 (2026-06-12): response_key by-construction. A projected
    # business endpoint whose declared response_key isn't the canonical
    # items/item envelope the projector emits is a latent blank page —
    # catch it at the gate instead of at the user's screen.
    noncanonical_response_keys = noncanonical_business_response_keys(hubs)
    if noncanonical_response_keys:
        failed_checks.append("business_response_key_noncanonical")

    # DELIVERY-QUALITY (user 2026-06-24): what ships must be verified by a REAL,
    # PASSING, verifier-authored business-flow chain covering every critical flow
    # — not just shallow api_smoke, and never the synthesized default. The verifier
    # MUST author it; a miss blocks delivery and routes back (dispatch_gate_level_checks).
    business_chain_block = business_chain_blockers(hubs)
    if business_chain_block:
        failed_checks.append(business_chain_block["reason"])

    ok = not (missing_files or missing_dirs or invalid_json or failed_checks)
    soft_fail_only = (
        bool(failed_checks)
        and set(failed_checks).issubset({"validation_retry_pending"})
        and not (missing_files or missing_dirs or invalid_json)
    )
    gate_state = "ok" if ok else ("waiting_for_retry" if soft_fail_only else "failed")
    return {
        "ok": ok,
        "state": gate_state,
        "soft_fail_only": soft_fail_only,
        "missing_files": missing_files,
        "missing_dirs": missing_dirs,
        "invalid_json": invalid_json,
        "failed_checks": failed_checks,
        "incomplete_required_tasks": incomplete_tasks,
        "noncanonical_response_keys": noncanonical_response_keys,
        "business_chain": business_chain_block,
        "hub_counts": {
            "endpoints": len(endpoints),
            "tables": len(tables),
            "pages": len(pages),
            "implemented_endpoints": implemented_endpoints,
            "implemented_tables": implemented_tables,
        },
        "verification": checklist,
        "contract_alignment": contract_report,
        "semantic_hub_drift": semantic_drift,
        "projection_errors": projection_errors,
        "build_evidence": build_report,
        "deliverability": (
            deliverability_report.to_dict()
            if deliverability_report is not None else None
        ),
        "validation_runtime": {
            "task_suite_exists": task_suite_exists,
            "total_results": validation_summary.get("total", 0),
            "all_passed": validation_summary.get("all_passed", False),
            "api_smoke_pass": api_smoke_pass,
            "ui_smoke_pass": ui_smoke_pass,
            "retries_used_total": validation_summary.get("retries_used_total", 0),
            "retry_pending_count": validation_summary.get("retry_pending_count", 0),
            "retry_exhausted_count": validation_summary.get("retry_exhausted_count", 0),
            "failed_top": failed_validation_top,
        },
    }


__all__ = ["format_delivery_gate_report", "delivery_gate_suggestions",
           "incomplete_required_tasks", "noncanonical_business_response_keys",
           "business_chain_blockers",
           "extract_spec_tables", "validate_contract_alignment", "validate_build_evidence",
           "validate_delivery_gate"]
