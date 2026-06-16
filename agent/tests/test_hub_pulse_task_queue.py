"""Tests that hub_pulse renders TASK QUEUE + BLOCKED ON OTHERS sections (Cutover 23)."""

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


class HubPulseTaskQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pulse_task_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pulse_renders_ready_task_sorted_p0_first(self) -> None:
        self.reg.workhub.create_task(
            title="low priority", agent="orch", assignee="backend", priority="P3")
        self.reg.workhub.create_task(
            title="critical", agent="orch", assignee="backend", priority="P0")
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("TASK QUEUE", rendered.upper())
        # Within the ## YOUR TASK QUEUE section, P0 must come before P3.
        queue_start = rendered.find("## YOUR TASK QUEUE")
        self.assertGreaterEqual(queue_start, 0)
        queue_segment = rendered[queue_start:]
        p0_idx = queue_segment.find("critical")
        p3_idx = queue_segment.find("low priority")
        self.assertGreaterEqual(p0_idx, 0)
        self.assertGreaterEqual(p3_idx, 0)
        self.assertGreater(p3_idx, p0_idx,
                            "P0 task should be rendered before P3 task")

    def test_pulse_renders_blocked_section_when_deps_incomplete(self) -> None:
        dep = self.reg.workhub.create_task(
            title="dep", agent="orch", assignee="frontend")
        self.reg.workhub.create_task(
            title="waiting", agent="orch", assignee="backend",
            depends_on=[dep["id"]])
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("BLOCKED", rendered.upper())
        self.assertIn("waiting", rendered)

    def test_pulse_omits_section_when_no_assigned_tasks(self) -> None:
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        # No section header when there's nothing to render
        # (this can be relaxed if the prompt always shows the header)
        self.assertNotIn("TASK QUEUE", (rendered or "").upper())

    def test_pulse_priority_label_in_render(self) -> None:
        self.reg.workhub.create_task(
            title="urgent task", agent="orch", assignee="backend", priority="P0")
        report = collect_hub_pulse(self.reg, "backend")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("[P0]", rendered)


if __name__ == "__main__":
    unittest.main()
