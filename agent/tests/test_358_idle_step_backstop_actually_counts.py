"""#358: the no-action backstop never fires for the pattern it exists to catch.

`_run_action_stage` ends with

    if not any_action_calls:
        no_action_tool_steps += 1
        if not background_mode and no_action_tool_steps >= 12:
            ... resident_idle / stuck-loop abort

It is inert twice over:

  1. `not background_mode` -- background lanes can never reach the threshold.
  2. A step that ends in `finish()` returns `done` at the `if done:` site ABOVE
     this block, so the counter is neither incremented nor reset. It freezes.

The second is the dominant idle shape. r91's orchestrator made 550 `finish()`
calls, 74% of them no-ops ('No change.' x102, 'Idle.' x97, 'Idle wake --
kickoff still in flight.' x37), and not one of them advanced the counter. Each
of those steps still paid for its full-context LLM calls.

Fix: a step that produced NO productive tool call still counts as idle even when
it ended in finish(), and the threshold applies to background lanes too.

Deliberately NOT changed: the threshold value (12) and the resident-lane
behaviour. Resident lanes are SUPPOSED to poll, and they exit through the
graceful `resident_idle` result rather than the stuck-loop error -- that
distinction is preserved. Lowering 12 is a separate, evidence-driven call; this
commit only makes the existing backstop reachable.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _run_step(*, finishes, used_tools, background, resident=False, carried=0):
    """Drive one real _run_action_stage; return (result, counter_out)."""
    from multi_agent.agents.base import EnvGenAgent
    from multi_agent.agents.runtime.step_pipeline.action import AgentActionStageMixin

    class _Stub:
        ACTION_INTERNAL_STAGES = EnvGenAgent.ACTION_INTERNAL_STAGES
        ACTION_STAGE_CATEGORY_HINTS = EnvGenAgent.ACTION_STAGE_CATEGORY_HINTS
        _execution_mode = "solo"
        _lean_impl_action_rounds = False
        _is_resident_lane = resident
        agent_id = "orchestrator"

        def _stamp_step_activity(self):
            pass

        def _in_endpoint_impl_mode(self):
            return False

        async def _run_action_round_plan(self, **kw):
            return None, {}

        async def _run_action_internal_stage(self, *, action_stage_name, **kw):
            if finishes and action_stage_name == "communicate":
                # what finish() looks like: the step is DONE, nothing produced
                return ({"success": True, "summary": "Idle.", "step_traces": []},
                        {"name": action_stage_name}, used_tools, True)
            return None, {"name": action_stage_name}, used_tools, False

        async def _check_and_handle_urgent(self, from_loop=False):
            return False

    return asyncio.run(AgentActionStageMixin._run_action_stage(
        _Stub(), enabled=True, tool_schema_map={"finish": {}},
        retrieved_action_names={}, knowledge_fetch_names=set(),
        knowledge_store_names=set(), hub_sync_tool_names=set(),
        initial_prompt="p", max_action_rounds=1, background_mode=background,
        no_action_tool_steps=carried, messages=[], files_created=[],
        files_modified=[], step=1, step_trace={}, step_traces=[],
        loop_time=lambda: 0.0, mark_stage=lambda name, **kw: None))


class AnIdleFinishCounts(unittest.TestCase):
    """r91's 550 finish() calls froze the counter instead of advancing it."""

    def test_finishing_with_no_tool_use_increments(self):
        _res, n = _run_step(finishes=True, used_tools=False, background=True)
        self.assertEqual(n, 1)

    def test_it_accumulates_across_steps(self):
        _res, n = _run_step(finishes=True, used_tools=False, background=True, carried=5)
        self.assertEqual(n, 6)

    def test_a_productive_step_that_finishes_does_not_count(self):
        _res, n = _run_step(finishes=True, used_tools=True, background=True, carried=3)
        self.assertEqual(n, 3)


class BackgroundLanesReachTheThreshold(unittest.TestCase):

    def test_background_lane_trips_the_stuck_abort(self):
        res, _n = _run_step(finishes=False, used_tools=False, background=True, carried=11)
        self.assertIsNotNone(res)
        self.assertFalse(res["success"])
        self.assertIn("stuck", res["error"].lower())

    def test_below_the_threshold_it_keeps_going(self):
        res, n = _run_step(finishes=False, used_tools=False, background=True, carried=3)
        self.assertIsNone(res)
        self.assertEqual(n, 4)


class ResidentLanesStillIdleGracefully(unittest.TestCase):
    """Polling is their job -- they must not get the stuck-loop error."""

    def test_resident_lane_returns_resident_idle_not_an_error(self):
        res, _n = _run_step(finishes=False, used_tools=False,
                            background=True, resident=True, carried=11)
        self.assertTrue(res["success"])
        self.assertTrue(res.get("resident_idle"))


class ProductiveStepsStillResetTheCounter(unittest.TestCase):

    def test_tool_use_resets(self):
        _res, n = _run_step(finishes=False, used_tools=True, background=True, carried=9)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
