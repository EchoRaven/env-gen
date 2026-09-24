"""Orch-F1: per-role action-stage allowlist.

Evidence (r93 Orchestrator Agent trajectory, 1164 LLM responses / 101M
response-context tokens): 166 responses (14.3% of calls, 14.9M tokens) are
``edit_code`` no-op filler — "no code to edit", "not an edit_code task",
"ACTION_STATUS: stop — no code edits needed". The coordinator has no
implementation role, yet ``ACTION_INTERNAL_STAGES`` walks it through
``edit_code`` every action round and the fast-skip at ``action.py`` never
fires because the orchestrator's memory/file/project tools DO map to the
edit_code category hint.

The fix is a per-role stage allowlist, but it cannot be a blunt drop: the
category hints feed ``rank_tool_names``' ``category_bonus * 4.0``, so a stage
that is disabled without re-homing its categories silently demotes every tool
that lived there. For the orchestrator that is ``read`` (11 calls in r93),
``update_memory_bank`` (10) and ``codehub_get_file_content`` (2) — exactly the
"orphan class" that ``tool_surface.detect_orphaned_tool_offerings`` exists to
catch (a granted-but-never-offered tool wedges the lane).

So this pins BOTH halves:
  1. disabled stages are skipped WITHOUT an LLM call, and
  2. a config that would orphan a category the profile is actually granted is
     rejected at construction, not discovered in a wedged run.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ALL_STAGES: Tuple[str, ...] = (
    "communicate", "edit_code", "run_checks", "delegate_team", "deliver",
)
BASE_HINTS: Dict[str, Set[str]] = {
    "communicate": {"communication", "progress"},
    "edit_code": {"file", "memory", "project", "analysis", "reference"},
    "run_checks": {"runtime", "api", "docker"},
    "delegate_team": {"team_spawn"},
    "deliver": {"progress"},
}


class _StubAgent:
    """Minimal stand-in exposing only what the policy helpers read."""

    ACTION_INTERNAL_STAGES = ALL_STAGES
    ACTION_STAGE_CATEGORY_HINTS = BASE_HINTS

    def __init__(self, allowlist=None, overrides=None):
        if allowlist is not None:
            self._action_stages_allowlist = tuple(allowlist)
        if overrides is not None:
            self._action_stage_category_overrides = {
                k: set(v) for k, v in overrides.items()
            }


class ResolveEnabledStages(unittest.TestCase):
    """Half 1 — which stages run at all."""

    def test_no_config_runs_every_stage(self):
        from multi_agent.agents.runtime.action_stage_policy import (
            resolve_enabled_action_stages)
        self.assertEqual(resolve_enabled_action_stages(_StubAgent()), ALL_STAGES)

    def test_allowlist_narrows_and_preserves_declared_order(self):
        from multi_agent.agents.runtime.action_stage_policy import (
            resolve_enabled_action_stages)
        # deliberately out of order in the config — engine order must win so
        # communicate still precedes deliver within a round.
        agent = _StubAgent(allowlist=("deliver", "run_checks", "communicate"))
        self.assertEqual(
            resolve_enabled_action_stages(agent),
            ("communicate", "run_checks", "deliver"),
        )

    def test_disabled_stage_is_absent(self):
        from multi_agent.agents.runtime.action_stage_policy import (
            resolve_enabled_action_stages)
        agent = _StubAgent(allowlist=("communicate", "run_checks", "deliver"))
        self.assertNotIn("edit_code", resolve_enabled_action_stages(agent))

    def test_unknown_agent_shape_degrades_to_class_default(self):
        """A stub/bare object without the attrs must not explode."""
        from multi_agent.agents.runtime.action_stage_policy import (
            resolve_enabled_action_stages)

        class _Bare:
            pass

        self.assertEqual(resolve_enabled_action_stages(_Bare()), ())


class ResolveCategoryHints(unittest.TestCase):
    """Half 2 — where a disabled stage's categories go."""

    def test_no_override_returns_base_hints(self):
        from multi_agent.agents.runtime.action_stage_policy import (
            resolve_stage_category_hints)
        self.assertEqual(
            resolve_stage_category_hints(_StubAgent())["edit_code"],
            BASE_HINTS["edit_code"],
        )

    def test_override_unions_into_the_stage_rather_than_replacing(self):
        from multi_agent.agents.runtime.action_stage_policy import (
            resolve_stage_category_hints)
        agent = _StubAgent(overrides={"run_checks": {"file", "memory"}})
        hints = resolve_stage_category_hints(agent)
        self.assertEqual(hints["run_checks"], {"runtime", "api", "docker", "file", "memory"})

    def test_base_hints_are_not_mutated_by_resolution(self):
        from multi_agent.agents.runtime.action_stage_policy import (
            resolve_stage_category_hints)
        agent = _StubAgent(overrides={"run_checks": {"file"}})
        resolve_stage_category_hints(agent)
        self.assertEqual(BASE_HINTS["run_checks"], {"runtime", "api", "docker"})


