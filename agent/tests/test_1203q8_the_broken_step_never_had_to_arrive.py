"""#1203q8: the #1 modern blocker's payload was guarded only by a source-text assertion.

`business_chain_failing` is the most frequent blocking reason in the modern era (291 of the
gate-ledger rows across the 7 modern runs that carry a ledger). #798 exists because its task
body used to say "read the broken step" without naming one; #1135 adds which PASSING chains
already exercise that endpoint. Both payloads are attached at ONE place --
`dispatch_gate_level_checks`'s `else:` branch, where `_brk798 = _chain_broken_detail_798(orch)`
feeds `_extra` into the task description.

What guarded that attachment:

    def test_it_is_attached_to_the_task_body():
        src = inspect.getsource(rd)
        assert "_chain_broken_detail_798(orch)" in src
        assert "THE BROKEN STEP(S), from the chain registry's own" in src

-- a quoted statement, which cannot see whether the statement RUNS (the #1203pi class, and the
same blindness as `test_the_action_404_branch_keeps_precedence`, which only compares
`src.index` positions). `None and _chain_broken_detail_798(orch)` leaves that source
byte-identical. The one behavioural test that reaches this branch,
`test_action_endpoint_chain_dispatch.test_business_chain_failing_without_action404_keeps_verifier`,
asserts the assignee and `validation_phase` and never looks at the description. So the
framework could stop telling the verifier which step broke -- the whole content of #798 and
#1135 -- with the suite green.

This file drives the real dispatcher and asserts the payload ARRIVES in the task body.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.remediation_dispatcher import RemediationDispatcher  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


class _FakeWorkHub:
    def __init__(self):
        self.tasks = []

    def create_task(self, **kw):
        self.tasks.append(kw)
        return {"id": "task_%d" % len(self.tasks)}


class _FakeBus:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


class _FakeRegistryHub:
    def __init__(self, chains):
        self._chains = chains

    def get_verification_chains(self):
        return self._chains


def _stub(chains):
    hubs = types.SimpleNamespace(workhub=_FakeWorkHub(),
                                 registryhub=_FakeRegistryHub(chains))
    return types.SimpleNamespace(
        hubs=hubs,
        message_bus=_FakeBus(),
        _logger=logging.getLogger("test_1203q8"),
        _current_milestone_version="1.2.0",
    )


def _step(method, path, ok, **kw):
    d = {"method": method, "path": path, "ok": ok}
    d.update(kw)
    return d


# netflix-local-r2's shape: the chain that aborted the run, plus a sibling that passes the
# endpoint its broken step failed on (#1135's motivating case).
def _chains(n_passing_siblings=1):
    chains = {
        "_meta": {"version": 3},
        "continue-watching_page": {
            "name": "continue-watching_page", "kind": "flow", "status": "failing",
            "last_result": {"broken": [], "steps": [
                _step("POST", "/api/continue-watching", False, status=400,
                      action="create continue-watching",
                      note='{"detail":"profile_id does not belong to the caller"}')]}},
    }
    for i in range(n_passing_siblings):
        chains["sibling_%02d" % i] = {
            "name": "sibling_%02d" % i, "kind": "flow", "status": "passing",
            "last_result": {"steps": [
                _step("POST", "/api/continue-watching", True, status=201)]}}
    return chains


def _body(chains):
    orch = _stub(chains)
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(["business_chain_failing"]))
    assert len(orch.hubs.workhub.tasks) == 1, orch.hubs.workhub.tasks
    t = orch.hubs.workhub.tasks[0]
    assert t["assignee"] == "verifier", t["assignee"]
    return t["description"]


class ThePayloadReachesTheTaskBody(unittest.TestCase):
    """Not "the call is spelled in the source" -- the text has to arrive."""

    def test_the_broken_step_section_is_in_the_description(self):
        body = _body(_chains())
        self.assertIn("THE BROKEN STEP(S), from the chain registry's own", body)

    def test_the_step_the_framework_already_knew_is_named(self):
        body = _body(_chains())
        self.assertIn("continue-watching_page", body)
        self.assertIn("POST /api/continue-watching", body)
        self.assertIn("returned 400", body)

    def test_the_apps_own_words_travel_with_it(self):
        """#1202wx: the app's answer is the discriminator, not a status code."""
        self.assertIn("profile_id does not belong to the caller", _body(_chains()))

    def test_the_passing_sibling_hint_arrives_too(self):
        """#1135: the fact that decided r2."""
        body = _body(_chains(1))
        self.assertIn("#1135", body)
        self.assertIn("sibling_00", body)
        self.assertIn("compare THEIR step inputs", body)


class TheCountSurvivesTheTrip(unittest.TestCase):
    """#1203q7: the hint argues from a count, so the count has to reach the lane."""

    def test_a_cut_sibling_list_declares_the_remainder_in_the_task_body(self):
        body = _body(_chains(48))
        named = set(re.findall(r"sibling_\d\d", body.split("ALREADY PASS")[0]))
        m = re.search(r"\+(\d+) more not shown", body)
        self.assertIsNotNone(m, body)
        self.assertEqual(len(named) + int(m.group(1)), 48,
                         "the lane cannot recover 48 from the task body")

    def test_three_siblings_are_not_decorated(self):
        body = _body(_chains(3))
        self.assertIn("ALREADY PASS", body)
        self.assertNotIn("more not shown", body)


class ItStillRoutesAndWakesTheVerifier(unittest.TestCase):
    """The payload must not have cost the routing that #148/V29 established."""

    def test_the_verifier_is_woken_in_validation_phase(self):
        orch = _stub(_chains())
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(["business_chain_failing"]))
        self.assertTrue(orch.message_bus.sent)
        msg = orch.message_bus.sent[0]
        self.assertEqual(msg.header.target_agent_id, "verifier")
        self.assertIs(msg.metadata.get("validation_phase"), True)

    def test_a_registry_with_nothing_broken_still_files_the_task(self):
        body = _body({"_meta": {"version": 3}})
        self.assertNotIn("THE BROKEN STEP(S)", body)


if __name__ == "__main__":
    unittest.main()
