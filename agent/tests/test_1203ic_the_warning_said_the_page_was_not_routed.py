"""#1203ic: #1203fh told the lane its auth page was not routed, while it was serving.

`#1203fh` fires 17-70 times per run and says, for every ui_page it drops off /login or
/signup:

    the page file (if any) is not routed and the registry record still says it is

That is only true while the framework still owns App.jsx. The rewrite is guarded by
`(not existing.strip()) or (_ROUTES_MARKER in existing) or ("</Routes>" not in existing)`,
so once the lane drops `@framework-managed-routes` and keeps a real `</Routes>`, the
projection stops writing App.jsx back -- and `scaffold_missing_local_pages` only fills
MISSING files (`if target.exists(): continue`, with #488's stub-fill "guarded so a REAL
page is NEVER clobbered"). The lane's auth page is then what React Router renders.

Measured over r170, r177, r181, r182, r183: the marker is absent 5/5,
`element={<LoginPage` is present 5/5, and `pages/LoginPage.jsx` is lane-authored 5/5
(124-565 bytes, importing the lane's own `components/` and `services/api`).

r183's cost, on record: told its page was not routed, the lane put `preventDefault`
`switchAuthRoute` anchors in its own components/TikTokUI.jsx, a capture-phase
`forceAuthRouteSwitch` in App.jsx and a `route-switch-sentinel` anchor -- three
workarounds aimed away from the live page -- and died on `2 critical UI flow(s) failed:
login_page, signup_page` after `7 consecutive cycles with NO source/contract/chain
change`. 8 of the 16 runs that die on a ui_flow blocker involve login/signup.

The DROP itself is untouched: #1203fh's own note says "The drop is right; it was silent".
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _ROUTES_MARKER,
    auth_route_is_served_by_lane_1203ic as served,
)

# r183's App.jsx, reduced to the parts the predicate reads (lane-owned: no marker,
# real </Routes>, routes the lane's LoginPage).
LANE_APP = """import { BrowserRouter, Routes, Route } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import SignupPage from './pages/SignupPage';
export default function App() {
  return <BrowserRouter><Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route path="/signup" element={<SignupPage />} />
  </Routes></BrowserRouter>;
}
"""


_N = [0]


def _fe(tmp_path, app_src=LANE_APP, write=True):
    """A fresh frontend root per call -- several cases live in one test function, and
    reusing the directory raised FileExistsError rather than testing anything."""
    _N[0] += 1
    root = tmp_path / ("case%d" % _N[0]) / "app" / "frontend"
    (root / "src").mkdir(parents=True)
    if write:
        (root / "src" / "App.jsx").write_text(app_src, encoding="utf-8")
    return root


def test_a_lane_owned_app_jsx_means_the_page_IS_served(tmp_path):
    """r183's actual shape. This is the case the old sentence got wrong."""
    fe = _fe(tmp_path)
    assert served(fe, "LoginPage").endswith("App.jsx")
    assert served(fe, "SignupPage").endswith("App.jsx")


def test_the_framework_marker_means_it_is_NOT_served(tmp_path):
    """The case #1203fh's original wording describes: the marker is still there, so the
    next projection rewrites App.jsx and the lane's page really will not be routed."""
    fe = _fe(tmp_path, LANE_APP.replace(
        "import { BrowserRouter", _ROUTES_MARKER + "\nimport { BrowserRouter"))
    assert served(fe, "LoginPage") == ""


def test_no_closing_routes_means_it_is_NOT_served(tmp_path):
    """Third arm of the writer's own guard: without `</Routes>` the projection rewrites."""
    assert served(_fe(tmp_path, LANE_APP.replace("</Routes>", "")), "LoginPage") == ""


def test_an_empty_or_absent_app_jsx_means_it_is_NOT_served(tmp_path):
    assert served(_fe(tmp_path, "   \n"), "LoginPage") == ""
    assert served(_fe(tmp_path, write=False), "LoginPage") == ""


def test_a_component_app_jsx_does_not_route_is_not_claimed(tmp_path):
    """The predicate must name the component, not just read a lane-owned App.jsx --
    otherwise it would claim a page is served whenever the lane owns the router."""
    assert served(_fe(tmp_path), "LoginModalPage") == ""


def test_the_route_element_spellings_all_count(tmp_path):
    """`element={<LoginPage/>}` and `element={<LoginPage />}` are the same thing; a
    predicate that only matched one spelling would be false for half the corpus."""
    for spelling in ("element={<LoginPage/>}", "element={<LoginPage />}",
                     "element={<LoginPage></LoginPage>}"):
        fe = _fe(tmp_path, LANE_APP.replace("element={<LoginPage />}", spelling))
        assert served(fe, "LoginPage"), spelling


def test_failure_keeps_the_original_wording(tmp_path):
    """Best-effort by design: on any failure the predicate returns "", which keeps
    #1203fh's original sentence -- correct whenever the framework does own the routes.
    A directory where App.jsx should be is the cheapest way to make the read raise."""
    root = tmp_path / "raise" / "app" / "frontend"
    (root / "src" / "App.jsx").mkdir(parents=True)
    assert served(root, "LoginPage") == ""
    assert served(None, "LoginPage") == ""
    assert served(root, "") == ""


def test_the_scaffolder_branches_on_it():
    """The predicate exists to change a SENTENCE; pin that the caller actually branches,
    and that the original wording survives for the framework-owned case."""
    import pathlib
    src = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/runtime/scaffolder.py"
    ).read_text(encoding="utf-8")
    assert "auth_route_is_served_by_lane_1203ic" in src
    # asserted within ONE source line: the message is a split string literal, so a
    # phrase spanning the break is absent from the file even though it reaches the log.
    assert "IS what serves this route" in src
    # the framework-owned branch must still say the original thing
    assert "the page file (if any) is not routed" in src
    # and the DROP itself must be intact. #1203fh's note says "The drop is right; it was
    # silent", so a future reader who tries to fix this ticket by keeping the lane's
    # record instead of correcting the sentence should go red here. (The first draft of
    # this assertion searched for the symbol in the scaffolder and failed on my own
    # comment -- it proved nothing either way.)
    fs = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py"
    ).read_text(encoding="utf-8")
    assert '{"id": "login_page", "route": "/login", "component": "LoginPage"' in fs
    assert "return auth + kept" in fs


def test_the_new_sentence_is_reachable_not_merely_present():
    """★ THE GUARD. Replacing `if _served1203ic:` with `if False:` -- i.e. always emitting
    the old, false sentence -- passed every other test in this file, because they only
    assert that the strings EXIST in the source. #1202w1's rule: a name appearing is not a
    name being used; pin its POSITION with AST.

    The new wording has to sit in the body of an `if` whose test is the predicate's
    result, and the old wording in that same `if`'s `else`."""
    import ast
    import pathlib

    src = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/runtime/scaffolder.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _text(nodes):
        return " ".join(
            n.value for node in nodes for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str))

    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = ast.get_source_segment(src, node.test) or ""
        if test.strip() != "_served1203ic":
            continue
        body, orelse = _text(node.body), _text(node.orelse)
        assert "IS what serves this route" in body, (
            "the corrected sentence is not in the TRUE branch of `if _served1203ic:`")
        assert "is not routed" in orelse, (
            "the framework-owned case lost its original (correct) wording")
        assert "IS what serves this route" not in orelse
        found = True
    assert found, (
        "no `if _served1203ic:` guards the warning — the predicate is computed and then "
        "ignored, which is how the old sentence would keep shipping")
