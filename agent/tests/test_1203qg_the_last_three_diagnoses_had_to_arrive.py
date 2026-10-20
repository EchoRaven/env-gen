r"""#1203qg: the last three of the twelve diagnosis wirings, proven to ARRIVE.

`dispatch_gate_level_checks` composes six recomputed diagnoses into one `_extra` assignment
per branch for the #2 and #3 modern blockers -- twelve call sites. #1203qb/qc closed the two
evidence ones, #1203qf closed `ui_smoke_refresh_1177` and `name_keyed_supersede_1202su` on
both branches. These three are the remainder, and they are the ones that read the generated
app's own source, which is why they had no driven test:

  auth_contradiction_1176          the contract demands a token on a route App.jsx leaves
                                   public, so the 401 the walk saw is correct behaviour and
                                   the lane must not "fix" the handler.
  control_absence_contradicted_1182  the walk said a control is missing; the page's own
                                   source declares it. r19 ended STUCK at $355 on one such
                                   record.
  two_step_login_1185              the app's login needs two submits, so the first one
                                   failing is not an auth defect.

All three are guarded today only by `test_1188_all_diagnoses_stay_wired`, which asserts
`f"{fn}(orch, _fp)" in branch` over a TEXT slice -- and that substring is byte-identical
under `+ (fn(orch, _fp) and "")`. Verified by re-running test_1188's own five assertions
against mutated source at four call sites: 5/5 passed every time.

THE FIXTURE IS A MINIATURE GENERATED APP, because that is what these three read:

    shared/hubs/codehub_checks.json        the failing validation:ui* records
    shared/hubs/registryhub_endpoints.json path+method+auth_required          (1176)
    shared/hubs/registryhub_ui_pages.json  name -> route                      (1176)
    app/frontend/src/App.jsx               <Route path=... element={<Comp/>}> (1176, 1182)
    app/frontend/src/pages/SearchPage.jsx  a real control tag                 (1182)
    app/frontend/src/pages/LoginPage.jsx   step === 0 ... setStep(1)          (1185)
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

_CONTRACT_1176 = "★ THE CONTRACT, NOT THE HANDLER, IS WHAT REQUIRES THE TOKEN HERE:"
_CONTROL_1182 = "★ THE PAGE'S SOURCE DECLARES THE CONTROL THIS RECORD CALLS MISSING:"
_TWOSTEP_1185 = "★ THIS APP'S LOGIN TAKES TWO SUBMITS — THE FIRST ONE IS NOT THE LOGIN:"

_APP_JSX = """
import { Routes, Route } from "react-router-dom";
import FeedPage from "./pages/FeedPage";
import SearchPage from "./pages/SearchPage";
export default function App() {
  return (
    <Routes>
      <Route path="/feed" element={<FeedPage />} />
      <Route path="/search" element={<SearchPage />} />
    </Routes>
  );
}
"""

_SEARCH_JSX = """
export default function SearchPage() {
  return (
    <div>
      <input type="text" placeholder="Search videos" aria-label="Search" />
      <button>Go</button>
    </div>
  );
}
"""

_LOGIN_JSX = """
import { useState } from "react";
export default function LoginPage() {
  const [step, setStep] = useState(0);
  const onSubmit = (e) => {
    e.preventDefault();
    if (step === 0) { setStep(1); return; }
    doLogin();
  };
  return <form onSubmit={onSubmit}>
    <button>{step === 1 ? 'Sign In' : 'Continue'}</button>
  </form>;
}
"""


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

    # ---- the miniature app -------------------------------------------------
    def _app(self, app_jsx=_APP_JSX, search_jsx=_SEARCH_JSX, login_jsx=_LOGIN_JSX):
        src = self.root / "app" / "frontend" / "src"
        (src / "pages").mkdir(parents=True, exist_ok=True)
        if app_jsx is not None:
            (src / "App.jsx").write_text(app_jsx, encoding="utf-8")
        if search_jsx is not None:
            (src / "pages" / "SearchPage.jsx").write_text(search_jsx, encoding="utf-8")
        if login_jsx is not None:
            (src / "pages" / "LoginPage.jsx").write_text(login_jsx, encoding="utf-8")
        (src / "pages" / "FeedPage.jsx").write_text(
            "export default function FeedPage(){return <div/>;}", encoding="utf-8")

    def _hubs(self, checks, endpoints=True, ui_pages=True):
        h = self.root / "shared" / "hubs"
        h.mkdir(parents=True, exist_ok=True)
        blob = {"_meta": {"version": 1}}
        for i, rec in enumerate(checks):
            blob["c%d" % i] = rec
        (h / "codehub_checks.json").write_text(json.dumps(blob), encoding="utf-8")
        eps = {"_meta": {"version": 1}}
        if endpoints:
            eps["e0"] = {"path": "/api/videos", "method": "GET", "auth_required": True}
        (h / "registryhub_endpoints.json").write_text(json.dumps(eps), encoding="utf-8")
        pages = {"_meta": {"version": 1}}
        if ui_pages:
            pages["p0"] = {"name": "feed_page", "route": "/feed"}
        (h / "registryhub_ui_pages.json").write_text(json.dumps(pages), encoding="utf-8")

    # ---- the records that trigger each diagnosis ---------------------------
    @staticmethod
    def _rec_1176(flow="feed_page"):
        return {"name": "validation:ui_flow:%s" % flow, "status": "failed",
                "evidence": {"summary": "GET /api/videos returned 401 while logged out"}}

    @staticmethod
    def _rec_1182(flow="search_page"):
        return {"name": "validation:ui_flow:%s" % flow, "status": "failed",
                "evidence": {"summary": "/search page loaded but the search box "
                                        "could not find any input"}}

    @staticmethod
    def _rec_1185(flow="login_page"):
        return {"name": "validation:ui_flow:%s" % flow, "status": "failed",
                "evidence": {"summary": "login submit returned 401 unauthorized"}}

    # ---- the two branches -------------------------------------------------
    def _flow_body(self, flows, checks, **app):
        self._app(**app)
        self._hubs(checks)
        rd.__dict__["compute_flow_coverage"] = lambda hubs, *a, **k: types.SimpleNamespace(
            failed=list(flows), missing=[], source="pages")
        orch = self._orch()
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["deliverability_ui_flow_failed"]))
        self.assertEqual(len(orch.hubs.workhub.tasks), 1, orch.hubs.workhub.tasks)
        return orch.hubs.workhub.tasks[0]["description"]

    def _evidence_body(self, pages, checks, **app):
        self._app(**app)
        self._hubs(checks)
        rd.__dict__["_ui_evidence_breadth_739"] = lambda results=None, *a, **k: ({
            "pages_failed": list(pages), "words_failed": {}, "failed_records": len(pages)}
            if results else {})
        orch = self._orch()
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["validation_ui_evidence_failed"]))
        self.assertEqual(len(orch.hubs.workhub.tasks), 1, orch.hubs.workhub.tasks)
        return orch.hubs.workhub.tasks[0]["description"]

    def _orch(self):
        hubs = types.SimpleNamespace(workhub=_FakeWorkHub(), codehub=_FakeCodeHub())
        orch = types.SimpleNamespace(
            hubs=hubs, message_bus=_FakeBus(),
            _logger=logging.getLogger("test_1203qg"),
            _current_milestone_version="1.2.0", output_dir=str(self.root))
        orch._get_validation_results = lambda limit=None: [{"check": "ui_evidence"}]
        return orch


class TheContractContradictionArrives(_Driven):
    """#1176, both branches."""

    def test_on_the_ui_flow_branch(self):
        body = self._flow_body(["feed_page"], [self._rec_1176()])
        self.assertIn(_CONTRACT_1176, body)
        self.assertIn("/api/videos", body)

    def test_on_the_ui_evidence_branch(self):
        self.assertIn(_CONTRACT_1176,
                      self._evidence_body(["feed_page"], [self._rec_1176()]))

    def test_a_guarded_route_stays_quiet(self):
        """#1176 says nothing when App.jsx wraps the route in an auth guard -- the 401 is
        then the guard working, not a contract contradiction."""
        guarded = _APP_JSX.replace(
            '<Route path="/feed" element={<FeedPage />} />',
            '<Route path="/feed" element={<RequireAuth><FeedPage /></RequireAuth>} />')
        body = self._flow_body(["feed_page"], [self._rec_1176()], app_jsx=guarded)
        self.assertNotIn(_CONTRACT_1176, body)

    def test_an_endpoint_without_auth_required_stays_quiet(self):
        self._app()
        h = self.root / "shared" / "hubs"
        self._hubs([self._rec_1176()], endpoints=False)
        rd.__dict__["compute_flow_coverage"] = lambda hubs, *a, **k: types.SimpleNamespace(
            failed=["feed_page"], missing=[], source="pages")
        orch = self._orch()
        _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["deliverability_ui_flow_failed"]))
        self.assertNotIn(_CONTRACT_1176, orch.hubs.workhub.tasks[0]["description"])


