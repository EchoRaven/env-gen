"""E2E: create P0 task with deps; backend's claim refused until dep complete; pulse reflects it."""

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
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse, build_hub_pulse_prompt  # noqa: E402


class TaskPriorityE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="task_e2e_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_dep_chain_flow(self) -> None:
        # Orchestrator creates dep + dependent + assigns both
        dep = self.reg.workhub.create_task(
            title="design schema", agent="orch",
            assignee="database", priority="P1")
        dependent = self.reg.workhub.create_task(
            title="implement feed endpoint", agent="orch",
            assignee="backend", priority="P0",
            depends_on=[dep["id"]])

        # Backend's pulse should show dependent BLOCKED (waiting on dep)
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("BLOCKED ON OTHERS", rendered.upper())
        self.assertIn("implement feed endpoint", rendered)

        # Backend tries to claim -> refused
        claim_result = self.reg.workhub.claim_task(dependent["id"], agent="backend")
        self.assertIn("error", claim_result)

        # Database claims + completes its dep
        self.reg.workhub.claim_task(dep["id"], agent="database")
        self.reg.workhub.complete_task(dep["id"], agent="database",
                                        result={"schema": "users"})

        # Now backend's pulse should show dependent READY
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("YOUR TASK QUEUE", rendered.upper())
        self.assertIn("implement feed endpoint", rendered)
        # And critically: [P0] prefix since it's priority P0
        self.assertIn("[P0]", rendered)

        # Backend can now claim
        claim_result = self.reg.workhub.claim_task(dependent["id"], agent="backend")
        self.assertEqual(claim_result.get("status"), "in_progress")

    def test_pulse_priority_sort_p0_before_p3(self) -> None:
        # Create one P3 first, then P0; both assigned to backend, no deps
        self.reg.workhub.create_task(
            title="cleanup logs", agent="orch",
            assignee="backend", priority="P3")
        self.reg.workhub.create_task(
            title="fix prod outage", agent="orch",
            assignee="backend", priority="P0")
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        # Scope the priority-sort check to within the ## YOUR TASK QUEUE
        # section (the older WorkHub summary lists tasks in creation order,
        # which would otherwise mask the queue-level sort).
        queue_start = rendered.find("## YOUR TASK QUEUE")
        self.assertGreaterEqual(queue_start, 0,
                                 "expected ## YOUR TASK QUEUE in rendered pulse")
        # Slice to end-of-section (next blank line or next ## header)
        queue_tail = rendered[queue_start:]
        next_section = queue_tail.find("\n## ", 1)
        if next_section < 0:
            queue_section = queue_tail
        else:
            queue_section = queue_tail[:next_section]
        # P0 should appear before P3 regardless of creation order
        self.assertLess(queue_section.find("fix prod outage"),
                          queue_section.find("cleanup logs"))


if __name__ == "__main__":
    unittest.main()
