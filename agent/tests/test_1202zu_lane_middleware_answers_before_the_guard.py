r"""#1202zu: a lane can answer before the framework's auth guard, and nothing said so.

`framework_guard_tampering_1202lj` BLOCKS a lane that edits `app.router.routes` or names
`_FW_PUBLIC_API_1202KH` / `_FW_PUBLIC_RE_1202KH` / `_fw_contract_public_1202kh`. A lane-installed
`@app.middleware("http")` does neither and still gets in front of `_framework_auth_guard`:
Starlette builds the stack in reverse, so middleware added later runs OUTER, and one that returns
a Response without awaiting `call_next` answers with the guard never consulted.

r139 is the worked example and its own docstring shows it knew which doors were watched:

    "install a lane-owned middleware that answers only anonymous/public GET requests for this
     exact path. It does not mutate framework route tables or guard allow-lists"

On the still-running r139 stack `GET /api/videos/feed/1` answers 200 with a real row while
`GET /api/me` answers 401, and the guard's public list holds only `('GET', '/api/search')`.

MEASURED over the corpus with an AST, because "returns a Response without `call_next`" is the
whole distinction: 43 lane-installed middlewares in 26 runs, of which **22 short-circuit across
17 runs** — r140 `_creator_feed_public_http_interceptor`, r139 `_public_feed_edge_handler`, r136
`_init_tenant_control_plane_middleware`, r124 `_auth_resilience_guard`, r108
`_tiktok_public_read_short_circuit`. Six of the 22 intercept an auth path, in 4 runs. The other
21 always await `call_next` and are not reported. The detector reproduces those three numbers
exactly, which is how it was validated before any of this was written.

★ REPORTED, NOT BLOCKED, and the harm test is the reason. On r139 the intercepted
`POST /auth/login` and `POST /api/auth/login` REFUSE a wrong password — 401 `invalid
credentials`, identical to the un-intercepted r135 — because the lane's handler delegates to the
framework's own `login()`. The mechanism is invisible, not yet harmful. Adding it to
`deliverability_guard_tampering` would block the shape in 17 runs while the pressure that
produces it, a contract-public feed answering 401, is exactly what #1202zn and #1202zr removed.
Blocking a lane for the only move that works is r140's M1.1 again (#1202z0's reasoning).
"""
import ast
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.backend_audit import (  # noqa: E402
    lane_installed_middleware_1202zu as _detect)
import multi_agent.runtime.heal_pipeline as HP  # noqa: E402

_SHORT_CIRCUIT = '''
from fastapi.responses import JSONResponse
@app.middleware("http")
async def _public_feed_edge(request, call_next):
    if request.url.path == "/api/videos/feed":
        return JSONResponse({"items": []})
    return await call_next(request)
'''

_AUTH_SHORT_CIRCUIT = '''
from fastapi.responses import JSONResponse
@app.middleware("http")
async def _auth_edge(request, call_next):
    if request.url.path in ("/auth/login", "/api/auth/login"):
        return JSONResponse({"token": "x"})
    return await call_next(request)
'''

_PASSTHROUGH = '''
@app.middleware("http")
async def _timing(request, call_next):
    resp = await call_next(request)
    resp.headers["x-ms"] = "1"
    return resp
'''


_CONDITIONAL = '''
from fastapi.responses import JSONResponse
@app.middleware("http")
async def _cond_edge(request, call_next):
    if request.url.path == "/api/videos/feed":
        return JSONResponse({"items": []}) if request.method == "GET" else await call_next(request)
    return await call_next(request)
'''


def _tree(tmp_path, **files):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "main.py").write_text("app = 1\n", encoding="utf-8")
    for name, src in files.items():
        (be / name).write_text(src, encoding="utf-8")
    return be


# ── the detector ──────────────────────────────────────────────────────────────────

def test_a_short_circuiting_middleware_is_found(tmp_path):
    hits = _detect(_tree(tmp_path, **{"custom_routes.py": _SHORT_CIRCUIT}))
    assert len(hits) == 1, hits
    assert hits[0]["func"] == "_public_feed_edge"
    assert "/api/videos/feed" in hits[0]["intercepts"]


def test_a_passthrough_middleware_is_not_reported(tmp_path):
    """★ The whole distinction. 21 of the corpus's 43 always await `call_next`."""
    assert _detect(_tree(tmp_path, **{"custom_routes.py": _PASSTHROUGH})) == []


def test_an_auth_path_is_marked(tmp_path):
    hits = _detect(_tree(tmp_path, **{"custom_routes.py": _AUTH_SHORT_CIRCUIT}))
    assert hits[0]["auth_paths"], hits
    assert hits[0]["intercepts"][0] in ("/auth/login", "/api/auth/login")


def test_main_py_is_not_scanned(tmp_path):
    """main.py IS the framework's guard; reporting it would report the baseline."""
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "main.py").write_text(_SHORT_CIRCUIT, encoding="utf-8")
    assert _detect(be) == []


def test_any_lane_file_is_scanned_not_just_custom_routes(tmp_path):
    """`framework_guard_tampering_1202lj` looks at two fixed names; a middleware can be
    installed from any module the app imports."""
    hits = _detect(_tree(tmp_path, **{"seed_data.py": _SHORT_CIRCUIT}))
    assert len(hits) == 1 and hits[0]["file"] == "seed_data.py", hits


def test_an_unparseable_file_does_not_raise(tmp_path):
    assert _detect(_tree(tmp_path, **{"custom_routes.py": "def (:\n"})) == []


