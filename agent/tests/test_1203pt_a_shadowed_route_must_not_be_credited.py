r"""#1203pt: "a route defined twice must not be credited as implemented" had no driver.

`backend_audit.sync_endpoint_statuses` refuses to credit an intra-module duplicate, because
FastAPI mounts only the first def and shadows the rest -- so which handler serves is
ambiguous and a broken first def would ship green (audit #6). #1202z4 added the task that
tells a lane about it, and r136 reported TWENTY-THREE shadowed endpoints.

FOUND BY MUTATION, not by reading. Two mutations -- `if _nr in dups:` -> `if False:` and
`dups = duplicated_routes(...)` -> `dups = set()` -- were MISSED against all FOUR test files
that mention the detector or drive the function:

    tests/test_backend_audit.py                                   MISSED (no duplicate case)
    tests/test_1202z4_a_route_defined_twice_never_runs.py         MISSED (hands a hardcoded
                                                                  dup list to the TASK
                                                                  builder; never calls the
                                                                  audit)
    tests/test_mounted_but_unreachable_is_a_framework_defect_1006.py   MISSED
    tests/test_344_served_routes_sees_dynamic_mount.py            MISSED

So the branch was drivable and undriven: nothing anywhere built a backend with two defs of
one route. `backend_audit.py` is the framework file with the most ticketed properties and no
mutation spec at all (56 tickets, 1969 lines), which is how this surfaced.
"""
import sys
import tempfile
import unittest
from pathlib import Path

_AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_AGENT))
sys.path.insert(0, str(_AGENT / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_audit import (  # noqa: E402
    duplicated_routes, served_routes, sync_endpoint_statuses)


class _Registry:
    def __init__(self):
        self._eps = {}

    def seed(self, method, path, status, **md):
        self._eps["%s %s" % (method.upper(), path)] = {
            "method": method.upper(), "path": path, "status": status,
            "metadata": dict(md)}

    def get_endpoints(self):
        return {k: dict(v) for k, v in self._eps.items()}

    def register_endpoint(self, method, path, schema=None, provider="", agent="",
                          status="defined", **md):
        key = "%s %s" % (method.upper(), path)
        old = self._eps.get(key, {})
        self._eps[key] = {**old, "method": method.upper(), "path": path,
                          "status": status or old.get("status") or "defined",
                          "metadata": {**(old.get("metadata") or {}), **md}}
        return self._eps[key]

    def status_of(self, method, path):
        return (self._eps.get("%s %s" % (method.upper(), path)) or {}).get("status")


_MAIN = ("from fastapi import FastAPI\n"
         "from dup_routes import router as _d\n"
         "app = FastAPI()\n"
         "app.include_router(_d)\n")

# `/api/videos/feed` is defined TWICE in one module; `/api/videos/trending` once. The second
# is the control: a check that answered "duplicated" for everything would pass without it.
_DUP = ("from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/api/videos/feed')\n"
        "def feed_first(): ...\n"
        "@router.get('/api/videos/feed')\n"
        "def feed_shadowed(): ...\n"
        "@router.get('/api/videos/trending')\n"
        "def trending(): ...\n")


def _backend(files):
    proj = Path(tempfile.mkdtemp(prefix="pt1203_"))
    be = proj / "app" / "backend"
    be.mkdir(parents=True)
    for name, content in files.items():
        (be / name).write_text(content, encoding="utf-8")
    return proj


class TheAuditSeesTheCollision(unittest.TestCase):

    def setUp(self):
        self.proj = _backend({"main.py": _MAIN, "dup_routes.py": _DUP})
        self.be = self.proj / "app" / "backend"

    def test_both_routes_are_served(self):
        """Precondition: without this the test below could pass because nothing was found
        at all."""
        served = served_routes(self.be)
        self.assertIn(("GET", "/api/videos/feed"), served)
        self.assertIn(("GET", "/api/videos/trending"), served)

    def test_the_duplicate_is_detected(self):
        self.assertIn(("GET", "/api/videos/feed"), duplicated_routes(self.be))

    def test_the_single_definition_is_NOT_called_a_duplicate(self):
        """The control. `duplicated_routes` returning everything would satisfy the test
        above and destroy the distinction the status sync rests on."""
        self.assertNotIn(("GET", "/api/videos/trending"), duplicated_routes(self.be))


class TheStatusSyncRefusesToCreditIt(unittest.TestCase):

    def setUp(self):
        self.proj = _backend({"main.py": _MAIN, "dup_routes.py": _DUP})
        self.reg = _Registry()

    def test_a_shadowed_route_is_not_promoted_to_implemented(self):
        """★ THE PROPERTY. It is served -- `served_routes` finds it -- so without the
        duplicate branch it would be credited, and a broken first def ships green."""
        self.reg.seed("GET", "/api/videos/feed", "defined")
        out = sync_endpoint_statuses(self.proj, self.reg)
        self.assertNotEqual(self.reg.status_of("GET", "/api/videos/feed"), "implemented")
        self.assertNotIn("GET /api/videos/feed", out.get("implemented") or [])

    def test_a_shadowed_route_already_marked_implemented_is_DEMOTED(self):
        """"Refuse to credit" is not enough on its own: the lane may already have written
        `implemented`, and the comment says demote if it was."""
        self.reg.seed("GET", "/api/videos/feed", "implemented")
        sync_endpoint_statuses(self.proj, self.reg)
        self.assertEqual(self.reg.status_of("GET", "/api/videos/feed"), "defined")

    def test_the_finding_is_returned_so_1202z4_can_file_it(self):
        """#1202z4's task is built from this key; an empty list means the task can never
        fire, and that half had no driver either."""
        self.reg.seed("GET", "/api/videos/feed", "implemented")
        out = sync_endpoint_statuses(self.proj, self.reg)
        self.assertIn("GET /api/videos/feed", out.get("duplicated") or [])

    def test_a_route_defined_ONCE_is_still_credited(self):
        """★ THE REGRESSION CONTROL. A mutation that treats every route as duplicated would
        pass every assertion above. The non-duplicated sibling must still be promoted."""
        self.reg.seed("GET", "/api/videos/trending", "defined")
        out = sync_endpoint_statuses(self.proj, self.reg)
        self.assertEqual(self.reg.status_of("GET", "/api/videos/trending"), "implemented")
        self.assertIn("GET /api/videos/trending", out.get("implemented") or [])

    def test_nothing_duplicated_reports_nothing(self):
        """#983: a check that fires while naming nothing. A clean backend must not produce
        a `duplicated` entry."""
        clean = _backend({"main.py": _MAIN,
                          "dup_routes.py": _DUP.replace(
                              "@router.get('/api/videos/feed')\ndef feed_shadowed(): ...\n",
                              "")})
        reg = _Registry()
        reg.seed("GET", "/api/videos/feed", "defined")
        out = sync_endpoint_statuses(clean, reg)
        self.assertEqual(out.get("duplicated") or [], [])
        self.assertEqual(reg.status_of("GET", "/api/videos/feed"), "implemented")


if __name__ == "__main__":
    unittest.main()
