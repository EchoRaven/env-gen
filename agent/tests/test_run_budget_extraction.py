"""PROPOSAL #8 Tier-1b: RunBudget extracted from Orchestrator (behavior-preserving).

Thin construction + round-trip guard for the new collaborator, plus a check that the
Orchestrator shims still delegate (the file's call surface is preserved byte-for-byte).
"""

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.run_budget import RunBudget  # noqa: E402

_ENV = {"max_wall_sec": 7200.0, "max_ticks": 240, "unlimited": False}


class RunBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="runbudget_"))
        self.b = RunBudget(self.tmp, logging.getLogger("test"))

    def test_path_under_output_dir(self):
        self.assertEqual(self.b.path(), self.tmp / "run_budget.json")

    def test_load_caps_falls_back_to_env_when_absent(self):
        self.assertEqual(self.b.load_caps(_ENV), dict(_ENV))

    def test_write_then_load_roundtrip(self):
        self.b.write(_ENV, started_at=1000.0, elapsed=12.3, ticks=4, status="running")
        data = json.loads(self.b.path().read_text())
        self.assertEqual(data["caps"]["max_ticks"], 240)
        self.assertEqual(data["usage"]["ticks"], 4)
        self.assertEqual(data["usage"]["status"], "running")
        # load_caps reads caps back (UI may raise them live)
        self.assertEqual(self.b.load_caps({"max_wall_sec": 1.0, "max_ticks": 1})["max_ticks"], 240)

    def test_load_caps_honors_live_unlimited_raise(self):
        self.b.write({"max_wall_sec": 1.0, "max_ticks": 1, "unlimited": True},
                     started_at=0.0, elapsed=0.0, ticks=0, status="running")
        self.assertTrue(self.b.load_caps(_ENV)["unlimited"])

    def test_write_never_raises_on_bad_dir(self):
        bad = RunBudget(Path("/nonexistent/which/should/not/exist"), logging.getLogger("test"))
        bad.write(_ENV, 0.0, 0.0, 0, "running")  # best-effort: no exception


class OrchestratorShimDelegationTests(unittest.TestCase):
    def test_shims_delegate_to_budget(self):
        # The Orchestrator shims must call through to self._budget (call surface
        # preserved). Bind the unbound methods to a stub holding a real RunBudget.
        from multi_agent.orchestrator import Orchestrator
        tmp = Path(tempfile.mkdtemp(prefix="runbudget_shim_"))

        class _Stub:
            _budget = RunBudget(tmp, logging.getLogger("test"))

        stub = _Stub()
        self.assertEqual(Orchestrator._run_budget_path(stub), tmp / "run_budget.json")
        self.assertEqual(Orchestrator._load_run_budget_caps(stub, _ENV), dict(_ENV))
        Orchestrator._write_run_budget(stub, _ENV, 0.0, 1.0, 2, "running")
        self.assertEqual(json.loads((tmp / "run_budget.json").read_text())["usage"]["ticks"], 2)


if __name__ == "__main__":
    unittest.main()
