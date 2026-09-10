"""#1202ki: #528 orders projected handlers first; lane code deletes them.

tiktok-r114, live. `custom_routes.py`, written by the backend lane:

    replacements = {("GET", "/api/v1/tenants"), ("POST", "/auth/register"),
                    ("POST", "/api/auth/register")}
    ...
    app.router.routes[:] = kept
    app.get("/api/v1/tenants")(_authenticated_tenants_list_endpoint)

and the consequence, by curl against the running container:

    $ curl -s localhost:8008/api/v1/tenants
    401 {"detail":"missing bearer token"}

`/api/v1/tenants` is a FIXED control-plane endpoint. `control_plane.py` declares it
`auth_required: False`, the framework registers it `kind='infra'`, and the TEST HARNESS drives
it with no token. The lane replaced it with an authenticated one, and #528's precedence
guarantee did not help: #528 works by ORDERING projected routes first, and this deletes them.

Measured across the 153 generated backends: 66 mutate `app.router.routes`, and 13 both remove
routes and name a framework-fixed path — almost always the whole control plane
(/api/v1/reset, /api/v1/tenants, /api/v1/admin/init-tenant, /api/v1/tenants/{tenant_id}), and
in six of them /auth/login or /auth/register as well.

This is the mirror of #1166. That hook restores a LANE route dropped for a projected handler
that turned out not to exist; this one restores a FRAMEWORK route a lane dropped.

WHAT IS VERIFIED: the framework's route objects are captured before any lane code runs; a
deleted one is put BACK, and back at the FRONT so ordering-based precedence holds again; one
that is still present is not duplicated; and the repair can never break startup.

WHAT IS NOT: that the lane's own handler is removed. It stays registered — it simply stops
being the one that answers, which is the same bargain #528 already makes.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
# House style, and NOT a detail: insert `llm_generator`, never `multi_agent` itself.
# `multi_agent/` contains its own `tests/` package, so putting it on sys.path ahead of `agent/`
# shadows `agent/tests` — and `test_kickoff_run_kickoff_finalize_hardening.py`, which does
# `from tests.test_kickoff_run_kickoff import ...`, then fails to COLLECT and takes the whole
# suite down with it. Passed alone; only the full run showed it.
_LLM = _AGENT / "env_generator" / "llm_generator"
for _p in (str(_LLM), str(_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ast                                                             # noqa: E402
import asyncio                                                        # noqa: E402

from multi_agent.runtime.backend_skeleton import render_skeleton_main              # noqa: E402
from multi_agent.runtime.kickoff.contract import fixed_surface_1202ke              # noqa: E402


def _src():
    return render_skeleton_main(
        [{"method": "GET", "path": "/api/videos/feed", "auth_required": False,
          "response_key": "items",
          "schema": {"auth_required": False, "response": {"tables": ["videos"]}}}],
        {"videos": {"name": "videos", "schema": {"columns": [{"name": "id", "type": "int"}]}}})


def _literal(src, name):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} was not emitted")


# --- what the skeleton emits ----------------------------------------------------------------

def test_the_fixed_paths_come_from_the_frameworks_own_declarations():
    got = _literal(_src(), "_FW_FIXED_PATHS_1202KI")
    assert got == {p for _m, p in fixed_surface_1202ke()}
    assert "/api/v1/tenants" in got and "/auth/login" in got


def test_the_snapshot_runs_before_any_lane_code():
    """★ A snapshot taken after `import custom_routes` would capture the table the lane has
    already edited — i.e. nothing to restore."""
    src = _src()
    assert (src.index("_FW_FIXED_PATHS_1202KI = ")
            < src.index("_FW_FIXED_ROUTES_1202KI = [")
            < src.index("import custom_routes"))


def test_the_restore_hook_is_registered_after_1166s():
    """Startup hooks run in registration order, and #1166 appends while this one inserts at
    the front — running first would let #1166's append land ahead of a restored route."""
    src = _src()
    assert (src.index("async def _fw_restore_unserved_dropped_1166")
            < src.index("async def _fw_restore_fixed_surface_1202ki"))


# --- the behaviour, executed ------------------------------------------------------------------

class _Route:
    def __init__(self, path, methods=("GET",)):
        self.path = path
        self.methods = set(methods)

    def __repr__(self):
        return f"<Route {self.path}>"


class _Router:
    def __init__(self, routes):
        self.routes = list(routes)


class _App:
    def __init__(self, routes):
        self.router = _Router(routes)

    @property
    def routes(self):
        return self.router.routes


def _restore_fn(src, app, snapshot):
    """Execute the SHIPPED hook body, so this cannot pass against a reimplementation."""
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_fw_restore_fixed_surface_1202ki")
    fn.decorator_list = []          # `@app.on_event("startup")` needs a real FastAPI app
    ast.fix_missing_locations(fn)
    g = {"app": app, "_FW_FIXED_ROUTES_1202KI": snapshot}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<hook>", "exec"), g)  # noqa: S102
    return g["_fw_restore_fixed_surface_1202ki"]


def test_a_deleted_framework_route_is_put_back():
    """★ r114's case: the lane removed GET /api/v1/tenants and registered its own."""
    src = _src()
    fixed = _Route("/api/v1/tenants")
    lane = _Route("/api/v1/tenants")            # the lane's authenticated replacement
    app = _App([lane])                          # `routes[:] = kept` already happened
    asyncio.run(_restore_fn(src, app, [fixed])())
    assert fixed in app.routes, "the framework's route was not restored"


def test_it_is_restored_in_FRONT_of_the_lanes_replacement():
    """★ #528's guarantee is about ORDER. Appending would restore the object and change
    nothing about which handler answers."""
    src = _src()
    fixed = _Route("/api/v1/tenants")
    lane = _Route("/api/v1/tenants")
    app = _App([lane])
    asyncio.run(_restore_fn(src, app, [fixed])())
    assert app.routes.index(fixed) < app.routes.index(lane)


def test_the_lanes_route_is_not_removed():
    """Scope: this restores precedence, it does not delete the lane's work."""
    src = _src()
    fixed, lane = _Route("/api/v1/tenants"), _Route("/api/v1/tenants")
    app = _App([lane])
    asyncio.run(_restore_fn(src, app, [fixed])())
    assert lane in app.routes


def test_a_route_still_present_is_not_duplicated():
    """★ The floor. Every run that did NOT delete anything must be byte-identical — a second
    copy of a route is its own defect (#713's duplicate shape one layer down)."""
    src = _src()
    fixed = _Route("/api/v1/tenants")
    app = _App([fixed, _Route("/api/videos/feed")])
    before = list(app.routes)
    asyncio.run(_restore_fn(src, app, [fixed])())
    assert app.routes == before


def test_identity_not_path_decides_presence():
    """A lane that registers its OWN handler on the same path must not be mistaken for the
    framework's route still being there — that is exactly r114, and a path-based check would
    call it present and restore nothing."""
    src = _src()
    fixed, lane = _Route("/api/v1/tenants"), _Route("/api/v1/tenants")
    app = _App([lane])
    asyncio.run(_restore_fn(src, app, [fixed])())
    assert fixed in app.routes


def test_the_repair_never_breaks_startup():
    """A broken app object must not stop the server booting — the same contract #1166's
    hook keeps."""
    src = _src()

    class _Broken:
        @property
        def routes(self):
            raise RuntimeError("router exploded")

    asyncio.run(_restore_fn(src, _Broken(), [_Route("/health")])())
