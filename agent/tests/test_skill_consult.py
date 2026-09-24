"""L3a — record_skill_consult: skill-trigger consult substrate.

Per docs/superpowers/plans/2026-06-03-skill-mandatory-trigger.md Task 1.
The agent records a get_skill consult onto agent._consulted_skills (read
by SkillConsultGate) and emits a skill_consulted event. Best-effort;
never raises into the tool path.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _FakeResult:
    def __init__(self, success, data):
        self.success = success
        self.data = data


class _FakeEventHub:
    def __init__(self):
        self.events = []

    def publish_event(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class _FakeHubs:
    def __init__(self, eventhub):
        self.eventhub = eventhub


class _FakeLogger:
    def debug(self, *a, **k):
        pass


class _FakeAgent:
    def __init__(self):
        self.agent_id = "backend"
        self._consulted_skills = set()
        self._hubs = _FakeHubs(_FakeEventHub())
        self._logger = _FakeLogger()


class RecordSkillConsult(unittest.TestCase):
    def test_records_found_skill_and_emits_event(self):
        from multi_agent.agents.runtime.skill_consult import record_skill_consult
        agent = _FakeAgent()
        result = _FakeResult(True, {"found": True, "skill": {"name": "api-contract-guard"}})
        record_skill_consult(agent, "get_skill", {"name": "api-contract-guard"}, result)
        self.assertIn("api-contract-guard", agent._consulted_skills)
        self.assertEqual(len(agent._hubs.eventhub.events), 1)
        self.assertEqual(agent._hubs.eventhub.events[0]["event_type"], "skill_consulted")
        self.assertEqual(agent._hubs.eventhub.events[0]["payload"]["skill"], "api-contract-guard")

    def test_ignores_not_found(self):
        from multi_agent.agents.runtime.skill_consult import record_skill_consult
        agent = _FakeAgent()
        result = _FakeResult(True, {"found": False, "message": "Skill not found: x"})
        record_skill_consult(agent, "get_skill", {"name": "x"}, result)
        self.assertEqual(agent._consulted_skills, set())
        self.assertEqual(agent._hubs.eventhub.events, [])

    def test_ignores_other_tools(self):
        from multi_agent.agents.runtime.skill_consult import record_skill_consult
        agent = _FakeAgent()
        result = _FakeResult(True, {"found": True, "skill": {"name": "x"}})
        record_skill_consult(agent, "read", {"name": "x"}, result)
        self.assertEqual(agent._consulted_skills, set())

    def test_never_raises_without_hubs(self):
        from multi_agent.agents.runtime.skill_consult import record_skill_consult
        agent = _FakeAgent()
        agent._hubs = None
        result = _FakeResult(True, {"found": True, "skill": {"name": "x"}})
        record_skill_consult(agent, "get_skill", {"name": "x"}, result)  # no raise
        self.assertIn("x", agent._consulted_skills)


if __name__ == "__main__":
    unittest.main()
