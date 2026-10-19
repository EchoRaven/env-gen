r"""#1203oq: one P0, two opposite orders, sent to the lane that can carry out neither.

`dispatch_failing_checks` files the `business_endpoints_reachable` blocker with a fixed body:

    "registered+implemented endpoints answer 404/405 — the routes are not actually mounted.
     Add them to app/backend/custom_routes.py ..."      -> assignee: backend

`#1202vq` already decided the case where nothing answered at all, and said the true thing in a
NOTICE prepended to the detail -- *"the request raised at the socket, so none of them is
evidence about your code ... Do NOT edit a handler for these. Check the stack is up and re-run
the validation."* It then left the contradicting instruction, the title ("Wire the unreachable
business endpoints") and the owner exactly as they were. `#1139`'s shape: half a fix.

★ THE OWNER IS THE DECIDING PART, AND IT IS MEASURED. Across the corpus's generation logs
`run_validation` was invoked **1,119 times and every one was the verifier**; backend, frontend
and debugger have called it ZERO times. "Check the stack is up and re-run the validation" is
not something the backend lane has ever been able to do -- so the one true sentence in that
task was unactionable by whoever received it.

MEASURED over the runs that HAVE #1202vq's notice: 2 tasks in 2 runs (tiktok-r166 and
tiktok-r190, the most recent full run) carry a detail in which EVERY fragment raised at the
socket. tiktok-r107 has the same shape and is deliberately NOT counted -- it predates the
notice, so the framework had not yet concluded anything for the prose to contradict.

★ AND THE MIXED CASE IS LEFT ALONE. A third r190 task has some endpoints answering and some
not; there the "wire them" prose is still true of the ones that answered, so the rewrite fires
only when the classification covers the whole failure (#647).

★ The rewrite itself is not new: the `docker_up` branch thirty lines below the same
`create_task` call already replaces owner + title + prose for exactly this reason -- "#143 ...
the only lane with docker_build/docker_logs".
"""
from __future__ import annotations

import asyncio
import collections
import glob
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.remediation_dispatcher import RemediationDispatcher  # noqa: E402

_CORPUS = ROOT.parent / "generated"

_ADD = "Add them to app/backend/custom_routes.py"
_NOTICE = "THE APP DID NOT ANSWER"

_TIMED_OUT = "; ".join(
    "%s → TimeoutError: timed out" % e for e in (
        "GET /api/creators/suggested", "POST /api/users/{username}/follow",
        "GET /api/videos", "GET /api/search"))
_MIXED = _TIMED_OUT + "; GET /api/notifications → 405"
_ANSWERED = "; ".join("%s → 405" % e for e in ("GET /api/videos", "GET /api/search"))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


class _WH:
    def __init__(self):
        self.tasks = []

    def list_tasks(self):
        return []

    def create_task(self, **kw):
        self.tasks.append(kw)
        return {"id": "task_%d" % len(self.tasks)}


class _Bus:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


def _dispatch(detail):
    """One `business_endpoints_reachable` failure through the real dispatcher."""
    tmp = tempfile.mkdtemp()
    be = Path(tmp) / "app" / "backend"
    be.mkdir(parents=True, exist_ok=True)
    # a main.py that mounts nothing, so #1006's "already mounted" branch stays quiet and
    # the case under test is #1202vq's
    (be / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n",
                                encoding="utf-8")
    wh = _WH()
    orch = types.SimpleNamespace(
        hubs=types.SimpleNamespace(workhub=wh),
        message_bus=_Bus(),
        _logger=logging.getLogger("test_1203oq"),
        output_dir=tmp,
        _current_milestone_version="1.2.0",
    )
    _run(RemediationDispatcher(orch).dispatch_failing_checks(
        {"checks": [{"name": "business_endpoints_reachable", "status": "fail",
                     "detail": detail}]}))
    return wh.tasks


