"""L2 — skill-consult preconditions (reuse PR3.2's precondition lever).

Per docs/superpowers/plans/2026-06-03-skill-mandatory-trigger.md, adapted:
instead of a separate SkillConsultGate policy (the bespoke-policy
anti-pattern), gate the tool via the existing stage_tool_preconditions
registry. A checker blocks the tool until the required skill is in
agent._consulted_skills (populated by L3a record_skill_consult).
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _agent(consulted=None):
    # A normal agent that CAN consult (get_skill in its tool surface) — so the
    # block-when-not-consulted nudge applies. The unsatisfiable-when-no-get_skill
    # path is covered by test_skill_consult_satisfiability.py.
    return SimpleNamespace(agent_id="x", _consulted_skills=set(consulted or []),
                           _tool_instances={"get_skill": object()})


class SkillConsultPreconditions(unittest.TestCase):
    def test_release_readiness_blocks_when_not_consulted(self):
        from multi_agent.agents.runtime.preconditions import release_readiness_consulted
        err = release_readiness_consulted(_agent(), "deliver_project", {})
        self.assertIsNotNone(err)
        self.assertIn("release-readiness", err)
        self.assertIn("get_skill", err)

    def test_release_readiness_passes_when_consulted(self):
        from multi_agent.agents.runtime.preconditions import release_readiness_consulted
        self.assertIsNone(release_readiness_consulted(_agent(["release-readiness"]), "deliver_project", {}))

    def test_api_contract_guard_blocks_then_passes(self):
        from multi_agent.agents.runtime.preconditions import api_contract_guard_consulted
        self.assertIsNotNone(api_contract_guard_consulted(_agent(), "codehub_open_pr", {}))
        self.assertIsNone(api_contract_guard_consulted(_agent(["api-contract-guard"]), "codehub_open_pr", {}))

    def test_registered_in_registry(self):
        from multi_agent.agents.runtime.preconditions import PRECONDITION_REGISTRY
        self.assertIn("release_readiness_consulted", PRECONDITION_REGISTRY)
        self.assertIn("api_contract_guard_consulted", PRECONDITION_REGISTRY)

    def test_no_consulted_attr_blocks_gracefully(self):
        from multi_agent.agents.runtime.preconditions import release_readiness_consulted
        # missing _consulted_skills attr → treated as not-consulted, blocks (no raise).
        # get_skill is available, so the gate is satisfiable and the nudge applies.
        agent = SimpleNamespace(agent_id="x", _tool_instances={"get_skill": object()})
        err = release_readiness_consulted(agent, "deliver_project", {})
        self.assertIsNotNone(err)


if __name__ == "__main__":
    unittest.main()
