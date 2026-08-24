"""Tests for runtime/deliverability.py aggregator (Cutover 24)."""

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.deliverability import (  # noqa: E402
    DeliverabilityReport, compute_deliverability,
)


def _good_seed(reg, table_name):
    reg.schema_hub.register_table(
        table_name, schema={"columns": []}, provider="backend", agent="backend")
    reg.schema_hub.register_seed_data(
        table_name, row_count=42,
        sample_excerpt=[{"id": 1, "name": "Alex Chen", "email": "alex@gmail.com"}],
        agent="backend")


def _passing_run(reg, ts_offset=0.0):
    """Insert a successful run with started_at = now + ts_offset."""
    now = time.time() + ts_offset
    r = reg.runhub.record_run(
        branch="feature/x", generated_dir="/tmp/g", agent="orch")
    # Patch started_at directly via the store
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = now
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = [{"verdict": "pass"}]
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"), change_info={"agent": "runhub"})
    # #193: a "functionally-validated app" now also carries UI evidence (the
    # REQUIRE_UI_EVIDENCE default flipped ON once the record matcher was fixed).
    reg.record_validation_result(
        "ui_flow:smoke", "passed", agent="verifier",
        metadata={"check": "ui_flow", "flow": "smoke"})
    return raw


class DeliverabilityAggregatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="deliverability_"))
        self.reg = HubRegistry(self.tmp)
        self.app_root = self.tmp / "app"
        self.app_root.mkdir()
        (self.app_root / "main.tsx").write_text("x = 1;\n")
        # The AUTHORED-SEED gate (outlook run-33) is deliberately NOT waived by
        # functional validation — an app whose lane never wrote seed_data.json
        # ships the bland framework-fallback seed as "SUCCESS". That is a
        # different question from the seed REGISTRATION bookkeeping these tests
        # are about, and with no file at all it fired here and masked it. Author
        # a file so the registration checks are what gets tested.
        _be = self.app_root / "backend"
        _be.mkdir(parents=True, exist_ok=True)
        # >= 10 structured rows: the sibling authored-seed QUALITY gate wants
        # populated list screens, and it is deliberate too.
        (_be / "seed_data.json").write_text(
            '{"users": [{"id": 1, "email": "user1@example.com", "name": "Ada Lovelace"}, {"id": 2, "email": "user2@example.com", "name": "Alan Turing"}, {"id": 3, "email": "user3@example.com", "name": "Grace Hopper"}, {"id": 4, "email": "user4@example.com", "name": "Katherine Johnson"}, {"id": 5, "email": "user5@example.com", "name": "Edsger Dijkstra"}, {"id": 6, "email": "user6@example.com", "name": "Barbara Liskov"}, {"id": 7, "email": "user7@example.com", "name": "Donald Knuth"}, {"id": 8, "email": "user8@example.com", "name": "Margaret Hamilton"}, {"id": 9, "email": "user9@example.com", "name": "Ken Thompson"}, {"id": 10, "email": "user10@example.com", "name": "Radia Perlman"}, {"id": 11, "email": "user11@example.com", "name": "Leslie Lamport"}]}\n')

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_state_blocks_on_no_run(self) -> None:
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertIsInstance(report, DeliverabilityReport)
        self.assertEqual(report.verdict, "blocked")
        self.assertTrue(any("run" in b.lower() for b in report.blockers))

    def test_with_passing_run_clean_state_is_deliverable(self) -> None:
        _passing_run(self.reg)
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.verdict, "deliverable", f"blockers: {report.blockers}")

    def test_run_before_session_start_blocks(self) -> None:
        _passing_run(self.reg, ts_offset=-1000.0)  # ran in the past
        report = compute_deliverability(
            self.reg, self.app_root, session_start_ts=time.time())
        self.assertEqual(report.verdict, "blocked")
        self.assertFalse(report.run_within_session)

    def test_failed_run_blocks(self) -> None:
        r = self.reg.runhub.record_run(
            branch="x", generated_dir="/g", agent="orch")
        self.reg.runhub.update_run_status(r["id"], "failed", agent="runhub", fail_count=3)
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.verdict, "blocked")

    def test_dead_endpoint_surfaced_in_report(self) -> None:
        # A dead artifact is SURFACED in coverage but, on a functionally-validated
        # app (passing in-session RunHub run), is a WARNING not a blocker: the
        # coverage audit false-flags spine tables / build config / support modules
        # as "dead" even on a provably-working app (smoke #14), so it must not
        # block delivery forever. Without a passing run it still blocks (next test).
        _passing_run(self.reg)
        self.reg.registryhub.register_endpoint(
            "GET", "/api/feed", schema={}, provider="backend", agent="backend")
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertFalse(report.coverage["is_clean"])  # surfaced
        self.assertFalse(
            any("dead artifact" in b for b in report.blockers),
            f"dead artifact must not block a validated app: {report.blockers}")

    def test_dead_endpoint_blocks_when_not_functionally_validated(self) -> None:
        # No passing run → not functionally validated → dead artifact DOES block.
        self.reg.registryhub.register_endpoint(
            "GET", "/api/feed", schema={}, provider="backend", agent="backend")
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertTrue(any("dead artifact" in b for b in report.blockers))

    def test_seed_block_surfaced(self) -> None:
        # Seed gap is SURFACED but, on a functionally-validated app (passing run),
        # is a WARNING not a blocker: api_smoke proved the table works (register
        # mints a user row), so a missing seed REGISTRATION is the backend's
        # bookkeeping drift, not a release blocker.
        _passing_run(self.reg)
        self.reg.schema_hub.register_table(
            "users", schema={"columns": []}, provider="backend", agent="backend")
        # No seed registered
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertGreater(report.seed_data["missing"], 0)  # surfaced
        self.assertFalse(
            any("seed" in b.lower() for b in report.blockers),
            f"missing seed must not block a validated app: {report.blockers}")

    def test_seed_blocks_when_not_functionally_validated(self) -> None:
        # No passing run → not functionally validated → missing seed DOES block.
        self.reg.schema_hub.register_table(
            "users", schema={"columns": []}, provider="backend", agent="backend")
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.verdict, "blocked")
        self.assertTrue(any("seed" in b.lower() for b in report.blockers))

    def test_visual_pending_surfaced(self) -> None:
        # A PENDING (un-reviewed) critical visual is surfaced in the report, but
        # on a functionally-validated app (passing in-session RunHub run, 0 failed
        # probes) it is a WARNING, not a blocker — an automated pipeline must not
        # block delivery forever on a review the reviewer LLM never performs.
        _passing_run(self.reg)
        _good_seed(self.reg, "users")
        self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertGreater(report.visual_reviews["pending"], 0)  # still surfaced
        # On a functionally-validated app the pending visual is NOT a blocker
        # (the unrouted /feed visual leaves a dead-artifact that still gates, but
        # the visual REVIEW itself no longer does — that's the relaxation).
        self.assertFalse(
            any("visual review" in b for b in report.blockers),
            f"pending visual must not block a validated app: {report.blockers}")

    def test_visual_pending_blocks_when_not_functionally_validated(self) -> None:
        # Without a successful run the same pending visual DOES block (alongside
        # the no-run blocker) — the relaxation is scoped to validated apps only.
        _good_seed(self.reg, "users")
        self.reg.gate_registry.register_visual_review_task(
            route="/feed", screenshot_path="s", reference_path="r",
            critical=True, agent="frontend")
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.verdict, "blocked")
        self.assertGreater(report.visual_reviews["pending"], 0)
        self.assertTrue(any("visual review" in b for b in report.blockers))

    def test_endpoint_probe_counts_aggregated(self) -> None:
        run = self.reg.runhub.record_run(branch="x", generated_dir="/g", agent="orch")
        raw = self.reg.runhub.stores.runs.get(run["id"])
        raw["started_at"] = time.time()
        raw["status"] = "completed"
        raw["fail_count"] = 0
        raw["probes"] = [
            {"verdict": "pass"}, {"verdict": "pass"},
            {"verdict": "skipped"}, {"verdict": "fail"},
        ]
        raw["mcp_probes"] = []
        self.reg.runhub.stores.runs.update(
            lambda m: m.set(run["id"], raw, "runhub"), change_info={"agent": "runhub"})
        # fail_count=0 contradicts probe fail; aggregator should trust probes list
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertEqual(report.endpoint_probes["total"], 4)
        self.assertEqual(report.endpoint_probes["passed"], 2)
        self.assertEqual(report.endpoint_probes["failed"], 1)
        self.assertEqual(report.endpoint_probes["skipped"], 1)

    def test_to_dict_round_trips(self) -> None:
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        d = report.to_dict()
        self.assertIn("verdict", d)
        self.assertIn("blockers", d)
        self.assertIn("endpoint_probes", d)


if __name__ == "__main__":
    unittest.main()
