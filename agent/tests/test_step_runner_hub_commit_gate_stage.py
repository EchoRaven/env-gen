"""Verify Task 6 surgery: step_runner replaces crdt_sync block with hub_commit_gate
and wires _pending_integrity_prompt roll-forward into the next step's hub_pulse."""

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


class StepRunnerHubCommitGateStageTests(unittest.TestCase):
    def test_default_stage_order_has_hub_commit_gate_last_data_stage(self):
        marker = "default_stage_order = ["
        idx = STEP_RUNNER_SRC.index(marker)
        end = STEP_RUNNER_SRC.index("]", idx)
        block = STEP_RUNNER_SRC[idx:end]
        self.assertIn('"hub_commit_gate"', block)
        # hub_commit_gate must come after action (the LLM-decision stage)
        self.assertGreater(
            block.index('"hub_commit_gate"'), block.index('"action"')
        )

    def test_engine_forces_hub_commit_gate_into_enabled_stages(self):
        self.assertIn('enabled_stages.add("hub_commit_gate")', STEP_RUNNER_SRC)

    def test_crdt_sync_stage_block_removed(self):
        # The legacy _run_crdt_sync_stage callsite must be gone
        self.assertNotIn("_run_crdt_sync_stage", STEP_RUNNER_SRC)
        # The legacy _stage_enabled("crdt_sync") gate must be gone
        self.assertNotIn('_stage_enabled("crdt_sync")', STEP_RUNNER_SRC)

    def test_hub_commit_gate_stage_block_present(self):
        self.assertIn('_stage_enabled("hub_commit_gate")', STEP_RUNNER_SRC)
        # Module imports should reference commit_gate symbols
        self.assertIn("from .commit_gate import", STEP_RUNNER_SRC)
        self.assertIn("collect_loose_ends", STEP_RUNNER_SRC)
        self.assertIn("collect_loose_ends_details", STEP_RUNNER_SRC)
        self.assertIn("build_commit_gate_prompt", STEP_RUNNER_SRC)
        self.assertIn("DEFAULT_THRESHOLDS", STEP_RUNNER_SRC)

    def test_pending_integrity_prompt_roll_forward_wired(self):
        # The gate sets the rollforward attribute when a prompt was produced.
        self.assertIn("self._pending_integrity_prompt = gate_prompt", STEP_RUNNER_SRC)
        # The pulse stage consumes and clears the rollforward attribute.
        self.assertIn(
            'getattr(self, "_pending_integrity_prompt", None)', STEP_RUNNER_SRC
        )
        self.assertIn("self._pending_integrity_prompt = None", STEP_RUNNER_SRC)

    def test_pulse_consumes_before_gate_sets(self):
        # In source order, the consume site (pulse stage) must come BEFORE the gate
        # set site so that within a single step iteration the prompt prepared by
        # the previous step's gate is what the pulse renders.
        consume_idx = STEP_RUNNER_SRC.index(
            'getattr(self, "_pending_integrity_prompt", None)'
        )
        set_idx = STEP_RUNNER_SRC.index("self._pending_integrity_prompt = gate_prompt")
        self.assertLess(consume_idx, set_idx)

    def test_gate_publishes_integrity_event_when_prompt_present(self):
        self.assertIn('event_type="integrity_check"', STEP_RUNNER_SRC)
        self.assertIn('source_hub="system"', STEP_RUNNER_SRC)


if __name__ == "__main__":
    unittest.main()
