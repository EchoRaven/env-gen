"""#1077 — the two halves of #913 disagree, and the audit half wedges the run.

`#913` (frontend_scaffold, the PROJECTOR) decides what a route carrying a query or
fragment means: it is a **STATE of the base path**, so when that base is already
claimed the record *"adds no route"* and its component is released. Its own comment
states the principle:

    One rule, one producer, and the other one wires it verbatim.

`#913b` (frontend_audit, the AUDITOR) then reads the same record and reports it
unimplemented — up to three ways at once, measured on the real corpus fixture below:

    `CommentsPanel` exists but NOT at the canonical path src/pages/CommentsPanel.jsx
    route `/?comments=1` carries a query/fragment and can NEVER match ...
    route `/?comments=1` not wired in App.jsx

`audit_ui_page` returns `(not missing), missing`, so each of those is a HARD block that
feeds `deliverability_ui_page_unwired`. None of them is fixable by writing code: the
record's route can only change by RE-REGISTRATION, while the projector has already
decided — correctly — that this record must not have a route of its own. #913b's own
comment says *"Reported, not hard: a contract typo should not wedge a run"*; the code
does the opposite of what the comment promises.

Corpus (67 runs carrying a ui_pages store): 9 records carry the shape, in **9 distinct
runs** — r35, r52, r54, r55, r74, r79, r86, r87, r89 — and it is the same shape every
time (`/?comments=1`, `/?comments=true`, `/?comments=1&video=:id`): a comments panel
registered as a query-state of the feed. It is the single largest reason today's auditor
reports a page unimplemented on those runs' delivered frontends (7 of 37).

The fix is the one FIX #146 already applies one line below — *the app is the authority on
where its screens live*. When the BASE path is wired, the record is audited with the
component semantics this function already implements (`_is_component`): look in
`src/components/`, do not demand a route of its own, do not apply the page-composes-page
rule. What replaces the route check is not nothing — a state must still be MOUNTED by
somebody, which is the real reachability question for an overlay.

Why not fix it at registration (normalize the route away): `register_ui_page` would then
route this shape into #593's alias-merge, whose `"component": component or existing…`
would overwrite the base page's ROOT component with the panel's. That path is unexercised
— **0 records in the whole corpus carry `merged_route_aliases`** — so normalizing there
would push a shape that recurs in 9 runs through code no run has ever run. Measured, then
rejected.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_audit import audit_ui_page  # noqa: E402

_APP_ROOT_WIRED = """
import { Routes, Route } from 'react-router-dom';
import FypFeedPage from './pages/FypFeedPage';
export default function App() {
  return (<Routes><Route path="/" element={<FypFeedPage/>} /></Routes>);
}
"""

_APP_ROOT_UNWIRED = """
import { Routes, Route } from 'react-router-dom';
import SearchPage from './pages/SearchPage';
export default function App() {
  return (<Routes><Route path="/search" element={<SearchPage/>} /></Routes>);
}
"""


def _fyp(mounts_panel: bool) -> str:
    mount = "{open && <CommentsPanel onClose={() => setOpen(false)} />}" if mounts_panel else ""
    return f"""
