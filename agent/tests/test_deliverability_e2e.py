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
    reg.workhub.create_page(
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
        # Before run: aggregator says blocked.
        report = compute_deliverability(self.reg, app_root, session_start_ts=9000.0)
        self.assertEqual(report.verdict, "blocked")
        # After run: aggregator says deliverable.
        _insert_passing_run(self.reg, started_at=9001.0)
        report = compute_deliverability(self.reg, app_root, session_start_ts=9000.0)
        self.assertEqual(report.verdict, "deliverable", f"blockers: {report.blockers}")


if __name__ == "__main__":
    unittest.main()
