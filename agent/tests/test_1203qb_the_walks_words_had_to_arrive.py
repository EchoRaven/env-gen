r"""#1203qb: the #3 blocker's diagnoses were verified STRUCTURALLY and never shown to ARRIVE.

`deliverability_ui_flow_failed` is 141 of the modern gate-ledger rows and 2503 red records
across 81 runs. Five recomputed diagnoses hang off one assignment in
`dispatch_gate_level_checks`:

    _extra = (_ui_flow_failed_extra(_ff)
              + ui_flow_failed_evidence_1203ft(orch, _ff)     # the walk's own words
              + auth_contradiction_1176(orch, _ff)
              + control_absence_contradicted_1182(orch, _ff)
              + ui_smoke_refresh_1177(orch, _ff))

`test_1203ft_the_walks_own_words_stayed_in_the_hub` guards that wiring with two AST
assertions, and they are good ones -- exactly one call, args `["orch", "_ff"]`, and the call
sits inside an `_extra` assignment together with its four siblings. #943's ratchet is even
cited for why they read the assignment's own expression instead of a byte window.

They are still blind to whether the VALUE arrives. Replace the call's result and every one of
those structural facts survives:

    + (ui_flow_failed_evidence_1203ft(orch, _ff) and "")

The `Call` node is still there exactly once, its args are still `orch, _ff`, it is still part
of the same `_extra` assignment beside the same four siblings -- and the walk's recorded
sentence is gone from the task body. That is #1203pi's class one level up from a quoted
statement: a structural assertion sees SHAPE, not the value flowing through it. The nine
behavioural tests in that file exercise `ui_flow_failed_evidence_1203ft` in isolation, so they
never see the task either.

This file drives the real dispatcher and asserts the recorded sentence is in the description.

The sibling branch `validation_ui_evidence_failed` (the #2 blocker, 204 modern rows) has the
identical shape -- `ui_evidence_failed_evidence_1203fx(orch, _fp)` plus six siblings in one
`_extra` assignment -- and is reached through `_ui_evidence_report_1203fx`, a different fetch.
It is NOT covered here; one owner per rule (#1032) and its fixture is its own job.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import remediation_dispatcher as rd  # noqa: E402
from multi_agent.runtime.remediation_dispatcher import RemediationDispatcher  # noqa: E402

# the r158 record, which #1203ft's docstring quotes as the thing that stayed in the hub
_R158 = ("Fresh comments UI flow failed after signup: posting a comment on /video/35 sent "
         "Authorization but POST /api/comments returned 401; bug task_07f26bcdce filed.")
_FLOW = "fresh_comments"


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


class _FakeCodeHub:
    def __init__(self, checks):
        self._checks = checks

    def list_checks(self):
        return self._checks


def _stub(checks):
    hubs = types.SimpleNamespace(workhub=_FakeWorkHub(), codehub=_FakeCodeHub(checks))
    return types.SimpleNamespace(
        hubs=hubs,
        message_bus=_FakeBus(),
        _logger=logging.getLogger("test_1203qb"),
        _current_milestone_version="1.2.0",
    )


def _checks(summary=_R158, flow=_FLOW, status="failed", key="summary"):
    rec = {"name": "validation:ui_flow:%s" % flow, "status": status}
    if summary is not None:
        rec[key] = summary
    return [rec]


class _Driven(unittest.TestCase):
    """`_ui_flow_failed_names` resolves `compute_flow_coverage` through `globals().get(...)`,
    which is the seam #1203fu left behind; patch it rather than building a hub graph."""

    def setUp(self):
        self._saved = rd.__dict__.get("compute_flow_coverage", None)
        self._had = "compute_flow_coverage" in rd.__dict__

    def tearDown(self):
        if self._had:
            rd.__dict__["compute_flow_coverage"] = self._saved
        else:
            rd.__dict__.pop("compute_flow_coverage", None)

    def _body(self, checks, failed=(_FLOW,)):
        rd.__dict__["compute_flow_coverage"] = \
            lambda hubs, *a, **k: types.SimpleNamespace(failed=list(failed), missing=[],
                                                        source="pages")
        orch = _stub(checks)
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["deliverability_ui_flow_failed"]))
        self.assertEqual(len(orch.hubs.workhub.tasks), 1, orch.hubs.workhub.tasks)
        return orch.hubs.workhub.tasks[0]["description"]


class TheRecordedSentenceReachesTheTask(_Driven):

    def test_the_walks_own_words_are_in_the_description(self):
        body = self._body(_checks())
        self.assertIn("POST /api/comments returned 401", body,
                      "the sentence the walk recorded never reached the lane")

    def test_the_flow_is_still_named_beside_it(self):
        """#981's naming must survive: additive, not a replacement."""
        body = self._body(_checks())
        self.assertIn(_FLOW, body)

    def test_reason_is_carried_when_there_is_no_summary(self):
        body = self._body(_checks(key="reason"))
        self.assertIn("POST /api/comments returned 401", body)

    def test_a_passing_record_contributes_no_quote(self):
        body = self._body(_checks(status="success"))
        self.assertIn(_FLOW, body)
        self.assertNotIn("POST /api/comments returned 401", body)

    def test_a_flow_with_nothing_recorded_still_files_the_task(self):
        body = self._body(_checks(summary=None))
        self.assertIn(_FLOW, body)


class ItStillRoutes(_Driven):
    """The arrival must not have cost the routing the branch already had."""

    def test_the_task_is_filed_and_an_agent_is_woken(self):
        rd.__dict__["compute_flow_coverage"] = \
            lambda hubs, *a, **k: types.SimpleNamespace(failed=[_FLOW], missing=[],
                                                        source="pages")
        orch = _stub(_checks())
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["deliverability_ui_flow_failed"]))
        self.assertEqual(len(orch.hubs.workhub.tasks), 1)
        self.assertTrue(orch.hubs.workhub.tasks[0].get("assignee"))
        self.assertTrue(orch.message_bus.sent)

    def test_no_failing_flow_means_the_generic_body_stands(self):
        body = self._body(_checks(), failed=())
        self.assertNotIn("POST /api/comments returned 401", body)


if __name__ == "__main__":
    unittest.main()
