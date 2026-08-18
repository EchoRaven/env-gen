r"""#938: the remediation task named a screen and a route, and left the FILE to the lane.

The per-screen header was `## {name}  (route {route}, similarity {sim})`. App.jsx is the source of
truth for what renders a route — `frontend_audit._route_element` says so in those words — and the
framework has parsed it since #566e, so the path costs a file read.

★ It found a mistake of mine on its first run, which is the best argument for it. Diagnosing r154's
flat login score I grepped for `LoginPage.jsx`, found `components/LoginPage.jsx` (2 commits in 148
minutes) and concluded the loop was editing the wrong things. App.jsx line 7 says
`import LoginPage from './pages/LoginPage.jsx'` — a DIFFERENT file, with **39 commits**. The
component I traced was an orphan re-export nothing imports. If a full-time reader of this codebase
resolves that wrong, a lane with one task description will too.

Omitted, never guessed: a task that names the wrong file is worse than one that names none — the
lane edits it, sees no change, and concludes the measurement is broken. That is exactly the
inference #934 caught me making from the other end.
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import _component_file_938


def _tree(tmp_path, app_jsx, files=()):
    src = tmp_path / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "App.jsx").write_text(app_jsx, encoding="utf-8")
    for f in files:
        (src / f).write_text("export default function X(){return null}", encoding="utf-8")
    return tmp_path


_APP = """
import LoginPage from './pages/LoginPage.jsx';
import BrowseHome from './pages/BrowseHome';
import { Shell } from './components/Shell.jsx';
export default function App(){ return (
  <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route path="/browse" element={<Protected><BrowseHome/></Protected>} />
    <Route path="/shell" element={<Shell />} />
  </Routes>); }
"""


def test_it_names_the_routed_file(tmp_path):
    t = _tree(tmp_path, _APP, ["pages/LoginPage.jsx"])
    assert _component_file_938(t, "/login") == "app/frontend/src/pages/LoginPage.jsx"


def test_it_is_not_fooled_by_a_same_named_orphan(tmp_path):
    """★ r154 exactly: components/LoginPage.jsx exists and is imported by nobody."""
    t = _tree(tmp_path, _APP, ["pages/LoginPage.jsx", "components/LoginPage.jsx"])
    assert _component_file_938(t, "/login") == "app/frontend/src/pages/LoginPage.jsx"


def test_an_extensionless_import_resolves(tmp_path):
    t = _tree(tmp_path, _APP, ["pages/BrowseHome.jsx"])
    assert _component_file_938(t, "/browse") == "app/frontend/src/pages/BrowseHome.jsx"


def test_a_guard_wrapper_does_not_hide_the_page(tmp_path):
    """`element={<Protected><BrowseHome/></Protected>}` must resolve to the PAGE."""
    t = _tree(tmp_path, _APP, ["pages/BrowseHome.jsx"])
    assert "BrowseHome" in (_component_file_938(t, "/browse") or "")


def test_a_named_import_resolves(tmp_path):
    t = _tree(tmp_path, _APP, ["components/Shell.jsx"])
    assert _component_file_938(t, "/shell") == "app/frontend/src/components/Shell.jsx"


def test_an_unknown_route_says_nothing(tmp_path):
    assert _component_file_938(_tree(tmp_path, _APP, ["pages/LoginPage.jsx"]), "/nope") is None


def test_a_missing_file_says_nothing_rather_than_a_path(tmp_path):
    """★ The rule: no guess. The import exists, the file does not."""
    assert _component_file_938(_tree(tmp_path, _APP), "/login") is None


def test_a_package_import_says_nothing(tmp_path):
    t = _tree(tmp_path, "import Login from 'some-pkg';\n<Route path=\"/login\" element={<Login />} />")
    assert _component_file_938(t, "/login") is None


def test_no_app_jsx_no_crash(tmp_path):
    assert _component_file_938(tmp_path, "/login") is None
    assert _component_file_938(None, "/login") is None
    assert _component_file_938(tmp_path, None) is None


def test_the_header_carries_it(tmp_path):
    """End-to-end through remediation_text, not a source-string check."""
    from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import remediation_text
    t = _tree(tmp_path, _APP, ["pages/LoginPage.jsx"])
    out = remediation_text({"screens": [{"name": "login", "route": "/login", "similarity": 0.5,
                                         "passed": False, "dimensions": {}, "deviations": ["x"],
                                         "fixes": [], "summary": ""}]}, t)
    assert "app/frontend/src/pages/LoginPage.jsx" in out, out[:400]


def test_the_header_omits_it_when_unresolvable(tmp_path):
    from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import remediation_text
    out = remediation_text({"screens": [{"name": "login", "route": "/login", "similarity": 0.5,
                                         "passed": False, "dimensions": {}, "deviations": ["x"],
                                         "fixes": [], "summary": ""}]}, tmp_path)
    assert "edit:" not in out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
