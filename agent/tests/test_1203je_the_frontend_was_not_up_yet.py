r"""#1203je: one of the two browser walks waited for the frontend; this one did not.

`test_user_runner._wait_frontend_ready` exists for exactly this and its docstring names
the harm: "the delivery flow restarts the compose stack per milestone, so the browser walk
can fire while the FRONTEND container is DOWN / rebuilding → every goto raises
net::ERR_CONNECTION_REFUSED → ... a FALSE 'unusable' that escape-ships a HEALTHY app
(outlook run-28 v1.2.0, live)". `_ui_auth_flow` never called it.

★ LARGEST ui_flow FAILURE CAUSE IN THE CORPUS. Ranking failing `ui_flows` notes since
2026-09-15 by normalised text: `Page.goto: net::ERR_CONNECTION_REFUSED at .../login` is
first with 32 records across 25 runs, ahead of "submit sent NO /auth request" (28 / 22)
and the #1126b landing check (17 / 9). It reaches the lane as `UI login: Error: ...` inside
`broken`, which makes the verdict ISSUES — a verdict about the APP.

★ NOT A PORT BUG, which #1136 and #1203ia make the first thing to rule out: in every
modern run carrying one of these notes the port in the note EQUALS the host port
`frontend` publishes in that run's own compose (r176 8053:3000, r126 8006:3000,
r127/r129/r130/r131 8009:3000), and in 34 of the 52 reports the API half had already
walked, so the stack was up and the frontend specifically was not.

★★ THE FIX IS INCOMPLETE WITHOUT THE VERDICT HALF. `_ui_broken` is derived from `flows`,
so skipping the walk empties it and an unrun walk looks like a passing one. Over the whole
corpus `ran: False` occurs twice, both July, and BOTH were recorded PASS. Turning 32
records into `ran: False` without touching the ladder would trade a FALSE ISSUES for a
FALSE PASS — #1202xc's shape, which was withdrawn for exactly that.
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.test_user_validation as TUV   # noqa: E402
import multi_agent.runtime.test_user_runner as TUR       # noqa: E402


def _flow_fn():
    src = inspect.getsource(TUV)
    for n in ast.walk(ast.parse(src)):
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "_ui_auth_flow"):
            return n
    raise AssertionError("_ui_auth_flow is gone")


def test_the_owner_still_exists_and_is_not_copied():
    """#1032: the readiness rule has ONE owner. If this module ever grows its own copy the
    two will drift, which is how #1203ip's two input-shape lists came to disagree."""
    assert callable(getattr(TUR, "_wait_frontend_ready", None)), \
        "test_user_runner._wait_frontend_ready is gone — the walk now has no owner to reuse"
    assert not hasattr(TUV, "_wait_frontend_ready"), \
        "test_user_validation defined its own readiness waiter instead of reusing the owner"


def test_the_walk_waits_before_it_navigates():
    """★ THE TICKET, located structurally: the readiness call must come BEFORE the route
    loop's first `page.goto`, because afterwards is exactly the ERR_CONNECTION_REFUSED
    the 32 records already contain."""
    fn = _flow_fn()
    waits = [n.lineno for n in ast.walk(fn)
             if isinstance(n, ast.Call)
             and (getattr(n.func, "id", "") or getattr(n.func, "attr", "")
                  ).startswith("_wfr_1203je")]
    assert waits, "_ui_auth_flow never waits for the frontend"
    loops = [n for n in ast.walk(fn) if isinstance(n, ast.For)]
    gotos = [c.lineno for lp in loops for c in ast.walk(lp)
             if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "goto"]
    assert gotos, "the route loop no longer navigates — re-read this test"
    assert min(waits) < min(gotos), (
        "the readiness wait at %s comes after the first navigation at %s" % (waits, gotos))


def test_a_frontend_that_never_serves_does_not_produce_flow_failures():
    """The honest treatment, and the owner's own distinction (#159): only NEVER SERVED
    skips. The branch must return `ran: False` and NO flows, so nothing lands in `broken`
    — a served-but-blank app keeps being caught, because `_wait_frontend_ready` returns
    True once anything answered."""
    fn = _flow_fn()
    rets = [n for n in ast.walk(fn) if isinstance(n, ast.Return)
            and isinstance(n.value, ast.Dict)
            and any(getattr(k, "value", None) == "ran" for k in n.value.keys)]
    jes = [n for n in rets if "1203je" in ast.dump(n)]
    assert jes, "the never-served branch does not return a `ran` dict"
    for n in jes:
        vals = dict(zip([getattr(k, "value", None) for k in n.value.keys], n.value.values))
        assert getattr(vals.get("ran"), "value", None) is False, ast.dump(n)
        assert "flows" not in vals, "the skip branch still publishes flows: %s" % ast.dump(n)


