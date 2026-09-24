"""Guard: a BUILT frontend must flip its registered ui_pages defined→implemented
and be counted as navigable — never reported as a blank shell.

Regression context (run #3 youtube, 2026-06-16): the frontend lane shipped 15
real page files + 15 wired ``<Route>``s, and 18 ui_pages were registered WITH
routes/components in RegistryHub — yet the 5 real pages stayed ``defined`` and
the navigable gate reported "0 page component(s), 0 route(s) — blank shell".

Root cause: ``frontend_audit.audit_ui_page`` resolved the declared ``component``
ONLY by filename/definition-name. The declared component is a LOGICAL page name
(``HomePage``), but the lane is free to render the route with a differently-named
real file (``Home.jsx`` → ``<Route path="/" element={<Home />}>``). The audit
ignored the route→element wiring, so the component "couldn't be found", the page
never flipped to ``implemented``, and a fully-built navigable UI looked blank.

This test builds a small, DOMAIN-NEUTRAL env where the declared component name
deliberately differs from the on-disk filename (resolved THROUGH the route
element), runs the status-flip audit, and asserts:
  (1) the pages flip defined→implemented via the real workhub→registryhub path;
  (2) the navigable gate counts pages AND routes (>0) — not a blank shell.

It also pins the negative: a declared page whose route is NOT wired must stay
``defined`` (the fix must not blanket-promote — it must agree with reality).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.frontend_audit import sync_ui_page_statuses  # noqa: E402
from multi_agent.runtime.validation_runner import _frontend_navigable  # noqa: E402


# A page that genuinely calls its declared API and binds a control — fully built.
def _page_body(fn_name: str, api_path: str) -> str:
    return (
        "import React from 'react';\n"
        f"export default function {fn_name}() {{\n"
        f"  const load = () => fetch('{api_path}');\n"
        "  return (<div><button onClick={load}>Load</button></div>);\n"
        "}\n"
    )


class FrontendNavigableFlipTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.project_dir = Path(self._td.name)
        self.hubs = HubRegistry(self.project_dir)
        self.workhub = self.hubs.workhub
        self.registryhub = self.hubs.registryhub

        self.fe_src = self.project_dir / "app" / "frontend" / "src"
        (self.fe_src / "pages").mkdir(parents=True, exist_ok=True)

        # On-disk page files use SHORT names; the ui_pages will declare LOGICAL
        # component names (…Page) that differ — resolution must go through the
        # route element wiring, not the filename.
        (self.fe_src / "pages" / "Home.jsx").write_text(
            _page_body("Home", "/api/items"), encoding="utf-8")
        (self.fe_src / "pages" / "Detail.jsx").write_text(
            _page_body("Detail", "/api/item-detail"), encoding="utf-8")
        # A page that exists on disk but is NOT wired into App.jsx (declared
        # ui_page below) — must stay `defined`.
        (self.fe_src / "pages" / "Orphan.jsx").write_text(
            _page_body("Orphan", "/api/orphan"), encoding="utf-8")

        # App.jsx wires Home and Detail via differently-named elements; Orphan
        # is intentionally absent (route unwired).
        (self.fe_src / "App.jsx").write_text(
            "import React from 'react';\n"
            "import { BrowserRouter, Routes, Route } from 'react-router-dom';\n"
            "import Home from './pages/Home.jsx';\n"
            "import Detail from './pages/Detail.jsx';\n"
            "export default function App() {\n"
            "  return (<BrowserRouter><Routes>\n"
            '    <Route path="/" element={<Home />} />\n'
            '    <Route path="/items/:id" element={<Detail />} />\n'
            "  </Routes></BrowserRouter>);\n"
            "}\n",
            encoding="utf-8",
        )

        # Register the endpoints the pages declare (so the contract-membership
        # check in sync_ui_page_statuses passes).
        for method, path in (("GET", "/api/items"),
                             ("GET", "/api/item-detail"),
                             ("GET", "/api/orphan")):
            self.registryhub.register_endpoint(
                method=method, path=path, agent="backend", status="implemented")

        # Declare the ui_pages with LOGICAL component names != filenames.
        self.registryhub.register_ui_page(
            "home", route="/", component="HomePage",
            apis_used=["GET /api/items"], agent="frontend", status="defined")
        self.registryhub.register_ui_page(
            "detail", route="/items/:id", component="DetailPage",
            apis_used=["GET /api/item-detail"], agent="frontend", status="defined")
        # Orphan: real file + declared component, but its route is NOT in App.jsx.
        self.registryhub.register_ui_page(
            "orphan", route="/orphan", component="OrphanPage",
            apis_used=["GET /api/orphan"], agent="frontend", status="defined")

    def tearDown(self):
        self._td.cleanup()

    def _status(self, name: str) -> str:
        return str((self.registryhub.get_ui_page(name) or {}).get("status") or "").lower()

    def test_built_pages_flip_and_navigable_counts_them(self):
        # precondition: all defined, navigable would still see files (sanity).
        self.assertEqual(self._status("home"), "defined")
        self.assertEqual(self._status("detail"), "defined")

        result = sync_ui_page_statuses(
            self.project_dir, self.workhub, registryhub=self.registryhub)

        # (1) the two BUILT + WIRED pages flip to implemented — resolved through
        #     the route element despite the component↔filename mismatch.
        self.assertIn("home", result["implemented"],
                      f"home should flip; pending={result.get('pending')}")
        self.assertIn("detail", result["implemented"],
                      f"detail should flip; pending={result.get('pending')}")
        self.assertEqual(self._status("home"), "implemented")
        self.assertEqual(self._status("detail"), "implemented")

        # (1b) the negative pin: the orphan page's route is unwired → stays defined.
        self.assertEqual(self._status("orphan"), "defined")
        self.assertIn("orphan", result.get("pending", {}))

        # (2) the navigable gate agrees with reality — NOT a blank shell.
        ok, detail = _frontend_navigable(self.project_dir)
        self.assertTrue(ok, f"frontend must be navigable, got: {detail}")
        # detail reads e.g. "3 page component(s), 2 route(s)"
        import re
        m = re.search(r"(\d+) page component\(s\), (\d+) route\(s\)", detail)
        self.assertIsNotNone(m, f"unexpected detail: {detail}")
        n_pages, n_routes = int(m.group(1)), int(m.group(2))
        self.assertGreater(n_pages, 0, detail)
        self.assertGreater(n_routes, 0, detail)


if __name__ == "__main__":
    unittest.main()
