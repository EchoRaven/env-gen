"""#1202nt: ENVGEN_ONE_CALL_PER_ROUND=1 makes an action round one LLM call instead of one per stage.

Each internal action stage (communicate, edit_code, run_checks, deliver) is its own full-context
LLM call with a ranked menu of 8-10 tools, and the stage names do not partition the work: in
tiktok-r125 the frontend's `communicate` stage mostly ran read/list_tasks/lint and its
`run_checks` mostly lint/read; edit_code carried 13% of spend; lanes averaged 16-22 LLM calls per
step, and 18% of all calls ($258) returned no tool call. The merged round collects every stage's
menu without an LLM call and offers the union in one call labelled `action`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.agents.base import EnvGenAgent  # noqa: E402
from multi_agent.agents.runtime.step_pipeline.action import AgentActionStageMixin  # noqa: E402

MENUS = {"communicate": {"check_inbox", "read"}, "edit_code": {"edit", "read"},
         "run_checks": {"lint"}, "deliver": {"finish"}}


def _drive(mode="solo", rounds=2):
    calls: List[dict] = []

    class _Loop:
        ACTION_INTERNAL_STAGES = EnvGenAgent.ACTION_INTERNAL_STAGES
        ACTION_STAGE_CATEGORY_HINTS = EnvGenAgent.ACTION_STAGE_CATEGORY_HINTS
        _execution_mode = mode
        _lean_impl_action_rounds = False
        agent_id = "frontend"

        def _stamp_step_activity(self):
            pass

        def _in_endpoint_impl_mode(self):
            return False

        async def _run_action_round_plan(self, **kw):
            return None, {"executed": True}

        async def _run_action_internal_stage(self, *, action_stage_name, selection_only_1202nt=False,
                                             preselected_1202nt=None, **kw):
            calls.append({"stage": action_stage_name, "selection_only": selection_only_1202nt,
                          "preselected": preselected_1202nt})
            if selection_only_1202nt:
                return None, {"name": action_stage_name,
                              "selected_1202nt": set(MENUS.get(action_stage_name, set()))}, False, False
            return None, {"name": action_stage_name, "executed": True}, True, False

        async def _check_and_handle_urgent(self, from_loop=False):
            return False

    asyncio.run(AgentActionStageMixin._run_action_stage(
        _Loop(), enabled=True, tool_schema_map={"deliver_project": {}, "finish": {}},
        retrieved_action_names={}, knowledge_fetch_names=set(), knowledge_store_names=set(),
        hub_sync_tool_names=set(), initial_prompt="p", max_action_rounds=rounds,
        background_mode=True, no_action_tool_steps=0, messages=[], files_created=[],
        files_modified=[], step=1, step_trace={}, step_traces=[], loop_time=lambda: 0.0,
        mark_stage=lambda name, **kw: None))
    return calls


def test_default_walk_is_one_call_per_stage(monkeypatch):
    monkeypatch.delenv("ENVGEN_ONE_CALL_PER_ROUND", raising=False)
    calls = _drive()
    assert all(not c["selection_only"] for c in calls)
    assert [c["stage"] for c in calls][:4] == ["communicate", "edit_code", "run_checks", "deliver"]


def test_merged_round_is_one_llm_call_with_the_union_of_menus(monkeypatch):
    monkeypatch.setenv("ENVGEN_ONE_CALL_PER_ROUND", "1")
    calls = _drive(rounds=2)
    real = [c for c in calls if not c["selection_only"]]
    assert [c["stage"] for c in real] == ["action", "action"]
    assert real[0]["preselected"] == {"check_inbox", "read", "edit", "lint", "finish"}
    selections = [c["stage"] for c in calls if c["selection_only"]]
    assert selections == ["communicate", "edit_code", "run_checks", "deliver"] * 2


def test_team_mode_keeps_the_per_stage_walk(monkeypatch):
    monkeypatch.setenv("ENVGEN_ONE_CALL_PER_ROUND", "1")
    calls = _drive(mode="team", rounds=1)
    assert all(not c["selection_only"] for c in calls)
    assert "action" not in [c["stage"] for c in calls]


class _Real(AgentActionStageMixin):
    """The real `_run_action_internal_stage`, with only its collaborators stubbed."""
    ACTION_INTERNAL_STAGES = EnvGenAgent.ACTION_INTERNAL_STAGES
    ACTION_STAGE_ALWAYS_INCLUDE = {}
    TEAM_TOOL_NAMES = ()
    TEAM_MODE_SUPPORT_TOOLS = ()
    _execution_mode = "solo"
    agent_id = "frontend"

    def __init__(self):
        self.llm_calls = []

    def _stage_tool_names(self, schema, stage, candidates, prompt, limit=10):
        return set(MENUS.get(stage, set())) & set(candidates)

    def _filtered_tool_schemas(self, schema, names):
        return [{"name": n} for n in sorted(names)]

    async def _call_stage_llm(self, messages, stage, prompt, tools):
        self.llm_calls.append((stage, sorted(t["name"] for t in tools)))
        return None

    def _stamp_step_activity(self):
        pass


def _kw(**extra):
    base = dict(action_round=0, max_action_rounds=15,
                all_names={"check_inbox", "read", "edit", "lint", "finish"},
                tool_schema_map={}, retrieved_action_names={}, knowledge_fetch_names=set(),
                knowledge_store_names=set(), hub_sync_tool_names=set(), initial_prompt="p",
                messages=[], files_created=[], files_modified=[], step=1, step_trace={},
                step_traces=[], action_round_results=[], round_internal_stage_results=[],
                loop_time=lambda: 0.0, mark_stage=lambda *a, **k: None)
    base.update(extra)
    return base


def test_selection_only_makes_no_llm_call():
    lane = _Real()
    out = asyncio.run(lane._run_action_internal_stage(
        action_stage_name="edit_code", selection_only_1202nt=True, **_kw()))
    assert out[1]["selected_1202nt"] == {"edit", "read"}
    assert lane.llm_calls == []


def test_the_merged_call_offers_exactly_the_preselected_union():
    lane = _Real()
    asyncio.run(lane._run_action_internal_stage(
        action_stage_name="action", preselected_1202nt={"edit", "lint", "finish"}, **_kw()))
    assert lane.llm_calls == [("action", ["edit", "finish", "lint"])]