class ParseAndValidateConfig(unittest.TestCase):
    """Fail-closed at construction — mirrors stage_tool_preconditions."""

    def _parse(self, exec_cfg, granted):
        from multi_agent.agents.runtime.action_stage_policy import (
            parse_action_stage_config)
        return parse_action_stage_config(
            agent_id="orchestrator",
            exec_cfg=exec_cfg,
            all_stages=ALL_STAGES,
            base_hints=BASE_HINTS,
            granted_categories=set(granted),
        )

    def test_absent_config_is_a_no_op(self):
        allowlist, overrides = self._parse({}, {"file"})
        self.assertIsNone(allowlist)
        self.assertEqual(overrides, {})

    def test_unknown_stage_name_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self._parse({"action_stages": ["communicate", "edit_kode"]}, set())
        self.assertIn("edit_kode", str(ctx.exception))

    def test_unknown_override_stage_name_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self._parse(
                {"action_stage_categories": {"run_cheks": ["file"]}}, set())
        self.assertIn("run_cheks", str(ctx.exception))

    def test_disabling_a_stage_that_orphans_a_granted_category_raises(self):
        """The whole point: dropping edit_code while the profile is granted
        `file`/`memory` tools would demote them out of every menu."""
        with self.assertRaises(ValueError) as ctx:
            self._parse(
                {"action_stages": ["communicate", "run_checks", "deliver"]},
                {"file", "memory", "communication"},
            )
        msg = str(ctx.exception)
        self.assertIn("file", msg)
        self.assertIn("memory", msg)

    def test_re_homing_the_categories_makes_the_same_config_valid(self):
        allowlist, overrides = self._parse(
            {
                "action_stages": ["communicate", "run_checks", "deliver"],
                "action_stage_categories": {"run_checks": ["file", "memory"]},
            },
            {"file", "memory", "communication"},
        )
        self.assertEqual(allowlist, ("communicate", "run_checks", "deliver"))
        self.assertEqual(overrides["run_checks"], {"file", "memory"})

    def test_categories_the_profile_is_not_granted_need_no_re_homing(self):
        """`reference`/`analysis` live in edit_code but the profile has no such
        tool — dropping them is free and must not raise."""
        allowlist, _ = self._parse(
            {"action_stages": ["communicate", "run_checks", "deliver"]},
            {"communication", "runtime"},
        )
        self.assertEqual(allowlist, ("communicate", "run_checks", "deliver"))


