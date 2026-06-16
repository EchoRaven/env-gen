"""B1 (2026-06-12): ui_page HARD wiring defects must block delivery EVEN on a
functionally-validated app.

Round 44 shipped a release whose api_smoke was green but whose /login page was
a blank screen — the declared route was never wired in App.jsx. api_smoke
probes the BACKEND only; it never opens a frontend page. So frontend_audit's
existing route/component checks are promoted to a deterministic delivery
blocker that is NOT relaxed by functionally_validated (unlike coverage/seed/
visual/ui_flow). It is self-clearing: a correctly wired page produces no
blocker, so it can never permanently block a pipeline.
"""

import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_audit import (  # noqa: E402
    ui_page_delivery_blockers,
    _is_hard_miss,
)
from multi_agent.runtime import deliverability  # noqa: E402


class _FakeWorkHub:
    def __init__(self, pages):
        self._pages = pages

    def get_ui_pages(self):
        return self._pages


class _FakeHubRegistry:
    def __init__(self, workhub):
        self.workhub = workhub


def _scaffold(tmp, app_jsx, extra_files=None):
    """Write src/App.jsx + optional component files; return frontend src dir."""
    src = Path(tmp) / "frontend" / "src"
    (src / "pages").mkdir(parents=True, exist_ok=True)
    (src / "App.jsx").write_text(app_jsx, encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return src


_GOOD_LOGIN = (
    "import { useState } from 'react';\n"
    "export default function LoginPage(){\n"
    "  const submit = () => fetch('/auth/login');\n"
    "  return <form onSubmit={submit}><button type='submit'>Go</button></form>;\n"
    "}\n"
)


class UiPageDeliveryBlockerTests(unittest.TestCase):

    def test_unwired_route_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            # App.jsx wires only "/", but the page declares route "/login".
            src = _scaffold(
                tmp,
                'import LoginPage from "./pages/LoginPage";\n'
                '<Routes><Route path="/" element={<LoginPage/>}/></Routes>',
                {"pages/LoginPage.jsx": _GOOD_LOGIN},
            )
            wh = _FakeWorkHub({"login": {
                "kind": "ui_page", "route": "/login",
                "component": "LoginPage", "apis_used": []}})
            blockers = ui_page_delivery_blockers(src, wh)
            self.assertEqual(len(blockers), 1)
            self.assertIn("login", blockers[0])
            self.assertIn("not wired in App.jsx", blockers[0])

    def test_wired_route_clears(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _scaffold(
                tmp,
                'import LoginPage from "./pages/LoginPage";\n'
                '<Routes><Route path="/login" element={<LoginPage/>}/></Routes>',
                {"pages/LoginPage.jsx": _GOOD_LOGIN},
            )
            wh = _FakeWorkHub({"login": {
                "kind": "ui_page", "route": "/login",
                "component": "LoginPage", "apis_used": []}})
            self.assertEqual(ui_page_delivery_blockers(src, wh), [])

    def test_missing_component_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            # route wired, but the declared component file is absent.
            src = _scaffold(
                tmp,
                '<Routes><Route path="/login" element={<LoginPage/>}/></Routes>')
            wh = _FakeWorkHub({"login": {
                "kind": "ui_page", "route": "/login",
                "component": "LoginPage", "apis_used": []}})
            blockers = ui_page_delivery_blockers(src, wh)
            self.assertEqual(len(blockers), 1)
            self.assertIn("not found", blockers[0])

    def test_soft_miss_not_hard(self):
        # apis_used loose-match failure is a SOFT miss — must NOT hard-block
        # (the call site may build the URL dynamically).
        self.assertFalse(_is_hard_miss(
            "declared API `/api/x` never referenced in frontend src"))
        self.assertTrue(_is_hard_miss("route `/login` not wired in App.jsx"))
        self.assertTrue(_is_hard_miss(
            "component `X` not found — expected at src/pages/X.jsx"))

    def test_empty_when_no_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _scaffold(tmp, "<Routes/>")
            self.assertEqual(ui_page_delivery_blockers(src, _FakeWorkHub({})), [])

    def test_deliverability_integration_blocks(self):
        # The blocker must flow through compute_deliverability into the report.
        with tempfile.TemporaryDirectory() as tmp:
            _scaffold(
                tmp,
                '<Routes><Route path="/" element={<LoginPage/>}/></Routes>',
                {"pages/LoginPage.jsx": _GOOD_LOGIN})
            wh = _FakeWorkHub({"login": {
                "kind": "ui_page", "route": "/login",
                "component": "LoginPage", "apis_used": []}})
            reg = _FakeHubRegistry(wh)
            got = deliverability._ui_page_wiring_blockers(reg, Path(tmp))
            self.assertEqual(len(got), 1)
            self.assertIn("declared but unusable", got[0])


if __name__ == "__main__":
    unittest.main()
