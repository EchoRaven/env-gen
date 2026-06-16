"""Tests that collect_hub_pulse installs default subscriptions on every call."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
LLM_DIR = AGENT_DIR / "env_generator" / "llm_generator"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.agents.runtime.hub_pulse import collect_hub_pulse  # noqa: E402


class HubPulseInstallsSubscriptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pulse_subs_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pulse_for_bug_triage_orch_installs_subscriptions(self) -> None:
        # Before pulse: no subs
        self.assertEqual(self.reg.eventhub.get_subscriptions(), [])
        collect_hub_pulse(self.reg, "debugger")
        subs = self.reg.eventhub.get_subscriptions("debugger")
        self.assertEqual(len(subs), 4)

    def test_pulse_for_unknown_profile_does_not_install(self) -> None:
        # Use a clearly-unregistered profile name; core agents
        # (backend/frontend/orchestrator/...) now have default
        # subscriptions wired up so they get push events.
        collect_hub_pulse(self.reg, "no_such_profile_xyz")
        self.assertEqual(self.reg.eventhub.get_subscriptions(), [])

    def test_pulse_called_repeatedly_does_not_duplicate(self) -> None:
        for _ in range(3):
            collect_hub_pulse(self.reg, "debugger")
        subs = self.reg.eventhub.get_subscriptions("debugger")
        self.assertEqual(len(subs), 4)


if __name__ == "__main__":
    unittest.main()
