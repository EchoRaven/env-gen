"""PR 7 (2026-05-30): flow-coverage gate tests.

Reviewer's structural finding: the system cannot guarantee zero bugs
in LLM-generated apps because the bar for "UI tested" was
``browser_navigate + browser_screenshot`` — page-load proof, not
functional proof. This PR adds a release-blocking flow-coverage gate
that requires a real ``validation:ui_flow:<name>`` record (driven by
the verifier or a spawned UI-flow tester worker through actual
browser interaction steps) for each critical flow declared in
``design/spec.ui.json``.

Two priority sources for "what's critical":
  1. Explicit ``critical_flows[]`` array in ``spec.ui.json``.
  2. Fallback: ``pages[]`` entries with ``critical: true``.

These tests pin:
  * empty / missing spec → no required flows → no blocker (don't
    punish small apps or legacy specs that never opted in)
  * critical flow declared, no matching record → blocker present,
    names the flow
  * critical flow declared, passing record → no blocker
  * critical flow declared, failing record → blocker present
  * later passing record clears an earlier failure (matches the
    smoke-check retry semantics)
  * explicit ``critical_flows`` wins over derived-from-pages
  * fold-in: ``compute_deliverability`` surfaces ``ui flow ...
    missing`` blocker; ``_validate_delivery_gate`` canonicalizes it
    to ``deliverability_ui_flow_missing``
  * autonomous delivery gate emits actionable suggestion text
"""

from __future__ import annotations

import json
import shutil
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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.flow_coverage import (  # noqa: E402
    FlowCoverageReport,
    compute_flow_coverage,
)
from multi_agent.runtime.deliverability import compute_deliverability  # noqa: E402


def _write_spec_ui(crdt, payload: dict) -> None:
    """Populate WorkHub with the frontend section of a kickoff meeting.

    Translates the legacy ``{critical_flows, pages}`` shape into the
    v3 source-of-truth: a kickoff meeting page with a frontend
    decision whose content carries ``user_flows`` (carrying the
    explicit critical_flows as ``critical=True`` entries) and
    ``ui_pages``.
    """
    workhub = crdt.workhub
    user_flows: list = []
    for entry in payload.get("critical_flows") or []:
        if isinstance(entry, dict):
            user_flows.append({**entry, "critical": True})
        elif isinstance(entry, str):
            user_flows.append({"name": entry, "critical": True})
    ui_pages = list(payload.get("pages") or [])

    meeting = workhub.create_meeting(
        agenda="kickoff",
        attendees=["frontend"],
        milestone_index=1,
        agent="orchestrator",
    )
    workhub.add_meeting_decision(
        meeting_id=meeting["id"],
        decision={
            "section": "frontend",
            "agent": "frontend",
            "round": 1,
            "content": {"user_flows": user_flows, "ui_pages": ui_pages},
        },
        agent="frontend",
        milestone_index=1,
    )


def _record_ui_flow(crdt: HubRegistry, flow_name: str, status: str,
                    task_id: str = None) -> None:
    crdt.record_validation_result(
        task_id=task_id or f"ui_flow_{flow_name}",
        status=status,
        agent="task_runner",
        summary=f"flow {flow_name}: {status}",
        execution_mode="browser",
        metadata={"check": "ui_flow", "flow": flow_name},
    )


def _add_passing_run(crdt: HubRegistry, started_at: float = 2000.0) -> None:
    """Otherwise compute_deliverability's runhub blocker dominates."""
    r = crdt.runhub.record_run(branch="x", generated_dir="/g",
                               agent="orchestrator")
    raw = crdt.runhub.stores.runs.get(r["id"])
    raw["started_at"] = started_at
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = []
    raw["mcp_probes"] = []
    crdt.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"),
        change_info={"agent": "runhub"},
    )


def _add_retro(crdt: HubRegistry, gen_id: float = 2000.0) -> None:
    crdt.workhub.create_document(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                  "lessons": [], "proposed_prompt_changes": []})


