"""FIX #222 — the page audit must see CONTENT, not strippable markers.

r18 (log-verified): the audit credited freshly-projected generic fallbacks as
implemented at birth (impl.page.* auto-completed minutes after kickoff), and
the lane's cheapest path to green was GAMING — stripping the _PAGE_MARKER
comment and the data-fallback attribute, tweaking API-call formats — instead
of building pages. Now:

- a GENERIC framework fallback (marker, attr, OR marker-stripped content
  fingerprint: the projection helper constellation + the generic list shell)
  is a HARD audit miss ("framework fallback page") → never credited, and it
  rides the existing ui_page_unwired deliverability channel;
- a #221 REFERENCE-STRUCTURED projection passes the audit (a genuine floor);
- a real lane-authored page passes as before.
LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _project_page_component,
)
from multi_agent.runtime.frontend_audit import (  # noqa: E402
    audit_ui_page, _is_hard_miss,
)


def _write(fe_src: Path, name: str, text: str):
    (fe_src / "pages").mkdir(parents=True, exist_ok=True)
    (fe_src / "pages" / f"{name}.jsx").write_text(text, encoding="utf-8")
    (fe_src / "App.jsx").write_text(
        f"import {name} from './pages/{name}';\n"
        "export default function App() {\n"
        f"  return (<Routes><Route path=\"/items\" element={{<{name} />}} /></Routes>);\n"
        "}\n", encoding="utf-8")


_PAGE = {"name": "items_page", "component": "ItemsPage", "route": "/items",
         "apis_used": ["GET /api/items"]}


def _generic_fallback() -> str:
    return _project_page_component("ItemsPage", _PAGE, nav_routes=[("Items", "/items")])


def _strip_markers(text: str) -> str:
    """The lane's exact r18 gaming moves: drop framework comments + the
    data-fallback attribute, keep the body."""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("//")]
    out = "\n".join(lines)
    return out.replace(' data-fallback="1"', "")


def test_generic_fallback_is_hard_miss(tmp_path):
    fe = tmp_path / "src"
    _write(fe, "ItemsPage", _generic_fallback())
    ok, missing = audit_ui_page(fe, _PAGE)
    assert not ok
    assert any("framework fallback page" in m for m in missing)
    assert any(_is_hard_miss(m) for m in missing)


def test_marker_stripped_fallback_still_hard_miss(tmp_path):
    """Comment/attr stripping (the r18 gaming) must not flip the verdict."""
    fe = tmp_path / "src"
    _write(fe, "ItemsPage", _strip_markers(_generic_fallback()))
    ok, missing = audit_ui_page(fe, _PAGE)
    assert not ok
    assert any("framework fallback page" in m for m in missing)


def test_reference_structured_projection_passes(tmp_path):
    """A #221 structured projection is a genuine floor — audit-green."""
    screen = {"name": "items", "route": "/items", "kind": "page",
              "components": [
                  {"id": "side-nav", "region": [0.0, 0.0, 0.17, 1.0],
                   "role": "Vertical navigation menu", "colors": {},
                   "assets": [], "state": "", "build_notes": ""},
                  {"id": "item-list", "region": [0.2, 0.05, 1.0, 1.0],
                   "role": "List of items", "colors": {}, "assets": [],
                   "state": "", "build_notes": ""}]}
    design = {"design_system": {"palette": {"bg": "#000000", "accent": "#fe2c55"},
                                "theme": {"default": "dark"}},
              "screens": [screen]}
    from multi_agent.runtime.frontend_scaffold import _render_reference_page
    body = _render_reference_page("ItemsPage", _PAGE, screen, design,
                                  [("Items", "/items")], "/api/items")
    fe = tmp_path / "src"
    _write(fe, "ItemsPage", body)
    ok, missing = audit_ui_page(fe, _PAGE)
    assert ok, missing


def test_lane_real_page_passes(tmp_path):
    fe = tmp_path / "src"
    _write(fe, "ItemsPage", """
import { useEffect, useState } from 'react';
export default function ItemsPage() {
  const [items, setItems] = useState([]);
  useEffect(() => { fetch('/api/items').then(r => r.json()).then(d => setItems(d.items)); }, []);
  return (<div>{items.map(it => <div key={it.id}><b>{it.title}</b><span>{it.owner_name}</span></div>)}</div>);
}
""")
    ok, missing = audit_ui_page(fe, _PAGE)
    assert ok, missing


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_routed_fallback_sweep_catches_unregistered_pages(tmp_path):
    """#223 — a fallback page ROUTE-WIRED in App.jsx but never registered as a
    ui_page is invisible to ui_page_delivery_blockers (it iterates the
    registry). The sweep catches it from code truth alone."""
    from multi_agent.runtime.frontend_audit import routed_fallback_page_blockers
    fe = tmp_path / "src"
    body = _strip_markers(_generic_fallback())
    _write(fe, "ItemsPage", body)   # wires /items in App.jsx, no registry
    blockers = routed_fallback_page_blockers(fe)
    assert blockers and any("ItemsPage" in b and "framework fallback page" in b
                            for b in blockers)


def test_routed_fallback_sweep_ignores_structured_and_lane_pages(tmp_path):
    from multi_agent.runtime.frontend_audit import routed_fallback_page_blockers
    fe = tmp_path / "src"
    _write(fe, "ItemsPage", """
import { useEffect, useState } from 'react';
export default function ItemsPage() {
  const [items, setItems] = useState([]);
  useEffect(() => { fetch('/api/items').then(r => r.json()).then(d => setItems(d.items)); }, []);
  return (<div>{items.map(it => <b key={it.id}>{it.title}</b>)}</div>);
}
""")
    assert routed_fallback_page_blockers(fe) == []


def test_deliverability_token_for_fallback_sweep():
    from multi_agent.runtime.delivery_gate import _deliverability_check_token
    tok = _deliverability_check_token(
        "route /items renders a framework fallback page (`ItemsPage`) — author the real page")
    assert tok == "deliverability_frontend_fallback_page"
    # the registered-page path keeps its existing token
    tok2 = _deliverability_check_token(
        "ui_page `items_page` declared but unusable: component `ItemsPage` is a "
        "framework fallback page (generic list)")
    assert tok2 == "deliverability_ui_page_unwired"