def test_a_missing_directory_is_empty_not_a_raise(tmp_path):
    assert _detect(tmp_path / "nope") == []


# ── the reporter ──────────────────────────────────────────────────────────────────

class _WH:
    def __init__(self, existing=None):
        self.tasks = list(existing or [])
        self.created = []

    def list_tasks(self):
        return self.tasks

    def create_task(self, **kw):
        self.created.append(kw)
        return {"id": "t1"}


class _Orch:
    def __init__(self, wh):
        class _H:
            workhub = wh
        self.hubs = _H()


def _report(tmp_path, src=_AUTH_SHORT_CIRCUIT, existing=None):
    _tree(tmp_path, **{"custom_routes.py": src})
    wh = _WH(existing)
    HP._lane_middleware_task_1202zu(_Orch(wh), str(tmp_path))
    return wh


def test_it_files_a_p1_backend_task(tmp_path):
    wh = _report(tmp_path)
    assert len(wh.created) == 1, wh.created
    assert wh.created[0]["assignee"] == "backend"
    assert wh.created[0]["priority"] == "P1", "a report must not block"


def test_the_task_names_the_site(tmp_path):
    d = _report(tmp_path).created[0]["description"]
    assert "custom_routes.py" in d and "_auth_edge" in d, d


def test_the_task_says_the_blocker_does_not_see_it(tmp_path):
    """The reason this is worth filing at all: a lane reading only the blockers would conclude
    the framework had approved the short-circuit."""
    d = _report(tmp_path).created[0]["description"]
    assert "not caught by the guard-tampering blocker" in d, d


def test_the_task_offers_the_contract_as_the_way_out(tmp_path):
    d = _report(tmp_path).created[0]["description"]
    assert "auth_required: false" in d and "READ" in d, d
    assert "delete the middleware" in d, d


def test_an_auth_interception_gets_its_own_warning(tmp_path):
    d = _report(tmp_path).created[0]["description"]
    assert "intercept an AUTH path" in d, d
    assert "never compare a password itself" in d, d


def test_a_passthrough_only_tree_files_nothing(tmp_path):
    assert _report(tmp_path, src=_PASSTHROUGH).created == []


def test_an_open_task_is_not_cloned(tmp_path):
    """#794: this runs every heal cycle."""
    wh = _report(tmp_path, existing=[
        {"title": "Lane middleware answers before the framework's auth guard (1)",
         "status": "in_progress"}])
    assert wh.created == []


def test_a_completed_task_does_not_suppress_a_new_one(tmp_path):
    wh = _report(tmp_path, existing=[
        {"title": "Lane middleware answers before the framework's auth guard (1)",
         "status": "completed"}])
    assert len(wh.created) == 1


def test_the_artifact_carries_every_site(tmp_path):
    """The title's count must be checkable against something (#1202w0/#947)."""
    _report(tmp_path)
    p = tmp_path / "logs" / "lane_middleware_1202zu.jsonl"
    assert p.is_file(), "no artifact"
    rec = json.loads(p.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["sites"] and rec["sites"][0]["func"] == "_auth_edge", rec


def test_a_missing_workhub_is_not_a_crash(tmp_path):
    _tree(tmp_path, **{"custom_routes.py": _SHORT_CIRCUIT})

    class _NoHub:
        hubs = None
    HP._lane_middleware_task_1202zu(_NoHub(), str(tmp_path))      # must not raise


# ── the caller ────────────────────────────────────────────────────────────────────

def test_the_heal_pipeline_calls_it(tmp_path):
    """★ I have tested a helper and not its caller repeatedly. Three properties: the call
    exists exactly once, it is inside `HealPipeline`, and it is not behind a branch that a run
    with nothing else to report would skip."""
    import inspect
    src = inspect.getsource(HP.HealPipeline)
    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_lane_middleware_task_1202zu"]
    assert len(calls) == 1, "called %d times" % len(calls)
    sib = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
           and getattr(n.func, "id", "") == "_unstaged_seed_media_task_1202zf"]
    assert sib, "the sibling reporter is gone"
    assert abs(calls[0].lineno - sib[0].lineno) <= 3, \
        "it must sit with the other post-merge reporters, which are known to run"


def test_a_conditional_short_circuit_is_reported(tmp_path):
    """★ The case the first draft would have MISSED. It skipped any return whose value mentioned
    `call_next`; this one mentions both, and substituting a 401 with data is precisely the
    guard-replacing move. No mutation of the fixtures above could reach that clause, and removing
    it left the corpus answer identical (22 sites in 17 runs) — dead AND pointed the wrong way."""
    hits = _detect(_tree(tmp_path, **{"custom_routes.py": _CONDITIONAL}))
    assert len(hits) == 1, hits
    assert hits[0]["func"] == "_cond_edge"


_MANY_PATHS = '''
from fastapi.responses import JSONResponse
@app.middleware("http")
async def _wide_edge(request, call_next):
    if request.url.path in ("/api/a", "/api/b", "/api/c", "/api/d", "/api/e", "/api/f"):
        return JSONResponse({})
    return await call_next(request)
'''


def test_the_per_site_path_list_declares_its_own_cut(tmp_path):
    """★ #1034's ratchet caught this, and it was right: the description shows at most four
    intercepted paths per site, and a site naming six must not show four in silence. The outer
    `... and N more` covers the SITES list; this is the inner one."""
    wh = _report(tmp_path, src=_MANY_PATHS)
    d = wh.created[0]["description"]
    assert "+2 more" in d, d
    assert "/api/a" in d, d