class FlowCoverageHelperBehaviour(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flow_cov_helper_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_spec_returns_empty_report(self):
        """No spec.ui.json yet → no required flows; nothing to block.

        Preserves the "strictly tighter never looser" invariant: the
        new gate must not retroactively reject apps that previously
        delivered."""
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.required, [])
        self.assertEqual(report.missing, [])
        self.assertEqual(report.failed, [])
        self.assertEqual(report.source, "none")
        self.assertTrue(report.is_clean)

    def test_empty_spec_returns_empty_report(self):
        _write_spec_ui(self.reg, {})
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.required, [])
        self.assertEqual(report.source, "none")
        self.assertTrue(report.is_clean)

    def test_pages_without_critical_flag_become_contract_derived_flows(self):
        """2026-06-22 user directive ("flows come from the registered
        CONTRACT, not authored user_flows", encoded in
        flow_coverage._extract_required_flows:245-268): with no explicit
        critical_flows and no critical:true pages, EVERY declared ui_page
        becomes a flow to validate (source "pages").

        The original "retroactively grows N missing-flow blockers"
        concern is now addressed differently — a MISSING ui_flow is a
        WARNING (surfaced) not a hard blocker on a functionally-validated
        app (see FlowCoverageFoldedIntoDeliverability
        .test_missing_flow_does_not_block_functionally_validated_app), so
        coverage widens without punishing small apps."""
        _write_spec_ui(self.reg, {
            "pages": [
                {"name": "home", "path": "/"},
                {"name": "about", "path": "/about"},
            ],
        })
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.source, "pages")
        self.assertEqual(sorted(report.required), ["about", "home"])
        # Surfaced as missing (no ui_flow records yet), but the delivery
        # gate treats missing as a warning on a validated app.
        self.assertEqual(sorted(report.missing), ["about", "home"])
        self.assertFalse(report.is_clean)

    def test_critical_pages_become_required_flows_when_no_explicit_list(self):
        _write_spec_ui(self.reg, {
            "pages": [
                {"name": "home", "path": "/", "critical": True},
                {"name": "login", "path": "/login", "critical": True},
                {"name": "about", "path": "/about", "critical": False},
            ],
        })
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.source, "critical_pages")
        self.assertEqual(sorted(report.required), ["home", "login"])
        self.assertEqual(sorted(report.missing), ["home", "login"])
        self.assertFalse(report.is_clean)

    def test_explicit_critical_flows_override_derived(self):
        """Explicit flows take priority — a multi-step user journey
        is a strictly better contract than per-page derivation."""
        _write_spec_ui(self.reg, {
            "pages": [
                {"name": "home", "path": "/", "critical": True},
            ],
            "critical_flows": [
                {"name": "register_to_first_post",
                 "description": "user signs up and posts"},
                {"name": "login_logout",
                 "description": "user logs in then out"},
            ],
        })
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.source, "critical_flows")
        self.assertEqual(
            sorted(report.required),
            ["login_logout", "register_to_first_post"],
        )

    def test_passing_record_clears_required_flow(self):
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}],
        })
        _record_ui_flow(self.reg, "register", "passed")
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.passed, ["register"])
        self.assertEqual(report.missing, [])
        self.assertEqual(report.failed, [])
        self.assertTrue(report.is_clean)

    def test_failing_record_surfaces_failure_not_missing(self):
        """Failed != missing — operator needs to distinguish "tester
        never ran" from "tester ran and the flow is broken"."""
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}, {"name": "post"}],
        })
        _record_ui_flow(self.reg, "register", "failed")
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.failed, ["register"])
        self.assertEqual(report.missing, ["post"])
        self.assertEqual(report.passed, [])
        self.assertFalse(report.is_clean)

    def test_later_pass_clears_earlier_failure(self):
        """Matches smoke-check retry semantics: a later passing run
        wins over an earlier failed run for the same flow."""
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}],
        })
        _record_ui_flow(self.reg, "register", "failed",
                        task_id="ui_flow_register_attempt_1")
        _record_ui_flow(self.reg, "register", "passed",
                        task_id="ui_flow_register_attempt_2")
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.passed, ["register"])
        self.assertEqual(report.failed, [])

    def test_record_with_wrong_metadata_check_is_ignored(self):
        """A ``validation:ui_smoke`` record does NOT satisfy a
        ``ui_flow`` requirement. They're separate dimensions and
        must stay that way — otherwise the new gate collapses back
        into the old smoke gate."""
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}],
        })
        # Wrong check token, but right flow name in metadata.
        self.reg.record_validation_result(
            task_id="ui_smoke_register",
            status="passed",
            agent="task_runner",
            summary="navigate ok",
            metadata={"check": "ui_smoke", "flow": "register"},
        )
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.missing, ["register"])

    def test_string_only_critical_flow_entry(self):
        """Tolerate a tester-friendly shorthand where flows are
        plain strings rather than objects."""
        _write_spec_ui(self.reg, {
            "critical_flows": ["register", "login"],
        })
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(sorted(report.required), ["login", "register"])