class TheControlContradictionArrives(_Driven):
    """#1182, both branches."""

    def test_on_the_ui_flow_branch(self):
        body = self._flow_body(["search_page"], [self._rec_1182()])
        self.assertIn(_CONTROL_1182, body)

    def test_on_the_ui_evidence_branch(self):
        self.assertIn(_CONTROL_1182,
                      self._evidence_body(["search_page"], [self._rec_1182()]))

    def test_a_page_with_no_control_stays_quiet(self):
        bare = "export default function SearchPage(){return <div>nothing</div>;}"
        body = self._flow_body(["search_page"], [self._rec_1182()], search_jsx=bare)
        self.assertNotIn(_CONTROL_1182, body)


class TheTwoStepLoginNoteArrives(_Driven):
    """#1185, both branches."""

    def test_on_the_ui_flow_branch(self):
        self.assertIn(_TWOSTEP_1185, self._flow_body(["login_page"], [self._rec_1185()]))

    def test_on_the_ui_evidence_branch(self):
        self.assertIn(_TWOSTEP_1185,
                      self._evidence_body(["login_page"], [self._rec_1185()]))

    def test_a_single_step_login_page_stays_quiet(self):
        one = ("import { useState } from 'react';\n"
               "export default function LoginPage(){ return <form><button>Sign In"
               "</button></form>; }\n")
        body = self._flow_body(["login_page"], [self._rec_1185()], login_jsx=one)
        self.assertNotIn(_TWOSTEP_1185, body)


class TheFixtureIsFalsifiable(_Driven):
    """Every positive above must be able to fail: no record, no diagnosis."""

    def test_no_failing_record_means_none_of_the_three_speak(self):
        body = self._flow_body(["feed_page"], [])
        for mark in (_CONTRACT_1176, _CONTROL_1182, _TWOSTEP_1185):
            self.assertNotIn(mark, body)

    def test_a_record_for_another_flow_is_not_claimed(self):
        body = self._flow_body(["feed_page"], [self._rec_1176(flow="some_other")])
        self.assertNotIn(_CONTRACT_1176, body)


if __name__ == "__main__":
    unittest.main()
