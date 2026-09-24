"""#324 — the DOMINANT per-run sink found by the r91/r92/r93 trajectory review (backend +
orchestrator reviewers, independently).

compute_deliverability reads the authored seed from the INTEGRATION tree
(``app_root/backend/seed_data.json``), but the backend lane commits its populated
seed_data.json to its OWN worktree (``worktrees/backend/app/backend/seed_data.json``).
#322's reconcile_integration_seed was only invoked at the two terminal MERGE sites
(final flush + release), never before THIS read — so every deliverability poll re-read
the ``{}`` placeholder and reported "authored seed missing" while a valid populated seed
sat in the lane worktree. The gate could clear ONLY by force-delivering (which triggered
the merge): "the gate that decides whether to deliver is only refreshed BY delivering."
r92: 571 deliverability polls / 16 phantom P0 tasks; r93: 486 / 6; both wedged M1.

Fix: reconcile the lane-authored seed onto integration at the TOP of compute_deliverability,
before the read. Idempotent + best-effort (#322 never clobbers a populated integration seed).
"""
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.deliverability import compute_deliverability  # noqa: E402


def _passing_run(reg):
    now = time.time()
    r = reg.runhub.record_run(branch="feature/x", generated_dir="/tmp/g", agent="orch")
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = now
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = [{"verdict": "pass"}]
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"), change_info={"agent": "runhub"})
    reg.record_validation_result(
        "ui_flow:smoke", "passed", agent="verifier",
        metadata={"check": "ui_flow", "flow": "smoke"})


_POP_SEED = (
    '{"users":[{"id":1,"username":"alex","email":"a@x.io"},'
    '{"id":2,"username":"bao","email":"b@x.io"}],'
    '"videos":[{"id":1,"caption":"hi","user_id":1}]}'
)


class SeedReconcileBeforeReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="seed324_"))
        self.reg = HubRegistry(self.tmp)
        self.app_root = self.tmp / "app"
        (self.app_root / "backend").mkdir(parents=True)
        (self.app_root / "main.tsx").write_text("x=1;\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _lane_seed(self, lane, body):
        p = self.tmp / "worktrees" / lane / "app" / "backend" / "seed_data.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    def test_lane_authored_seed_clears_the_gate_before_merge(self):
        # integration has only the {} placeholder; the backend lane authored a real seed.
        (self.app_root / "backend" / "seed_data.json").write_text("{}", encoding="utf-8")
        self._lane_seed("backend", _POP_SEED)
        _passing_run(self.reg)
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertFalse(
            any("authored seed missing" in b.lower() for b in report.blockers),
            f"lane-authored seed must clear the gate before merge: {report.blockers}")
        # reconcile side-effect: integration seed is now populated
        integ = (self.app_root / "backend" / "seed_data.json")
        self.assertIn("username", integ.read_text())

    def test_absent_integration_seed_also_filled_from_lane(self):
        # not even the placeholder present yet
        self._lane_seed("frontend", _POP_SEED)   # any lane worktree
        _passing_run(self.reg)
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertFalse(any("authored seed missing" in b.lower() for b in report.blockers),
                         f"blockers: {report.blockers}")

    def test_no_lane_seed_still_blocks(self):
        # genuinely no authored seed anywhere → the gate MUST still fire (no false clear).
        (self.app_root / "backend" / "seed_data.json").write_text("{}", encoding="utf-8")
        _passing_run(self.reg)
        report = compute_deliverability(self.reg, self.app_root, session_start_ts=0.0)
        self.assertTrue(
            any("authored seed missing" in b.lower() for b in report.blockers),
            "a genuinely missing seed must still block — reconcile must not invent data")


if __name__ == "__main__":
    unittest.main()
