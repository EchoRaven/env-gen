"""PR 6 review follow-up (2026-05-30): the autonomous-deliver
hard gate (``Orchestrator._validate_delivery_gate``) now folds in
``compute_deliverability`` so the LLM-driven deliver path mirrors
the UI-driven deliver path's enforcement.

History of the gap that this closes:

  * ``DeliverProjectTool.execute`` used to have FIVE inline gates
    (retro / coverage / visual / seed / runhub-since-session).
    All five were dead-on-production because they read
    ``self.agent.hub_registry`` while production agents only
    expose ``self._hubs``. The 2026-05-30 cleanup commit
    ``dbbd38ea`` deleted them.
  * After that deletion, retro stayed enforced via the policy
    layer (``RetroBeforeDeliverPolicy``) on the autonomous
    finish hook. But coverage / visual / seed / runhub had no
    autonomous-path backstop — they were only enforced on the
    UI path via ``compute_deliverability`` in
    ``deliver_project_call``.
  * The reviewer's recommendation: don't re-scatter in-tool
    gates; fold ``compute_deliverability`` INTO the existing
    autonomous hard gate so both paths share one enforcement
    point. That's what this test pins.

For each new dimension (coverage / visual / seed / runhub) we set
up the minimal workspace that satisfies the OLD gate (topology,
build, contract) but violates exactly one new dimension, then
assert the gate now reports the corresponding canonical
``deliverability_*`` failure_check.

Note on test scope: we use ``Orchestrator.__new__(Orchestrator)``
to bypass the heavy init (network, agent spawning, message bus),
following the established pattern from
``test_task_suite_regressions.py``. We populate just enough state
for ``_validate_delivery_gate`` to run.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.orchestrator import Orchestrator  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


_GOOD_DEV = [
    {"aspect": "a", "expected": "e", "actual": "a2", "severity": "low"},
    {"aspect": "b", "expected": "e", "actual": "a2", "severity": "low"},
    {"aspect": "c", "expected": "e", "actual": "a2", "severity": "low"},
]


def _prepare_min_delivery_layout(out: Path):
    """Minimal layout that satisfies the gate's file / dir / spec
    checks. Copy of the helper in test_task_suite_regressions —
    kept local so this test file is self-contained."""
    required_files = {
        "docker/docker-compose.yml": "services: {}",
        "design/README.md": "# Design",
        "design/spec.database.json": "{}",
        "design/spec.api.json": "{}",
        "design/spec.ui.json": "{}",
    }
    for rel, content in required_files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    for rel in ["app/backend/main.py", "app/frontend/main.js",
                 "app/database/schema.sql"]:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")


def _seed_topology(hubs, *, session_start_ts: float):
    """Satisfy the OLD gate's topology requirements (endpoints /
    tables / pages, all marked implemented). The deliverability
    fold runs ON TOP of this — its failures are what each test
    case isolates."""
    hubs.registryhub.register_endpoint(
        "GET", "/health", schema={},
        provider="backend", agent="backend", status="implemented",
    )
    hubs.schema_hub.register_table(
        name="users", schema={"id": "int"},
        provider="database", agent="backend", status="implemented",
    )
    hubs.workhub.update_ui_page(
        "home", {"status": "implemented"}, agent="frontend",
    )


def _record_passing_run(hubs, *, started_at: float):
    """Insert a RunHub run with started_at >= session_start_ts so
    the runhub-since-session check passes. Same shape as the
    helper test_deliverability_aggregator uses."""
    r = hubs.runhub.record_run(branch="x", generated_dir="/g", agent="orch")
    raw = hubs.runhub.stores.runs.get(r["id"])
    raw["started_at"] = started_at
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = []
    raw["mcp_probes"] = []
    hubs.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"),
        change_info={"agent": "runhub"},
    )


def _build_orch_for_gate(td: Path) -> Orchestrator:
    """Test fixture: minimal Orchestrator wired enough to call
    ``_validate_delivery_gate`` directly. Mirrors the pattern from
    ``test_task_suite_regressions``."""
    _prepare_min_delivery_layout(td)
    hubs = HubRegistry(td)
    orch = Orchestrator.__new__(Orchestrator)
    orch.output_dir = td
    orch.hubs = hubs
    # The fold reads ``_session_start_ts`` to scope runhub-since-
    # session correctly. Anchor it at 1000 — tests insert runs at
    # 2000 (after) or 500 (before) depending on what they want.
    orch._session_start_ts = 1000.0
    return orch


class GateFoldsInDeliverabilityFailures(unittest.TestCase):
    """One test per dimension the fold added. Each populates a
    workspace that satisfies every OTHER check and isolates the
    target dimension."""

    def test_no_successful_run_blocks_delivery_via_runhub_check(self):
        """No RunHub run at all → ``deliverability_no_successful_run``
        appears in failed_checks. This was previously the
        ``Cutover 24`` in-tool gate; now enforced via the fold."""
        with tempfile.TemporaryDirectory() as td:
            orch = _build_orch_for_gate(Path(td))
            _seed_topology(orch.hubs, session_start_ts=orch._session_start_ts)
            gate = orch._validate_delivery_gate()
            self.assertIn(
                "deliverability_no_successful_run",
                gate.get("failed_checks", []),
                f"gate didn't surface the runhub gap; "
                f"failed_checks={gate.get('failed_checks')}",
            )
            self.assertFalse(gate["ok"])

    def test_run_before_session_start_doesnt_satisfy_gate(self):
        """A successful run recorded BEFORE the session start
        doesn't satisfy the gate — same regression the old in-tool
        gate intended."""
        with tempfile.TemporaryDirectory() as td:
            orch = _build_orch_for_gate(Path(td))
            _seed_topology(orch.hubs, session_start_ts=orch._session_start_ts)
            # Run BEFORE session_start_ts=1000 → must not count.
            _record_passing_run(orch.hubs, started_at=500.0)
            gate = orch._validate_delivery_gate()
            self.assertIn(
                "deliverability_no_successful_run",
                gate.get("failed_checks", []),
                "stale pre-session run silently passed the gate — "
                "session_start_ts plumbing broken",
            )

    def test_critical_visual_pending_does_not_block_validated_app(self):
        """A PENDING (un-reviewed) critical visual is a WARNING, not a blocker,
        once the app is functionally validated (a successful in-session RunHub run
        with 0 failed probes — set up here via _record_passing_run). An automated
        pipeline must not block delivery forever on a review the reviewer LLM never
        performs. An explicit FAIL (needs_revision) still blocks (next test); so
        does pending WITHOUT a passing run."""
        with tempfile.TemporaryDirectory() as td:
            orch = _build_orch_for_gate(Path(td))
            _seed_topology(orch.hubs, session_start_ts=orch._session_start_ts)
            _record_passing_run(orch.hubs, started_at=2000.0)
            # Register critical visual but don't approve (pending / un-reviewed).
            orch.hubs.gate_registry.register_visual_review_task(
                route="/feed", screenshot_path="s", reference_path="r",
                critical=True, agent="frontend",
            )
            gate = orch._validate_delivery_gate()
            self.assertNotIn(
                "deliverability_critical_visuals_pending",
                gate.get("failed_checks", []),
                f"pending visual must NOT block a functionally-validated app; "
                f"failed_checks={gate.get('failed_checks')}",
            )

    def test_critical_visual_needs_revision_blocks_delivery(self):
        """needs_revision status → distinct
        ``deliverability_critical_visuals_needs_revision`` token."""
        with tempfile.TemporaryDirectory() as td:
            orch = _build_orch_for_gate(Path(td))
            _seed_topology(orch.hubs, session_start_ts=orch._session_start_ts)
            _record_passing_run(orch.hubs, started_at=2000.0)
            page = orch.hubs.gate_registry.register_visual_review_task(
                route="/feed", screenshot_path="s", reference_path="r",
                critical=True, agent="frontend",
            )
            orch.hubs.gate_registry.submit_visual_review(
                page["id"], reviewer="verifier",
                state="needs_revision", similarity_score=0.30,
                deviations=[_GOOD_DEV[0]], summary="Layout off",
            )
            gate = orch._validate_delivery_gate()
            self.assertIn(
                "deliverability_critical_visuals_needs_revision",
                gate.get("failed_checks", []),
            )

    def test_approved_critical_visual_passes_dimension(self):
        """Counterpart: an APPROVED critical visual doesn't trip
        the dimension. (Other dimensions may still fail; this test
        asserts the visual gate is satisfiable.)"""
        with tempfile.TemporaryDirectory() as td:
            orch = _build_orch_for_gate(Path(td))
            _seed_topology(orch.hubs, session_start_ts=orch._session_start_ts)
            _record_passing_run(orch.hubs, started_at=2000.0)
            page = orch.hubs.gate_registry.register_visual_review_task(
                route="/feed", screenshot_path="s", reference_path="r",
                critical=True, agent="frontend",
            )
            orch.hubs.gate_registry.submit_visual_review(
                page["id"], reviewer="verifier",
                state="approve", similarity_score=0.95,
                deviations=_GOOD_DEV,
                summary="Layout matches reference; minor drift only.",
            )
            gate = orch._validate_delivery_gate()
            self.assertNotIn(
                "deliverability_critical_visuals_pending",
                gate.get("failed_checks", []),
            )
            self.assertNotIn(
                "deliverability_critical_visuals_needs_revision",
                gate.get("failed_checks", []),
            )

    def test_missing_seed_data_blocks_delivery(self):
        """A ``status='defined'`` table without seed registration
        triggers ``deliverability_missing_seed`` via seed_audit.
        Previously the dead-wired ``Cutover 21`` in-tool gate.

        Note on test shape: ``seed_audit`` only flags tables with
        ``status='defined'`` (an implemented table is assumed to
        own its own seed lifecycle). So we register BOTH an
        ``implemented`` table (to satisfy the topology's
        ``no_implemented_tables`` check) AND a ``defined`` table
        (to trigger seed_audit). This mirrors a real failure mode:
        database agent gets an implementation through but stalls
        on the next table's seed."""
        with tempfile.TemporaryDirectory() as td:
            orch = _build_orch_for_gate(Path(td))
            _seed_topology(orch.hubs, session_start_ts=orch._session_start_ts)
            # Add a defined-but-unseeded table on top of the seeded one.
            orch.hubs.schema_hub.register_table(
                name="posts", schema={"id": "int", "body": "text"},
                provider="database", agent="backend", status="defined",
            )
            # Run started BEFORE session_start (1000) → not functionally-validated
            # → missing seed still blocks (the relaxation only spares validated
            # apps; this pins the missing-seed gate itself).
            _record_passing_run(orch.hubs, started_at=500.0)
            gate = orch._validate_delivery_gate()
            self.assertIn(
                "deliverability_missing_seed",
                gate.get("failed_checks", []),
                f"missing seed didn't block; "
                f"failed_checks={gate.get('failed_checks')}",
            )

    def test_deliverability_report_surfaced_in_gate_result(self):
        """The gate result dict carries the full
        ``deliverability_report.to_dict()`` so the operator-facing
        log shows prose (not just the canonical tokens)."""
        with tempfile.TemporaryDirectory() as td:
            orch = _build_orch_for_gate(Path(td))
            _seed_topology(orch.hubs, session_start_ts=orch._session_start_ts)
            gate = orch._validate_delivery_gate()
            self.assertIn("deliverability", gate)
            self.assertIsNotNone(gate["deliverability"])
            self.assertEqual(gate["deliverability"]["verdict"], "blocked")
            self.assertGreater(len(gate["deliverability"]["blockers"]), 0)


class GateContinuesToReportOriginalChecks(unittest.TestCase):
    """Sanity: the fold must NOT swallow the original gate's
    file/dir/topology/build checks. Existing test surface
    (``test_task_suite_regressions``) covers these but a tight
    paired test pins it here so the fold can't silently mask
    them on a future regression."""

    def test_original_topology_checks_still_fire(self):
        """An empty topology still surfaces the original checks
        (``no_endpoints_in_hub`` etc.) — the fold doesn't replace
        them, it adds to them."""
        with tempfile.TemporaryDirectory() as td:
            orch = _build_orch_for_gate(Path(td))
            # No topology seeded — original checks should fire.
            gate = orch._validate_delivery_gate()
            self.assertIn("no_endpoints_in_hub", gate["failed_checks"])
            self.assertIn("no_tables_in_hub", gate["failed_checks"])
            self.assertIn("no_pages_in_hub", gate["failed_checks"])


if __name__ == "__main__":
    unittest.main()
