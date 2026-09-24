"""Tests for runtime/agent_subscriptions.py (Cutover 12)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.agent_subscriptions import (  # noqa: E402
    DEFAULT_SUBSCRIPTIONS,
    ensure_default_subscriptions,
)


class DefaultSubscriptionsTableTests(unittest.TestCase):
    def test_bug_triage_orchestrator_subscribes_to_any_bug_found(self) -> None:
        # A bug_found can be filed by any source (verifier, business_chain,
        # api_smoke, …); the debugger subscribes with a WILDCARD source so a
        # chain-filed bug is not silently missed (a prior ('verifier','bug_found')
        # sub dropped every chain-filed bug).
        subs = DEFAULT_SUBSCRIPTIONS.get("debugger", [])
        triples = [(s[0], s[1]) for s in subs]
        self.assertIn(("*", "bug_found"), triples)

    def test_bug_triage_orchestrator_subscribes_to_runhub_run_failed(self) -> None:
        subs = DEFAULT_SUBSCRIPTIONS.get("debugger", [])
        triples = [(s[0], s[1]) for s in subs]
        self.assertIn(("runhub", "run_failed"), triples)

    def test_bug_triage_orchestrator_subscribes_to_runhub_run_completed(self) -> None:
        subs = DEFAULT_SUBSCRIPTIONS.get("debugger", [])
        triples = [(s[0], s[1]) for s in subs]
        self.assertIn(("runhub", "run_completed"), triples)


class EnsureDefaultSubscriptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="subs_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unknown_agent_is_noop(self) -> None:
        ensure_default_subscriptions(self.reg, "no_such_agent_profile")
        self.assertEqual(self.reg.eventhub.get_subscriptions(), [])

    def test_bug_triage_orchestrator_registers_four_subscriptions(self) -> None:
        ensure_default_subscriptions(self.reg, "debugger")
        subs = self.reg.eventhub.get_subscriptions("debugger")
        triples = {(s["source_hub"], s["event_type"]) for s in subs}
        # Round 7b added the 4th: ('orchestrator', 'kickoff_complete') —
        # the debugger wakes when the kickoff meeting closes so its
        # next-cycle hub_pulse picks up any kickoff-time bug-triage
        # decisions (e.g. orchestrator routed an unresolved cross-check
        # to debugger for analysis at synthesis time).
        self.assertEqual(triples, {
            ("*", "bug_found"),
            ("runhub", "run_failed"),
            ("runhub", "run_completed"),
            ("orchestrator", "kickoff_complete"),
        })

    def test_idempotent_repeated_calls_dont_duplicate(self) -> None:
        for _ in range(5):
            ensure_default_subscriptions(self.reg, "debugger")
        subs = self.reg.eventhub.get_subscriptions("debugger")
        self.assertEqual(len(subs), 4)

    def test_swallowed_exception_does_not_propagate(self) -> None:
        # Pass a hubs surrogate without eventhub; should not raise.
        class _Fake:
            pass
        ensure_default_subscriptions(_Fake(), "debugger")  # must not raise


if __name__ == "__main__":
    unittest.main()
