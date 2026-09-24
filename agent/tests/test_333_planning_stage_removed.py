"""#333: delete the per-step `planning` stage.

It cost one full-context LLM call per step, on every lane, and it could not
act (`tools=[]` — part of the ~30% of all r91/r92/r93 calls that carried an
empty tool list).

Its ONLY functional effect was a substring check on its own reply:

    stages.py: "Include one line in your reasoning text: MODE: team|direct|stay."
               if "mode: team" in plan_text:   self._enter_team_mode(...)
               elif "mode: direct" in plan_text: self._exit_team_mode(...)

`MODE:` has no other consumer anywhere in the codebase, and the switch NEVER
fired: `grep -ci "mode: team"` over r91/r92/r93 = 0, 0, 0, and `delegate_team`
tool calls = 0 across all non-orchestrator lanes in all three runs.

Deleting it removes no capability, because team mode has independent
TOOL-driven triggers in both directions — `tooling.py` calls
`_enter_team_mode(reason=f"tool={tool_name}")` and
`_exit_team_mode(reason=f"tool={tool_name}")`. Actually calling a team tool is
a truer signal than the model reciting a MODE line.

Planning itself is not lost either: there is a real `plan` tool
(`reasoning_tools.py`) the model can call when it wants one, and after #332
each step still opens its action loop with a round-0 plan — so the deleted
stage was the SECOND consecutive `tools=[]` planning call in every step.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MA = LLM_DIR / "multi_agent"


class TheStageIsGone(unittest.TestCase):

    def test_run_planning_stage_no_longer_exists(self):
        from multi_agent.agents.runtime.step_pipeline import stages as stages_mod
        for cls_name in dir(stages_mod):
            cls = getattr(stages_mod, cls_name)
            if isinstance(cls, type):
                self.assertFalse(
                    hasattr(cls, "_run_planning_stage"),
                    f"{cls_name} still defines _run_planning_stage",
                )

    def test_step_runner_no_longer_dispatches_it(self):
        src = (MA / "agents/runtime/step_runner.py").read_text()
        self.assertNotIn("_run_planning_stage", src)

    def test_no_mode_line_prompt_survives(self):
        """The MODE: team|direct|stay instruction had exactly one author."""
        src = (MA / "agents/runtime/step_pipeline/stages.py").read_text()
        self.assertNotIn("MODE: team", src)


class NoProfileStillSchedulesIt(unittest.TestCase):

    def _cfg(self):
        import yaml
        return yaml.safe_load((MA / "agents/agents_config.yaml").read_text())

    def test_default_stage_list_has_no_planning(self):
        cfg = self._cfg()
        stages = (cfg.get("execution_pipeline_defaults") or {}).get("stages") or []
        self.assertNotIn("planning", stages)

    def test_no_profile_stage_list_has_planning(self):
        cfg = self._cfg()
        offenders = []
        for name, profile in (cfg.get("profiles") or {}).items():
            stages = ((profile.get("execution_pipeline") or {}).get("stages")) or []
            if "planning" in stages:
                offenders.append(name)
        self.assertEqual(offenders, [])

    def test_no_leftover_planning_tool_call_budget(self):
        """A stale `max_tool_calls_per_stage.planning` would be dead config."""
        cfg = self._cfg()
        offenders = []
        scopes = [("defaults", cfg.get("execution_pipeline_defaults") or {})]
        scopes += [(n, (p.get("execution_pipeline") or {}))
                   for n, p in (cfg.get("profiles") or {}).items()]
        for name, scope in scopes:
            if "planning" in (scope.get("max_tool_calls_per_stage") or {}):
                offenders.append(name)
        self.assertEqual(offenders, [])


class TeamModeCapabilitySurvives(unittest.TestCase):
    """The one thing the deleted stage did must still be reachable."""

    def test_both_team_mode_transitions_keep_a_tool_driven_trigger(self):
        src = (MA / "agents/runtime/tooling.py").read_text()
        self.assertIn("_enter_team_mode", src)
        self.assertIn("_exit_team_mode", src)

    def test_the_transition_methods_still_exist(self):
        from multi_agent.agents.base import EnvGenAgent
        self.assertTrue(hasattr(EnvGenAgent, "_enter_team_mode"))
        self.assertTrue(hasattr(EnvGenAgent, "_exit_team_mode"))


if __name__ == "__main__":
    unittest.main()
