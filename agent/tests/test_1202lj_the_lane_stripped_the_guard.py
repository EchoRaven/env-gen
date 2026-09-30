"""#1202lj: lane code that reaches into the framework's route table or auth allow-list.

The projector's guarantee is that a route the CONTRACT and the MATERIALS call per-user is
projected with an actor and an owner filter, and that the blanket guard denies it to an
anonymous caller. A lane cannot edit main.py -- but it can undo that from `custom_routes.py`
at import or on a startup hook.

tiktok-r120 is the worked example, function name and all:

    @router.on_event("startup")
    async def _promote_public_engagement_and_notification_routes():
        app.router.routes[:] = [r for r in app.router.routes if not (...)]
        app.router.routes.insert(0, APIRoute(path="/api/video_likes", ...,
                                             name="public_list_video_likes"))
        main_mod._FW_PUBLIC_RE_1202KH = regexes

for five endpoints at once. The framework was entirely correct: the materials call
`video_likes` owner-private, the projected handler at main.py:865 takes `get_current_user` and
owner-filters, and the path is NOT in the public list. The lane replaced it at startup, so an
anonymous GET answered 200 with every user's rows.

WHY CATCHING IT AT THE GATE WAS NOT ENOUGH, and why this is static. Once the endpoint answers
200 the verifier authors chains against THAT: r120 ended with TEN chains asserting 200 on it
and passing, and ONE asserting the denial and failing. Restoring the guard turns ten green
chains red, so the locally cheap move is to leave it -- and the run wedges on
`business_chain_failing` until the stuck-detector aborts. The wrong fact gets baked into the
checks that would have caught it. #1202kx/#1202ky/#1202lf/#1202ld all name this in the lane's
task text; r120 received them and did it anyway, because by then ten chains depended on it.

A RUNTIME DETECTOR WAS TRIED FIRST AND ABANDONED, recorded because the failure is instructive:
pairing "projected handler takes get_current_user" with "a chain step got an unauthenticated
2xx" both MISSED r120's /api/video_likes -- the ten passing chains DO send a token, so their
200 is legitimate -- and flagged four endpoints in netflix-local-r41 that were fine. Reading
the lane's own source needs no such inference.

Corpus: 14 of 158 runs (9%) contain at least one site.

WHAT IS VERIFIED: r120's three shapes; r117's ALIASED reach (`public_api = getattr(main_mod,
"_FW_PUBLIC_API_1202KH", None)` then `public_api.append(...)`, which a name-adjacent pattern
missed); netflix-local-r41's reorder-not-delete; clean runs staying clean; each finding naming
file and line; and no exception on a missing directory.

WHAT IS NOT: a verdict on intent, or a repair. It reports the site. Whether the route SHOULD be
public is the contract/materials question #1202kx and #1202ky already state.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.backend_audit import (  # noqa: E402
    framework_guard_tampering_1202lj as tamper)


class _Backend:
    def __init__(self, src):
        self.d = Path(tempfile.mkdtemp(prefix="lj_"))
        (self.d / "custom_routes.py").write_text(src, encoding="utf-8")

    def __enter__(self):
        return self.d

    def __exit__(self, *a):
        shutil.rmtree(self.d, ignore_errors=True)


class TheR120Shapes(unittest.TestCase):

    def test_reassigning_the_route_table(self):
        with _Backend("app.router.routes[:] = [r for r in app.router.routes if ok(r)]\n") as d:
            out = tamper(d)
        self.assertEqual(len(out), 1)
        self.assertIn("custom_routes.py:1", out[0])
        self.assertIn("reassigns app.router.routes", out[0])

    def test_removing_from_the_route_table(self):
        with _Backend("app.router.routes.remove(route)\n") as d:
            self.assertTrue(tamper(d))

    def test_writing_the_public_regex_list(self):
        with _Backend("main_mod._FW_PUBLIC_RE_1202KH = regexes\n") as d:
            self.assertTrue(tamper(d))


class TheAliasedReach(unittest.TestCase):
    """★ r117: the name and the write are on different lines, through a local alias."""

    def test_r117_shape_is_caught(self):
        src = ('public_api = getattr(main_mod, "_FW_PUBLIC_API_1202KH", None)\n'
               'if isinstance(public_api, list):\n'
               '    public_api.append(("GET", "/api/notifications"))\n')
        with _Backend(src) as d:
            out = tamper(d)
        self.assertTrue(out, "an aliased reach into the allow-list was missed")
        self.assertIn("_FW_PUBLIC_API_1202KH", out[0])

    def test_rebinding_the_guard_predicate(self):
        with _Backend("main._fw_contract_public_1202kh = lambda *a: True\n") as d:
            self.assertTrue(tamper(d))


class ReorderCountsToo(unittest.TestCase):
    """netflix-local-r41 does not delete — it puts lane routes FIRST, which shadows a guarded
    projected handler just the same."""

    def test_reorder_is_flagged(self):
        with _Backend("app.router.routes[:] = ours + rest\n") as d:
            self.assertTrue(tamper(d))


class ItStaysQuietOnCleanLanes(unittest.TestCase):

    def test_ordinary_lane_code_is_not_flagged(self):
        src = ('@router.get("/api/videos")\n'
               'def list_videos(db=Depends(get_db)):\n'
               '    return {"items": []}\n'
               'app.include_router(router)\n')
        with _Backend(src) as d:
            self.assertEqual(tamper(d), [])

    def test_reading_routes_without_writing_is_not_flagged(self):
        """A lane may LOOK at the table (diagnostics); only writing it is the defect."""
        with _Backend("n = len(app.router.routes)\nfor r in app.router.routes: pass\n") as d:
            self.assertEqual(tamper(d), [])

    def test_a_missing_backend_dir_never_raises(self):
        self.assertEqual(tamper("/nonexistent/xyz/backend"), [])

    def test_every_finding_names_a_file_and_line(self):
        with _Backend("x = 1\napp.router.routes[:] = []\n") as d:
            out = tamper(d)
        self.assertTrue(out[0].startswith("custom_routes.py:2 "), out[0])


if __name__ == "__main__":
    unittest.main()


class TheShapesThePatternsMissed(unittest.TestCase):
    """#1202zv: the docstring beside these patterns was wider than the patterns.

    It cites "`routes.insert(0,` in 9" runs as a measured tampering shape and NO pattern matched
    it; r120's own worked example is `app.router.routes.insert(0, APIRoute(...))`, caught only
    because that same function reassigns the list a line above. And "reassigns
    app.router.routes" required the SLICE form, so r136's plain attribute assignment walked
    through:

        app.router.routes = [r for r in app.router.routes if id(r) not in force_ids]
        for route in reversed(force_routes):
            app.router.routes.insert(0, route)

    for a target list holding `/api/users/{username}`, `/api/videos/{id}/likes`,
    `/api/videos/{id}/saves` and `/auth/logout`.

    Re-measured after widening both: 22 runs were already caught, 33 are now — the 11 added are
    r136 (both shapes, 4 inserts), r119, r109, r107, r97, r94, r91, r76, r32, r30, r26. Every new
    match was read by hand: `= kept` after a filter, `= [route for route in app.router.routes
    ...]`, `insert(0, route)`. No false positive in the set.
    """

    def test_a_plain_attribute_assignment_is_caught(self):
        with _Backend("app.router.routes = [r for r in app.router.routes if ok(r)]\n") as d:
            out = tamper(d)
        self.assertEqual(len(out), 1, out)
        self.assertIn("reassigns", out[0])

    def test_the_slice_form_is_still_caught(self):
        """Regression: the narrower shape must keep working."""
        with _Backend("app.router.routes[:] = kept\n") as d:
            self.assertEqual(len(tamper(d)), 1)

    def test_inserting_at_index_zero_is_caught(self):
        with _Backend("app.router.routes.insert(0, route)\n") as d:
            out = tamper(d)
        self.assertEqual(len(out), 1, out)
        self.assertIn("index 0", out[0])
        self.assertIn("shadows", out[0])

    def test_appending_is_deliberately_not_caught(self):
        """★ `append` puts the lane route BEHIND the projected one, where it can never match —
        a lane bug, not a guard bypass. Measured: 3 corpus runs do only that."""
        with _Backend("app.router.routes.append(route)\n") as d:
            self.assertEqual(tamper(d), [])

    def test_inserting_elsewhere_is_not_caught(self):
        """Index 0 is the shadowing position; anything else lands behind a projected route."""
        with _Backend("app.router.routes.insert(3, route)\n") as d:
            self.assertEqual(tamper(d), [])

    def test_a_comparison_is_not_an_assignment(self):
        """`(?!=)`: reading the table is not rewriting it."""
        with _Backend("if app.router.routes == expected:\n    pass\n") as d:
            self.assertEqual(tamper(d), [])

    def test_both_shapes_in_one_file_are_reported_separately(self):
        """r136's actual shape. A lane that does both must see both lines, or fixing one reads
        as fixing all of it."""
        with _Backend("app.router.routes = kept\n"
                      "app.router.routes.insert(0, route)\n") as d:
            out = tamper(d)
        self.assertEqual(len(out), 2, out)
        self.assertTrue(any("reassigns" in o for o in out), out)
        self.assertTrue(any("index 0" in o for o in out), out)
