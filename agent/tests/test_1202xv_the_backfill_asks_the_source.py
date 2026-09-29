"""#1202xv: the backfill must ask the page's source, not the page's name.

r138, live, on the corpus's top delivery blocker: 7 registered ui_pages carry
`apis_used: []` and `deliverability_page_apis_understated` was the one check left standing
for 25 consecutive gate ticks while the lane did nothing about it. The framework's own
source reader answers `['GET /api/videos/feed']` for every one of those pages; the name
heuristic answers nothing, because the only registered `/api/` GET collection is
`/api/videos/feed` and its last segment `feed` shares no token with `explore_grid_page`,
`live_discover_page` or `messages_dm_empty_page`.

#1202uv's note had already written the gap down -- "`backfill_page_apis` (#579) matches
endpoint NAMES and never reads source. So no path in the framework turns frontend source
into what this app tries to call." That was true when written and stopped being true when
#1202wd added the reader the delivery gate now BLOCKS on. The reader was wired to the
report and never to the writer.

Verified before trusting it (#1202w1 -- a name present is not a name used):
MessagesDmEmptyPage.jsx imports `getVideoFeed`, CALLS it on line 26, and `getVideoFeed`
requests `/api/videos/feed`.

LOCAL-ONLY (gitignored).
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.frontend_scaffold import backfill_page_apis  # noqa: E402

_RUNTIME = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime")

_EPS = [
    {"method": "GET", "path": "/api/videos/feed"},
    {"method": "POST", "path": "/api/videos/{video_id}/like"},
    {"method": "DELETE", "path": "/api/videos/{video_id}/like"},
]


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


class _Reader:
    """Stands in for the gate's reader, answering in ITS normalised form."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def __call__(self, app_root, component):
        self.asked.append((app_root, component))
        return self.answers.get(component, [])


def _with_reader(monkeypatch, answers):
    import multi_agent.runtime.frontend_scaffold as fs
    r = _Reader(answers)
    monkeypatch.setattr(fs, "_page_calls_1202xv",
                        lambda app_root, component: r(app_root, component))
    return r


def test_the_source_answer_wins_over_the_name_heuristic(monkeypatch):
    """`explore_grid_page` shares no token with `feed`, so the heuristic fills nothing."""
    pages = [{"name": "explore_grid_page", "route": "/explore",
              "component": "ExploreGridPage", "apis_used": []}]
    assert not (backfill_page_apis(pages, _EPS)[0].get("apis_used") or []), (
        "the premise is gone: the name heuristic now matches this page on its own")
    _with_reader(monkeypatch, {"ExploreGridPage": ["GET /api/videos/feed"]})
    got = backfill_page_apis(pages, _EPS, app_root="/any")[0]["apis_used"]
    assert got == ["GET /api/videos/feed"], got


def test_the_normalised_answer_is_mapped_back_to_the_registered_spelling(monkeypatch):
    """The reader says `{}`; the registry spells `{video_id}`. Writing the reader's form
    would put a string into the contract that no reader of the contract recognises."""
    _with_reader(monkeypatch, {"P": ["POST /api/videos/{}/like", "GET /api/videos/feed"]})
    got = backfill_page_apis([{"name": "p", "component": "P", "apis_used": []}],
                             _EPS, app_root="/any")[0]["apis_used"]
    assert "POST /api/videos/{video_id}/like" in got, got
    assert not any("{}" in a for a in got), got


def test_a_call_no_endpoint_serves_is_not_registered(monkeypatch):
    """"The frontend calls something nothing serves" is #1202uv's report to make, not this
    one's to write into the contract."""
    _with_reader(monkeypatch, {"P": ["GET /api/nobody/serves/this",
                                     "GET /api/videos/feed"]})
    got = backfill_page_apis([{"name": "p", "component": "P", "apis_used": []}],
                             _EPS, app_root="/any")[0]["apis_used"]
    assert got == ["GET /api/videos/feed"], got


def test_a_declared_apis_used_is_never_overridden(monkeypatch):
    _with_reader(monkeypatch, {"P": ["GET /api/videos/feed"]})
    pages = [{"name": "p", "component": "P", "apis_used": ["GET /api/something/else"]}]
    assert backfill_page_apis(pages, _EPS, app_root="/any")[0]["apis_used"] == \
        ["GET /api/something/else"]


def test_no_tree_falls_back_to_exactly_what_it_did_before():
    """ADDITIVE: the kickoff-time call has no app_root and must behave as it always did."""
    pages = [{"name": "videos_feed_page", "route": "/feed",
              "component": "VideosFeedPage", "apis_used": []}]
    assert backfill_page_apis(pages, _EPS) == backfill_page_apis(pages, _EPS, app_root=None)


def test_the_reader_is_consulted_with_the_app_tree(monkeypatch):
    """#1202wd's reader takes `<run>/app`; handing it the run root makes it answer []."""
    r = _with_reader(monkeypatch, {})
    backfill_page_apis([{"name": "p", "component": "P", "apis_used": []}],
                       _EPS, app_root="/run/app")
    assert r.asked and r.asked[0][0] == "/run/app", r.asked


def test_the_caller_hands_it_the_app_tree():
    """Structural (#1202w1): pin that the call site passes app_root, by AST."""
    tree = ast.parse(_read(os.path.join(_RUNTIME, "scaffolder.py")))
    calls = [c for c in ast.walk(tree)
             if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "backfill_page_apis"]
    assert calls, "backfill_page_apis is no longer called"
    for c in calls:
        assert any(k.arg == "app_root" for k in c.keywords), (
            "a call site does not hand it the tree, so it silently keeps guessing")


def test_the_reader_import_is_late():
    """frontend_scaffold is imported during scaffolding and frontend_audit during auditing;
    a module-level import here couples the two."""
    src = _read(os.path.join(_RUNTIME, "frontend_scaffold.py"))
    tree = ast.parse(src)
    for node in tree.body:                       # module level only
        if isinstance(node, ast.ImportFrom) and "frontend_audit" in str(node.module or ""):
            raise AssertionError("frontend_audit is imported at module level")


def test_the_real_reader_finds_a_real_call(tmp_path):
    """★ Caught by mutation: every test above monkeypatches `_page_calls_1202xv`, so making
    the REAL one return [] left them all green. This one drives it against a tree on disk --
    the shape r138 actually had: the page imports a service function and calls it."""
    from multi_agent.runtime.frontend_scaffold import _page_calls_1202xv

    src = tmp_path / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "services").mkdir()
    (src / "services" / "api.js").write_text(
        "export async function getVideoFeed({ limit = 5 } = {}) {\n"
        "  const data = await request(`/api/videos/feed?limit=${limit}`);\n"
        "  return data;\n}\n", encoding="utf-8")
    (src / "pages" / "ExploreGridPage.jsx").write_text(
        "import { getVideoFeed } from '../services/api.js';\n"
        "export default function ExploreGridPage() {\n"
        "  getVideoFeed({ limit: 18 });\n"
        "  return null;\n}\n", encoding="utf-8")
    got = _page_calls_1202xv(str(tmp_path), "ExploreGridPage")
    assert any("/api/videos/feed" in g for g in got), (
        "the real reader found nothing in a tree that plainly calls it: %r" % got)
