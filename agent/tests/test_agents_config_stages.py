"""Lock the shape of agents_config.yaml for the post-CRDT step pipeline.

These tests guard against accidental reintroduction of the dead
``inbox_status`` / ``crdt_changes`` / ``crdt_sync`` stages whose CRDT
backings were stripped in Cutovers 4-5, and ensure the new code-forced
``hub_pulse`` / ``hub_commit_gate`` stages appear in every profile plus
the engine defaults, with the commit_gate threshold block present.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


CONFIG_PATH = (
    LLM_DIR
    / "multi_agent"
    / "agents"
    / "agents_config.yaml"
)

EXPECTED_STAGES = [
    "hub_pulse",
    "runtime_team_status",
    # `planning` deleted in #333: one tools=[] LLM call per step whose only
    # effect was a MODE: team|direct substring switch that never fired
    # (0 hits across r91/r92/r93). Team mode keeps its tool-driven triggers.
    # test_333_planning_stage_removed.py guards it staying out.
    "retrieve_context",
    "action",
    "hub_commit_gate",
    "knowledge_sync",
]

DEAD_STAGES = {"inbox_status", "crdt_changes", "crdt_sync"}


class AgentsConfigStagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            cls.cfg = yaml.safe_load(fh)
        cls.raw_text = CONFIG_PATH.read_text(encoding="utf-8")

    def test_no_dead_stage_keywords_anywhere_in_file(self):
        for dead in DEAD_STAGES:
            self.assertNotIn(
                dead,
                self.raw_text,
                f"Dead stage '{dead}' still referenced in agents_config.yaml",
            )

    def test_execution_pipeline_defaults_stages_match_expected(self):
        defaults = self.cfg["execution_pipeline_defaults"]
        self.assertEqual(defaults["stages"], EXPECTED_STAGES)

    def test_execution_pipeline_defaults_has_commit_gate_block(self):
        defaults = self.cfg["execution_pipeline_defaults"]
        self.assertIn("commit_gate", defaults)
        gate = defaults["commit_gate"]
        self.assertIs(gate.get("enabled"), True)
        # All three thresholds present and positive ints.
        for key in ("stale_task_steps", "stale_review_steps", "stale_pr_steps"):
            self.assertIn(key, gate, f"commit_gate missing '{key}'")
            self.assertIsInstance(gate[key], int)
            self.assertGreater(gate[key], 0)

    def test_default_max_tool_calls_has_hub_pulse_and_gate_zero(self):
        defaults = self.cfg["execution_pipeline_defaults"]
        caps = defaults.get("max_tool_calls_per_stage", {})
        self.assertEqual(caps.get("hub_pulse"), 0)
        self.assertEqual(caps.get("hub_commit_gate"), 0)

    def test_every_profile_uses_expected_stage_list(self):
        # STALE-TEST drift: a profile's execution_pipeline is MERGED over
        # execution_pipeline_defaults at runtime (configurable_agent.py:
        # {**execution_pipeline_defaults, **profile.execution_pipeline}), so a profile may
        # omit `stages` and legitimately inherit them from the defaults. What must hold is
        # the EFFECTIVE stage list, not that every profile restates it verbatim.
        # design_analyst (one-shot pre-generation agent added 2026-07-21) overrides only
        # max_action_rounds_per_step and inherits `stages` this way — so compare the
        # effective (profile-or-default) stages, mirroring the runtime merge.
        defaults = self.cfg["execution_pipeline_defaults"]
        profiles = self.cfg.get("profiles", {})
        self.assertGreater(len(profiles), 0, "no profiles found")
        for name, profile in profiles.items():
            ep = profile.get("execution_pipeline")
            self.assertIsNotNone(
                ep, f"profile '{name}' has no execution_pipeline block"
            )
            effective_stages = ep.get("stages") or defaults.get("stages")
            self.assertEqual(
                effective_stages,
                EXPECTED_STAGES,
                f"profile '{name}' stages do not match expected post-CRDT pipeline",
            )

    def test_every_profile_max_tool_calls_excludes_dead_stages(self):
        profiles = self.cfg.get("profiles", {})
        for name, profile in profiles.items():
            caps = (
                profile.get("execution_pipeline", {}).get("max_tool_calls_per_stage")
                or {}
            )
            for dead in DEAD_STAGES:
                self.assertNotIn(
                    dead,
                    caps,
                    f"profile '{name}' max_tool_calls still references dead "
                    f"stage '{dead}'",
                )

    def test_engine_forced_stages_appear_first_and_last_in_defaults(self):
        defaults = self.cfg["execution_pipeline_defaults"]
        stages = defaults["stages"]
        self.assertEqual(
            stages[0],
            "hub_pulse",
            "hub_pulse must be the first default stage",
        )
        self.assertEqual(
            stages[-2:][0] if stages[-1] == "knowledge_sync" else stages[-1],
            "hub_commit_gate",
            "hub_commit_gate must run after action (before knowledge_sync)",
        )
        # knowledge_sync is the optional tail; gate must come right before it.
        self.assertIn("hub_commit_gate", stages)
        self.assertLess(
            stages.index("action"),
            stages.index("hub_commit_gate"),
            "hub_commit_gate must come after action",
        )

    def test_optional_stages_drops_crdt_sync(self):
        defaults = self.cfg["execution_pipeline_defaults"]
        optional = set(defaults.get("optional_stages") or [])
        self.assertNotIn(
            "crdt_sync",
            optional,
            "optional_stages still references dead crdt_sync stage",
        )


class TestHubConsistencyGatesInConfig(unittest.TestCase):
    def test_each_implementer_profile_has_hub_consistency_gate(self):
        import yaml
        from pathlib import Path
        cfg_path = (
            Path(__file__).resolve().parents[1]
            / "env_generator" / "llm_generator"
            / "multi_agent" / "agents" / "agents_config.yaml"
        )
        cfg = yaml.safe_load(cfg_path.read_text())
        profiles = cfg["profiles"]
        for role in ("backend", "frontend"):
            kinds = [
                str((p or {}).get("kind", ""))
                for p in (profiles[role].get("workflow_policies") or [])
            ]
            self.assertIn(
                "hub_consistency_gate", kinds,
                f"{role} profile is missing hub_consistency_gate "
                f"(workflow_policies={kinds})",
            )


if __name__ == "__main__":
    unittest.main()