import {{ useEffect, useState }} from 'react';
import CommentsPanel from '../components/CommentsPanel';
export default function FypFeedPage() {{
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  useEffect(() => {{ fetch('/api/feed').then(r => r.json()).then(d => setItems(d.items || [])); }}, []);
  return (<div className="feed">
    {{items.map(v => <article key={{v.id}}><h2>{{v.title}}</h2>
      <button onClick={{() => setOpen(true)}}>Comments</button></article>)}}
    {mount}
  </div>);
}}
"""


_PANEL = """
import { useEffect, useState } from 'react';
export default function CommentsPanel({ onClose }) {
  const [rows, setRows] = useState([]);
  useEffect(() => { fetch('/api/comments').then(r => r.json()).then(d => setRows(d.items || [])); }, []);
  return (<aside className="panel">
    <button onClick={onClose}>Close</button>
    <ul>{rows.map(c => <li key={c.id}>{c.text}</li>)}</ul>
  </aside>);
}
"""

_PAGE = {"name": "comments_panel", "component": "CommentsPanel",
         "route": "/?comments=1", "apis_used": ["GET /api/comments"]}


def _tree(app_jsx: str, *, mounts_panel: bool = True, panel: str = _PANEL,
          panel_dir: str = "components") -> Path:
    src = Path(mkdtemp()) / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True, exist_ok=True)
    (src / "App.jsx").write_text(app_jsx, encoding="utf-8")
    (src / "pages" / "FypFeedPage.jsx").write_text(_fyp(mounts_panel), encoding="utf-8")
    (src / "pages" / "SearchPage.jsx").write_text(
        "export default function SearchPage() { return <div>search</div>; }", encoding="utf-8")
    if panel:
        (src / panel_dir / "CommentsPanel.jsx").write_text(panel, encoding="utf-8")
    return src


class AStateOfAWiredBaseIsNotABlocker(unittest.TestCase):
    """The corpus shape, on a frontend that genuinely delivers the feature."""

    def test_it_audits_clean(self):
        ok, missing = audit_ui_page(_tree(_APP_ROOT_WIRED), dict(_PAGE))
        self.assertTrue(ok, f"a mounted state of a wired base still blocks: {missing}")
        self.assertEqual(missing, [])

    def test_no_route_of_its_own_is_demanded(self):
        _, missing = audit_ui_page(_tree(_APP_ROOT_WIRED), dict(_PAGE))
        self.assertFalse([m for m in missing if "not wired in App.jsx" in m])
        self.assertFalse([m for m in missing if "can NEVER match" in m])

    def test_its_component_is_looked_for_under_components(self):
        """A state is an overlay its parent mounts — src/components/ IS its canonical home,
        so the page-layout rule must not fire on it."""
        _, missing = audit_ui_page(_tree(_APP_ROOT_WIRED), dict(_PAGE))
        self.assertFalse([m for m in missing if "canonical path" in m], missing)


class ButItStillHasToBeMounted(unittest.TestCase):
    """What replaces the route check. An overlay nobody renders is as dead as an
    unwired page — the reachability question just has a different answer for a state."""

    def test_an_unmounted_state_blocks(self):
        ok, missing = audit_ui_page(_tree(_APP_ROOT_WIRED, mounts_panel=False), dict(_PAGE))
        self.assertFalse(ok)
        self.assertTrue([m for m in missing if "CommentsPanel" in m and "mount" in m.lower()],
                        f"expected a 'never mounted' finding, got: {missing}")

    def test_a_missing_component_still_blocks(self):
        ok, missing = audit_ui_page(_tree(_APP_ROOT_WIRED, panel=""), dict(_PAGE))
        self.assertFalse(ok)
        self.assertTrue([m for m in missing if "not found" in m], missing)

    def test_an_unreferenced_declared_api_still_blocks(self):
        """The substantive checks are untouched — a state that declares an API and never
        calls it is still unimplemented.

        (This case replaced a `_page_dead_controls` assertion I wrote first. Measured, that
        helper returns False for this panel with AND without the handler, so the assertion
        would have passed only because the route messages were blocking — vacuous the moment
        they stopped. A check that cannot fail for the reason you named is not a check.)"""
        mute = _PANEL.replace("fetch('/api/comments')", "fetch('/api/unrelated')")
        ok, missing = audit_ui_page(_tree(_APP_ROOT_WIRED, panel=mute), dict(_PAGE))
        self.assertFalse(ok)
        self.assertTrue([m for m in missing if "never referenced" in m], missing)


class AnUnwiredBaseKeepsTodaysMessage(unittest.TestCase):
    """#913b is CORRECT and actionable when the base path is not claimed — that is the
    r153 case its comment records (`/browse?title=:id`, nothing at `/browse`). Only the
    projector-agrees branch changes."""

    def test_the_never_match_message_survives_verbatim(self):
        page = dict(_PAGE, route="/browse?title=:id")
        ok, missing = audit_ui_page(_tree(_APP_ROOT_UNWIRED), page)
        self.assertFalse(ok)
        hit = [m for m in missing if "can NEVER match" in m]
        self.assertTrue(hit, missing)
        self.assertIn("`/browse`", hit[0])


class PlainRoutesAreUntouched(unittest.TestCase):

    def test_a_normal_wired_page_still_passes(self):
        src = _tree(_APP_ROOT_WIRED)
        ok, missing = audit_ui_page(src, {"name": "fyp", "component": "FypFeedPage",
                                          "route": "/", "apis_used": ["GET /api/feed"]})
        self.assertTrue(ok, missing)

    def test_a_normal_unwired_page_still_blocks(self):
        src = _tree(_APP_ROOT_UNWIRED)
        ok, missing = audit_ui_page(src, {"name": "fyp", "component": "FypFeedPage",
                                          "route": "/", "apis_used": ["GET /api/feed"]})
        self.assertFalse(ok)
        self.assertTrue([m for m in missing if "not wired in App.jsx" in m], missing)


if __name__ == "__main__":
    unittest.main()
