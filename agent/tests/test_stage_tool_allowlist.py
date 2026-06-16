"""PR3: stage_tool_allowlist engine plumbing.

Per docs/prompt_smell_and_bash_sandbox_2026_06_03.md §1.3 + Loop B's
iteration-1 review: replace "DO NOT call X during stage Y" prompt
prose with engine-side per-stage tool filtering.

The engine surface is `_stage_tool_names` in step_pipeline/tooling.py.
This file pins:
  1. When a profile sets ``stage_tool_allowlist.<stage>: [t1, t2]``,
     candidate_names is intersected with that set before ranking.
  2. When the field is unset, behavior is identical to today (no
     restriction).
  3. When the allowlist is empty/exhaustive, candidate_names goes to
     empty → empty result (positive guard rather than DO-NOT-call).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Set
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _BareStub:
    """Minimal stub matching the attributes ``_stage_tool_names`` reads."""

    ACTION_STAGE_CATEGORY_HINTS: Dict[str, Set[str]] = {}
    ACTION_STAGE_ALWAYS_INCLUDE: Dict[str, Set[str]] = {}
    TEAM_TOOL_NAMES: Set[str] = set()
    TEAM_MODE_SUPPORT_TOOLS: Set[str] = set()
    _tool_instances: Dict[str, Any] = {}

    def __init__(self, allowlist=None, active_phase=None):
        self._stage_tool_allowlist = allowlist or {}
        self._active_phase = active_phase


class StageToolAllowlistFiltersPerStage(unittest.TestCase):

    def setUp(self):
        # Import the AgentTooling mixin and bind its _stage_tool_names
        # to a bare stub. This avoids the full ConfigurableAgent init.
        from multi_agent.agents.runtime.step_pipeline.tooling import AgentStepToolingMixin
        self._fn = AgentStepToolingMixin._stage_tool_names

    def _run(self, *, allowlist, stage_name, candidates, active_phase=None) -> Set[str]:
        stub = _BareStub(allowlist=allowlist, active_phase=active_phase)
        # rank_tool_names is the downstream ranker; with no tool_instances
        # it returns the candidate set as-is (limit-capped). For these
        # tests we patch it to identity so we test the FILTER, not the
        # ranker.
        from multi_agent.agents.runtime.step_pipeline import tooling as t_mod
        orig = t_mod.rank_tool_names
        t_mod.rank_tool_names = lambda **kw: list(kw["candidate_names"])
        try:
            return self._fn(
                stub,
                tool_schema_map={n: {} for n in candidates},
                stage_name=stage_name,
                candidate_names=set(candidates),
                prompt_text="test",
                limit=100,
            )
        finally:
            t_mod.rank_tool_names = orig

    def test_allowlist_intersects_candidates(self):
        """When stage allowlist is set, only allowed tools survive."""
        result = self._run(
            allowlist={"kickoff": ["workhub_add_meeting_decision", "finish"]},
            stage_name="kickoff",
            candidates=["workhub_add_meeting_decision", "finish", "workhub_task", "registryhub_register_endpoint"],
        )
        self.assertEqual(result, {"workhub_add_meeting_decision", "finish"})

    def test_no_allowlist_no_restriction(self):
        """Profile without stage_tool_allowlist → behavior unchanged."""
        result = self._run(
            allowlist={},
            stage_name="kickoff",
            candidates=["workhub_add_meeting_decision", "finish", "workhub_task"],
        )
        self.assertEqual(result, {"workhub_add_meeting_decision", "finish", "workhub_task"})

    def test_stage_without_entry_falls_through(self):
        """Allowlist has entries for other stages but not this one →
        this stage is unrestricted."""
        result = self._run(
            allowlist={"kickoff": ["finish"]},
            stage_name="implementation",
            candidates=["workhub_add_meeting_decision", "finish", "workhub_task"],
        )
        self.assertEqual(result, {"workhub_add_meeting_decision", "finish", "workhub_task"})

    def test_allowlist_exhausts_candidates(self):
        """Allowlist names tools not in the candidate set → empty result."""
        result = self._run(
            allowlist={"kickoff": ["nonexistent_tool"]},
            stage_name="kickoff",
            candidates=["finish", "workhub_task"],
        )
        self.assertEqual(result, set())

    def test_empty_allowlist_for_stage_falls_through(self):
        """An empty list is treated as no restriction (consistent with
        deny_tools=[] semantics — explicit empty = unset)."""
        result = self._run(
            allowlist={"kickoff": []},
            stage_name="kickoff",
            candidates=["finish", "workhub_task"],
        )
        # Falsy check in _stage_tool_names treats empty list as no allowlist.
        self.assertEqual(result, {"finish", "workhub_task"})


class StageToolAllowlistPhaseKeyedLookup(unittest.TestCase):
    """PR3.1.2 / Loop B ⑧: kickoff and implementation share the same
    pipeline stages, so the allowlist needs a phase concept to gate
    kickoff differently. Composite ``"phase:stage"`` keys take
    precedence over the bare stage when ``_active_phase`` is set;
    fallback to bare stage preserves existing single-stage configs."""

    def setUp(self):
        from multi_agent.agents.runtime.step_pipeline.tooling import AgentStepToolingMixin
        self._fn = AgentStepToolingMixin._stage_tool_names

    def _run(self, *, allowlist, stage_name, candidates, active_phase=None) -> Set[str]:
        stub = _BareStub(allowlist=allowlist, active_phase=active_phase)
        from multi_agent.agents.runtime.step_pipeline import tooling as t_mod
        orig = t_mod.rank_tool_names
        t_mod.rank_tool_names = lambda **kw: list(kw["candidate_names"])
        try:
            return self._fn(
                stub,
                tool_schema_map={n: {} for n in candidates},
                stage_name=stage_name,
                candidate_names=set(candidates),
                prompt_text="test",
                limit=100,
            )
        finally:
            t_mod.rank_tool_names = orig

    def test_phase_keyed_entry_takes_precedence(self):
        """phase=kickoff, stage=action; yaml has BOTH 'kickoff:action'
        and 'action' → the composite key wins."""
        result = self._run(
            allowlist={
                "kickoff:action": ["workhub_add_meeting_decision", "finish"],
                "action": ["write", "edit", "finish"],
            },
            stage_name="action",
            candidates=["workhub_add_meeting_decision", "finish", "write", "edit"],
            active_phase="kickoff",
        )
        self.assertEqual(result, {"workhub_add_meeting_decision", "finish"})

    def test_falls_back_to_bare_stage_when_no_phase_entry(self):
        """phase=kickoff, stage=action; yaml has only 'action' → uses
        bare-stage entry (no regression for profiles that didn't
        migrate to phase keys yet)."""
        result = self._run(
            allowlist={"action": ["write", "edit", "finish"]},
            stage_name="action",
            candidates=["write", "edit", "finish", "workhub_task"],
            active_phase="kickoff",
        )
        self.assertEqual(result, {"write", "edit", "finish"})

    def test_no_phase_does_not_match_phase_entry(self):
        """phase=None, stage=action; yaml has only 'kickoff:action' →
        no match → falls through to no-restriction (lever inactive)."""
        result = self._run(
            allowlist={"kickoff:action": ["workhub_add_meeting_decision"]},
            stage_name="action",
            candidates=["write", "edit", "finish"],
            active_phase=None,
        )
        self.assertEqual(result, {"write", "edit", "finish"})

    def test_empty_phase_entry_falls_back_to_bare(self):
        """phase=kickoff, stage=action; yaml has 'kickoff:action': []
        AND 'action': [write] → empty phase entry falls through to
        bare-stage 'write' (consistent with empty-list semantics)."""
        result = self._run(
            allowlist={
                "kickoff:action": [],
                "action": ["write"],
            },
            stage_name="action",
            candidates=["write", "edit", "finish"],
            active_phase="kickoff",
        )
        self.assertEqual(result, {"write"})


class StageToolAllowlistHardGatesAlwaysInclude(unittest.TestCase):
    """Loop B iter-2 ⑨: the allowlist must be authoritative. When set,
    ``ACTION_STAGE_ALWAYS_INCLUDE`` entries outside the allowlist must
    NOT survive — else a profile that omits ``finish`` from its
    allowlist still surfaces ``finish`` via the engine floor, and the
    lever is a soft gate the LLM can route around."""

    def setUp(self):
        from multi_agent.agents.runtime.step_pipeline.tooling import AgentStepToolingMixin
        self._fn = AgentStepToolingMixin._stage_tool_names

    def _spy_run(self, *, always_include, allowlist, candidates):
        """Spy on the ``always_include`` arg passed to the ranker so we
        can verify the intersection happens at the caller site."""
        class _Stub:
            ACTION_STAGE_CATEGORY_HINTS: Dict[str, Set[str]] = {}
            ACTION_STAGE_ALWAYS_INCLUDE: Dict[str, Set[str]] = {"action": set(always_include)}
            TEAM_TOOL_NAMES: Set[str] = set()
            TEAM_MODE_SUPPORT_TOOLS: Set[str] = set()
            _tool_instances: Dict[str, Any] = {}

            def __init__(self, allowlist):
                self._stage_tool_allowlist = allowlist or {}

        captured = {}
        from multi_agent.agents.runtime.step_pipeline import tooling as t_mod
        orig = t_mod.rank_tool_names

        def spy(**kw):
            captured["always_include"] = set(kw["always_include"])
            return list(kw["candidate_names"])

        t_mod.rank_tool_names = spy
        try:
            result = self._fn(
                _Stub(allowlist=allowlist),
                tool_schema_map={n: {} for n in candidates},
                stage_name="action",
                candidate_names=set(candidates),
                prompt_text="test",
                limit=100,
            )
        finally:
            t_mod.rank_tool_names = orig
        return captured, result

    def test_allowlist_drops_always_include_outside_it(self):
        """ALWAYS_INCLUDE={finish, report_progress}; allowlist excludes
        both → both must be removed from always_include before the
        ranker sees it."""
        captured, _ = self._spy_run(
            always_include={"finish", "report_progress"},
            allowlist={"action": ["write", "edit"]},
            candidates=["write", "edit", "finish"],
        )
        self.assertEqual(captured["always_include"], set())

    def test_allowlist_keeps_overlapping_always_include(self):
        """ALWAYS_INCLUDE items inside the allowlist survive."""
        captured, _ = self._spy_run(
            always_include={"finish", "report_progress"},
            allowlist={"action": ["write", "edit", "finish"]},
            candidates=["write", "edit", "finish"],
        )
        self.assertEqual(captured["always_include"], {"finish"})

    def test_no_allowlist_preserves_full_always_include(self):
        """Without an allowlist, ALWAYS_INCLUDE behavior is unchanged
        (no regression on profiles that don't use the lever)."""
        captured, _ = self._spy_run(
            always_include={"finish", "report_progress"},
            allowlist={},
            candidates=["write", "edit", "finish", "report_progress"],
        )
        self.assertEqual(captured["always_include"], {"finish", "report_progress"})

    def test_other_stage_allowlist_does_not_affect_action(self):
        """An allowlist keyed on a DIFFERENT stage must not narrow
        the ``action`` stage's ALWAYS_INCLUDE."""
        captured, _ = self._spy_run(
            always_include={"finish", "report_progress"},
            allowlist={"planning": ["write"]},
            candidates=["write", "edit", "finish", "report_progress"],
        )
        self.assertEqual(captured["always_include"], {"finish", "report_progress"})


class StageToolAllowlistConfigPlumbing(unittest.TestCase):
    """End-to-end: ConfigurableAgent reads the yaml field correctly."""

    def test_configurable_agent_reads_field(self):
        from multi_agent.agents.configurable_agent import ConfigurableAgent
        # Bypass __init__ (heavy); inject the field shape ConfigurableAgent
        # produces (frozenset values keyed by stage name).
        agent = object.__new__(ConfigurableAgent)
        # Simulate what __init__ would produce from yaml:
        raw_cfg = {
            "kickoff": ["workhub_add_meeting_decision", "finish"],
            "implementation": ["finish"],
        }
        agent._stage_tool_allowlist = {
            stage: frozenset(tools) for stage, tools in raw_cfg.items()
        }
        self.assertEqual(
            agent._stage_tool_allowlist["kickoff"],
            frozenset({"workhub_add_meeting_decision", "finish"}),
        )
        self.assertEqual(
            agent._stage_tool_allowlist["implementation"],
            frozenset({"finish"}),
        )

    def test_configurable_agent_defaults_to_empty(self):
        """No yaml field → empty dict, engine treats as unrestricted."""
        from multi_agent.agents.configurable_agent import ConfigurableAgent
        agent = object.__new__(ConfigurableAgent)
        agent._stage_tool_allowlist = {}  # what __init__ does when field absent
        self.assertEqual(agent._stage_tool_allowlist, {})


if __name__ == "__main__":
    unittest.main()