class WhenNothingAnswered(unittest.TestCase):

    def setUp(self):
        self.tasks = _dispatch(_TIMED_OUT)
        self.assertEqual(len(self.tasks), 1, "no task was filed at all: %r" % self.tasks)
        self.t = self.tasks[0]

    def test_it_goes_to_the_lane_that_holds_run_validation(self):
        self.assertEqual(self.t.get("assignee"), "verifier")

    def test_the_title_carries_the_verdict_the_body_reached(self):
        """#1202ff: "Wire the unreachable business endpoints" is a different claim."""
        self.assertIn("never answered", str(self.t.get("title")))
        self.assertNotIn("Wire the unreachable", str(self.t.get("title")))

    def test_the_body_no_longer_also_says_to_add_them(self):
        self.assertNotIn(_ADD, str(self.t.get("description")))

    def test_the_notice_that_got_it_right_is_still_there(self):
        """The rewrite replaces the instruction, not the evidence or the classification."""
        d = str(self.t.get("description"))
        self.assertIn(_NOTICE, d)
        self.assertIn("TimeoutError", d)

    def test_it_says_what_to_do_and_who_gets_it_next(self):
        """★ The first version asserted `"backend" in description`, which mutation OQ8 walked
        straight through: `app/backend/` appears in the evidence anyway. The assertion has to
        name the SENTENCE, not a token that occurs for another reason."""
        d = str(self.t.get("description"))
        self.assertIn("run_validation", d)
        self.assertIn("goes to the backend lane", d,
                      "nothing tells the verifier where the work goes once the app is up: %r"
                      % d)


class WhenOnlySomeAnswered(unittest.TestCase):
    """#647: the rewrite fires only when the classification covers the whole failure."""

    def test_a_mixed_detail_keeps_the_wire_them_instruction_and_the_backend_owner(self):
        tasks = _dispatch(_MIXED)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].get("assignee"), "backend")
        self.assertIn(_ADD, str(tasks[0].get("description")))
        self.assertIn("Wire the unreachable", str(tasks[0].get("title")))

    def test_a_detail_with_no_transport_failure_is_untouched(self):
        tasks = _dispatch(_ANSWERED)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].get("assignee"), "backend")
        self.assertIn(_ADD, str(tasks[0].get("description")))
        self.assertNotIn(_NOTICE, str(tasks[0].get("description")))

    def test_an_empty_detail_is_untouched(self):
        tasks = _dispatch("")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].get("assignee"), "backend")
        self.assertIn(_ADD, str(tasks[0].get("description")))


class NoDispatchedBodyHoldsBothOrders(unittest.TestCase):
    """★ The first version of this class asserted the two sentences never coexist AT ALL, and
    the mixed case failed it -- correctly. The assertion was stronger than the design: when
    only some endpoints went unanswered, the notice is scoped to "THESE" and the "wire them"
    prose is still true of the ones that answered, which is the carve-out #647 asked for. The
    property is about the case where the notice covers the WHOLE failure; the mixed case is
    asserted separately, as a documented exception rather than a hole."""

    def test_they_never_coexist_when_nothing_answered(self):
        for label, detail in (("all gone", _TIMED_OUT), ("answered", _ANSWERED)):
            with self.subTest(detail=label):
                d = str(_dispatch(detail)[0].get("description"))
                self.assertFalse(_NOTICE in d and _ADD in d,
                                 "one task says both 'do NOT edit a handler for these' and "
                                 "'add them to custom_routes.py': %r" % d[:300])

    def test_in_the_mixed_case_both_are_present_and_both_are_true(self):
        """Deliberate: the notice says "THESE" and names only the ones that raised, so the
        other instruction is about the endpoints that did answer."""
        d = str(_dispatch(_MIXED)[0].get("description"))
        self.assertIn(_NOTICE, d)
        self.assertIn(_ADD, d)
        self.assertIn("these", d.split(_NOTICE)[1][:120].lower(),
                      "the notice has to scope itself, or the two really do contradict: %r"
                      % d[:300])


