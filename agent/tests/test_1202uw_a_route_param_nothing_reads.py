r"""#1202uw: a route carries a `:param` the component never reads, so every address renders the same page.

FOUND ON THE DELIVERED r135 STACK. `/@charlidamelio` renders

    "0 Following  0 Followers  0 Likes / No bio yet. / Upload your first video"

for a creator who has four videos and real counts in the database. `ProfileOwnPage` passes
straight through to `ProfileView`, which takes `user` from PROPS -- the logged-in user -- and
never reads `useParams().username`. So every profile URL shows the viewer's own shell, empty
when logged out. The registry calls the route `/@:username`, which promises somebody else's
page.

MEASURED over 155 runs: 22 of 292 parameterised routes ignore their parameter, across 17 runs
(10%). r131's is a comments panel at `/video/:video_id/comments` that cannot tell which video
it is showing.

★ VALIDATED IN BOTH DIRECTIONS BEFORE BEING TRUSTED. An earlier, NAME-based attempt at a
related property ("a detail route with no `GET /api/<resource>/{id}`") ran at 32% and both
samples I checked were FALSE: instagram's `/p/:id` is served by `/api/posts/{id}` (`p`
abbreviates `posts`), and r129's `/profile/:id` by `/api/users/{username}` (different resource
name). Route segments and resource names routinely differ, so that heuristic was discarded
rather than shipped. This check reads SOURCE instead: on r135 it flags `/:username`, which I
verified by loading the page, and does NOT flag `/video/:id` or `/comments/:id`, whose
components really do call `useParams`.

Depth 2, because delegation is the common shape -- #1202uv measured 15% of pages making no
call in their own file at all.

REPORTS, NEVER BLOCKS -- same standing as #1202uv. A route may legitimately carry a parameter
a later milestone will use. What it must not be is invisible after the run.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.scaffolder import (  # noqa: E402
    record_route_params_ignored_1202uw,
    route_params_ignored_1202uw,
)


def _app(tmp_path, app_jsx, files=None):
    src = tmp_path / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "App.jsx").write_text(app_jsx, encoding="utf-8")
    for rel, text in (files or {}).items():
        (src / rel).write_text(text, encoding="utf-8")
    return str(tmp_path)


APP = """
import ProfileOwnPage from './pages/ProfileOwnPage';
import VideoPage from './pages/VideoPage';
export default function App() {
  return (<Routes>
    <Route path="/@:username" element={<ProfileOwnPage />} />
    <Route path="/video/:id" element={<VideoPage />} />
    <Route path="/" element={<Feed />} />
  </Routes>);
}
"""


def test_a_param_the_subtree_never_reads_is_reported(tmp_path):
    """★ r135's exact shape: page -> view, and neither reads the name."""
    out = route_params_ignored_1202uw(_app(tmp_path, APP, {
        "pages/ProfileOwnPage.jsx": "import ProfileView from '../components/ProfileView';\n"
                                    "export default (p) => <ProfileView {...p} />;",
        "components/ProfileView.jsx": "export default function ProfileView({ user }) "
                                      "{ return <div>{user?.username}</div>; }",
        "pages/VideoPage.jsx": "import { useParams } from 'react-router-dom';\n"
                               "export default () => { const { id } = useParams(); return id; };",
    }))
    assert out == ["/@:username -> ProfileOwnPage"], out


def test_a_param_read_one_hop_down_is_not_reported(tmp_path):
    """★ The true negative that makes the positive believable: delegation is normal, and a
    page whose CHILD reads the param is fine."""
    out = route_params_ignored_1202uw(_app(tmp_path, APP, {
        "pages/ProfileOwnPage.jsx": "import ProfileView from '../components/ProfileView';\n"
                                    "export default (p) => <ProfileView {...p} />;",
        "components/ProfileView.jsx": "import { useParams } from 'react-router-dom';\n"
                                      "export default () => useParams().username;",
        "pages/VideoPage.jsx": "import { useParams } from 'react-router-dom';\n"
                               "export default () => useParams().id;",
    }))
    assert out == [], out


def test_the_other_ways_of_reading_the_address_count(tmp_path):
    """`useSearchParams` and `useLocation` also read the address; flagging them would be a
    false positive."""
    for reader in ("useSearchParams()", "useLocation()", "match.params.username",
                   "props.params.username"):
        out = route_params_ignored_1202uw(_app(tmp_path / reader[:6], APP, {
            "pages/ProfileOwnPage.jsx": f"export default () => {reader};",
            "pages/VideoPage.jsx": "import { useParams } from 'react-router-dom';\n"
                                   "export default () => useParams().id;",
        }))
        assert out == [], (reader, out)


def test_a_route_without_a_parameter_is_never_reported(tmp_path):
    out = route_params_ignored_1202uw(_app(tmp_path, """
      import Feed from './pages/Feed';
      export default () => <Route path="/" element={<Feed />} />;
    """, {"pages/Feed.jsx": "export default () => 'feed';"}))
    assert out == [], out


def test_an_unresolvable_component_is_skipped(tmp_path):
    """A route whose element cannot be read must be SKIPPED, not reported.

    ★ Two distinct ways it becomes unreadable, and my first version of this test only had the
    first -- so disabling the second guard left it green. A package import never enters the
    default-import map at all and exits early; a LOCAL import whose file is missing gets past
    that and needs the `if not rel` guard. Both are asserted now.
    """
    out = route_params_ignored_1202uw(_app(tmp_path / "pkg", """
      import { Thing } from 'some-package';
      export default () => <Route path="/x/:id" element={<Thing />} />;
    """))
    assert out == [], out
    # a default import of a local file that does not exist -- reaches the `rel` guard
    out = route_params_ignored_1202uw(_app(tmp_path / "gone", """
      import Missing from './pages/Missing';
      export default () => <Route path="/x/:id" element={<Missing />} />;
    """))
    assert out == [], out


def test_no_app_jsx_is_silent(tmp_path):
    """The scaffolder runs before the frontend lane writes anything."""
    (tmp_path / "app" / "backend").mkdir(parents=True)
    assert route_params_ignored_1202uw(str(tmp_path)) == []


def test_it_never_raises(tmp_path):
    assert route_params_ignored_1202uw(None) == []
    assert route_params_ignored_1202uw(str(tmp_path / "nope")) == []


def test_the_finding_reaches_an_artifact(tmp_path):
    """#947, and the same guard as #1202ui/#1202uv against a folder literally named None."""
    assert record_route_params_ignored_1202uw(str(tmp_path), ["/@:username -> P"]) is True
    rows = [json.loads(x) for x in
            (tmp_path / "logs" / "route_params_ignored_1202uw.jsonl").read_text().splitlines()
            if x.strip()]
    assert rows[0]["count"] == 1 and rows[0]["routes"] == ["/@:username -> P"]
    assert record_route_params_ignored_1202uw(None, ["x"]) is False
    assert record_route_params_ignored_1202uw(str(tmp_path), []) is False
    assert not (Path.cwd() / "None").exists()


def test_it_is_wired():
    """★ A detector nothing calls finds nothing."""
    src = (LLM_DIR / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    assert "route_params_ignored_1202uw(out_dir)" in src
    assert "record_route_params_ignored_1202uw(out_dir, _rp1202uw)" in src
