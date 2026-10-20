r"""#1203qf: two more of the twelve diagnosis wirings, proven to ARRIVE rather than be spelled.

`dispatch_gate_level_checks` composes six recomputed diagnoses into one `_extra` assignment
per branch, for the #2 and #3 modern blockers -- twelve call sites in all. #1203qb and
#1203qc closed the two evidence ones. `test_1188_all_diagnoses_stay_wired`, the file named
for this exact job, guards four per branch with TEXT substrings
(`assert f"{fn}(orch, _fp)" in branch`), and every one of them survives

    + (fn(orch, _fp) and "")

-- spelling unchanged, AST shape unchanged, diagnosis gone from the task body. Measured, not
argued: test_1188's own five assertions were re-run against mutated source at four different
call sites and passed 5/5 each time.

This file covers the two that need no app source, on BOTH branches:

  ui_smoke_refresh_1177     reads `<output_dir>/shared/hubs/codehub_checks.json` for a record
                            with status in ("failure","failed") whose name starts
                            `validation:ui_smoke` and whose last `:` segment is one of the
                            named pages/flows. It exists because `run_validation` is API-only
                            and never touches a ui_smoke record -- r17 spent 18 minutes
                            re-running it while the page defect was already repaired.
  name_keyed_supersede_1202su  reads `orch._get_validation_results(limit=9999)` and fires when
                            a ui_flow record PASSED under a name that is not one of the
                            failing names. Measured when it landed: in 15 of 24 runs a pass
                            was recorded after the failure under a different name and the
                            failure still stood (r130: 12 passes, the newest 52s later).
                            `1202su` is not even in `test_1188._DIAGNOSES`, so its two call
                            sites had no wiring assertion of any kind.

The three remaining diagnoses (1176/1182/1185) also read `app/frontend/src/**`, so they need
an App.jsx + page components + a two-step login page; they are left to their own fixture.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
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

_FLOW = "fresh_comments"
_PAGE = "landing_page"
_OTHER = "profile_page_basic"
_SMOKE_1177 = "★ THESE RECORDS CANNOT BE REWRITTEN BY `run_validation`:"
_KEYED_1202SU = "★ THE RECORD IS KEYED BY ITS NAME."


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


def _write_hub(root: Path, smoke_for):
    """`codehub_checks.json` with one FAILING ui_smoke record per name in `smoke_for`."""
    hubs = root / "shared" / "hubs"
    hubs.mkdir(parents=True, exist_ok=True)
    blob = {"_meta": {"version": 1}}
    for i, name in enumerate(smoke_for):
        blob["c%d" % i] = {
            "name": "validation:ui_smoke:%s" % name,
            "status": "failed",
            "evidence": {"summary": "the %s smoke walk found no composer" % name},
        }
    (hubs / "codehub_checks.json").write_text(json.dumps(blob), encoding="utf-8")


class _Driven(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._saved = {k: rd.__dict__.get(k) for k in
                       ("compute_flow_coverage", "_ui_evidence_breadth_739")}
        self._had = {k: k in rd.__dict__ for k in self._saved}

    def tearDown(self):
        for k, v in self._saved.items():
            if self._had[k]:
                rd.__dict__[k] = v
            else:
                rd.__dict__.pop(k, None)
        self._tmp.cleanup()

    def _orch(self, validation_results):
        hubs = types.SimpleNamespace(workhub=_FakeWorkHub(), codehub=_FakeCodeHub())
        orch = types.SimpleNamespace(
            hubs=hubs, message_bus=_FakeBus(),
            _logger=logging.getLogger("test_1203qf"),
            _current_milestone_version="1.2.0",
            output_dir=str(self.root),
        )
        orch._get_validation_results = lambda limit=None: list(validation_results)
        return orch

    def _ui_flow_body(self, smoke_for=(_FLOW,), passes=(_OTHER,)):
        _write_hub(self.root, smoke_for)
        rd.__dict__["compute_flow_coverage"] = lambda hubs, *a, **k: types.SimpleNamespace(
            failed=[_FLOW], missing=[], source="pages")
        recs = [{"name": "validation:ui_flow:%s" % p, "status": "success",
                 "metadata": {"check": "ui_flow"}} for p in passes]
        orch = self._orch(recs)
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["deliverability_ui_flow_failed"]))
        self.assertEqual(len(orch.hubs.workhub.tasks), 1, orch.hubs.workhub.tasks)
        return orch.hubs.workhub.tasks[0]["description"]

    def _ui_evidence_body(self, smoke_for=(_PAGE,), passes=(_OTHER,)):
        _write_hub(self.root, smoke_for)
        # the stand-in MUST depend on its input: a breadth function answering the same for any
        # argument would hide #1178, which was exactly a producer handing it nothing.
        rd.__dict__["_ui_evidence_breadth_739"] = lambda results=None, *a, **k: ({
            "pages_failed": [_PAGE], "words_failed": {_PAGE: "renders a blank root div"},
            "failed_records": 1} if results else {})
        recs = [{"name": "validation:ui_flow:%s" % p, "status": "success",
                 "metadata": {"check": "ui_flow"}} for p in passes]
        orch = self._orch(recs)
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["validation_ui_evidence_failed"]))
        self.assertEqual(len(orch.hubs.workhub.tasks), 1, orch.hubs.workhub.tasks)
        return orch.hubs.workhub.tasks[0]["description"]


class TheSmokeRefreshCorrectionArrives(_Driven):
    """#1177 on both branches."""

    def test_on_the_ui_flow_branch(self):
        self.assertIn(_SMOKE_1177, self._ui_flow_body())

    def test_on_the_ui_evidence_branch(self):
        self.assertIn(_SMOKE_1177, self._ui_evidence_body())

    def test_it_names_the_record_that_cannot_be_rewritten(self):
        self.assertIn("validation:ui_smoke:%s" % _FLOW, self._ui_flow_body())

    def test_a_smoke_record_for_another_page_is_not_claimed(self):
        body = self._ui_flow_body(smoke_for=("some_other_page",))
        self.assertNotIn(_SMOKE_1177, body)

    def test_no_smoke_record_at_all_leaves_the_rest_standing(self):
        body = self._ui_flow_body(smoke_for=())
        self.assertNotIn(_SMOKE_1177, body)
        self.assertIn(_FLOW, body)


