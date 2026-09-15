"""#1202mp: four framework projections that re-applied the same stale diff after every merge.

tiktok-r124, `app/frontend` on the integration branch: 61 `merge agent/frontend` commits, each
followed by a `framework delivery: backend skeleton + frontend infra + projections` commit.
Of the 276 lane-owned file changes those delivery commits made, 191 restored the file to its
exact content from BEFORE the merge. The lane fixed; the framework undid it; the lane fixed
it again. The run log names the writers, and each one reproduces on the real tree:

  1. `repair_fabricated_fallbacks` (#175 heal) turned `following ? 'Following' : busy` into
     `following ? '—' : busy` — a button label, not a fallback for a missing field.
  2. `scaffold_pages_from_contract` wrote three page files that nothing imports (two records
     had `route=''`, one sat at a path the lane serves with its own page) and linked their
     name-derived routes from every projected sidebar. The lane deleted them; they came back.
  3. `project_missing_ui_routes` injected `/?comments=<video_id>` — a route that can never
     match — while App.jsx already routed `/`.
  4. `_dominant_route_wrapper` took the first identifier of `element={<ProfileOwnPage />}` for
     a wrapper, so injected routes shipped as `<ProfileOwnPage><X /></ProfileOwnPage>`.

Running HEAD's `scaffold_pages_from_contract` on the tree right after the merge (9b08c1a)
reproduces that delivery commit exactly: the same three files and the same two App.jsx lines.
With the fix it writes nothing and injects one bare `/:username`, and a second pass is a no-op.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import frontend_audit as FA  # noqa: E402
from multi_agent.runtime import frontend_scaffold as FS  # noqa: E402


def _heal(line):
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "components" / "X.jsx"
        f.parent.mkdir()
        f.write_text(line + "\n", encoding="utf-8")
        out = FA.repair_fabricated_fallbacks(Path(tmp))
        return f.read_text(encoding="utf-8").rstrip("\n"), out


# ── 1. the heal ────────────────────────────────────────────────────────────────────────────

R124_BUTTON = ("<button className=\"follow-btn\" type=\"button\" onClick={follow} "
               "disabled={busy || following}>{following ? 'Following' : busy ? "
               "'Following…' : 'Follow'}</button>")


def test_r124s_follow_button_label_survives_the_heal():
    after, out = _heal(R124_BUTTON)
    assert after == R124_BUTTON, out


def test_a_label_chain_that_compares_the_value_is_not_a_fallback():
    # 124 of the corpus's rewritten ternaries are this shape (`? '—' : mode` / `: kind`).
    for line in ("{mode === 'movies' ? 'Movies' : mode === 'games' ? 'Games' : 'TV Shows'}",
                 "const label = mode === 'genre' ? 'Sports TV Shows' : mode;",
                 "{'genre' === mode ? 'Sports TV Shows' : mode}",
                 "<Action count={shared ? 'Copied' : fmt(video?.share_count)} />"):
        after, out = _heal(line)
        assert after == line, (line, out)


def test_a_condition_that_tests_for_absence_is_still_a_fallback():
    for line, want in (
            ("{raw ? raw : 'haibotong7'}", "{raw ? raw : '—'}"),
            ("{!user ? 'Jane Doe' : user}", "{!user ? '—' : user}"),
            ("{user == null ? 'Jane Doe' : user}", "{user == null ? '—' : user}"),
            ("{!v.caption ? 'some caption here' : v.caption}",
             "{!v.caption ? '—' : v.caption}")):
        after, out = _heal(line)
        assert after == want, (line, after, out)


def test_the_checker_flagged_form_is_still_cleared_so_the_gate_stays_clearable():
    """#496's round-trip invariant: the member-access false branch is flagged by the checker
    without looking at the condition, so the heal must keep rewriting it."""
    line = "{sel ? selectedPlace.name : 'HI Point Montara Lighthouse'}"
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "components" / "X.jsx"
        f.parent.mkdir()
        f.write_text("export default function X(){return <p>" + line + "</p>}\n")
        assert len(FA.invented_field_fallback_blockers(Path(tmp))) == 1
        FA.repair_fabricated_fallbacks(Path(tmp))
        assert FA.invented_field_fallback_blockers(Path(tmp)) == []


def test_a_number_is_not_a_value_that_can_be_absent():
    # `16.5` matches the member-access shape `a.b`, so only the digit check keeps it.
    line = "<aside style={{ width: compact ? 16.5 : 'Sidebar Width' }} />"
    after, out = _heal(line)
    assert after == line, out


def test_the_mirror_literal_cannot_run_across_its_closing_quote():
    """The corpus has `? 'active':''} ${it==='Following'...?'/' : it` rewritten as ONE literal."""
    rx = FA._HEAL_TERNARY_TRUE
    m = rx.search("x ? 'active':''} ${it==='Following'?'hovered':''} href={it==='For You'?'/' : it")
    assert m is None or "'" not in m.group(2), m.group(0)


def test_the_condition_scan_stops_where_the_expression_does():
    c = FA._ternary_condition_1202mp
    assert c("disabled={busy || following}>{following ").strip() == "following"
    assert c("const label = mode === 'genre' ").strip() == "mode === 'genre'"
    assert c("xs.map((v) => !v.caption ").strip() == "!v.caption"
    assert c("f(a, b && user ").strip() == "b && user"


# ── 3 & 4. route injection ────────────────────────────────────────────────────────────────

LANE_APP = """import { BrowserRouter, Routes, Route } from 'react-router-dom';
import FeedPage from './pages/FeedPage.jsx';
import ProfilePage from './pages/ProfilePage.jsx';
export default function App() {
  return (<BrowserRouter><Routes>
        <Route path="/" element={<FeedPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/me" element={<ProfilePage />} />
  </Routes></BrowserRouter>);
}
"""


def test_a_bare_route_element_is_not_a_wrapper():
    assert FS._dominant_route_wrapper(LANE_APP) is None


def test_a_real_wrapper_is_still_found():
    app = LANE_APP.replace("<FeedPage />", "<Guard><FeedPage /></Guard>").replace(
        'element={<ProfilePage />} />\n        <Route path="/me"',
        'element={<Guard><ProfilePage /></Guard>} />\n        <Route path="/me"')
    app = app.replace("import FeedPage", "import Guard from './Guard.jsx';\nimport FeedPage")
    assert FS._dominant_route_wrapper(app) == "Guard"


def test_a_query_route_is_a_state_of_a_path_the_lane_already_routes():
    new, injected = FS.project_missing_ui_routes(
        LANE_APP, [{"route": "/?comments=<video_id>", "component": "CommentsPage"}])
    assert injected == [] and new == LANE_APP


def test_a_query_route_whose_base_is_unrouted_injects_the_base_only():
    app = LANE_APP.replace('        <Route path="/" element={<FeedPage />} />\n', "")
    new, injected = FS.project_missing_ui_routes(
        app, [{"route": "/?comments=<video_id>", "component": "CommentsPage"}])
    assert injected == ["/"]
    assert '<Route path="/" element={<CommentsPage />} />' in new
    assert "?comments" not in new


def test_an_at_param_route_is_wired_once_and_then_recognised():
    pages = [{"route": "/@:username", "component": "ProfilePage"}]
    once, injected = FS.project_missing_ui_routes(LANE_APP, pages)
    assert injected == ["/@:username"]
    assert '<Route path="/:username" element={<ProfilePage />} />' in once
    twice, again = FS.project_missing_ui_routes(once, pages)
    assert again == [] and twice == once


# ── 2. orphan pages and dead nav links ─────────────────────────────────────────────────────

MINI_APP = """import { BrowserRouter, Routes, Route } from 'react-router-dom';
import FeedPage from './pages/FeedPage.jsx';
import ExplorePage from './pages/ExplorePage.jsx';
import FollowingPage from './pages/FollowingPage.jsx';
export default function App() {
  return (<BrowserRouter><Routes>
        <Route path="/" element={<FeedPage />} />
        <Route path="/explore" element={<ExplorePage />} />
        <Route path="/following" element={<FollowingPage />} />
  </Routes></BrowserRouter>);
}
"""

MINI_PAGES = [
    {"id": "feed", "name": "feed", "route": "/", "component": "FeedPage",
     "apis_used": ["/api/videos"]},
    {"id": "explore", "name": "explore", "route": "/explore", "component": "ExplorePage",
     "apis_used": ["/api/videos"]},
    # r124's three shapes: served by the lane's own page, and two with no route at all
    {"id": "following_suggested_creators", "name": "following_suggested_creators",
     "route": "/following", "component": "", "apis_used": ["/api/creators"]},
    {"id": "friends_suggested_creators", "name": "friends_suggested_creators",
     "route": "", "component": "", "apis_used": ["/api/creators"]},
    {"id": "inbox", "name": "inbox", "route": "/inbox", "component": "InboxPage",
     "apis_used": ["/api/messages"]},
]


def _mini(tmp, app_text=MINI_APP):
    fe = Path(tmp) / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "App.jsx").write_text(app_text, encoding="utf-8")
    for name in ("FeedPage", "FollowingPage"):
        (fe / "src" / "pages" / f"{name}.jsx").write_text(
            f"export default function {name}(){{return <div/>}}\n", encoding="utf-8")
    return fe


def _hrefs(fe):
    return {h for f in (fe / "src" / "pages").glob("*.jsx")
            for h in re.findall(r'href="(/[^"]*)"', f.read_text(encoding="utf-8"))}


def test_a_page_nobody_routes_is_not_written_when_the_lane_owns_the_router():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mini(tmp)
        rep = FS.scaffold_pages_from_contract(fe, MINI_PAGES)
        pages = set(os.listdir(fe / "src" / "pages"))
        assert "FriendsSuggestedCreators.jsx" not in pages, rep
        assert "FollowingSuggestedCreators.jsx" not in pages, rep
        assert set(rep["orphan_pages_not_written"]) == {
            "FriendsSuggestedCreators", "FollowingSuggestedCreators"}


def test_a_page_the_router_needs_is_still_written():
    """ExplorePage is imported by the lane's App.jsx; InboxPage's route gets injected."""
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mini(tmp)
        rep = FS.scaffold_pages_from_contract(fe, MINI_PAGES)
        pages = set(os.listdir(fe / "src" / "pages"))
        assert {"ExplorePage.jsx", "InboxPage.jsx"} <= pages, rep
        assert "/inbox" in rep["injected_routes"]


def test_projected_pages_link_only_to_routes_the_router_serves():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mini(tmp)
        FS.scaffold_pages_from_contract(fe, MINI_PAGES)
        hrefs = _hrefs(fe)
        assert "/explore" in hrefs, hrefs   # the nav is still there
        assert "/friends-suggested-creators" not in hrefs, hrefs


def test_a_page_another_file_imports_is_written():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mini(tmp)
        (fe / "src" / "pages" / "FollowingPage.jsx").write_text(
            "import Suggested from './FriendsSuggestedCreators';\n"
            "export default function FollowingPage(){return <Suggested/>}\n", encoding="utf-8")
        FS.scaffold_pages_from_contract(fe, MINI_PAGES)
        assert (fe / "src" / "pages" / "FriendsSuggestedCreators.jsx").exists()


def test_a_framework_router_still_gets_every_page():
    """Regenerated App.jsx wires every entry, so nothing is an orphan there."""
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mini(tmp, app_text="")
        rep = FS.scaffold_pages_from_contract(fe, MINI_PAGES)
        assert rep["app_wired"] is True
        assert rep["orphan_pages_not_written"] == []
        assert (fe / "src" / "pages" / "FriendsSuggestedCreators.jsx").exists()


def test_the_second_pass_is_a_no_op():
    with tempfile.TemporaryDirectory() as tmp:
        fe = _mini(tmp)
        FS.scaffold_pages_from_contract(fe, MINI_PAGES)
        before = {f.name: f.read_text(encoding="utf-8") for f in (fe / "src").rglob("*.jsx")}
        rep = FS.scaffold_pages_from_contract(fe, MINI_PAGES)
        after = {f.name: f.read_text(encoding="utf-8") for f in (fe / "src").rglob("*.jsx")}
        assert rep["injected_routes"] == [] and before == after
