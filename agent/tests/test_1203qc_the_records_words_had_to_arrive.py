r"""#1203qc: ten diagnosis wirings on the top-two blockers were guarded by SPELLING.

`test_1188_all_diagnoses_stay_wired` — the file named for exactly this job — asserts

    assert f"{fn}(orch, _fp)" in branch        # six diagnoses, ui-evidence branch
    assert f"{fn}(orch, _ff)" in branch        # four diagnoses, ui_flow branch

over a text slice of `dispatch_gate_level_checks`. `test_1203fx_the_record_says_what_to_reproduce`
adds `assert "ui_evidence_failed_evidence_1203fx(orch, _fp)" in branch`. Every one of those
substrings survives intact when the value is thrown away:

    + (ui_evidence_failed_evidence_1203fx(orch, _fp) and "")

The spelling is unchanged; the sentence the failing record recorded never reaches the lane.
(#1203ft's two AST assertions on the sibling branch are stronger — one Call, args, membership
in the `_extra` assignment — and they are blind to the same thing, which is the point: a
structural assertion sees SHAPE, not the value flowing through it. #1203qb covers that branch.)

WHY THIS CHECK. `validation_ui_evidence_failed` is the #2 modern blocker (204 gate-ledger rows)
and #1040 calls it "the single most common live blocker — 7 of the last 10 declining runs";
r134, r137 and r158 all died with it or its sibling open after 75 minutes of lane time.
#1203fx's own measurement is the pre-fix baseline: of 508 tasks across 92 runs naming this
check, 319 named the failing pages and **0 quoted a record**. The whole value of the fix is
that a record's own words arrive — so that is what has to be asserted.

AND THE FAILURE MODE IS NOT HYPOTHETICAL. #1178 records this exact class on this exact path:
the producer read `_last_validation_results` / `_validation_results`, two attributes the
orchestrator does not have, so `_b(None)` reported nothing failing and the function returned []
"on every call since #982 landed" — #982's page list, #1043's auth-root hint, #1176 and #1177
all went silent at once and the dispatcher fell through to the 789-character generic body. r17
shows it on both sides of a resume while the gate one line above printed "1 named page(s):
landing_page". A spelling assertion cannot see any of that; this file's QC3 reproduces it.
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

_PAGE = "landing_page"          # r17's named page, from #1178's comment
_WORDS = ("Landing page /signup renders a blank <div id='root'></div> due to a React error "
          "thrown by <Routes> mounted outside a Router. Flow cannot begin.")


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
    def list_checks(self):
        return []


def _stub():
    hubs = types.SimpleNamespace(workhub=_FakeWorkHub(), codehub=_FakeCodeHub())
    orch = types.SimpleNamespace(
        hubs=hubs,
        message_bus=_FakeBus(),
        _logger=logging.getLogger("test_1203qc"),
        _current_milestone_version="1.2.0",
    )
    # #1178: the producer calls the METHOD `_get_validation_results(limit=...)`; a run with
    # no results is the case that used to be indistinguishable from a broken read.
    orch._get_validation_results = lambda limit=None: [{"check": "ui_evidence"}]
    return orch


class _Driven(unittest.TestCase):
    """`_ui_evidence_report_1203fx` resolves `_ui_evidence_breadth_739` through
    `globals().get(...)`, the same seam #1203fu/#1178 left; inject the gate's answer rather
    than reconstructing a validation-results graph."""

    def setUp(self):
        self._had = "_ui_evidence_breadth_739" in rd.__dict__
        self._saved = rd.__dict__.get("_ui_evidence_breadth_739")

    def tearDown(self):
        if self._had:
            rd.__dict__["_ui_evidence_breadth_739"] = self._saved
        else:
            rd.__dict__.pop("_ui_evidence_breadth_739", None)

    def _body(self, pages=(_PAGE,), words=None):
        if words is None:
            words = {_PAGE: _WORDS}
        # THE FIXTURE MUST DEPEND ON ITS INPUT. A lambda that ignores `results` would make
        # #1178's defect invisible -- that bug was precisely a producer handing the gate's
        # breadth function None, and a fixture answering the same regardless of its argument
        # "already agrees with the conclusion" (the #1202fu/#757 fixture trap).
        rd.__dict__["_ui_evidence_breadth_739"] = lambda results=None, *a, **k: ({
            "pages_failed": list(pages), "words_failed": dict(words),
            "failed_records": len(pages)} if results else {})
        orch = _stub()
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["validation_ui_evidence_failed"]))
        self.assertEqual(len(orch.hubs.workhub.tasks), 1, orch.hubs.workhub.tasks)
        return orch.hubs.workhub.tasks[0]["description"]


class TheRecordsOwnWordsReachTheTask(_Driven):

    def test_the_recorded_sentence_is_in_the_description(self):
        body = self._body()
        self.assertIn("mounted outside a Router", body,
                      "#1203fx's whole point is that the record's words arrive")

    def test_the_page_is_still_named_beside_it(self):
        """#982's page list is additive, not replaced."""
        self.assertIn(_PAGE, self._body())

    def test_a_page_with_no_recorded_words_still_files_the_task(self):
        body = self._body(words={})
        self.assertIn(_PAGE, body)
        self.assertNotIn("mounted outside a Router", body)

    def test_words_for_another_page_are_not_attributed_to_this_one(self):
        body = self._body(words={"some_other_page": _WORDS})
        self.assertNotIn("mounted outside a Router", body)


