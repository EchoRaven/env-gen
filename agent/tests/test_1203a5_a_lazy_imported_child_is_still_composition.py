r"""#1203a5: `React.lazy` composition read as a placeholder stub, and it cost a whole run.

`_composes_child` credits a page that imports a component and renders it — the user's own model
("pages compose COMPONENTS"). It has been widened twice already: #566j for an optional file
extension, #1202y5 for a named import. Both patterns look for a STATIC `import X from '...'`.

`React.lazy` has no `from` clause:

    const VideoFeedComponent = lazy(() => import('../components/VideoFeedComponent'));

WHAT IT COST. r142's lane wrote both core pages that way. `ForYouFeedPage` is 33 lines with
real state, `requireAuth`/`selectVideo` handlers and `apis_used = ['GET /api/feed']`, mounting
TiktokShell + VideoFeedComponent + CommentsDrawerComponent + AuthModalComponent. The children
are real: `VideoFeed` is 36 lines with `useEffect` + `getFeed()` from services/api rendering
`VideoCard`; Shell 51 lines, CommentsDrawer 70, AuthModal 71. THE FEED WORKED. This check
called both pages "a placeholder stub — it renders no real UI/behavior" from the 1st delivery
gate evaluation through the 149th, `ok=True` zero times, and the run aborted at 41 coordination
ticks: $153.23 spent, nothing delivered. The lane kept marking the repair tasks complete
because there was nothing to repair.

MEASURED over the 2625 page files in the corpus: exactly 2 flip from flagged to exempt — those
two. Nothing else in any run is loosened.

★ I ALMOST GOT THIS WRONG. My first reading was "the check cannot see composition at all", and
I was about to report that. The standing rule — a detector patched four times, the fifth "false
positive" is probably an exemption I did not read — sent me to the exemption branch, and the
real defect turned out to be far narrower and the fix far smaller: composition IS supported,
for two of the three import syntaxes.
"""
import os
import re
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.frontend_audit as FA  # noqa: E402

# The exact shape r142 shipped, trimmed to what the predicate reads.
_LAZY_PAGE = """\
import { useMemo, useState, lazy, Suspense } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

const TiktokShell = lazy(() => import('../components/TiktokShell'));
const VideoFeedComponent = lazy(() => import('../components/VideoFeedComponent'));

export const apis_used = [
  'GET /api/feed',
];

export default function ForYouFeedPage({ user }) {
  const [selected, setSelected] = useState(null);
  return (
    <div className="app">
      <Suspense fallback={<div className="state">Loading videos…</div>}>
        <TiktokShell user={user}>
          <VideoFeedComponent onSelectVideo={setSelected} selectedId={selected} />
        </TiktokShell>
      </Suspense>
    </div>
  );
}
"""

_STATIC_PAGE = """\
import Shell from '../components/Shell';
export const apis_used = ['GET /api/feed'];
export default function P() { return <Shell><div/></Shell>; }
"""

_NAMED_PAGE = """\
import { ExploreView } from '../components/DiscoveryPages';
export const apis_used = ['GET /api/videos'];
export default function P() { return <ExploreView />; }
"""

_REAL_STUB = """\
export const apis_used = ['GET /api/feed'];
export default function P() { return <div>TODO</div>; }
"""

_LAZY_BUT_NO_CHILD = """\
import { lazy } from 'react';
const X = lazy(() => import('../components/X'));
export const apis_used = ['GET /api/feed'];
export default function P() { return <div>nothing mounted</div>; }
"""


def _predicate_node():
    """The production expression assigned to `_composes_child`, located by AST.

    NOT by slicing source text: the first draft of this test cut a fixed window and produced
    an unbalanced expression (`SyntaxError: '(' was never closed`). #943 has caught that same
    shortcut repeatedly — pin the node, not a byte range.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(FA))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_composes_child" for t in node.targets):
            return node.value
    raise AssertionError("_composes_child is gone from frontend_audit")


def _composes(text):
    """Evaluate the production predicate itself, so this test cannot drift into testing its
    own copy of the regexes."""
    import ast
    expr = ast.Expression(_predicate_node())
    ast.fix_missing_locations(expr)
    return bool(eval(compile(expr, "<predicate>", "eval"),
                     {"re": re}, {"comp_file_text": text}))


def test_a_real_stub_is_still_flagged():
    """★ Non-vacuity and the whole safety case: this must stay False, or the fix would
    hide the defect the check exists for."""
    assert _composes(_REAL_STUB) is False


def test_the_static_import_form_still_counts():
    assert _composes(_STATIC_PAGE) is True


def test_the_named_import_form_still_counts():
    """#1202y5's case — pinned so this widening cannot regress it."""
    assert _composes(_NAMED_PAGE) is True


def test_a_lazy_imported_child_counts():
    """★ The defect: r142's shape."""
    assert _composes(_LAZY_PAGE) is True


def test_a_lazy_import_without_a_rendered_child_does_not_count():
    """The JSX half of the conjunction still has to hold — importing a component and
    mounting nothing is not composition."""
    assert _composes(_LAZY_BUT_NO_CHILD) is False


def test_both_halves_are_still_required():
    """Stated as the property: neither half alone is enough."""
    assert _composes("const X = lazy(() => import('../components/X'));") is False
    assert _composes("export default function P(){ return <Shell/>; }") is False


def test_a_non_components_dynamic_import_does_not_count():
    """`import('./utils/helpers')` is not a child component; the path still has to name
    a components/ module, exactly as the static forms require."""
    text = ("const h = lazy(() => import('../utils/helpers'));\n"
            "export default function P(){ return <Shell/>; }")
    assert _composes(text) is False


def test_the_delivered_r142_pages_are_exempt_now():
    """Against the real artifacts that aborted the run, when they are still on disk."""
    import glob
    # _AGENT is <repo>/agent, so the repo root is one level up — not two. The first
    # version went up twice, the glob missed, and this test SKIPPED silently: the one
    # assertion that runs against the artifacts that actually aborted the run was the one
    # not running.
    base = glob.glob(os.path.join(
        os.path.dirname(_AGENT),
        "generated", "tiktok-web-r142", "app", "frontend", "src", "pages"))
    if not base:
        import pytest
        pytest.skip("r142 tree not on this machine")
    hits = 0
    for name in ("ForYouFeedPage.jsx", "VideoDetailPage.jsx"):
        p = os.path.join(base[0], name)
        if not os.path.exists(p):
            continue
        hits += 1
        with open(p, encoding="utf-8") as fh:
            assert _composes(fh.read()) is True, name
    if not hits:
        import pytest
        pytest.skip("r142 pages not on this machine")


def test_the_exemption_is_not_stricter_than_its_siblings():
    """Deliberate: the static forms do not verify the imported file exists, so this one must
    not either. A 'widening' that quietly applies a new standard to only the new shape is how
    a check grows a hole on one side and a cliff on the other."""
    import ast
    # #943: NOT a byte window — the first draft used `getsource(FA)[i:i + 900]` and the
    # ratchet caught it in the same file where I had just replaced another one. Unparse the
    # node instead, so a growing comment cannot move the boundary.
    expr = ast.unparse(_predicate_node())
    for forbidden in ("_component_resolves", "exists(", "is_file("):
        assert forbidden not in expr, forbidden
