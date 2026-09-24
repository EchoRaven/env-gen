"""Verify Task 5 surgery: step_runner replaces inbox_status + crdt_changes blocks with hub_pulse."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


STEP_RUNNER_SRC = (
    LLM_DIR
    / "multi_agent"
    / "agents"
    / "runtime"
    / "step_runner.py"
).read_text()


STAGES_SRC = (
    LLM_DIR
    / "multi_agent"
    / "agents"
    / "runtime"
    / "step_pipeline"
    / "stages.py"
).read_text()


class StepRunnerStageReplacementTests(unittest.TestCase):
    def test_default_stage_order_has_hub_pulse_first(self):
        self.assertIn('"hub_pulse"', STEP_RUNNER_SRC)
        # hub_pulse should appear in default_stage_order list
        marker = "default_stage_order = ["
        idx = STEP_RUNNER_SRC.index(marker)
        end = STEP_RUNNER_SRC.index("]", idx)
        block = STEP_RUNNER_SRC[idx:end]
        # hub_pulse listed before runtime_team_status
        self.assertIn('"hub_pulse"', block)
        self.assertLess(block.index('"hub_pulse"'), block.index('"runtime_team_status"'))

    def test_default_stage_order_drops_inbox_status_and_crdt_changes(self):
        marker = "default_stage_order = ["
        idx = STEP_RUNNER_SRC.index(marker)
        end = STEP_RUNNER_SRC.index("]", idx)
        block = STEP_RUNNER_SRC[idx:end]
        self.assertNotIn('"inbox_status"', block)
        self.assertNotIn('"crdt_changes"', block)

    def test_engine_forces_hub_pulse_into_enabled_stages(self):
        # Engine-force lines should be present so yaml cannot disable hub_pulse
        self.assertIn('enabled_stages.add("hub_pulse")', STEP_RUNNER_SRC)

    def test_inbox_status_stage_block_removed(self):
        # The old "_stage_enabled(\"inbox_status\")" gate should be gone
        self.assertNotIn('_stage_enabled("inbox_status")', STEP_RUNNER_SRC)

    def test_crdt_changes_stage_block_removed(self):
        self.assertNotIn('_stage_enabled("crdt_changes")', STEP_RUNNER_SRC)

    def test_hub_pulse_stage_block_present(self):
        self.assertIn('_stage_enabled("hub_pulse")', STEP_RUNNER_SRC)
        # Module import should reference hub_pulse
        self.assertIn("collect_hub_pulse", STEP_RUNNER_SRC)
        self.assertIn("build_hub_pulse_prompt", STEP_RUNNER_SRC)

    def test_retrieve_context_no_longer_takes_dead_prompt_params(self):
        # The retrieve_context stage callsite should not pass the two dead kwargs
        self.assertNotIn("inbox_status_prompt=inbox_status_prompt", STEP_RUNNER_SRC)
        self.assertNotIn("crdt_changes_prompt=crdt_changes_prompt", STEP_RUNNER_SRC)
        # And the stage signature should no longer demand those kwargs
        self.assertNotIn("inbox_status_prompt: Optional[str]", STAGES_SRC)
        self.assertNotIn("crdt_changes_prompt: Optional[str]", STAGES_SRC)


if __name__ == "__main__":
    unittest.main()
