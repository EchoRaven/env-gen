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
from typing import Any, Dict, List


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
            if _endpoint_norm(t) in impl_ep:
                continue
            reason = "endpoint not implemented in registry"
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


__all__ = ["format_delivery_gate_report", "delivery_gate_suggestions",
           "incomplete_required_tasks", "noncanonical_business_response_keys",
           "extract_spec_tables"]
