"""Tests for hub_pulse bug rendering enhancements (Cutover 10)."""

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
from multi_agent.agents.runtime.hub_pulse import collect, build_hub_pulse_prompt  # noqa: E402


class HubPulseBugRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pulse_bug_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_normal_agent_pulse_renders_assigned_bug_with_severity_prefix(self) -> None:
        self.reg.workhub.create_task(title="500 on feed", assignee="backend",
                                     agent="debugger",
                                     kind="bug", severity="P1", bug_state="assigned",
                                     bug_artifacts={})
        report = collect("backend", self.reg)
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("[P1] 500 on feed", rendered)
        self.assertIn("ASSIGNED BUGS", rendered.upper())

    def test_bug_triage_orchestrator_pulse_shows_open_bug_queue(self) -> None:
        self.reg.workhub.create_task(title="A", agent="verifier",
                                     kind="bug", severity="P0", bug_state="open",
                                     bug_artifacts={})
        self.reg.workhub.create_task(title="B", agent="verifier",
                                     kind="bug", severity="P2", bug_state="open",
                                     bug_artifacts={})
        report = collect("debugger", self.reg)
        rendered = build_hub_pulse_prompt(report)
        upper = rendered.upper()
        self.assertIn("OPEN BUG QUEUE", upper)
        self.assertIn("[P0] A", rendered)
        self.assertIn("[P2] B", rendered)

    def test_normal_agent_with_no_assigned_bugs_skips_bug_section(self) -> None:
        report = collect("backend", self.reg)
        rendered = build_hub_pulse_prompt(report)
        # When pulse is otherwise empty, render is None or doesn't contain ASSIGNED BUGS.
        if rendered is not None:
            self.assertNotIn("ASSIGNED BUGS", rendered.upper())


if __name__ == "__main__":
    unittest.main()
