r"""#1203rh -- a criterion may not infer a tool call's ARGUMENTS from the fact that the tool exists.

`verify_1018.py`'s `p2` check asks whether `#1203p2`'s recorder ever reported the no-op that
`#1203b0` is about: a `register_ui_page` re-registration that omits `apis_used`, keeps the
stored list, and returns success -- which is how r143's lane concluded it had fixed a
`page_apis_understated` blocker 19 times over.

Its FALSIFIED arm read:

    elif _p2_blocked and "registryhub_register_ui_page" in logtext:

The second conjunct was meant to establish "pages were re-registered". It cannot. That string
is in the log because the tool is OFFERED: a lane's tool set renders as
`registryhub_register_ui_page(name,path,route,component)` -- 23 times in instagram-core-di --
and the `Tool calls:` summary prints parameter NAMES rather than values too.

MEASURED, WITH THE TWO PRINTER FORMATS SEPARATED FIRST (#572: blending them is how a count
like this goes wrong) -- the modern printer renders `name=... path=...` and shows at most
`name,path,status`, so `apis_used` appears in **0 of its 6913** invocation lines across 92 logs
(2026-08-24 onward, both post-patch runs among them). The legacy printer rendered
`args=['status','name','path']`, an actual list of the parameters passed, and `apis_used` is
absent from all **5662** of those as well -- but that era ended 2026-07-29, three months before
`#1203p2` existed, so it cannot speak to the recorder. For every run this criterion can be
asked about, no log can say whether the argument was passed.

THE RECORDER ITSELF IS FINE -- which is why only the criterion changed. `test_the_recorder_
actually_fires_when_its_precondition_holds` drives the real tool over a real RegistryHub and
WorkHub, and gets both halves: #1203b0's note in `ToolResult.data` and the #1203p2 log line.
Its silence in the two post-patch runs is the no-op not happening, not the recorder breaking:
all 8 instagram pages ended with a NON-EMPTY `apis_used`, and the blocker failed ONCE there
with one remediation dispatch.

So FALSIFIED now needs an observable that implies failure -- #1201's announcement that the
recorder did not run -- and everything else is N-A WITH THE BLIND SPOT NAMED. #1203rd's rule
(a false FALSIFIED sends a reader after a defect that is not there), and the same shape as
#1203rg one marker earlier in this session.
"""
import asyncio
import importlib.util
import json
import logging
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_1018.py"

MENU = ("17:20:39 [I] Agent.Frontend Engineer Agent: [frontend] [deliver] Tool calls: "
        "registryhub_register_ui_page(name,path,route,component), "
        "registryhub_register_ui_page(name,path,route,component)\n")
INVOKED = ("17:20:39 [I] Agent.Frontend Engineer Agent: [frontend] "
           "\U0001f527 registryhub_register_ui_page: path=frontend/src/pages/Home.jsx "
           "name=home_feed_page\n")
BLOCKED = ("17:58:02 [W] Orchestrator: Framework deliver declined: delivery gate has 1 failed "
           "check(s): ['deliverability_page_apis_understated']\n")
RECORDED = ("17:20:40 [I] tools.hub_tools: #1203p2 register_ui_page(home_feed_page) omitted "
            "`apis_used` for the 1st time; 2 existing entry(ies) kept, so a "
            "`page_apis_understated` blocker is unchanged by this call\n")
BROKE = ("17:20:40 [W] multi_agent.runtime.message_format: #1201 recording that a "
         "re-registration omitted `apis_used` did NOT run this process: ImportError: x. It is "
         "guarded so it cannot break the run.\n")