class TheNameKeyedSupersedeNoteArrives(_Driven):
    """#1202su on both branches -- it is not in test_1188._DIAGNOSES, so these two call
    sites had no wiring assertion at all before this file."""

    def test_on_the_ui_flow_branch(self):
        self.assertIn(_KEYED_1202SU, self._ui_flow_body())

    def test_on_the_ui_evidence_branch(self):
        self.assertIn(_KEYED_1202SU, self._ui_evidence_body())

    def test_it_names_the_pass_recorded_under_another_name(self):
        self.assertIn(_OTHER, self._ui_flow_body())

    def test_a_pass_under_the_SAME_name_is_not_a_supersede_claim(self):
        """The whole point: only a pass under a DIFFERENT name leaves the failure standing."""
        body = self._ui_flow_body(passes=(_FLOW,))
        self.assertNotIn(_KEYED_1202SU, body)

    def test_no_passing_record_means_no_note(self):
        self.assertNotIn(_KEYED_1202SU, self._ui_flow_body(passes=()))


class TheFixturesAreFalsifiable(_Driven):
    """Each stand-in must be able to say nothing, or every assertion above is vacuous."""

    def test_an_empty_hub_file_yields_no_smoke_note(self):
        self.assertNotIn(_SMOKE_1177, self._ui_flow_body(smoke_for=()))

    def test_a_run_with_no_validation_results_yields_no_keyed_note(self):
        self.assertNotIn(_KEYED_1202SU, self._ui_flow_body(passes=()))


if __name__ == "__main__":
    unittest.main()
