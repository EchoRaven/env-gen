"""Deliverability aggregator end-to-end test.

PR 6 review cleanup (2026-05-30) deleted five gate blocks from
``DeliverProjectTool.execute`` that were dead-on-production
(they read ``self.agent.hub_registry`` which is never set on
real agents — production agents store hubs as ``self._hubs``).
The old ``test_full_flow_blocked_then_run_unblocks`` test
exercised the now-deleted ``runhub-since-session`` gate via a
MagicMock that injected ``hub_registry``; it tested dead-on-
production code so was removed.

What remains here covers the LIVE deliverability path:
``compute_deliverability`` is called by ``deliver_project_call``
in the live monitor server (UI path) and computes the same
gates (runhub / coverage / visual / seed / retro) that the
DeliverProjectTool internal gates intended to enforce. This
suite pins that the aggregator returns ``blocked`` before a
successful run and ``deliverable`` after one.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _add_retro(reg, gen_id):
    reg.workhub.create_document(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                   "lessons": [], "proposed_prompt_changes": []})


def _insert_passing_run(reg, started_at):
    r = reg.runhub.record_run(branch="x", generated_dir="/g", agent="orch")
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = started_at
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = []
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"), change_info={"agent": "runhub"})


class DeliverabilityAggregatorE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="deliv_e2e_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg, 9000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deliverability_verdict_flips_blocked_to_deliverable_after_run(self) -> None:
        """End-to-end: ``compute_deliverability`` (the UI-deliver
        path's enforcement) returns ``blocked`` until a successful
        run is recorded, then ``deliverable``. Uses the per-test
        tempdir as app_root to avoid the reviewer-flagged ``/tmp``
        recursion bug."""
        from multi_agent.runtime.deliverability import compute_deliverability
        app_root = self.tmp
        # The AUTHORED-SEED gate is deliberately NOT waived by functional
        # validation (outlook run-33: a lane that never wrote seed_data.json
        # shipped the bland framework-fallback seed as "SUCCESS"), so without a
        # seed file this test's "deliverable" half could never be reached — for a
        # reason that has nothing to do with the run recording it is about.
        _be = app_root / "backend"
        _be.mkdir(parents=True, exist_ok=True)
        (_be / "seed_data.json").write_text('{"users": [{"id": 1, "email": "user1@example.com", "name": "Ada Lovelace"}, {"id": 2, "email": "user2@example.com", "name": "Alan Turing"}, {"id": 3, "email": "user3@example.com", "name": "Grace Hopper"}, {"id": 4, "email": "user4@example.com", "name": "Katherine Johnson"}, {"id": 5, "email": "user5@example.com", "name": "Edsger Dijkstra"}, {"id": 6, "email": "user6@example.com", "name": "Barbara Liskov"}, {"id": 7, "email": "user7@example.com", "name": "Donald Knuth"}, {"id": 8, "email": "user8@example.com", "name": "Margaret Hamilton"}, {"id": 9, "email": "user9@example.com", "name": "Ken Thompson"}, {"id": 10, "email": "user10@example.com", "name": "Radia Perlman"}, {"id": 11, "email": "user11@example.com", "name": "Leslie Lamport"}]}\n')
        # Before run: aggregator says blocked.
        report = compute_deliverability(self.reg, app_root, session_start_ts=9000.0)
        self.assertEqual(report.verdict, "blocked")
        # After run: aggregator says deliverable.
        _insert_passing_run(self.reg, started_at=9001.0)
        report = compute_deliverability(self.reg, app_root, session_start_ts=9000.0)
        self.assertEqual(report.verdict, "deliverable", f"blockers: {report.blockers}")


if __name__ == "__main__":
    unittest.main()
