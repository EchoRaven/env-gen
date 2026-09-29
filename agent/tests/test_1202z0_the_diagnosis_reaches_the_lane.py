r"""#1202z0: #1202jx's diagnosis reaches a surface the lane can read.

#1202lc fixed WHEN this diagnostic speaks -- it sat past ten earlier `return`s and could
only be reached once the gate was GREEN, which is precisely when the problem it diagnoses is
already gone. Nobody fixed WHO hears it. Everything it does is `self._logger.error`, and a
lane reads WorkHub, EventHub and its own files, not the orchestrator's log.

★ r140, measured on the live run: the framework diagnosed this contradiction THREE times and
delivered it to nobody.
  * `#1202jx` once at 01:54:34 -- naming the screen, the route and the endpoints
  * `#1202vt` 39 times from 02:04 -- naming the table, the shape and the way out
  * business_chain at 01:59:54 -- `GET /api/feed -> 200 (expected [401]; DENIAL-PROBE got
    success)`
Grep of every file under `shared/hubs/` for `1202jx`, `1202vt`, `SHAPE OVERRODE` and
`LOGGED-OUT SCREEN NEEDS AUTH`: ZERO hits.

So the lane saw only the 401. It appended to `_FW_PUBLIC_API_1202KH` from custom_routes.py;
`deliverability_guard_tampering` blocked delivery for ~20 minutes over two episodes; the lane
then REMOVED the workaround and `GET /api/feed` went back to 401 for anonymous callers
(curl against the live stack: 401, while `/health` answered 200), so `fyp_feed_logged_out`
failed and `deliverability_ui_flow_failed` blocked it instead. Neither move wins. r137 died
in this state at 81 minutes and $190.

★ A TASK, NOT A BLOCKER. The same contradiction is present in 54 of the 179 corpus runs
(30%), many of which delivered, so blocking would stop three runs in ten for something often
survivable. That is why #1202vt is announce-only, and this keeps that judgement: it changes
the audience, not the verdict.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.orchestrator import Orchestrator  # noqa: E402


class _WH:
    def __init__(self, existing=None):
        self.tasks = list(existing or [])
        self.created = []

    def list_tasks(self):
        return self.tasks

    def create_task(self, **kw):
        self.created.append(kw)
        return {"id": "task_x", **kw}


class _Hubs:
    def __init__(self, wh):
        self.workhub = wh


def _orch(wh):
    o = Orchestrator.__new__(Orchestrator)
    o.hubs = _Hubs(wh)
    return o


_FOUND = [{"screen": "fyp_feed_logged_out", "route": "/",
           "auth_endpoints": ["GET /api/feed", "GET /api/me"]}]


def test_a_task_is_filed_for_the_backend():
    wh = _WH()
    _orch(wh)._file_logged_out_auth_task_1202z0(_FOUND)
    assert len(wh.created) == 1, wh.created
    assert wh.created[0]["assignee"] == "backend"


def test_the_task_names_the_screen_the_route_and_the_endpoints():
    """The whole point: a lane reading only the 401 cannot find any of these."""
    wh = _WH()
    _orch(wh)._file_logged_out_auth_task_1202z0(_FOUND)
    d = wh.created[0]["description"]
    assert "fyp_feed_logged_out" in d and "GET /api/feed" in d and "GET /api/me" in d, d


def test_the_task_names_the_table_write_not_only_auth_required():
    """★ The half the lane cannot see. r140's lane DID set `auth_required: false` and was
    demoted anyway, because the table carried no `visibility` and the shape decided."""
    wh = _WH()
    _orch(wh)._file_logged_out_auth_task_1202z0(_FOUND)
    d = wh.created[0]["description"]
    assert "metadata.visibility" in d, d
    assert "owner_scoped_reads" in d, "the flag that actually filters must be named"
    assert "is NOT enough" in d, "must say why auth_required alone failed"


def test_the_task_names_both_ways_out_and_rules_out_the_third():
    wh = _WH()
    _orch(wh)._file_logged_out_auth_task_1202z0(_FOUND)
    d = wh.created[0]["description"]
    assert "(a)" in d and "(b)" in d
    assert "guard_tampering" in d, "the move the lane actually made must be ruled out"


def test_it_does_not_block():
    """★ 30% of corpus runs carry this shape and many delivered. P0 would put it ahead of
    checks that genuinely stop delivery."""
    wh = _WH()
    _orch(wh)._file_logged_out_auth_task_1202z0(_FOUND)
    assert wh.created[0].get("priority") == "P1", wh.created[0].get("priority")


def test_an_open_task_is_not_cloned():
    """#794: re-wake, do not file r130's 13th clone."""
    wh = _WH([{"title": "Logged-out screen calls an auth-required endpoint (1 screen(s))",
               "status": "in_progress"}])
    _orch(wh)._file_logged_out_auth_task_1202z0(_FOUND)
    assert wh.created == [], wh.created


def test_a_closed_task_does_not_suppress_a_new_one():
    wh = _WH([{"title": "Logged-out screen calls an auth-required endpoint (1 screen(s))",
               "status": "completed"}])
    _orch(wh)._file_logged_out_auth_task_1202z0(_FOUND)
    assert len(wh.created) == 1


def test_no_findings_files_nothing():
    wh = _WH()
    _orch(wh)._file_logged_out_auth_task_1202z0([])
    assert wh.created == []


def test_a_missing_workhub_is_not_a_crash():
    o = Orchestrator.__new__(Orchestrator)
    o.hubs = _Hubs(None)
    o._file_logged_out_auth_task_1202z0(_FOUND)          # must not raise


def test_a_listing_that_raises_still_files():
    class _Bad(_WH):
        def list_tasks(self):
            raise RuntimeError("hub down")
    wh = _Bad()
    _orch(wh)._file_logged_out_auth_task_1202z0(_FOUND)
    assert len(wh.created) == 1, "a dedupe fault must not swallow the task"


def test_the_caller_actually_calls_it():
    """★ I have tested a helper and not its caller four times in one day. Three predicates:
    the call is inside the reporting method, it is inside the try (so a hub fault is caught
    by the same handler that guards the rest), and it is NOT behind the `len(found) > 6`
    branch -- which would file a task only for the runs with seven or more screens."""
    import ast
    import inspect
    import multi_agent.orchestrator as O

    src = inspect.getsource(O.Orchestrator._report_logged_out_auth_screens_1202lc)
    tree = ast.parse(src.lstrip())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))

    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "_file_logged_out_auth_task_1202z0"]
    assert len(calls) == 1, "called %d times" % len(calls)

    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
    assert any(any(c is call for call in calls for c in ast.walk(t)) for t in tries), (
        "the call must sit inside the try that guards this method")

    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            assert not any(c in ast.walk(node) for c in calls), (
                "the call must not sit behind a branch")


def test_the_existing_log_lines_are_untouched():
    """The log is still the record; this adds a reader, it does not move the message."""
    import inspect
    import multi_agent.orchestrator as O
    src = inspect.getsource(O.Orchestrator._report_logged_out_auth_screens_1202lc)
    assert "#1202jx LOGGED-OUT SCREEN NEEDS AUTH" in src
    assert src.count("self._logger.error") >= 2
