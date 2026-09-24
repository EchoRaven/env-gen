"""#1202hs — the failure told the lane "you cannot fix this" about its own handler.

tiktok-web-r106's last remaining gate failure:

    GET /api/search → 500 (expected [200]; Internal Server Error)
      [FRAMEWORK-PROJECTED route — served by a _projected_ handler in main.py;
       the lane cannot edit it, fix the projector/contract]

The captured backend traceback says otherwise:

    custom_routes.py:493 in search — sqlalchemy.exc.ProgrammingError
    (psycopg.errors.DatatypeMismatch) UNION types text and integer cannot be matched

A lane bug, in a lane file, on a route the lane's own router is serving — and the framework
told it the route was not its to fix. `classify_endpoint_failure` had already reached the
right answer from the same evidence (a 500 whose traceback names no `_projected_` handler is
`broken`, i.e. lane-owned); `_projected_owner_note` then contradicted it in the same sentence,
because it decides from main.py's decorators alone and never asks whether a lane route for
that path exists.

Measured over the 120 runs here that have a `custom_routes.py`: 115 (96%) declare at least
one route whose method+path is ALSO projected, 1536 such paths in total. main.py drops the
duplicates in the projector's favour case by case (`_custom_route_overrides_projected`, plus
#1166's startup restore of ones nothing else serves), so which side actually serves is a
per-route runtime outcome — and asserting "the lane cannot edit it" from the path alone is
wrong across the great majority of runs.

So the note stops asserting when a lane route for the same path exists, and names both
places instead. Where NO lane route exists it is unchanged: that is the case #587 built it
for, and the one where "you cannot edit this" is true and worth saying.
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.chain_executor import (_lane_routes_1202hs,
                                                _projected_owner_note)

_PROJ = {("GET", "/api/search"), ("GET", "/api/videos")}


class LaneRouteDiscovery(unittest.TestCase):
    def test_it_reads_the_lane_router_declarations(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            be = Path(d) / "app" / "backend"
            be.mkdir(parents=True)
            (be / "custom_routes.py").write_text(
                'from fastapi import APIRouter\n'
                'router = APIRouter()\n\n'
                '@router.get("/api/search")\n'
                'def search():\n'
                '    return {}\n\n'
                '@router.post("/api/videos/{id}/like")\n'
                'def like(id: str):\n'
                '    return {}\n', encoding="utf-8")
            got = _lane_routes_1202hs(d)
            self.assertIn(("GET", "/api/search"), got)
            self.assertIn(("POST", "/api/videos/{id}/like"), got)

    def test_a_missing_custom_routes_is_an_empty_set_not_a_fault(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_lane_routes_1202hs(d), set())


class TheNote(unittest.TestCase):
    def test_it_stops_asserting_when_a_lane_route_shares_the_path(self):
        note = _projected_owner_note(_PROJ, "GET", "/api/search",
                                     lane={("GET", "/api/search")})
        self.assertNotIn("the lane cannot edit it", note)
        self.assertIn("custom_routes", note, note)

    def test_it_is_unchanged_where_only_the_projector_serves(self):
        """#587's case, and the one where the claim is true."""
        note = _projected_owner_note(_PROJ, "GET", "/api/videos", lane=set())
        self.assertIn("the lane cannot edit it", note)

    def test_a_route_nobody_projected_still_gets_no_note(self):
        self.assertEqual(_projected_owner_note(_PROJ, "GET", "/api/nope", lane=set()), "")

    def test_the_default_keeps_the_old_behaviour_for_existing_callers(self):
        """`lane` is optional: a caller that has not been taught to pass it must not start
        emitting a different verdict silently."""
        note = _projected_owner_note(_PROJ, "GET", "/api/search")
        self.assertIn("the lane cannot edit it", note)


if __name__ == "__main__":
    unittest.main()
