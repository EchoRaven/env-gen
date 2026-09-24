"""#344: the route auditor must see the routes the framework's OWN main.py mounts.

`served_routes` enumerates mounted routes via `_included_modules`, which only
resolves the pattern

    from <mod> import router as <name>   ...   app.include_router(<name>)

But the main.py the framework ITSELF emits (backend_skeleton) mounts custom
routes dynamically, per FIX #127:

    import custom_routes as _custom_mod          # a plain ast.Import
    ...
    for _custom_router in _routers:
        app.include_router(_custom_router)       # a LOOP VARIABLE

Neither is statically resolvable by that pattern, so `_included_modules`
returned {} for the framework's own file -- 100% blindness in r91/r92/r93.

Consequence: `sync_endpoint_statuses` then took its
`not is_served and status == "implemented"` branch and silently demoted every
lane-authored endpoint back to `defined`, attributed to "orchestrator". In r91
the backend re-registered the same four auth endpoints 56 times over 5h41m,
saying "the code was already there" ~9 times, and the run died on the
wall-clock cap with them still `defined`. `grep -c "ENDPOINT LIFECYCLE"` = 0 --
every demotion was silent.

This is the iron law violated inside the framework: #127 fixed router MOUNTING
at runtime and broke the STATIC auditor that reads the same file. So the
regression guard here is deliberately anchored to the framework's own emitted
idiom, not to a hand-written fixture that can drift away from it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# The exact mounting idiom backend_skeleton emits (asserted below).
DYNAMIC_MAIN = '''from fastapi import FastAPI
app = FastAPI()

@app.get("/api/health")
def health():
    return {"ok": True}

try:
    import custom_routes as _custom_mod
    from fastapi import APIRouter as _APIRouter
    _seen_r = set()
    _routers = []
    _named = getattr(_custom_mod, "router", None)
    if isinstance(_named, _APIRouter):
        _routers.append(_named); _seen_r.add(id(_named))
    for _rn in vars(_custom_mod):
        _rv = getattr(_custom_mod, _rn, None)
        if isinstance(_rv, _APIRouter) and id(_rv) not in _seen_r:
            _routers.append(_rv); _seen_r.add(id(_rv))
    for _custom_router in _routers:
        app.include_router(_custom_router)
except Exception:
    pass
'''

CUSTOM = '''from fastapi import APIRouter
router = APIRouter()

@router.post("/api/auth/signup")
def signup():
    return {"item": {}}

@router.get("/api/videos/{id}")
def get_video(id: int):
    return {"item": {}}
'''

STATIC_MAIN = '''from fastapi import FastAPI
from custom_routes import router as custom_router
app = FastAPI()
app.include_router(custom_router)
'''


def _tree(tmp, main_src):
    be = Path(tmp) / "backend"
    be.mkdir()
    (be / "main.py").write_text(main_src)
    (be / "custom_routes.py").write_text(CUSTOM)
    return be


def _served(be):
    from multi_agent.runtime.backend_audit import served_routes
    return served_routes(be)


class TheFixtureMatchesTheFrameworksOwnEmission(unittest.TestCase):
    """If backend_skeleton changes its idiom, this test must fail loudly rather
    than let the auditor go quietly blind again."""

    def _skeleton_src(self):
        from multi_agent.runtime import backend_skeleton
        return Path(backend_skeleton.__file__).read_text()

    def test_skeleton_still_uses_a_plain_import_alias(self):
        self.assertIn("import custom_routes as _custom_mod", self._skeleton_src())

    def test_skeleton_still_mounts_through_a_loop_variable(self):
        src = self._skeleton_src()
        self.assertIn("for _custom_router in _routers:", src)
        self.assertIn("app.include_router(_custom_router)", src)


class DynamicMountIsVisible(unittest.TestCase):

    def test_lane_routes_are_seen_through_the_dynamic_mount(self):
        with TemporaryDirectory() as tmp:
            served = _served(_tree(tmp, DYNAMIC_MAIN))
            self.assertIn(("POST", "/api/auth/signup"), served)
            # served_routes normalizes path params: /api/videos/{id} -> {}
            self.assertIn(("GET", "/api/videos/{}"), served)

    def test_the_apps_own_routes_are_still_seen(self):
        with TemporaryDirectory() as tmp:
            self.assertIn(("GET", "/api/health"), _served(_tree(tmp, DYNAMIC_MAIN)))

    def test_a_module_that_is_never_mounted_is_not_reported(self):
        with TemporaryDirectory() as tmp:
            be = _tree(tmp, DYNAMIC_MAIN)
            (be / "orphan_routes.py").write_text(
                'from fastapi import APIRouter\n'
                'router = APIRouter()\n\n'
                '@router.get("/api/orphan")\n'
                'def orphan():\n'
                '    return {}\n')
            self.assertNotIn(("GET", "/api/orphan"), _served(be))


class TheStaticFormStillWorks(unittest.TestCase):
    """The original `from x import router as y` path must be untouched."""

    def test_static_import_form_is_still_resolved(self):
        with TemporaryDirectory() as tmp:
            served = _served(_tree(tmp, STATIC_MAIN))
            self.assertIn(("POST", "/api/auth/signup"), served)

    def test_no_main_py_is_handled(self):
        with TemporaryDirectory() as tmp:
            be = Path(tmp) / "backend"
            be.mkdir()
            (be / "custom_routes.py").write_text(CUSTOM)
            self.assertEqual(_served(be), set())


if __name__ == "__main__":
    unittest.main()
