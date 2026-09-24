"""FIX #151 — a route wired to a hardcoded-mock twin ships mock data (googlemaps run-3).

The frontend lane built BOTH a real API-calling page (SearchPage.jsx: useEffect +
api.searchPlaces) AND a static-mock twin (SearchResults.jsx: hardcoded rows), then wired
App.jsx's /search to the MOCK twin — leaving the real one an orphan. audit_ui_page checked
the DECLARED component (SearchPage, has a call → passed), never the component the route
ACTUALLY renders (SearchResults, mock). Every core Google Maps screen shipped mock while
the API version sat unimported. Same class as the A2b-2 dead-component fork, at page scale.

The gate: when a page declares non-empty apis_used and App.jsx wires its route to an
element that (a) has its own file, (b) is NOT the declared component, and (c) makes no api
call itself nor composes a child that does → flag it (the user sees a static mock).
Empty-apis pages and API-calling wired elements never flag. LOCAL-ONLY (agent/tests/).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_audit import audit_ui_page  # noqa: E402

APP_JSX_MOCK = """
import SearchResults from './pages/SearchResults';
import SearchPage from './pages/SearchPage';
export default function App() {
  return (<Routes><Route path="/search" element={<SearchResults />} /></Routes>);
}
"""
MOCK_COMP = "export default function SearchResults(){ return <div>HI Point Montara Lighthouse $165</div>; }"
API_COMP = ("import { api } from '../services/api';\n"
            "export default function SearchPage(){ const [r,setR]=useState([]);\n"
            "  useEffect(()=>{ api.searchPlaces({q:'x'}).then(setR); },[]);\n"
            "  return <div>{r.map(p=><div key={p.id}>{p.name}</div>)}</div>; }")


def _fe(tmp_path, files):
    fe = tmp_path / "app" / "frontend" / "src"
    (fe / "pages").mkdir(parents=True)
    for rel, txt in files.items():
        (fe / rel).write_text(txt)
    return fe


def _page(component, route, apis):
    return {"name": "search_page", "component": component, "route": route, "apis_used": apis}


def test_route_wired_to_mock_twin_is_flagged(tmp_path):
    fe = _fe(tmp_path, {"App.jsx": APP_JSX_MOCK,
                        "pages/SearchResults.jsx": MOCK_COMP,
                        "pages/SearchPage.jsx": API_COMP})
    ok, missing = audit_ui_page(fe, _page("SearchPage", "/search", ["GET /api/places/search"]))
    assert not ok
    assert any("SearchResults" in m and ("mock" in m.lower() or "does not call" in m.lower()
                                         or "static" in m.lower()) for m in missing), missing


def test_route_wired_to_api_component_passes(tmp_path):
    app = APP_JSX_MOCK.replace("<SearchResults />", "<SearchPage />")
    fe = _fe(tmp_path, {"App.jsx": app,
                        "pages/SearchResults.jsx": MOCK_COMP,
                        "pages/SearchPage.jsx": API_COMP})
    ok, missing = audit_ui_page(fe, _page("SearchPage", "/search", ["GET /api/places/search"]))
    assert not any("mock" in m.lower() or "static mock" in m.lower() for m in missing), missing


def test_empty_apis_page_not_flagged(tmp_path):
    # a legitimately static page (no declared data) must not trip this gate
    fe = _fe(tmp_path, {"App.jsx": APP_JSX_MOCK,
                        "pages/SearchResults.jsx": MOCK_COMP,
                        "pages/SearchPage.jsx": API_COMP})
    ok, missing = audit_ui_page(fe, _page("SearchPage", "/search", []))
    assert not any("mock" in m.lower() for m in missing), missing


def test_wired_element_composing_api_child_passes(tmp_path):
    app = APP_JSX_MOCK.replace("<SearchResults />", "<SearchResults />")
    mock_composes = ("import ResultList from '../components/ResultList';\n"
                     "export default function SearchResults(){ return <ResultList/>; }")
    fe = _fe(tmp_path, {"App.jsx": app,
                        "pages/SearchResults.jsx": mock_composes,
                        "pages/SearchPage.jsx": API_COMP})
    (fe / "components").mkdir()
    (fe / "components" / "ResultList.jsx").write_text(API_COMP.replace("SearchPage", "ResultList"))
    ok, missing = audit_ui_page(fe, _page("SearchPage", "/search", ["GET /api/places/search"]))
    assert not any("mock" in m.lower() for m in missing), missing


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── #151b: the mock-twin defect must be a DELIVERY BLOCKER (hard miss), not just a status ──
class _WH:
    def __init__(self, pages): self._p = pages
    def get_ui_pages(self): return self._p


def test_mock_twin_is_a_delivery_blocker(tmp_path):
    from multi_agent.runtime.frontend_audit import ui_page_delivery_blockers
    fe = _fe(tmp_path, {"App.jsx": APP_JSX_MOCK,
                        "pages/SearchResults.jsx": MOCK_COMP,
                        "pages/SearchPage.jsx": API_COMP})
    wh = _WH({"search_page": _page("SearchPage", "/search", ["GET /api/places/search"])})
    blockers = ui_page_delivery_blockers(fe, wh)
    assert any("STATIC MOCK" in b or "static mock" in b.lower() for b in blockers), blockers


def test_api_wired_page_is_not_a_delivery_blocker(tmp_path):
    from multi_agent.runtime.frontend_audit import ui_page_delivery_blockers
    app = APP_JSX_MOCK.replace("<SearchResults />", "<SearchPage />")
    fe = _fe(tmp_path, {"App.jsx": app,
                        "pages/SearchResults.jsx": MOCK_COMP,
                        "pages/SearchPage.jsx": API_COMP})
    wh = _WH({"search_page": _page("SearchPage", "/search", ["GET /api/places/search"])})
    blockers = ui_page_delivery_blockers(fe, wh)
    assert not any("mock" in b.lower() for b in blockers), blockers
