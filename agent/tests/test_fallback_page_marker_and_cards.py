"""Framework fallback pages (2026-06-21): the generic projection used to render a
raw {key}: {value} DUMP and carried NO marker — so frontend_fallback_pages always
reported 0 and the (future) runtime gate couldn't tell a framework page from a real
one. Now: GET pages render a card/grid, every fallback carries _PAGE_MARKER +
data-fallback, and auth pages (framework-OWNED, real) are NOT marked.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.frontend_scaffold import _project_page_component  # noqa: E402
from multi_agent.runtime.frontend_page_projector import _PAGE_MARKER  # noqa: E402


class FallbackMarkerAndCardTests(unittest.TestCase):
    def test_get_page_is_light_list_not_dump_or_videocards(self):
        # 2026-06-22: the GET fallback is now a LIGHT ROW LIST (universal business-app
        # shape), NOT a dark 16:9 video-card grid (which rendered emails as blank tiles
        # on black). It fetches the page's OWN declared endpoint and shows title+snippet.
        src = _project_page_component("InboxPage", {"route": "/inbox", "apis_used": ["GET /api/messages"]})
        self.assertNotIn("Object.keys(row", src)          # not the raw key:value dump
        self.assertNotIn("aspect-video", src)             # NOT video-card thumbnails
        self.assertNotIn("bg-black", src)                 # NOT dark theme
        self.assertIn("bg-zinc-50", src)                  # light theme
        self.assertIn("divide-y", src)                    # row-list layout
        self.assertIn("_imgOf", src)                      # still detects an avatar/thumbnail
        self.assertIn("_subOf", src)                      # shows a sender/snippet subtitle
        self.assertIn("/api/messages", src)               # fetches its OWN declared endpoint

    def test_fallback_pages_carry_marker_and_attr(self):
        for page in ({"route": "/x", "apis_used": ["GET /api/x"]},   # GET
                     {"route": "/y", "apis_used": ["POST /api/y"]},  # POST
                     {"route": "/z"}):                                # stub (no api)
            src = _project_page_component("ZPage", page)
            self.assertIn(_PAGE_MARKER, src, f"fallback page missing marker: {page}")
        self.assertIn('data-fallback="1"',
                      _project_page_component("XPage", {"route": "/x", "apis_used": ["GET /api/x"]}))

    def test_write_only_page_renders_a_form_not_an_inert_stub(self):
        # A page whose apis_used are only write verbs (PUT/PATCH/DELETE — no GET, no POST)
        # used to fall through to the inert no-api stub (a dead heading). It must render a
        # functional form that calls its declared endpoint with the RIGHT method.
        stub = _project_page_component("StubPage", {"route": "/s"})  # the inert baseline
        for verb, path in (("PUT", "/api/settings"), ("PATCH", "/api/profile"), ("DELETE", "/api/session")):
            src = _project_page_component("WPage", {"route": "/w", "apis_used": [f"{verb} {path}"]})
            self.assertNotEqual(src, stub, f"{verb}-only page degraded to the inert stub")
            self.assertIn("onSubmit", src, f"{verb}-only page has no form")
            self.assertIn(f"method: '{verb}'", src, f"{verb}-only page does not use {verb}")
            self.assertIn(path, src)

    def test_auth_pages_are_not_marked_as_fallback(self):
        # auth pages are framework-OWNED real pages, not fallbacks
        for page in ({"route": "/login", "id": "login_page"},
                     {"route": "/signup", "id": "signup_page"}):
            self.assertNotIn(_PAGE_MARKER, _project_page_component("LoginPage", page))

    def test_marker_idempotent(self):
        src = _project_page_component("APage", {"route": "/a", "apis_used": ["GET /api/a"]})
        self.assertEqual(src.count(_PAGE_MARKER), 1)


if __name__ == "__main__":
    unittest.main()
