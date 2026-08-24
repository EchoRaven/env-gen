"""#1082 — the audit graded a file the app never renders.

run67 (instagram, *** 3 MILESTONES VALIDATED ***) ships three pages twice:

    src/pages/DirectMessagesPage.jsx   55 lines, `// framework-generated page
                                       (frontend_page_projector) — edits are overwritten`
    src/pages/DirectMessages.jsx       52 lines, the lane's real page — composes NavRail,
                                       MessagesSidebar, ChatArea, NotificationModal

and App.jsx binds the second one under the first one's NAME:

    import DirectMessagesPage from './pages/DirectMessages';
    <Route path="/direct" element={<DirectMessagesPage />} />

The framework's own stub is an orphan — imported by nobody, rendered by nothing. The audit
resolves the declared component `DirectMessagesPage` to `src/pages/DirectMessagesPage.jsx`
by CONVENTION, finds the stub, and reports *"component `DirectMessagesPage` is a framework
fallback page (generic list) — author the REAL page"* about a page that has one. Three false
blockers (Explore, Reels, DirectMessages) on a validated app, feeding
`deliverability_frontend_fallback_page` — 1253 occurrences across 201 run logs, the #3
blocker overall.

`_route_element` cannot see this: the element NAME matches (that is what the import aliases),
and only the MODULE PATH differs. The canonical path is a convention; App.jsx's import is
what the bundler and the browser obey. This is the principle the audit already states twice —
FIX #146 (*"the app is the authority on where its screens live"*) and the 2026-06-16
route-element resolution (*"the route→element wiring is the source of truth for what renders
the page"*) — applied to the one input neither of them reads.

Scope kept deliberately narrow, because this is a delivery-blocking path: the import is
followed ONLY when the canonical file is the framework's OWN generic fallback. A lane page at
the canonical path is never second-guessed, a divergent import that also resolves to a
fallback still blocks, and a missing import target falls through to today's behaviour.
Measured: 3 of 448 resolvable declarations drift this way, all in run67 — rare, and the
mechanism is exact, which is the same footing FIX #146 (one run) and #151 (one run) shipped on.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_audit import audit_ui_page  # noqa: E402

_FALLBACK = """// framework-generated page (frontend_page_projector) — edits are overwritten
import { useState, useEffect } from 'react';
const _imgOf = (r) => (r && r.image_url) || null;
const _titleOf = (r) => String((r && r.title) || '');
const _subOf = (r) => String((r && r.body) || '');
const _metaOf = (r) => Object.keys(r || {}).slice(0, 3);
export default function %s() {
  const [rows, setRows] = useState([]);
  useEffect(() => { fetch('/api/messages').then(r => r.json()).then(d => setRows(d.items || [])); }, []);
  if (!rows.length) return <div>No data yet</div>;
  return (<ul className="divide-y">{rows.map(r => <li key={r.id}>{_titleOf(r)}</li>)}</ul>);
}
"""

_REAL = """import { useState, useEffect } from 'react';
import ChatArea from '../components/ChatArea';
export default function DirectMessagesPage() {
  const [convos, setConvos] = useState([]);
  const [active, setActive] = useState(null);
  useEffect(() => { fetch('/api/messages').then(r => r.json()).then(d => setConvos(d.items || [])); }, []);
  return (<section className="dm">
    <aside>{convos.map(c => <button key={c.id} onClick={() => setActive(c)}>{c.name}</button>)}</aside>
    <ChatArea conversation={active} />
  </section>);
}
"""

_PAGE = {"name": "direct_messages", "component": "DirectMessagesPage",
         "route": "/direct", "apis_used": ["GET /api/messages"]}


def _tree(*, import_from: str = "DirectMessages", real_module: bool = True,
          canonical_is_stub: bool = True) -> Path:
    """run67's shape: App.jsx imports the declared NAME from a different module."""
    src = Path(mkdtemp()) / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "components" / "ChatArea.jsx").write_text(
        "export default function ChatArea() { return <div>chat</div>; }", encoding="utf-8")
    (src / "App.jsx").write_text(
        "import { Routes, Route } from 'react-router-dom';\n"
        f"import DirectMessagesPage from './pages/{import_from}';\n"
        "export default function App() {\n"
        "  return (<Routes><Route path=\"/direct\" element={<DirectMessagesPage/>} />"
        "</Routes>);\n}\n", encoding="utf-8")
    (src / "pages" / "DirectMessagesPage.jsx").write_text(
        (_FALLBACK % "DirectMessagesPage") if canonical_is_stub else _REAL, encoding="utf-8")
    if import_from != "DirectMessagesPage":
        (src / "pages" / f"{import_from}.jsx").write_text(
            _REAL if real_module else (_FALLBACK % "DirectMessagesPage"), encoding="utf-8")
    return src


class TheAppsOwnImportDecidesWhatIsGraded(unittest.TestCase):

    def test_the_real_page_behind_a_stub_is_not_a_fallback(self):
        ok, missing = audit_ui_page(_tree(), dict(_PAGE))
        self.assertFalse([m for m in missing if "framework fallback page" in m],
                         f"graded the orphan stub: {missing}")
        self.assertTrue(ok, missing)


class TheNarrowingHolds(unittest.TestCase):

    def test_a_stub_with_no_divergent_import_still_blocks(self):
        ok, missing = audit_ui_page(_tree(import_from="DirectMessagesPage"), dict(_PAGE))
        self.assertFalse(ok)
        self.assertTrue([m for m in missing if "framework fallback page" in m], missing)

    def test_a_divergent_import_that_is_also_a_stub_still_blocks(self):
        ok, missing = audit_ui_page(_tree(real_module=False), dict(_PAGE))
        self.assertFalse(ok)
        self.assertTrue([m for m in missing if "framework fallback page" in m], missing)

    def test_a_missing_import_target_falls_through_to_todays_behaviour(self):
        src = _tree()
        (src / "pages" / "DirectMessages.jsx").unlink()
        ok, missing = audit_ui_page(src, dict(_PAGE))
        self.assertFalse(ok)
        self.assertTrue([m for m in missing if "framework fallback page" in m], missing)

    def test_a_real_page_at_the_canonical_path_is_never_second_guessed(self):
        ok, missing = audit_ui_page(
            _tree(import_from="DirectMessagesPage", canonical_is_stub=False), dict(_PAGE))
        self.assertTrue(ok, missing)


if __name__ == "__main__":
    unittest.main()
