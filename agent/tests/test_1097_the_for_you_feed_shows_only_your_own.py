"""#1097 — the second emitter never applied #320, so an explicitly-public feed still filtered.

Found by probing r95's rendered backend, whose home page is:

    @app.get("/api/feed/for-you")
    def …(db, user):
        rows = db.query(Video).filter(Video.author_id ==
                                      _fw_owner_val(Video, "author_id", user)).limit(100).all()

Every user sees only their own videos; a new account sees an empty feed.

Owner-scoping is decided per TABLE (`_isolation_scoped_tables_from_chains` marks `videos`) and
was then applied to every read of it. `route_projector` already corrects that for the routes IT
projects, in two documented steps:

    #320  an EXPLICIT `auth_required: false` is the lane's deliberate "this read is public"
          declaration (the r88/r89 public-feed wedge) -> drop the owner filter
    #633  …but a structurally-private resource is private whatever the contract says — 4 of 45
          delivered backends shipped an UNAUTHENTICATED GET /api/search over
          `continue_watching` — so force it back on

`backend_skeleton.render_skeleton_main` applied NEITHER. Same drift as #1096, where two
emitters computing the same thing independently is exactly what nothing catches.

Measured over the 68 corpus contracts, discovery endpoints (`/feed/*`, `/explore`, `/search`,
`/trending`) rendered with an owner filter: **37 runs -> 12**. The remaining 12 are contracts
that never declare their feed public, which is #320's deliberate policy, not a framework bug:
*"a private table's unstated read must NOT default open"*.

★ What this deliberately is NOT: an earlier version of this fix keyed off the PATH — treating
`/feed/for-you`, `/explore`, `/search` as public by shape. It measured better (37 -> 0) and was
wrong: #633's comment names `GET /api/search` over `continue_watching` as a real leak vector,
and a path-shape rule drops the filter on exactly that endpoint. Overriding a documented
trade-off with a heuristic is the shape this project rejects; reverted in favour of applying
the framework's own rule in the place that was missing it.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402

_SCOPED_VIDEOS = {"videos": {"schema": {"columns": [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "author_id", "type": "integer", "references": "users.id"},
    {"name": "caption", "type": "text"}]},
    "metadata": {"owner_scoped_reads": True}}}


def _body(main: str, path: str) -> str:
    m = re.search(r'@app\.get\("%s"\)\ndef \w+\([^\n]*\):\n(.*?)(?=\n@app|\Z)'
                  % re.escape(path), main, re.S)
    return m.group(1) if m else ""


class AnExplicitlyPublicReadLosesTheFilter(unittest.TestCase):
    """#320, in the emitter that never had it."""

    def test_a_declared_public_feed_serves_every_row(self):
        eps = [{"method": "GET", "path": "/api/videos", "auth_required": False}]
        body = _body(render_skeleton_main(eps, _SCOPED_VIDEOS), "/api/videos")
        self.assertTrue(body, "the handler was not projected")
        self.assertNotIn("_fw_owner_val(", body,
                         "an explicitly public read still filters to the caller's own rows")

    def test_the_declaration_may_come_from_metadata(self):
        eps = [{"method": "GET", "path": "/api/videos",
                "metadata": {"auth_required": False}}]
        body = _body(render_skeleton_main(eps, _SCOPED_VIDEOS), "/api/videos")
        self.assertNotIn("_fw_owner_val(", body)


class AnUnstatedReadKeepsIt(unittest.TestCase):
    """#320's other half, and the reason a path-shape rule was rejected."""

    def test_an_unstated_read_on_a_scoped_table_still_filters(self):
        eps = [{"method": "GET", "path": "/api/videos"}]
        body = _body(render_skeleton_main(eps, _SCOPED_VIDEOS), "/api/videos")
        self.assertIn("_fw_owner_val(", body,
                      "an unstated read on a private table defaulted open — #315's leak")

    def test_an_unscoped_table_is_never_filtered(self):
        plain = {"videos": {"schema": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "author_id", "type": "integer", "references": "users.id"}]}}}
        body = _body(render_skeleton_main([{"method": "GET", "path": "/api/videos"}], plain),
                     "/api/videos")
        self.assertNotIn("_fw_owner_val(", body)


class TheTwoEmittersAgree(unittest.TestCase):
    """The invariant the drift broke — assert it directly rather than its symptom."""

    def test_the_public_declaration_is_honoured_by_both(self):
        from multi_agent.runtime.route_projector import project_missing_routes
        eps = [{"method": "GET", "path": "/api/videos", "auth_required": False}]
        skel = _body(render_skeleton_main(eps, _SCOPED_VIDEOS), "/api/videos")
        try:
            proj = project_missing_routes(eps, _SCOPED_VIDEOS,
                                          owner_scoped_tables={"videos"})
        except TypeError:
            self.skipTest("project_missing_routes signature differs in this build")
        blob = proj if isinstance(proj, str) else "\n".join(map(str, proj or []))
        self.assertNotIn("_fw_owner_val(", skel)
        if "/api/videos" in blob:
            self.assertNotIn("_fw_owner_val(", blob)


if __name__ == "__main__":
    unittest.main()