class TheClassificationDoesNotOutliveItsCheck(unittest.TestCase):
    """★ Mutation OQ9: a flag computed inside the loop and READ at the dispatch is only right
    if it is reset per check. Made observable by dispatching twice on ONE orchestrator, with
    the milestone advanced so the storm guard does not swallow the second call: an all-gone
    failure first, an answered one second. A sticky flag rewrites the second one too."""

    def test_an_earlier_all_gone_failure_does_not_rewrite_a_later_answered_one(self):
        tmp = tempfile.mkdtemp()
        be = Path(tmp) / "app" / "backend"
        be.mkdir(parents=True, exist_ok=True)
        (be / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n",
                                    encoding="utf-8")
        wh = _WH()
        orch = types.SimpleNamespace(
            hubs=types.SimpleNamespace(workhub=wh), message_bus=_Bus(),
            _logger=logging.getLogger("test_1203oq"), output_dir=tmp,
            _current_milestone_version="1.2.0")
        rd = RemediationDispatcher(orch)
        _run(rd.dispatch_failing_checks({"checks": [
            {"name": "business_endpoints_reachable", "status": "fail", "detail": _TIMED_OUT}]}))
        orch._current_milestone_version = "1.3.0"
        _run(rd.dispatch_failing_checks({"checks": [
            {"name": "business_endpoints_reachable", "status": "fail", "detail": _ANSWERED}]}))
        self.assertEqual(len(wh.tasks), 2, "the second dispatch was swallowed: %r"
                         % [t.get("title") for t in wh.tasks])
        self.assertEqual(wh.tasks[0].get("assignee"), "verifier")
        self.assertEqual(wh.tasks[1].get("assignee"), "backend",
                         "the first failure's classification outlived its own check")
        self.assertIn(_ADD, str(wh.tasks[1].get("description")))


class WhatTheCorpusSays(unittest.TestCase):
    _PRE = "The `business_endpoints_reachable` validation check FAILED: "

    def setUp(self):
        if not _CORPUS.is_dir():
            self.skipTest("no corpus on this disk")

    def test_the_measured_tasks_are_the_two_runs_with_the_notice(self):
        from multi_agent.runtime.chain_executor import is_transport_failure_1202od as gone
        allgone, mixed, seen = collections.Counter(), collections.Counter(), 0
        for f in sorted(glob.glob(str(_CORPUS / "*" / "shared" / "hubs"
                                      / "workhub_tasks.json"))):
            run = Path(f).parents[2].name
            try:
                d = json.loads(Path(f).read_text(encoding="utf-8"))
            except Exception:
                continue
            seen += 1
            for k, t in d.items():
                if k == "_meta" or not isinstance(t, dict):
                    continue
                desc = str(t.get("description") or "")
                if not desc.startswith(self._PRE) or _ADD not in desc:
                    continue
                if _NOTICE not in desc:
                    continue          # pre-#1202vq: nothing had been concluded yet
                frags = [x.strip() for x
                         in desc[len(self._PRE):].split("\n")[0].split(" || ")[-1].split(";")
                         if x.strip()]
                g = [x for x in frags if gone({"status": None, "error": x})]
                if frags and len(g) == len(frags):
                    allgone[run] += 1
                elif g:
                    mixed[run] += 1
        # ★ ON4's lesson: a ratchet that looked at nothing SKIPS, and a skip passes.
        self.assertGreater(seen, 90, "only %d task ledgers read" % seen)
        self.assertEqual(dict(allgone), {"tiktok-web-r166": 1, "tiktok-web-r190": 1})
        self.assertEqual(dict(mixed), {"tiktok-web-r190": 1})

    def test_only_the_verifier_has_ever_run_a_validation(self):
        """The claim the re-route rests on. Measured from the run logs, not from the config:
        a lane could in principle be granted the tool anywhere."""
        logs = sorted(glob.glob(str(_CORPUS / "*" / "logs" / "generation_*.log")))
        if not logs:
            self.skipTest("no generation logs on this disk")
        try:
            out = subprocess.run(
                ["grep", "-ohE", r"\[(backend|frontend|verifier|debugger)\][^\n]{0,40}"
                                 r"(🔧|✅) run_validation"] + logs,
                capture_output=True, text=True, timeout=600)
        except Exception as exc:
            self.skipTest("grep unavailable: %s" % exc)
        by = collections.Counter(re.findall(r"\[(backend|frontend|verifier|debugger)\]",
                                           out.stdout))
        self.assertGreater(sum(by.values()), 900,
                           "only %d run_validation invocations found -- the scan stopped "
                           "working and a verdict from it would be about nothing" % sum(by.values()))
        self.assertEqual([a for a in by if a != "verifier"], [],
                         "a lane other than the verifier has run a validation: %r" % dict(by))


if __name__ == "__main__":
    unittest.main()
