"""Bounded frontend-page build gate (2026-06-21): detect business ui_pages the lane
never built (framework fallback marker / missing file) + a bounded defer→release
decision (no deadlock). LOCAL-ONLY (agent/tests/ gitignored)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.page_build_gate import (  # noqa: E402
    frontend_unbuilt_pages, pages_release_decision, PAGES_ATTEMPT_CAP,
    PAGES_DEFERRAL_ESCAPE_S)
from multi_agent.runtime.frontend_page_projector import _PAGE_MARKER  # noqa: E402


def _wh(pages):
    return SimpleNamespace(get_ui_pages=lambda: pages)


def _rh(pages):
    # RegistryHub-style source (ui_pages are a first-class registry contract now).
    return SimpleNamespace(list_ui_pages=lambda: pages)


def _app(page_files):
    d = Path(tempfile.mkdtemp())
    pdir = d / "app" / "frontend" / "src" / "pages"
    pdir.mkdir(parents=True)
    for fname, txt in page_files.items():
        (pdir / fname).write_text(txt, encoding="utf-8")
    return d


class UnbuiltPagesTests(unittest.TestCase):
    def test_fallback_and_missing_pages_are_unbuilt(self):
        wh = _wh({
            "home": {"component": "HomePage", "route": "/"},
            "watch": {"component": "WatchPage", "route": "/watch/:id"},
            "login": {"component": "LoginPage", "route": "/login"},  # auth → excluded
        })
        app = _app({
            "HomePage.jsx": _PAGE_MARKER + "\nexport default function HomePage(){return null}",  # fallback
            # WatchPage.jsx MISSING → unbuilt
        })
        unbuilt = set(frontend_unbuilt_pages(wh, app))
        self.assertIn("HomePage", unbuilt)   # fallback marker
        self.assertIn("WatchPage", unbuilt)  # missing file
        self.assertNotIn("LoginPage", unbuilt)  # auth excluded

    def test_real_lane_page_is_built(self):
        wh = _wh({"home": {"component": "HomePage", "route": "/"}})
        app = _app({"HomePage.jsx": "export default function HomePage(){return <div>REAL YT FEED</div>}"})
        self.assertEqual(frontend_unbuilt_pages(wh, app), [])

    def test_no_pages_or_no_dir_safe(self):
        self.assertEqual(frontend_unbuilt_pages(_wh({}), _app({})), [])
        self.assertEqual(frontend_unbuilt_pages(None, "/nonexistent"), [])

    def test_reads_registryhub_list_ui_pages_accessor(self):
        # ui_pages are a RegistryHub first-class contract — the gate must read
        # list_ui_pages (registryhub), not only the legacy workhub.get_ui_pages.
        rh = _rh({
            "inbox": {"component": "InboxPage", "route": "/inbox"},     # fallback
            "calendar": {"component": "CalendarPage", "route": "/calendar"},  # real
            "login": {"component": "LoginPage", "route": "/login"},     # auth → excluded
        })
        app = _app({
            "InboxPage.jsx": _PAGE_MARKER + "\nexport default function InboxPage(){return null}",
            "CalendarPage.jsx": "export default function CalendarPage(){return <div>REAL</div>}",
        })
        self.assertEqual(frontend_unbuilt_pages(rh, app), ["InboxPage"])


class BoundedDecisionTests(unittest.TestCase):
    def test_defers_within_budget(self):
        self.assertEqual(pages_release_decision(1000.0, 0, 1000.0), "defer")
        self.assertEqual(pages_release_decision(1000.0, PAGES_ATTEMPT_CAP - 1, 1100.0), "defer")

    def test_releases_on_attempt_cap(self):
        self.assertEqual(pages_release_decision(1000.0, PAGES_ATTEMPT_CAP, 1100.0), "release")

    def test_releases_on_wallclock_escape(self):
        self.assertEqual(
            pages_release_decision(1000.0, 0, 1000.0 + PAGES_DEFERRAL_ESCAPE_S + 1), "release")

    def test_first_defer_anchor_none_defers(self):
        self.assertEqual(pages_release_decision(None, 0, 5000.0), "defer")

    def test_referenced_unbuilt_NEVER_escapes(self):
        # USER bar (2026-06-29): a page the references DEPICT must ship as the REAL page,
        # never the framework fallback — so it NEVER escapes, even far past the attempt cap
        # and wall-clock escape (the run fails honestly at its overall cap if the lane
        # truly cannot build it, rather than shipping a stub).
        big_attempts = PAGES_ATTEMPT_CAP * 10
        long_after = 1000.0 + PAGES_DEFERRAL_ESCAPE_S * 10
        self.assertEqual(
            pages_release_decision(1000.0, big_attempts, long_after,
                                   has_referenced_unbuilt=True), "defer")

    def test_non_referenced_still_escapes(self):
        # a page with NO reference to match keeps the bounded escape (fallback acceptable)
        big_attempts = PAGES_ATTEMPT_CAP * 10
        long_after = 1000.0 + PAGES_DEFERRAL_ESCAPE_S * 10
        self.assertEqual(
            pages_release_decision(1000.0, big_attempts, long_after,
                                   has_referenced_unbuilt=False), "release")


if __name__ == "__main__":
    unittest.main()
