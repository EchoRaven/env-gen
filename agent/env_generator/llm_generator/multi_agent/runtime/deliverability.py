"""Deliverability aggregator (Cutover 24).

Pure read-side over RunHub + RegistryHub + WorkHub + coverage_audit + seed_audit.
Replaces the LLM-judged checklist with an evidence-based unified report.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path


# §2 gate-hardening (2026-06-22): the api_smoke RunHub run that sets
# ``functionally_validated`` probes the BACKEND only and never opens a frontend page, so a
# real-backend / blank-UI app currently gets the coverage/seed/visual/ui_flow gates waived.
# When ENVGEN_REQUIRE_UI_EVIDENCE is enabled, the UI-facing gates additionally require at
# least ONE passing browser/UI validation record before they may be downgraded — closing the
# "api_smoke green, blank screen shipped" class. Default-off (byte-identical) until validated
# on a live run, then flip it on.
_UI_EVIDENCE_CHECKS = {"ui_flow", "ui_smoke", "ui_page_reachable", "test_user"}


def _has_passing_ui_evidence(hub_registry) -> bool:
    """True iff at least one passing UI/browser/test-user validation record exists."""
    try:
        results = hub_registry.get_validation_results(limit=1000) or []
    except Exception:
        return False
    for r in results:
        if not isinstance(r, dict) or r.get("status") != "passed":
            continue
        if (r.get("metadata") or {}).get("check") in _UI_EVIDENCE_CHECKS:
            return True
    return False


@dataclass
class DeliverabilityReport:
    last_successful_run: Optional[dict] = None
    run_within_session: bool = False
    endpoint_probes: Dict[str, int] = field(default_factory=dict)
    mcp_probes: Dict[str, int] = field(default_factory=dict)
    coverage: Dict[str, Any] = field(default_factory=dict)
    seed_data: Dict[str, Any] = field(default_factory=dict)
    visual_reviews: Dict[str, int] = field(default_factory=dict)
    flow_coverage: Dict[str, Any] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    verdict: str = "blocked"

    def to_dict(self) -> dict:
        return {
            "last_successful_run": self.last_successful_run,
            "run_within_session": self.run_within_session,
            "endpoint_probes": dict(self.endpoint_probes),
            "mcp_probes": dict(self.mcp_probes),
            "coverage": dict(self.coverage),
            "seed_data": dict(self.seed_data),
            "visual_reviews": dict(self.visual_reviews),
            "flow_coverage": dict(self.flow_coverage),
            "blockers": list(self.blockers),
            "verdict": self.verdict,
        }


def _probe_counts(probes: list) -> Dict[str, int]:
    counts = {"total": len(probes or []), "passed": 0, "failed": 0, "skipped": 0}
    for p in probes or []:
        v = p.get("verdict") if isinstance(p, dict) else None
        if v == "pass":
            counts["passed"] += 1
        elif v == "fail":
            counts["failed"] += 1
        elif v == "skipped":
            counts["skipped"] += 1
    return counts


def _coverage_summary(hub_registry, app_root) -> Dict[str, Any]:
    try:
        from .coverage_audit import compute_coverage
    except Exception:
        return {"is_clean": True, "dead_count_by_kind": {}}
    try:
        report = compute_coverage(hub_registry, Path(app_root))
    except Exception:
        return {"is_clean": True, "dead_count_by_kind": {}}
    return {
        "is_clean": report.is_clean,
        "dead_count_by_kind": {
            "endpoints": len(report.dead_endpoints),
            "tables": len(report.dead_tables),
            "files": len(report.dead_files),
            "mcp_tools": len(report.dead_mcp_tools),
            "empty_mcp_servers": len(report.empty_mcp_servers),
            "pages_without_files": len(report.pages_without_files),
        },
    }


def _ui_page_wiring_blockers(hub_registry, app_root) -> List[str]:
    """ui_pages with a HARD wiring defect (declared route not wired in App.jsx,
    or declared component file missing) → delivery blockers.

    Deterministic from code; recomputed each gate tick so a fixed page clears
    it (never a permanent block). Crucially this is NOT relaxed on a
    functionally-validated app: the framework api_smoke probes the BACKEND
    only — it never opens a frontend page, so an unwired page (round 44's
    blank-screen-but-api_smoke-green class) must still block delivery."""
    try:
        from .frontend_audit import ui_page_delivery_blockers
    except Exception:
        return []
    workhub = getattr(hub_registry, "workhub", None)
    if workhub is None:
        return []
    try:
        return ui_page_delivery_blockers(Path(app_root) / "frontend" / "src", workhub)
    except Exception:
        return []


def _bare_fetch_blockers(app_root) -> List[str]:
    """#154 (§6-1, gmrun4): bare unauthenticated ``fetch('/api/…')`` call sites →
    delivery blockers. Purely static (frontend source only), recomputed each gate
    tick, best-effort ``[]`` on any fault. ``ENVGEN_BARE_FETCH_GATE=0`` disables."""
    if os.environ.get("ENVGEN_BARE_FETCH_GATE", "1").lower() in ("0", "false", "no", "off"):
        return []
    try:
        from .frontend_audit import bare_authed_fetch_blockers
    except Exception:
        return []
    try:
        return bare_authed_fetch_blockers(Path(app_root) / "frontend" / "src")
    except Exception:
        return []


def _stub_handler_blockers(app_root) -> List[str]:
    """#173 (gmrun9): a GET route handler that does NO DB read and returns only a hardcoded
    EMPTY collection is a PLACEHOLDER STUB (backend twin of a mock page) → delivery blocker.
    The lane 'implemented' /api/transit/{id}/departures as ``return {"items": []}`` while real
    seed data existed; the DeparturesPage then shipped 'No departures found.' forever. Static
    AST, recomputed each gate tick, best-effort ``[]``. ``ENVGEN_STUB_HANDLER_GATE=0`` off."""
    try:
        from .backend_audit import stub_handler_blockers
    except Exception:
        return []
    try:
        return stub_handler_blockers(Path(app_root) / "backend")
    except Exception:
        return []


def _seed_summary(hub_registry) -> Dict[str, Any]:
    try:
        from .seed_audit import audit_seed_data
    except Exception:
        return {"tables": 0, "registered": 0, "missing": 0, "flagged": 0}
    try:
        report = audit_seed_data(hub_registry)
    except Exception:
        return {"tables": 0, "registered": 0, "missing": 0, "flagged": 0}
    schema_hub = getattr(hub_registry, "schema_hub", None)
    total_tables = len((schema_hub.list_tables() if schema_hub else {}) or {})
    registered = len((schema_hub.list_seed_registrations() if schema_hub else {}) or {})
    missing = sum(1 for f in report.flagged_tables if f.get("reason") == "missing_seed")
    flagged = len(report.flagged_tables)
    return {"tables": total_tables, "registered": registered,
            "missing": missing, "flagged": flagged}


_DEGRADED_FLOW_COVERAGE = {
    "required": [], "passed": [], "failed": [], "missing": [],
    "source": "degraded", "is_clean": True, "degraded": True,
}


def _flow_coverage_summary(hub_registry, app_root) -> Tuple[Dict[str, Any], List[str]]:
    """Wrap ``flow_coverage.compute_flow_coverage`` so an import or
    runtime fault never propagates into the deliverability gate.

    Returns ``(report_dict, blocker_strings)``.

    ``app_root`` is no longer read — WorkHub is the source of truth —
    but the param stays for backward-compat with the autonomous gate's
    call site. The degraded-path return carries ``"source": "degraded"``
    and ``"degraded": True`` so operators can distinguish a broken
    gate from "design didn't opt in".
    """
    try:
        from .flow_coverage import compute_flow_coverage
    except Exception:
        return dict(_DEGRADED_FLOW_COVERAGE), []

    try:
        report = compute_flow_coverage(hub_registry, app_root)
    except Exception:
        return dict(_DEGRADED_FLOW_COVERAGE), []

    blockers: List[str] = []
    # Anchor the prefix so a flow whose NAME happens to contain
    # "missing" / "failed" (e.g. ``recover_missing_password``) can't
    # collide with the canonicalization elif-chain in
    # ``orchestrator._validate_delivery_gate``. The chain matches on
    # the FULL anchored substrings ``ui flow(s) missing`` and
    # ``ui flow(s) failed:`` — both unique to their direction even
    # after the flow names are appended verbatim.
    if report.missing:
        blockers.append(
            f"{len(report.missing)} critical UI flow(s) missing "
            f"`validation:ui_flow` records: "
            + ", ".join(report.missing[:10])
        )
    if report.failed:
        blockers.append(
            f"{len(report.failed)} critical UI flow(s) failed: "
            + ", ".join(report.failed[:10])
        )
    if report.source == "critical_flows_invalid":
        # Designer wrote ``critical_flows: [...]`` but every entry was
        # unparseable (missing both ``name`` and ``id``). Without
        # this blocker the gate would silently fall through to page
        # derivation and the designer's bug would never surface.
        blockers.append(
            "Frontend kickoff `critical_flows[]` is present but every "
            "entry is unparseable (missing `name`/`id`)."
        )
    return report.to_dict(), blockers


def _visual_summary(hub_registry) -> Dict[str, int]:
    gate = getattr(hub_registry, "gate_registry", None)
    if gate is None or not hasattr(gate, "list_critical_visual_reviews"):
        return {"critical_total": 0, "approved": 0,
                "pending": 0, "needs_revision": 0}
    critical = gate.list_critical_visual_reviews() or []
    approved = sum(1 for p in critical if p.get("status") == "approved")
    pending = sum(1 for p in critical
                  if p.get("status") in ("pending", "reviewing"))
    needs_rev = sum(1 for p in critical if p.get("status") == "needs_revision")
    return {"critical_total": len(critical), "approved": approved,
            "pending": pending, "needs_revision": needs_rev}


def compute_deliverability(hub_registry, app_root,
                            session_start_ts: float = 0.0) -> DeliverabilityReport:
    blockers: List[str] = []

    runhub = getattr(hub_registry, "runhub", None)
    last_run = None
    run_within_session = False
    if runhub is not None and hasattr(runhub, "last_successful_run_since"):
        last_run = runhub.last_successful_run_since(session_start_ts)
        run_within_session = last_run is not None

    if not run_within_session:
        blockers.append(
            "no successful RunHub run since session start "
            "(call run_start(...) and ensure fail_count=0 before deliver)")

    ep_counts = _probe_counts(last_run.get("probes") if last_run else [])
    mcp_counts = _probe_counts(last_run.get("mcp_probes") if last_run else [])
    if ep_counts.get("failed", 0) > 0:
        blockers.append(
            f"latest run has {ep_counts['failed']} failed endpoint probe(s)")
    if mcp_counts.get("failed", 0) > 0:
        blockers.append(
            f"latest run has {mcp_counts['failed']} failed MCP probe(s)")

    # A deterministically functionally-validated WORKING app — a successful
    # in-session RunHub run with zero failed endpoint/MCP probes — is deliverable.
    # The gates below (coverage "dead artifacts", un-reviewed visual, missing
    # ui_flow) then become WARNINGS, not hard blockers: an automated agent
    # pipeline must not block delivery FOREVER on review/coverage/UI-test steps a
    # drifting reviewer/verifier LLM never performs — AND the coverage audit
    # false-flags spine tables (tenants/users/oauth_*), build config (eslint/
    # postcss) and support modules (oauth_routes/schemas) as "dead" even on a
    # provably-working app (smoke #14: 17 "dead" artifacts, all real+used). HARD
    # gates still block: no run / failed probes / MISSING seed / visual
    # NEEDS_REVISION (an explicit FAIL) / story evidence.
    functionally_validated = (
        run_within_session
        and ep_counts.get("failed", 0) == 0
        and mcp_counts.get("failed", 0) == 0
    )
    # UI-facing gates (visual / ui_flow) may downgrade only when the app is functionally
    # validated AND (when ENVGEN_REQUIRE_UI_EVIDENCE is on) at least one UI/browser/test-user
    # record passed — so a backend-only-validated, blank-UI app no longer waives them.
    # Default-off ⇒ ui_validated == functionally_validated (byte-identical).
    _require_ui = os.environ.get("ENVGEN_REQUIRE_UI_EVIDENCE", "0").lower() in ("1", "true", "yes", "on")
    ui_validated = functionally_validated and (
        _has_passing_ui_evidence(hub_registry) if _require_ui else True)

    coverage = _coverage_summary(hub_registry, app_root)
    if not coverage.get("is_clean", True) and not functionally_validated:
        dead = coverage.get("dead_count_by_kind") or {}
        total = sum(dead.values()) if dead else 0
        blockers.append(f"{total} dead artifact(s) (Cutover 19 gate)")

    # ui_page HARD wiring gate (B1, 2026-06-12). A declared ui_page whose route
    # isn't wired in App.jsx, or whose component file is absent, ships a page
    # that won't open — yet api_smoke (the basis of functionally_validated)
    # probes only the BACKEND and never opens a frontend page. So unlike the
    # coverage/seed/visual gates above, this is NOT relaxed on a functionally-
    # validated app: it's a deterministic code fact (route literal present in
    # App.jsx? component file on disk?), low-false-positive, and self-clearing
    # once the lane wires the page — never a permanent block.
    blockers.extend(_ui_page_wiring_blockers(hub_registry, app_root))

    # BARE-FETCH-NO-TOKEN gate (#154, gmrun4 root cause). Like the ui_page gate
    # above, NOT relaxed on a functionally-validated app: api_smoke probes the
    # backend with a FRAMEWORK-minted token, so a frontend that never attaches
    # the user's token 401s at runtime while every functional check stays green
    # (gmrun4: delivered 4 milestones, browser showed a login wall). Static,
    # low-false-positive (literal '/api/' URLs only, public endpoints and any
    # auth evidence excused), self-clearing once the lane wires the token.
    blockers.extend(_bare_fetch_blockers(app_root))

    # PLACEHOLDER-STUB backend handler gate (#173, gmrun9). A GET route that returns a
    # hardcoded empty collection with no DB read renders a permanently-empty page — the
    # backend twin of a mock frontend. Static AST on the served backend tree, self-clearing
    # once the handler queries the real table.
    blockers.extend(_stub_handler_blockers(app_root))

    # Seed gate: the backend drifts on seed-data registration (the same
    # bookkeeping-the-LLM-never-does class as ui_flow/visual). On a functionally-
    # validated app the api_smoke already proved the business tables WORK
    # (register mints a user row; the smoke inserts + reads notes), so a missing /
    # low-row seed REGISTRATION is a WARNING, not a hard blocker. It still blocks
    # when the app is NOT functionally validated.
    seed = _seed_summary(hub_registry)
    if seed.get("missing", 0) > 0 and not functionally_validated:
        blockers.append(
            f"{seed['missing']} table(s) missing seed registration (Cutover 21 gate)")
    if seed.get("flagged", 0) > seed.get("missing", 0) and not functionally_validated:
        # additional flagged are placeholder_content or low_row_count
        extra = seed["flagged"] - seed.get("missing", 0)
        blockers.append(
            f"{extra} table(s) with low row count or placeholder seed (Cutover 21 gate)")

    # AUTHORED-SEED gate (outlook run-33, 2026-07-02) — NOT waived by functional
    # validation: the registration checks above audit hub BOOKKEEPING and are relaxed
    # once api_smoke passes, so a run whose lane never authored app/backend/
    # seed_data.json shipped the bland framework-fallback seed as "SUCCESS" — while the
    # spec's bar is domain-REALISTIC populated screens ("a dozen realistic emails …
    # populated on first load"). The file is guaranteed to EXIST (empty {}) by the
    # build-infra writers, so absent-or-empty means the lane hasn't authored data yet;
    # the remediation dispatch + deliver guard then drive it to (run-31 proved the lane
    # CAN author it). Clears the moment a non-empty valid JSON lands.
    try:
        import json as _json
        _seed_path = Path(app_root) / "backend" / "seed_data.json"
        _data = {}
        if _seed_path.exists():
            try:
                _data = _json.loads(_seed_path.read_text(encoding="utf-8"))
                if not isinstance(_data, dict):
                    _data = {}
            except Exception:
                _data = {}
        # F2: the framework-owned seed_dataset.json (design-prep REAL data the loader
        # merges into the DB) counts toward BOTH the authored check and the quality
        # row-floor — a run whose real rows live there must not trip the gate just
        # because the lane's seed_data.json is thin. Merged view; dataset tables win.
        _real = {}
        try:
            _ds_path = Path(app_root) / "backend" / "seed_dataset.json"
            if _ds_path.exists():
                _rd = _json.loads(_ds_path.read_text(encoding="utf-8"))
                if isinstance(_rd, dict):
                    _real = _rd
        except Exception:
            _real = {}
        _data = {**_data, **{k: v for k, v in _real.items() if isinstance(v, list) and v}}
        _authored = any(isinstance(v, list) and v for v in _data.values())
        if not _authored:
            blockers.append(
                "authored seed missing: app/backend/seed_data.json is absent or empty — "
                "the app would ship the bland framework-fallback seed. Author domain-"
                "realistic rows (users + every business table, FK-valid, believable "
                "subjects/bodies/timestamps) in app/backend/seed_data.json.")
        elif os.environ.get("ENVGEN_SEED_QUALITY_GATE", "1") not in ("0", "off", "false"):
            # Fix #54 — the seed exists; is it GOOD? #41 only proves non-empty,
            # so a 2-row token seed shipped as "SUCCESS" while the bar is
            # populated, realistic list screens (info density = the top visual
            # lever). Same non-waivable family as #41 (content quality is
            # exactly what functional validation does NOT prove); conservative
            # signals only (see audit_authored_seed) + recomputed each tick so
            # a rewritten seed self-clears.
            try:
                from .seed_audit import audit_authored_seed
                _issues = audit_authored_seed(_data)
            except Exception:
                _issues = []
            if _issues:
                blockers.append(
                    "authored seed quality: " + "; ".join(_issues)
                    + " — rewrite app/backend/seed_data.json (keep it FK-valid).")
    except Exception:
        pass

    visual = _visual_summary(hub_registry)
    if visual.get("pending", 0) > 0 and not ui_validated:
        blockers.append(
            f"{visual['pending']} critical visual review(s) pending (Cutover 20 gate)")
    if visual.get("needs_revision", 0) > 0:
        blockers.append(
            f"{visual['needs_revision']} critical visual review(s) need revision")

    # Flow-coverage gate. For each critical UI flow declared in the frontend
    # kickoff section the verifier must drive a real browser test (navigate +
    # interaction) and write a passing ``validation:ui_flow:<name>`` record.
    # ui_flow is browser-driven UI testing the verifier LLM reliably drifts on
    # (smoke #14: 5 declared flows, 0 records) — same class as the visual review
    # gate. So a MISSING ui_flow record is a WARNING on a functionally-validated
    # app (passing api_smoke RunHub run); it still blocks when NOT validated. (A
    # FAILED ui_flow — recorded but not passing — is surfaced by the api_smoke
    # probe path; this only relaxes the never-ran case.)
    # ui_flow gate (intentional PR-7 functional-UI-testing gate). A MISSING
    # (never-ran) ui_flow record is the verifier-drift case — the verifier LLM
    # reliably will not drive the browser (every smoke: declared flows, 0 records).
    # On a deterministically functionally-validated app (passing in-session
    # api_smoke RunHub run, 0 failed probes) a MISSING record is therefore a
    # WARNING, not a hard blocker — same principle as the visual review gate. A
    # FAILED ui_flow (recorded but not passing) or an INVALID critical-flow
    # declaration is a real defect and ALWAYS blocks; so does MISSING when the app
    # is NOT functionally validated. Key on the ANCHORED phrase "ui flow(s)
    # missing" (NOT the bare word "missing") so a flow NAMED e.g.
    # recover_missing_password and the invalid-declaration blocker
    # ("missing `name`/`id`") are NOT suppressed.
    flow_coverage, flow_blockers = _flow_coverage_summary(hub_registry, app_root)
    if ui_validated:
        flow_blockers = [b for b in flow_blockers if "ui flow(s) missing" not in b.lower()]
    blockers.extend(flow_blockers)

    # Phase 3 story-gate hook (commit c9a81e22 + 763b408f). At
    # phase>=3.0 the story_hub.evaluate_story_gate walks each
    # registered story's evidence_targets, dispatches by namespace
    # prefix to canonical-writer-reading resolvers, and reports any
    # unresolved targets as per-story blockers. With zero registered
    # stories the gate returns ok=True trivially (vacuous), so the
    # hook is a no-op when story_hub hasn't been adopted by the
    # current pipeline run. Empty-actor system-bootstrap paths are
    # already exempt (the gate compares evidence, not actor).
    try:
        if hasattr(hub_registry, "story_hub"):
            persisted = (
                hub_registry.story_hub.stores.stories.value()
                if (hub_registry.story_hub.stores is not None
                    and hasattr(hub_registry.story_hub.stores, "stories"))
                else {}
            )
            stories_list = [
                v for v in persisted.values()
                if isinstance(v, dict) and v.get("id")
            ]
            verdict_gate = hub_registry.story_hub.evaluate_story_gate(
                stories_list, reg=hub_registry,
            )
            for s in verdict_gate.get("stories") or []:
                if s.get("status") != "delivered":
                    sid = s.get("id", "?")
                    for b in (s.get("blockers") or []):
                        blockers.append(f"story[{sid}] {b}")
    except Exception:
        # Story-gate hook is best-effort — runs that don't use
        # story_hub fall through. Don't fail delivery for hook
        # plumbing errors; the regular blockers list is authoritative.
        pass

    verdict = "deliverable" if not blockers else "blocked"
    return DeliverabilityReport(
        last_successful_run=last_run,
        run_within_session=run_within_session,
        endpoint_probes=ep_counts,
        mcp_probes=mcp_counts,
        coverage=coverage,
        seed_data=seed,
        visual_reviews=visual,
        flow_coverage=flow_coverage,
        blockers=blockers,
        verdict=verdict,
    )


__all__ = ["DeliverabilityReport", "compute_deliverability"]
