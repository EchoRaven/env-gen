"""#1202ev: a killed run must not be indistinguishable from a running one.

40 of the 104 undelivered runs in the corpus carry `status="running"` with no
terminal reason. Every one is a process someone killed -- and on disk it reads
exactly like a run still working, so no post-mortem can classify them.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.run_budget import (  # noqa: E402
    RunBudget,
    _proc_started_1202ev,
    process_liveness_1202ev,
)


def _ledger(usage):
    d = tempfile.mkdtemp()
    (Path(d) / "run_budget.json").write_text(
        json.dumps({"caps": {}, "usage": dict(usage), "llm": {"cost_usd": 163.0}}),
        encoding="utf-8")
    return Path(d)


def _status(d):
    return json.loads((d / "run_budget.json").read_text(encoding="utf-8"))


class TestKilledRunsAreDistinguishable(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # A genuinely dead pid, carrying the start time it really had while alive.
        victim = subprocess.Popen(["sleep", "30"])
        cls.dead_pid = victim.pid
        cls.dead_start = _proc_started_1202ev(victim.pid)
        victim.kill()
        victim.wait()

    def test_the_writer_of_a_ledger_is_recorded(self):
        """Without this the rest is unanswerable -- nothing says who wrote the file."""
        d = Path(tempfile.mkdtemp())
        RunBudget(d, None).write({"max_wall_sec": 1.0, "max_ticks": 1}, 0.0, 1.0, 1, "running")
        usage = _status(d)["usage"]
        self.assertEqual(usage.get("pid"), os.getpid())
        self.assertIsNotNone(usage.get("pid_started"))
        self.assertEqual(process_liveness_1202ev(usage), "alive")

    def test_a_killed_run_is_sealed_as_abandoned(self):
        d = _ledger({"status": "running", "pid": self.dead_pid,
                     "pid_started": self.dead_start})
        self.assertEqual(RunBudget(d, None).seal_abandoned_predecessor_1202ev(), "sealed")
        usage = _status(d)["usage"]
        self.assertEqual(usage["status"], "abandoned")
        self.assertIn(str(self.dead_pid), usage["terminal_reason"])

    def test_a_recycled_pid_does_not_read_as_alive(self):
        """A live pid with a different start time is a DIFFERENT process."""
        d = _ledger({"status": "running", "pid": os.getpid(), "pid_started": 1.0})
        self.assertEqual(RunBudget(d, None).seal_abandoned_predecessor_1202ev(), "sealed")

    def test_a_concurrent_live_run_is_never_sealed(self):
        """The r43 shape: two processes over one dir. Sealing would libel a live run."""
        d = _ledger({"status": "running", "pid": os.getppid(),
                     "pid_started": _proc_started_1202ev(os.getppid())})
        self.assertEqual(RunBudget(d, None).seal_abandoned_predecessor_1202ev(), "alive")
        self.assertEqual(_status(d)["usage"]["status"], "running")

    def test_an_unidentifiable_writer_is_left_alone(self):
        """Ledgers written before #1202ev prove nothing. No false certainty."""
        d = _ledger({"status": "running"})
        self.assertEqual(RunBudget(d, None).seal_abandoned_predecessor_1202ev(), "unknown")
        self.assertEqual(_status(d)["usage"]["status"], "running")

    def test_a_terminal_status_is_not_rewritten(self):
        d = _ledger({"status": "finished", "pid": self.dead_pid,
                     "pid_started": self.dead_start})
        self.assertEqual(RunBudget(d, None).seal_abandoned_predecessor_1202ev(), "not running")
        self.assertEqual(_status(d)["usage"]["status"], "finished")

    def test_sealing_keeps_the_predecessors_spend(self):
        """_carry_1202cg_for reads this file to keep cost honest across a resume."""
        d = _ledger({"status": "running", "pid": self.dead_pid,
                     "pid_started": self.dead_start})
        RunBudget(d, None).seal_abandoned_predecessor_1202ev()
        self.assertEqual(_status(d)["llm"]["cost_usd"], 163.0)

    def test_the_orchestrator_seals_before_it_writes(self):
        """The seal is useless after this process rebuilds the payload."""
        src = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
               / "orchestrator.py").read_text(encoding="utf-8")
        made = src.index("self._budget = RunBudget(")
        sealed = src.index("seal_abandoned_predecessor_1202ev()")
        self.assertLess(made, sealed, "the seal runs before RunBudget exists")
        # and before run() -- where #1170's early write happens.
        self.assertLess(sealed, src.index("\n    async def run("),
                        "the seal must happen at construction, not inside run()")


if __name__ == "__main__":
    unittest.main()
