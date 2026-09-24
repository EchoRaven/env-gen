"""#238 (tiktok r27 M1, runtime-verified): the delivered app's own Profile and
Upload nav links (`<Link to="/profile">`, `to="/upload">`) resolved to NO
App.jsx route (only `/@:username` was wired) → clicking them hit the `*` 404.
A dead nav control is a functional break the existing gates miss (they check
DECLARED routes are wired, never that the app's own LINKS resolve)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (  # noqa: E402
    dead_nav_link_blockers,
)

_APP = """
import { BrowserRouter, Routes, Route } from 'react-router-dom';
export default function App() {
  return (<BrowserRouter><Routes>
    <Route path="/" element={<Feed />} />
    <Route path="/explore" element={<Explore />} />
    <Route path="/@:username" element={<Profile />} />
    <Route path="*" element={<div>404</div>} />
  </Routes></BrowserRouter>);
}
"""


def _mk(tmp_path, app=_APP, **pages):
    src = tmp_path / "src"
    (src).mkdir(parents=True)
    (src / "App.jsx").write_text(app)
    for name, body in pages.items():
        (src / f"{name}.jsx").write_text(body)
    return src


def test_dead_static_link_flagged(tmp_path):
    src = _mk(tmp_path, Nav='<Link to="/profile">Profile</Link>')
    b = dead_nav_link_blockers(src)
    assert len(b) == 1 and "/profile" in b[0] and "Nav.jsx" in b[0]


def test_wired_static_link_ok(tmp_path):
    src = _mk(tmp_path, Nav='<Link to="/explore">Explore</Link>')
    assert dead_nav_link_blockers(src) == []


def test_dynamic_route_matches_literal_target(tmp_path):
    # /@alice must satisfy the wired /@:username → NOT a dead link
    src = _mk(tmp_path, Nav='<Link to="/@alice">Alice</Link>')
    assert dead_nav_link_blockers(src) == []


def test_navigate_call_flagged(tmp_path):
    src = _mk(tmp_path, Nav="const go=()=>navigate('/settings')")
    b = dead_nav_link_blockers(src)
    assert len(b) == 1 and "/settings" in b[0]


def test_template_literal_skipped(tmp_path):
    # can't statically resolve `/@${user}` — never flag (avoids false blocks)
    src = _mk(tmp_path, Nav="<Link to={`/@${user}`}>u</Link>")
    assert dead_nav_link_blockers(src) == []


def test_external_and_hash_skipped(tmp_path):
    src = _mk(tmp_path, Nav=(
        '<a href="https://x.com/y">x</a>'
        '<Link to="mailto:a@b.c">m</Link>'
        '<Link to="#top">t</Link>'))
    assert dead_nav_link_blockers(src) == []


def test_query_and_trailing_slash_normalized(tmp_path):
    # /explore?tab=live and /explore/ both resolve to the wired /explore
    src = _mk(tmp_path, Nav='<Link to="/explore?tab=live">e</Link><Link to="/explore/">e2</Link>')
    assert dead_nav_link_blockers(src) == []


def test_catch_all_never_absorbs(tmp_path):
    # the `*` route must NOT make every link "resolve"
    src = _mk(tmp_path, Nav='<Link to="/nonexistent">x</Link>')
    assert len(dead_nav_link_blockers(src)) == 1


def test_dedupe_same_target(tmp_path):
    src = _mk(tmp_path, Nav='<Link to="/profile">P</Link><Link to="/profile">P2</Link>')
    assert len(dead_nav_link_blockers(src)) == 1


def test_missing_app_jsx_returns_empty(tmp_path):
    (tmp_path / "src").mkdir()
    assert dead_nav_link_blockers(tmp_path / "src") == []


def test_r27_regression_profile_and_upload(tmp_path):
    app = _APP.replace('<Route path="/explore"',
                       '<Route path="/videos" element={<V/>} />\n    <Route path="/explore"')
    src = _mk(tmp_path, app=app,
              SidebarNavigation='<Link to="/upload">Up</Link><Link to="/profile">Pr</Link>')
    b = dead_nav_link_blockers(src)
    targets = sorted(x.split('`')[1] for x in b)
    assert targets == ["/profile", "/upload"]
