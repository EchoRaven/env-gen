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


# ---------------------------------------------------------------------------
# #1202y6 (2026-09-29): what has to hold before this flag is turned on.
#
# #1202nt has never run. `ENVGEN_ONE_CALL_PER_ROUND` is opt-in "until measured" and a grep
# of `1202nt` across every recent run log returns zero — so it is a mechanism that was
# built and never exercised, and the tests above pin its mechanics but not the two claims
# its own comment makes about SAFETY.
#
# The measurement it was waiting for now exists. In r140 the orchestrator's tool blob
# changed on 74.8% of its calls against 8.8% for every other agent, and its two
# conversations were 22% of the calls but 46% of the run's uncached tokens -- $20.30 of a
# $172 run, 12%. The cause is that its four action-inner sub-stages are separate calls with
# different force-offer sets, so the blob rotates and the cached prefix dies with it.
# Merging the round is exactly the fix, and for the orchestrator specifically it is a
# COMPLETE one: its profile's action_stages are
# ['communicate', 'run_checks', 'delegate_team', 'deliver'], `delegate_team` is skipped
# outside team mode, `deliver` is kept because it holds deliver_project and finish, and
# `lean_impl` cannot fire for it (`_in_endpoint_impl_mode` filters endpoints by
# provider == owning lane, and endpoints are provided by `backend`). So its
# `_stages_this_round` is the same three stages every round, the union is the same union
# every round, and the blob stops moving.
# ---------------------------------------------------------------------------


def test_no_precondition_is_keyed_on_an_action_inner_substage():
    """★ THE LOAD-BEARING SAFETY CLAIM, checked against config other people edit.

    The merged call is labelled `action` — "the key stage_tool_preconditions already fall
    back to", says the comment. That is true only while no precondition is keyed on a
    sub-stage: `_enforce_stage_preconditions` looks up `<phase>:<stage>` then `<stage>`, so
    a gate written as `implementation:edit_code` would simply stop being enforced once the
    round merges, silently, with no error anywhere.

    Today every profile keys its preconditions on `action` alone. This pins that, so the
    day someone adds a sub-stage-keyed gate they are told it is incompatible with the merge
    rather than losing it.
    """
    import yaml

    cfg = yaml.safe_load(
        (LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml").read_text(
            encoding="utf-8"))
    inner = set(EnvGenAgent.ACTION_INTERNAL_STAGES) - {"action"}
    offenders = []
    for name, prof in sorted((cfg.get("profiles") or {}).items()):
        for key in ((prof or {}).get("stage_tool_preconditions") or {}):
            if str(key).split(":")[-1] in inner:
                offenders.append("%s:%s" % (name, key))
    assert not offenders, (
        "these preconditions are keyed on an action-inner sub-stage, so they stop being "
        "enforced under ENVGEN_ONE_CALL_PER_ROUND=1 (the merged call is labelled `action`): "
        + ", ".join(offenders))


def test_the_scan_would_notice_a_substage_key():
    """★ Non-vacuity: the assertion above passes on an empty config too."""
    inner = set(EnvGenAgent.ACTION_INTERNAL_STAGES) - {"action"}
    assert inner, "ACTION_INTERNAL_STAGES lost its sub-stages — the scan above is now blind"
    assert "edit_code" in inner and "communicate" in inner, sorted(inner)


def test_the_selection_pass_has_no_side_effects():
    """★ The union is collected by calling each stage with selection_only_1202nt=True. If
    anything before that early return marked a stage, appended a trace or touched the file
    lists, the merged round would record work that never happened — N times per round.
    """
    import ast
    import inspect
    from multi_agent.agents.runtime.step_pipeline import action as A

    src = inspect.getsource(A.AgentActionStageMixin._run_action_internal_stage)
    tree = ast.parse(src.lstrip())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))

    guard = next((n for n in ast.walk(fn) if isinstance(n, ast.If)
                  and getattr(n.test, "id", "") == "selection_only_1202nt"), None)
    assert guard is not None, "the selection-only early return is gone"
    assert any(isinstance(b, ast.Return) for b in guard.body), ast.dump(guard)

    before = [n for n in ast.walk(fn)
              if isinstance(n, (ast.Call, ast.Await)) and getattr(n, "lineno", 0) < guard.lineno]
    for node in before:
        if isinstance(node, ast.Await):
            raise AssertionError("an await runs before the selection-only return (line %d)"
                                 % node.lineno)
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        assert name not in ("mark_stage", "append", "_stamp_step_activity"), (
            "%s() runs before the selection-only return (line %d)" % (name, node.lineno))


def test_a_single_stage_round_does_not_merge():
    """The `> 1` guard: with nothing to union, the plain walk is what runs. Pinned because
    a round that merges a single stage would relabel it `action` for no benefit — and the
    relabel is what moves the tool blob."""
    import inspect
    from multi_agent.agents.runtime.step_pipeline import action as A
    src = inspect.getsource(A.AgentActionStageMixin._run_action_stage)
    assert "len(_stages_this_round) > 1" in src


def test_the_orchestrator_profile_keeps_a_constant_round_shape():
    """★ Why the merge is a COMPLETE fix for the agent that needs it.

    The blob is stable only while the set of stages in a round is stable. The orchestrator's
    profile lists four action stages; `delegate_team` drops outside team mode and the other
    three always run, so its union is the same union every round. A profile change that put
    a conditionally-skipped stage into that list would reintroduce the churn this is meant
    to remove, and would do it silently.
    """
    import yaml
    cfg = yaml.safe_load(
        (LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml").read_text(
            encoding="utf-8"))
    stages = (((cfg.get("profiles") or {}).get("orchestrator") or {})
              .get("execution_pipeline") or {}).get("action_stages")
    assert stages, "the orchestrator no longer pins its action stages"
    # `edit_code` is the one whose presence would make `lean_impl` able to vary the shape.
    assert "edit_code" not in stages, stages
    assert set(stages) - {"delegate_team"} == {"communicate", "run_checks", "deliver"}, stages
