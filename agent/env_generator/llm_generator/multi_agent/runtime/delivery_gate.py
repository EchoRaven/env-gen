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


__all__ = ["format_delivery_gate_report", "delivery_gate_suggestions"]