def test_the_import_cannot_leave_the_name_unbound():
    """#1203iu's lesson, in the same file: an ImportError that leaves the helper undefined
    would raise NameError inside the walk, and the surrounding handler would turn a
    framework fault into a flow failure about the app."""
    fn = _flow_fn()
    handlers = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)
                and any(isinstance(s, ast.Assign)
                        and getattr(s.targets[0], "id", "") == "_wfr_1203je"
                        for s in ast.walk(h))]
    assert handlers, "a failed import leaves `_wfr_1203je` unbound"
    for h in handlers:
        for s in ast.walk(h):
            if isinstance(s, ast.Assign) and getattr(s.targets[0], "id", "") == "_wfr_1203je":
                assert getattr(s.value, "value", "x") is None, ast.dump(s)


# ---------------------------------------------------------------- the verdict half

def _run(monkeypatch, tmp_path, steps, ui_flows_obj, mcp_complete=True):
    (tmp_path / "docker").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(TUV, "_http", lambda *a, **k: {"status": 200, "json": {}},
                        raising=False)
    monkeypatch.setattr(TUV, "_backend_host_port", lambda *a, **k: 8080, raising=False)
    monkeypatch.setattr(TUV, "_api_test_user",
                        lambda *a, **k: {"steps": list(steps), "actor": "alpha"})
    monkeypatch.setattr(TUV, "_mcp_test_user",
                        lambda *a, **k: {"complete": mcp_complete, "tools_found": 1})

    async def _flows(_base):
        return dict(ui_flows_obj)
    monkeypatch.setattr(TUV, "_ui_auth_flow", _flows)
    import multi_agent.runtime.validation_runner as VR
    monkeypatch.setattr(VR, "_service_host_port", lambda *a, **k: 8021, raising=False)
    return TUV.run_test_user_validation(tmp_path, [{"path": "/api/videos"}], version="1.1.0")


_OK = [{"action": "create videos", "method": "POST", "path": "/api/videos",
        "status": 201, "ok": True, "kind": "ok", "note": "author_id=10"}]
_UI_OK = {"ran": True, "flows": [{"flow": "signup", "ok": True, "note": ""},
                                 {"flow": "login", "ok": True, "note": ""}]}
_UI_SKIPPED = {"ran": False, "reason": "frontend at http://localhost:8033 never served "
                                       "within the readiness budget (#1203je)"}


def test_an_undriven_ui_is_not_a_pass(monkeypatch, tmp_path):
    """★ THE SILENCE TRADE, closed. A walked API journey plus a complete MCP surface used
    to be enough for PASS while no browser flow ran at all."""
    s = _run(monkeypatch, tmp_path, _OK, _UI_SKIPPED)["summary"]
    assert s["ui_walk_ran_1203je"] is False
    assert s["verdict"] != "PASS", "the UI was never driven and the report says PASS"
    assert s["verdict"] == "NOT_WALKED", s["verdict"]


def test_a_driven_ui_still_passes(monkeypatch, tmp_path):
    """WITHOUT THIS THE FIX IS A REGRESSION."""
    s = _run(monkeypatch, tmp_path, _OK, _UI_OK)["summary"]
    assert s["ui_walk_ran_1203je"] is True and s["verdict"] == "PASS", s


def test_a_real_ui_failure_still_outranks_the_skip(monkeypatch, tmp_path):
    """An absence of evidence must not displace evidence somebody collected — the same
    ordering #1203jc's branch depends on."""
    ui = {"ran": True, "flows": [{"flow": "signup", "ok": False, "note": "no handler"}]}
    s = _run(monkeypatch, tmp_path, _OK, ui)["summary"]
    assert s["verdict"] == "ISSUES", s["verdict"]


def test_the_cause_slot_names_which_half_is_missing(monkeypatch, tmp_path):
    """Two different facts: an empty API journey is a CONTRACT fact about the milestone, a
    UI walk that did not run is an ENVIRONMENT fact about the moment. The reason travels
    through the SUMMARY because that is all `describe_non_pass_1038` receives."""
    r = _run(monkeypatch, tmp_path, _OK, _UI_SKIPPED)
    msg = TUV.describe_non_pass_1038(r["summary"], r.get("mcp"))
    assert "UI WALK DID NOT RUN" in msg.upper(), msg
    assert "never served" in msg, "the recorded reason did not reach the cause slot: %s" % msg
    assert "API JOURNEY NOT WALKED" not in msg.upper(), (
        "it blamed the API half too, and that half DID walk: %s" % msg)


def test_a_driven_ui_is_not_reported_as_skipped(monkeypatch, tmp_path):
    """The equivalence the previous test could hide."""
    r = _run(monkeypatch, tmp_path, _OK, _UI_OK)
    msg = TUV.describe_non_pass_1038(r["summary"], r.get("mcp"))
    assert "UI WALK DID NOT RUN" not in msg.upper(), msg