class FlowCoverageFoldedIntoDeliverability(unittest.TestCase):
    """Integration: ``compute_deliverability`` is now the canonical
    aggregator both the autonomous gate and the UI path consume.
    Flow coverage must surface there as a blocker, not just in the
    helper."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flow_cov_deliv_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg)
        _add_passing_run(self.reg, started_at=2000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_flow_surfaces_as_deliverability_blocker(self):
        _write_spec_ui(self.reg, {
            "critical_flows": [
                {"name": "register_to_first_post"},
                {"name": "login_logout"},
            ],
        })
        # session_start AFTER the setUp run (2000.0) → not functionally-validated
        # → MISSING ui_flow records still surface as a blocker.
        report = compute_deliverability(
            self.reg, self.tmp, session_start_ts=2500.0,
        )
        self.assertEqual(report.verdict, "blocked")
        joined = " ".join(report.blockers).lower()
        self.assertIn("ui flow", joined)
        self.assertIn("missing", joined)
        # Both flow names appear in the blocker for operator visibility
        self.assertIn("register_to_first_post", joined)
        self.assertIn("login_logout", joined)
        # ``flow_coverage`` field round-trips into the dict form
        as_dict = report.to_dict()
        self.assertIn("flow_coverage", as_dict)
        self.assertEqual(
            sorted(as_dict["flow_coverage"]["missing"]),
            ["login_logout", "register_to_first_post"],
        )
        self.assertEqual(as_dict["flow_coverage"]["source"], "critical_flows")

    def test_missing_flow_does_not_block_functionally_validated_app(self):
        # The relaxation: on a functionally-validated app (the setUp passing run
        # @2000 IS counted when session_start=1000), a MISSING (never-ran) ui_flow
        # record is a WARNING — surfaced in flow_coverage but NOT a blocker. The
        # verifier LLM reliably never drives the browser, so an automated pipeline
        # must not block delivery forever on it. (A FAILED record still blocks.)
        #
        # #193 (REQUIRE_UI_EVIDENCE default-ON, deliverability.py:318-319): the
        # ui_flow-missing relaxation now ALSO requires at least one PASSING
        # UI/browser record — a backend-only-validated, blank-UI app no longer
        # waives the UI gates. Provide one passing ui_smoke record so the app is
        # genuinely UI-validated; the "register" ui_flow itself stays MISSING
        # (never-ran) and must remain a warning, not a hard blocker.
        _write_spec_ui(self.reg, {"critical_flows": [{"name": "register"}]})
        self.reg.record_validation_result(
            task_id="ui_smoke_home", status="passed", agent="task_runner",
            summary="home smoke ok",
            metadata={"check": "ui_smoke", "flow": "home"})
        # The authored-seed gate (deliverability.py:403-443) is NOT waived by
        # functional validation, so a genuinely-deliverable app must ship a
        # populated app/backend/seed_data.json (>=10 realistic rows, no
        # placeholder markers). Provide one so the ONLY thing that could keep
        # the verdict from "deliverable" is the missing ui_flow record under test.
        (self.tmp / "backend").mkdir(parents=True, exist_ok=True)
        _names = [
            "Ava Mitchell", "Liam Torres", "Noah Bennett", "Mia Chen",
            "Ethan Rivera", "Sofia Nguyen", "Lucas Park", "Emma Delgado",
            "Oliver Haas", "Isla Romano", "Mason Clarke", "Zoe Abram",
        ]
        _users = [
            {"id": i + 1,
             "name": n,
             "email": n.lower().replace(" ", ".") + "@lumenfeed.com",
             "created_at": f"2026-05-{(i % 27) + 1:02d}T09:{(i * 7) % 60:02d}:00Z"}
            for i, n in enumerate(_names)
        ]
        (self.tmp / "backend" / "seed_data.json").write_text(
            json.dumps({"users": _users}), encoding="utf-8")
        report = compute_deliverability(self.reg, self.tmp, session_start_ts=1000.0)
        self.assertEqual(report.verdict, "deliverable")
        self.assertFalse(
            any("ui flow(s) missing" in b.lower() for b in report.blockers),
            f"missing ui_flow must not block a validated app: {report.blockers}")
        # still surfaced for operator visibility
        self.assertIn("register", report.flow_coverage.get("missing", []))

    def test_failing_flow_surfaces_failed_not_missing_blocker(self):
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}],
        })
        _record_ui_flow(self.reg, "register", "failed")
        report = compute_deliverability(
            self.reg, self.tmp, session_start_ts=1000.0,
        )
        joined = " ".join(report.blockers).lower()
        self.assertIn("ui flow", joined)
        self.assertIn("failed", joined)
        self.assertNotIn(
            "1 critical ui flow(s) missing", joined,
            "missing blocker must not fire when the only flow has a "
            "(failing) record — that's a separate dimension",
        )

    def test_passing_flow_clears_blocker(self):
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}],
        })
        _record_ui_flow(self.reg, "register", "passed")
        report = compute_deliverability(
            self.reg, self.tmp, session_start_ts=1000.0,
        )
        joined = " ".join(report.blockers).lower()
        self.assertNotIn("ui flow", joined)

    def test_no_required_flows_does_not_block(self):
        """No spec.ui.json + no critical pages → flow coverage stays
        silent. Critical "strictly tighter never looser" invariant."""
        # No spec.ui.json at all.
        report = compute_deliverability(
            self.reg, self.tmp, session_start_ts=1000.0,
        )
        joined = " ".join(report.blockers).lower()
        self.assertNotIn("ui flow", joined)

    def test_app_root_inside_app_dir_still_finds_spec(self):
        """The autonomous gate passes ``self.output_dir / "app"`` when
        the app dir exists. spec.ui.json lives at
        ``<workspace>/design/spec.ui.json``, a sibling of app/.
        The flow_coverage helper must walk up one level."""
        (self.tmp / "app").mkdir(parents=True, exist_ok=True)
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}],
        })
        # session_start AFTER the setUp run (2000.0) → not functionally-validated
        # → a MISSING ui_flow record still blocks (the relaxation only spares
        # validated apps). Verifies spec discovery via the surfaced blocker.
        report = compute_deliverability(
            self.reg, self.tmp / "app", session_start_ts=2500.0,
        )
        joined = " ".join(report.blockers).lower()
        self.assertIn("ui flow", joined,
                      "spec.ui.json sibling of app/ wasn't discovered; "
                      "the walk-up logic broke")


class AutonomousGateCanonicalizesFlowBlocker(unittest.TestCase):
    """The autonomous delivery gate maps deliverability blockers to
    stable token strings via the canonicalization block in
    ``_validate_delivery_gate``. The ``ui_flow_missing`` and
    ``ui_flow_failed`` tokens must be reachable from the prose
    blocker the new check emits."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flow_cov_gate_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg)
        _add_passing_run(self.reg, started_at=2000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gate_canonicalizes_missing_blocker_token(self):
        from multi_agent.orchestrator import Orchestrator
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}],
        })
        orch = Orchestrator.__new__(Orchestrator)
        orch.output_dir = self.tmp
        orch.crdt_workspace = self.reg
        orch.hubs = self.reg
        # session_start AFTER the setUp run (2000.0) → not functionally-validated
        # → MISSING ui_flow still blocks (relaxation only spares validated apps).
        orch._session_start_ts = 2500.0

        gate = orch._validate_delivery_gate()
        self.assertIn(
            "deliverability_ui_flow_missing", gate["failed_checks"],
            f"expected ui_flow_missing token; "
            f"failed_checks={gate.get('failed_checks')}",
        )

    def test_gate_canonicalizes_failed_blocker_token(self):
        from multi_agent.orchestrator import Orchestrator
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}],
        })
        _record_ui_flow(self.reg, "register", "failed")
        orch = Orchestrator.__new__(Orchestrator)
        orch.output_dir = self.tmp
        orch.crdt_workspace = self.reg
        orch.hubs = self.reg
        orch._session_start_ts = 1000.0

        gate = orch._validate_delivery_gate()
        self.assertIn(
            "deliverability_ui_flow_failed", gate["failed_checks"],
        )

    def test_gate_emits_actionable_suggestion_text(self):
        """The operator-facing suggestion must explicitly tell the
        verifier how to satisfy the gate — the record signature is
        the load-bearing detail."""
        from multi_agent.orchestrator import Orchestrator
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}],
        })
        orch = Orchestrator.__new__(Orchestrator)
        orch.output_dir = self.tmp
        orch.crdt_workspace = self.reg
        orch.hubs = self.reg
        orch._session_start_ts = 2500.0  # after setUp run → not validated → missing blocks

        gate = orch._validate_delivery_gate()
        suggestions = orch._delivery_gate_suggestions(gate)
        # At least one suggestion mentions the canonical record contract
        joined = "\n".join(suggestions).lower()
        self.assertIn("ui_flow", joined)
        self.assertIn("validation:ui_flow", joined)
        # #339/#340: the suggestion must name the recorder an agent can
        # actually CALL. It used to say `record_validation_result(...,
        # metadata=...)`, a HubRegistry method that is not a tool, so the
        # instruction was unfollowable and the blocker unsatisfiable.
        self.assertIn("codehub_record_check", joined)


if __name__ == "__main__":
    unittest.main()