def _p2(logtext):
    """Run the real `main()` over a synthetic run and return its `p2` verdict."""
    spec = importlib.util.spec_from_file_location("v1018_1203rh", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    d = Path(tempfile.mkdtemp())
    (d / "shared" / "hubs").mkdir(parents=True)
    lg = d / "run.log"
    # The script refuses a log whose header names a DIFFERENT run -- measured after a glob
    # handed one run's log to another and five criteria answered confidently about a run the
    # log never watched. So the synthetic log has to carry the real header, or every verdict
    # here comes back "no run log given" and the tests pass for the wrong reason (they did).
    lg.write_text("Output directory: %s\n%s" % (d.resolve(), logtext), encoding="utf-8")
    got = []
    m.say = lambda t, v, det="": got.append((t, v, det))
    try:
        m.main(["verify_1018.py", str(d), "--log", str(lg)])
    except SystemExit:
        pass
    except Exception:
        # `main()` ends in a summary the captured `say` does not feed; p2 is recorded earlier.
        pass
    return next(((v, det) for t, v, det in got if t == "p2"), (None, ""))


# ------------------------------------------------------------------ the bug

def test_the_tool_being_offered_is_not_evidence_that_an_argument_was_omitted():
    """THE BUG. The menu line alone used to make this FALSIFIED on every blocked run."""
    verdict, detail = _p2(MENU + BLOCKED)
    assert verdict == "N-A", (
        "a tool MENU line plus the blocker came back %s: %s" % (verdict, detail))
    assert "6913" in detail, "say WHY the log cannot answer, with the number"


def test_a_real_invocation_line_is_not_evidence_either():
    """The invocation line prints at most name/path/status -- never `apis_used`."""
    verdict, detail = _p2(INVOKED + BLOCKED)
    assert verdict == "N-A", (verdict, detail)


def test_the_na_detail_still_points_at_the_live_blocker():
    """N-A must not be silence: when the blocker IS present, name the surviving explanation."""
    _verdict, detail = _p2(MENU + BLOCKED)
    assert "understatement" in detail, (
        "with the blocker present the reader needs the alternative cause, not just N-A")
    _v2, d2 = _p2(MENU)
    assert "understatement" not in d2, (
        "without the blocker there is nothing to explain, so do not assert a cause")


# ------------------------------------------------------------------ what must still work

def test_a_recorded_line_confirms():
    """COUNTER-PROOF: narrowing must not cost the CONFIRMED the ticket was written to get."""
    verdict, detail = _p2(RECORDED + BLOCKED)
    assert verdict == "CONFIRMED", (verdict, detail)
    assert "1 omission(s)" in detail
    assert "changed nothing" in detail, "with the blocker present, say these are those calls"


def test_the_recorder_announcing_it_did_not_run_is_the_falsifier():
    """FALSIFIED keeps a real trigger: #1201 saying the recorder is OFF. 0 corpus-wide today."""
    verdict, detail = _p2(BROKE + BLOCKED)
    assert verdict == "FALSIFIED", (verdict, detail)
    assert "did NOT run" in detail


def test_an_unrelated_1201_line_must_not_falsify():
    """The falsifier matches the SITE's sentence, not the `#1201` marker.

    `#1201` is a shared channel: 595 lines across 67 logs, almost none of them about this
    recorder. Matching the marker would turn every run that reports any guarded mechanism
    being off into a falsification of this one -- the mistake this session made twice while
    counting an emitter by its marker instead of its words.
    """
    other = ("17:20:40 [W] multi_agent.runtime.message_format: #1201 recording that a design "
             "system was adopted did NOT run this process: KeyError: x.\n")
    verdict, detail = _p2(other + MENU + BLOCKED)
    assert verdict == "N-A", (
        "an unrelated #1201 announcement must not falsify p2: %s / %s" % (verdict, detail))


# ------------------------------------------------------------------ the recorder is not broken

def test_the_recorder_actually_fires_when_its_precondition_holds():
    """Drive the REAL tool over a REAL RegistryHub/WorkHub: register with `apis_used`, then
    re-register omitting it. Both halves must appear -- #1203b0's note (which reaches the
    model) and #1203p2's log line (which reaches the operator).

    This is the evidence that the recorder's silence across both post-patch runs is the
    no-op not happening, rather than the recorder failing. Production has never shown the
    line, so without this the criterion would be asserting something nothing had checked.
    """
    from env_generator.llm_generator.tools import hub_tools
    from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub
    from env_generator.llm_generator.multi_agent.runtime.hubs.workhub.service import WorkHub

    d = Path(tempfile.mkdtemp())
    wh, rh = WorkHub(str(d)), RegistryHub(str(d))
    wh.attach_registryhub(rh)

    class _Hubs:
        workhub = wh
        registryhub = rh

    cls = next(c for c in vars(hub_tools).values()
               if isinstance(c, type)
               and getattr(c, "NAME", "") == "registryhub_register_ui_page")
    tool = cls.__new__(cls)
    tool._hubs = _Hubs()
    tool._agent_id = "frontend"
    tool._agent = None

    seen = []

    class _Cap(logging.Handler):
        def emit(self, rec):
            seen.append(rec.getMessage())

    cap = _Cap()
    lg = logging.getLogger(hub_tools.__name__)
    lg.addHandler(cap)
    old = lg.level
    lg.setLevel(logging.INFO)
    try:
        async def _go():
            await tool._run(name="home_feed_page", path="frontend/src/pages/Home.jsx",
                            apis_used=["GET /api/feed", "POST /api/posts"])
            return await tool._run(name="home_feed_page",
                                   path="frontend/src/pages/Home.jsx")
        res = asyncio.new_event_loop().run_until_complete(_go())
    finally:
        lg.removeHandler(cap)
        lg.setLevel(old)

    assert "_apis_used_unchanged_1203b0" in (res.data or {}), (
        "#1203b0's note must ride in ToolResult.data -- that is the half the MODEL reads")
    assert any("#1203p2" in m for m in seen), (
        "#1203p2's line must be logged -- the half the OPERATOR reads. Emitted: %r" % (seen,))
    assert any("2 existing entry(ies) kept" in m for m in seen), (
        "the line carries the COUNT of what was kept (#1203qd); got %r" % (seen,))


def test_the_recorders_logger_is_not_suppressed_by_the_run_configuration():
    """The line can only reach the run log if `main.py` does not mute that logger.

    Read from the source list rather than restated here, so adding `tools` to it turns this
    red instead of leaving a criterion that can never be satisfied in production.
    """
    import ast as _ast
    src = (ROOT / "agent/env_generator/llm_generator/main.py").read_text(encoding="utf-8")
    muted = set()
    for node in _ast.walk(_ast.parse(src)):
        if (isinstance(node, _ast.For) and isinstance(node.iter, _ast.List)
                and all(isinstance(e, _ast.Constant) for e in node.iter.elts)):
            vals = [e.value for e in node.iter.elts]
            if "httpx" in vals:
                muted |= set(vals)
    assert muted, "could not find the noisy-logger suppression list in main.py"
    for name in ("tools", "tools.hub_tools", "env_generator"):
        assert name not in muted, (
            "%r is muted to WARNING, so #1203p2's INFO line can never reach a run log" % name)
