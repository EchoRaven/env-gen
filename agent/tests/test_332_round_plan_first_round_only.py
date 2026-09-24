"""#332: the per-round planning call runs on round 0 only.

Measured (r91/r92/r93): ~30% of ALL LLM calls pass `tools=[]` and are therefore
structurally incapable of producing a tool call. r91 = 7,041 such calls, 32% of
all 21,691 requests, carrying 1.935G of 6.203G request chars.

`_run_action_round_plan` is the biggest of the three `tools=[]` sites: it fires
once per ACTION ROUND, and `max_action_rounds_per_step` is 15. Its response is
appended to `messages` (action.py: `messages.append(Message.assistant(...))`),
so from round 1 onward the plan the model just stated is already in its own
context -- the call re-derives what it can already read.

Round 0 keeps its plan (a step should think before it acts). Later rounds
inherit it. `execution_pipeline.action_round_plan: all` restores the old
behavior per profile.

This does NOT touch the action stages themselves -- no tool loses its home, and
no capability is removed, because a `tools=[]` call could never exercise one.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _run_rounds(max_rounds: int, exec_cfg=None) -> List[int]:
    """Drive the real action-stage loop; return the round indices on which the
    round-plan call actually fired."""
    from multi_agent.agents.base import EnvGenAgent
    from multi_agent.agents.runtime.step_pipeline.action import (
        AgentActionStageMixin)

    planned: List[int] = []

    class _LoopStub:
        ACTION_INTERNAL_STAGES = EnvGenAgent.ACTION_INTERNAL_STAGES
        ACTION_STAGE_CATEGORY_HINTS = EnvGenAgent.ACTION_STAGE_CATEGORY_HINTS
        _execution_mode = "solo"
        _lean_impl_action_rounds = False
        agent_id = "backend"

        def __init__(self):
            if exec_cfg is not None:
                self._execution_pipeline_cfg = exec_cfg

        def _stamp_step_activity(self):
            pass

        def _in_endpoint_impl_mode(self):
            return False

        async def _run_action_round_plan(self, *, action_round, **kw):
            planned.append(action_round)
            return None, {"executed": True}

        async def _run_action_internal_stage(self, *, action_stage_name, **kw):
            # Report tool use so the round loop keeps going to max_rounds
            # (a round that used no tools breaks out early).
            return None, {"name": action_stage_name, "executed": True}, True, False

        async def _check_and_handle_urgent(self, from_loop=False):
            return False

    stub = _LoopStub()
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
            max_action_rounds=max_rounds,
            background_mode=True,
            no_action_tool_steps=0,
            messages=[],
            files_created=[],
            files_modified=[],
            step=1,
            step_trace={},
            step_traces=[],
            loop_time=lambda: 0.0,
            mark_stage=lambda name, **kw: None,
        )
    )
    return planned


class RoundPlanFiresOnceByDefault(unittest.TestCase):

    def test_five_rounds_produce_one_plan_call(self):
        self.assertEqual(_run_rounds(5), [0])

    def test_fifteen_rounds_still_produce_one_plan_call(self):
        """max_action_rounds_per_step is 15 — the worst case is 14 saved calls."""
        self.assertEqual(_run_rounds(15), [0])

    def test_single_round_step_is_unchanged(self):
        self.assertEqual(_run_rounds(1), [0])


class ProfileCanRestoreThePerRoundPlan(unittest.TestCase):

    def test_action_round_plan_all_plans_every_round(self):
        self.assertEqual(
            _run_rounds(4, exec_cfg={"action_round_plan": "all"}), [0, 1, 2, 3])

    def test_explicit_first_matches_the_default(self):
        self.assertEqual(
            _run_rounds(4, exec_cfg={"action_round_plan": "first"}), [0])

    def test_unknown_value_falls_back_to_the_default(self):
        """A typo must not silently restore the expensive behavior."""
        self.assertEqual(
            _run_rounds(4, exec_cfg={"action_round_plan": "evry"}), [0])


class Resolver(unittest.TestCase):

    def _resolve(self, agent):
        from multi_agent.agents.runtime.action_stage_policy import (
            round_plan_fires_every_round)
        return round_plan_fires_every_round(agent)

    def test_absent_config_is_first_round_only(self):
        class _Bare:
            pass

        self.assertFalse(self._resolve(_Bare()))

    def test_all_enables_every_round(self):
        class _A:
            _execution_pipeline_cfg = {"action_round_plan": "all"}

        self.assertTrue(self._resolve(_A()))


if __name__ == "__main__":
    unittest.main()