class OrchestratorProfileIsConfigured(unittest.TestCase):
    """The shipped yaml actually turns the win on — and stays safe."""

    def _profile(self) -> Dict[str, Any]:
        import yaml
        cfg_path = (
            LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml")
        cfg = yaml.safe_load(cfg_path.read_text())
        return cfg["profiles"]["orchestrator"]

    def test_orchestrator_disables_edit_code(self):
        stages = (self._profile().get("execution_pipeline") or {}).get("action_stages")
        self.assertIsNotNone(stages, "orchestrator must declare action_stages")
        self.assertNotIn("edit_code", stages)

    def test_orchestrator_keeps_coordination_stages(self):
        stages = (self._profile().get("execution_pipeline") or {}).get("action_stages")
        for required in ("communicate", "run_checks", "deliver"):
            self.assertIn(required, stages)

    def test_orchestrator_config_passes_the_orphan_validation(self):
        """Parsing the SHIPPED yaml against the SHIPPED tool_categories must
        not raise — i.e. read / update_memory_bank keep a home."""
        from multi_agent.agents.base import EnvGenAgent
        from multi_agent.agents.runtime.action_stage_policy import (
            parse_action_stage_config)
        profile = self._profile()
        parse_action_stage_config(
            agent_id="orchestrator",
            exec_cfg=profile.get("execution_pipeline") or {},
            all_stages=EnvGenAgent.ACTION_INTERNAL_STAGES,
            base_hints=EnvGenAgent.ACTION_STAGE_CATEGORY_HINTS,
            granted_categories=set(profile.get("tool_categories") or []),
        )


class ActionLoopSkipsDisabledStagesWithoutAnLLMCall(unittest.TestCase):
    """End of the chain: no LLM call is spent on a disabled stage."""

    def _run_loop(self, allowlist: Optional[Tuple[str, ...]]) -> List[str]:
        import asyncio

        from multi_agent.agents.base import EnvGenAgent
        from multi_agent.agents.runtime.step_pipeline.action import (
            AgentActionStageMixin)

        visited: List[str] = []

        class _LoopStub:
            ACTION_INTERNAL_STAGES = EnvGenAgent.ACTION_INTERNAL_STAGES
            ACTION_STAGE_CATEGORY_HINTS = EnvGenAgent.ACTION_STAGE_CATEGORY_HINTS
            _execution_mode = "solo"
            _lean_impl_action_rounds = False
            agent_id = "orchestrator"

            def __init__(self):
                if allowlist is not None:
                    self._action_stages_allowlist = allowlist

            def _stamp_step_activity(self):
                pass

            def _in_endpoint_impl_mode(self):
                return False

            async def _run_action_round_plan(self, **kw):
                return None, {}

            async def _run_action_internal_stage(self, *, action_stage_name, **kw):
                # Reaching here IS the LLM call (the stage builds its prompt
                # and calls _call_stage_llm downstream).
                visited.append(action_stage_name)
                return None, {"name": action_stage_name, "executed": True}, False, False

            async def _check_and_handle_urgent(self, from_loop=False):
                return False

        stub = _LoopStub()
        marks: List[str] = []
        asyncio.run(
            AgentActionStageMixin._run_action_stage(
                stub,
                enabled=True,
                tool_schema_map={"deliver_project": {}, "finish": {}},
                retrieved_action_names={},
                knowledge_fetch_names=set(),
                knowledge_store_names=set(),
                hub_sync_tool_names=set(),
                initial_prompt="p",
                max_action_rounds=1,
                background_mode=True,
                no_action_tool_steps=0,
                messages=[],
                files_created=[],
                files_modified=[],
                step=1,
                step_trace={},
                step_traces=[],
                loop_time=lambda: 0.0,
                mark_stage=lambda name, **kw: marks.append(name),
            )
        )
        return visited

    def test_default_visits_edit_code(self):
        self.assertIn("edit_code", self._run_loop(None))

    def test_allowlist_skips_edit_code_entirely(self):
        visited = self._run_loop(("communicate", "run_checks", "deliver"))
        self.assertNotIn("edit_code", visited)
        self.assertEqual(visited, ["communicate", "run_checks", "deliver"])


if __name__ == "__main__":
    unittest.main()