class TheCutIsDeclared(_Driven):
    """#1034: eight are quoted and the remainder has to be stated."""

    def test_more_than_eight_pages_declares_how_many_were_not_shown(self):
        pages = ["page_%02d" % i for i in range(10)]
        body = self._body(pages=pages, words={p: "%s is blank" % p for p in pages})
        self.assertIn("more failing page(s) carry a recorded sentence", body)
        self.assertIn("2 more", body)

    def test_exactly_eight_declares_nothing(self):
        pages = ["page_%02d" % i for i in range(8)]
        body = self._body(pages=pages, words={p: "%s is blank" % p for p in pages})
        self.assertNotIn("more failing page(s) carry a recorded sentence", body)


class TheFixtureItselfIsFalsifiable(_Driven):
    """If the injected breadth function answered the same for any input, every assertion in
    this file would hold while the producer read nothing at all."""

    def test_a_run_with_no_validation_results_says_nothing(self):
        rd.__dict__["_ui_evidence_breadth_739"] = lambda results=None, *a, **k: ({
            "pages_failed": [_PAGE], "words_failed": {_PAGE: _WORDS},
            "failed_records": 1} if results else {})
        orch = _stub()
        orch._get_validation_results = lambda limit=None: []
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["validation_ui_evidence_failed"]))
        body = orch.hubs.workhub.tasks[0]["description"]
        self.assertNotIn("mounted outside a Router", body,
                         "the fixture is answering regardless of its input")


class TheProducerReadsARealApi(_Driven):
    """#1178's defect, reproduced: a producer that reads nothing must not look like a run
    with nothing to report."""

    def test_no_named_page_means_the_generic_body_stands(self):
        body = self._body(pages=(), words={})
        self.assertNotIn("mounted outside a Router", body)

    def test_the_task_is_still_filed_and_an_agent_woken(self):
        rd.__dict__["_ui_evidence_breadth_739"] = lambda results=None, *a, **k: ({
            "pages_failed": [_PAGE], "words_failed": {_PAGE: _WORDS},
            "failed_records": 1} if results else {})
        orch = _stub()
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["validation_ui_evidence_failed"]))
        self.assertEqual(len(orch.hubs.workhub.tasks), 1)
        self.assertTrue(orch.hubs.workhub.tasks[0].get("assignee"))
        self.assertTrue(orch.message_bus.sent)


if __name__ == "__main__":
    unittest.main()
