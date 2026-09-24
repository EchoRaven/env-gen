"""#1202bx — #1182 must see a control the page RENDERS but does not DECLARE.

#1182 answers a "the control is not there" record with the markup that declares it, by
resolving the route to its page file. That is blind exactly when the page delegates its form
to a child: SearchPage.jsx renders <SearchBox/> and the <input> lives in
components/SearchBox.jsx, so the diagnosis came back empty and the generic remediation
stood. r35 died there (delivery gate, ui_flow:search, $174); r19 before it ($355, STUCK
after 18 ticks). Both apps had a correct, labelled input.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.remediation_dispatcher import (  # noqa: E402
    _page_controls_1182, _delegated_controls_1202bx, _controls_from_1182)

APP = """
import SearchPage from './pages/SearchPage.jsx';
<Route path="/search" element={<RequireAuth><SearchPage /></RequireAuth>} />
<Route path="/login" element={<LoginPage />} />
"""

# The real shape from r35: the page renders the child and declares nothing itself.
PAGE_DELEGATING = """
import SearchBox from '../components/SearchBox.jsx';
export default function SearchPage() {
  return <div><SearchBox value={query} onChange={updateQuery} /></div>;
}
"""

# The arrow function inside onChange is why a naive `<input\\b[^>]*>` truncates the tag
# before placeholder/aria-label — the trap #1182's brace-aware scanner already handles.
BOX = """
export default function SearchBox({ value, onChange }) {
  return <input type="search" autoFocus aria-label="Search titles"
    data-testid="search-input" placeholder="Search titles, people, genres"
    value={value} onChange={(e) => onChange?.(e.target.value)} />;
}
"""

PAGE_INLINE = """
export default function LoginPage() {
  return <form>
    <input type="text" name="email" placeholder="Email or phone number"
      onChange={(e) => setEmail(e.target.value)} />
  </form>;
}
"""


def _lay(tmp_path, pages: dict, components: dict, app=APP):
    src = tmp_path / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "App.jsx").write_text(app, encoding="utf-8")
    for n, body in pages.items():
        (src / "pages" / f"{n}.jsx").write_text(body, encoding="utf-8")
    for n, body in components.items():
        (src / "components" / f"{n}.jsx").write_text(body, encoding="utf-8")
    return tmp_path


def test_known_answer_the_child_declares_a_control_and_the_page_does_not():
    """Guard the fixtures: if these two ever stopped differing, every assertion below
    would pass for the wrong reason."""
    assert _controls_from_1182(PAGE_DELEGATING) == []
    assert _controls_from_1182(BOX)


def test_a_control_rendered_from_a_component_is_found(tmp_path):
    root = _lay(tmp_path, {"SearchPage": PAGE_DELEGATING}, {"SearchBox": BOX})
    comp, ctrls = _page_controls_1182(root, "/search")
    assert ctrls, "the input in SearchBox.jsx was not found"
    assert comp == "SearchBox", "must name the file that DECLARES it, not the page"


def test_the_attributes_a_walk_selects_by_survive(tmp_path):
    """The whole point is handing the verifier something to select on. The arrow function in
    onChange must not truncate the tag before these."""
    root = _lay(tmp_path, {"SearchPage": PAGE_DELEGATING}, {"SearchBox": BOX})
    _, ctrls = _page_controls_1182(root, "/search")
    got = ctrls[0]
    assert got.get("type") == "search"
    assert got.get("aria-label") == "Search titles"
    assert "Search titles" in got.get("placeholder", "")


def test_an_inline_page_is_unchanged(tmp_path):
    """No regression on the path that already worked: a page declaring its own control still
    reports the PAGE, and the child lookup never runs."""
    root = _lay(tmp_path, {"LoginPage": PAGE_INLINE}, {"SearchBox": BOX})
    comp, ctrls = _page_controls_1182(root, "/login")
    assert comp == "LoginPage" and len(ctrls) == 1
    assert ctrls[0]["name"] == "email"


def test_a_page_that_really_has_no_control_still_yields_nothing(tmp_path):
    """#1182 is deliberately not a gate discount — a record may be right. A page with no
    control anywhere must not acquire one from this."""
    root = _lay(tmp_path, {"SearchPage": "export default () => <div>nothing</div>;"},
                {"SearchBox": "export default () => <span/>;"})
    comp, ctrls = _page_controls_1182(root, "/search")
    assert ctrls == [] and comp == "SearchPage"


def test_a_component_that_is_imported_but_declares_nothing_is_skipped(tmp_path):
    page = ("import Banner from '../components/Banner.jsx';\n"
            "import SearchBox from '../components/SearchBox.jsx';\n"
            "export default () => <div><Banner/><SearchBox/></div>;")
    root = _lay(tmp_path, {"SearchPage": page},
                {"Banner": "export default () => <h1>hi</h1>;", "SearchBox": BOX})
    comp, ctrls = _page_controls_1182(root, "/search")
    assert comp == "SearchBox" and ctrls


def test_a_missing_component_file_does_not_raise(tmp_path):
    page = "import Gone from '../components/Gone.jsx';\nexport default () => <Gone/>;"
    root = _lay(tmp_path, {"SearchPage": page}, {})
    assert _page_controls_1182(root, "/search") == ("SearchPage", [])


def test_the_scan_is_bounded(tmp_path):
    """One level and capped: a page importing many components must not turn into a walk of
    the component graph."""
    many = "".join(f"import C{i} from '../components/C{i}.jsx';\n" for i in range(40))
    comps = {f"C{i}": "export default () => <span/>;" for i in range(40)}
    comps["C39"] = BOX  # past the cap, deliberately
    root = _lay(tmp_path, {"SearchPage": many + "export default () => <div/>;"}, comps)
    name, ctrls = _delegated_controls_1202bx(
        root / "app" / "frontend" / "src", many)
    assert (name, ctrls) == (None, [])
