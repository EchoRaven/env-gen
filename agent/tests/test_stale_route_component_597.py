r"""#597: a route that IS wired, but to the component the contract used to name.

`project_missing_ui_routes` only ever INJECTS — it asks `_route_is_wired(route, app_jsx)` and
skips anything already present. `/login` IS present, pointing at the wrong file, so the drift it
cannot see is exactly the one that orphans the lane's work.

App.jsx is projected from the ui_pages contract at one moment; the contract's `component` can
change afterwards and the router is never re-projected. From the artifacts:

    r134  ui_page `login` updated 07:34:51 -> component `Login`, path .../Login.jsx
          App.jsx last written    07:09:15   (25 minutes EARLIER, still importing LoginPage)
    r115  ui_page `login` updated 00:50:23 -> component `Login`
          App.jsx last written    00:49:39   (44 s earlier)

The lane builds what the CONTRACT names and is silently unrouted. r134's orphaned `Login.jsx`
says so in its own comment — "the canonical /login page component declared in the ui_page
contract (name='login', component='Login')" — and composes AuthShell+AuthForm, while the router
keeps serving the framework's 72-line base template. r115's orphan is 162 lines with router
navigation, an auth service and a logo component.

Both were found with a STRUCTURAL arbiter (imported project components x2 + a services import +
react-router usage) run over all 23 forked `X.jsx`/`XPage.jsx` pairs in the arc: it agrees with
the router on 21 and disagrees on exactly these 2 — and on both it is right. Line count is NOT
the arbiter and would be wrong twice: r134's orphan is 17 lines (it delegates to two components)
and r134's `Landing.jsx` is a 3-line re-export shim.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    repair_stale_route_components_597 as repair,
)

_APP = """import React from 'react';
import LoginPage from './pages/LoginPage.jsx';
import BrowseHome from './pages/BrowseHome.jsx';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/browse" element={<BrowseHome />} />
      </Routes>
    </BrowserRouter>
  );
}
"""

_PAGES = [{"name": "login", "route": "/login", "component": "Login"},
          {"name": "browse_home", "route": "/browse", "component": "BrowseHome"}]


def _pages_dir(tmp_path, *names):
    d = tmp_path / "pages"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / f"{n}.jsx").write_text("export default function X(){return null}", encoding="utf-8")
    return d


# --- the r134/r115 shape ----------------------------------------------------------------------

def test_the_stale_import_and_element_are_both_rewritten(tmp_path):
    d = _pages_dir(tmp_path, "Login", "LoginPage", "BrowseHome")
    out, fixed = repair(_APP, _PAGES, d)
    assert fixed == [("LoginPage", "Login")]
    assert "import Login from './pages/Login.jsx';" in out
    assert "import LoginPage from" not in out
    assert '<Route path="/login" element={<Login />} />' in out


def test_the_route_that_was_already_correct_is_untouched(tmp_path):
    d = _pages_dir(tmp_path, "Login", "LoginPage", "BrowseHome")
    out, _ = repair(_APP, _PAGES, d)
    assert '<Route path="/browse" element={<BrowseHome />} />' in out
    assert out.count("import BrowseHome from './pages/BrowseHome.jsx';") == 1


def test_it_is_idempotent(tmp_path):
    d = _pages_dir(tmp_path, "Login", "LoginPage", "BrowseHome")
    once, _ = repair(_APP, _PAGES, d)
    twice, fixed2 = repair(once, _PAGES, d)
    assert fixed2 == [] and twice == once


# --- the guards that keep it from doing harm ----------------------------------------------------

def test_it_never_points_a_route_at_a_file_that_is_not_there(tmp_path):
    """The single most important guard: the contract can name a component nobody built."""
    d = _pages_dir(tmp_path, "LoginPage", "BrowseHome")      # no Login.jsx
    out, fixed = repair(_APP, _PAGES, d)
    assert fixed == [] and out == _APP


def test_an_unrelated_component_is_deliberate_wiring_not_drift(tmp_path):
    """Only the `Page`-suffix twin of the contract's component counts as drift."""
    app = _APP.replace("<LoginPage />", "<AuthGate />").replace(
        "import LoginPage from './pages/LoginPage.jsx';",
        "import AuthGate from './pages/AuthGate.jsx';")
    d = _pages_dir(tmp_path, "Login", "AuthGate", "BrowseHome")
    out, fixed = repair(app, _PAGES, d)
    assert fixed == [] and out == app


def test_a_page_with_no_route_or_no_component_is_skipped(tmp_path):
    d = _pages_dir(tmp_path, "Login", "LoginPage", "BrowseHome")
    for pg in ({"name": "x", "route": "", "component": "Login"},
               {"name": "x", "route": "/login", "component": ""},
               {"name": "x", "route": "/login", "component": "not an ident"}):
        assert repair(_APP, [pg], d)[1] == []


def test_a_route_the_router_does_not_carry_is_skipped(tmp_path):
    d = _pages_dir(tmp_path, "Profiles")
    assert repair(_APP, [{"route": "/profiles", "component": "Profiles"}], d)[1] == []


def test_junk_is_inert(tmp_path):
    d = _pages_dir(tmp_path, "Login")
    assert repair("", _PAGES, d) == ("", [])
    assert repair(_APP, [], d) == (_APP, [])
    assert repair(_APP, [None, "x", {}], d) == (_APP, [])
    assert repair(_APP, _PAGES, None) == (_APP, [])


# --- wiring ---------------------------------------------------------------------------------------

def test_it_runs_alongside_the_inject_pass_and_shares_its_write():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    src = inspect.getsource(fs)
    i = src.index("new_text, injected_routes = project_missing_ui_routes(existing, ui_pages)")
    window = src[i:i + 700]
    assert "repair_stale_route_components_597(" in window
    assert "if injected_routes or _recomped:" in window   # the repair alone must still write


def test_the_reason_the_inject_pass_cannot_see_this_is_documented():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    doc = inspect.getdoc(fs.repair_stale_route_components_597) or ""
    assert "_route_is_wired" in doc and "only ever INJECT" in doc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
