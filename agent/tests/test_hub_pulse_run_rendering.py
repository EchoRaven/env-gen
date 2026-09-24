"""Tests for hub_pulse RunHub rendering (Cutover 11)."""

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
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse, build_hub_pulse_prompt  # noqa: E402


class HubPulseRunRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pulse_run_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_runs_no_section(self) -> None:
        report = collect_hub_pulse(self.reg, "orchestrator")
        rendered = build_hub_pulse_prompt(report)
        if rendered is not None:
            self.assertNotIn("RECENT RUN", rendered.upper())

    def test_orchestrator_sees_latest_run_status(self) -> None:
        run = self.reg.runhub.record_run(branch="x", generated_dir="/tmp/g", agent="orch")
        self.reg.runhub.update_run_status(run["id"], "failed", agent="runhub", fail_count=3)
        report = collect_hub_pulse(self.reg, "orchestrator")
        rendered = build_hub_pulse_prompt(report)
        self.assertIn("RECENT RUN", rendered.upper())
        self.assertIn("failed", rendered.lower())
        self.assertIn("3", rendered)  # fail_count


if __name__ == "__main__":
    unittest.main()
