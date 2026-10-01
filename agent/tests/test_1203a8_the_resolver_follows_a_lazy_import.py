r"""#1203a8: the api resolver went blind on `React.lazy`, and that is how r142 died.

`frontend_audit`'s page→endpoint resolver walks a delegating page's imports transitively. It
matched a default import (`import X from './X'`) and, since #1202y2, a named one
(`import { X } from '../components/Barrel'`). `React.lazy` has no `from` clause:

    const VideoFeedComponent = lazy(() => import('../components/VideoFeedComponent'));

THE FULL CAUSAL CHAIN OF r142, from its gate log:

  records   4..125  `deliverability_page_apis_understated`, 122 times, sentence UNCHANGED:
                    "for_you_feed (ForYouFeedPage.jsx) unlisted 5: GET /api/videos/{}/comments,
                     POST /api/auth/logout, ..."   ← the resolver could still see the children
  between 125/126   the lane converted both core pages to `lazy(() => import(...))`
  records 126..149  `deliverability_ui_page_unwired` alone — the #1203a5 false positive, which
                    no lane could ever clear. The run aborted at 41 ticks, $153, nothing shipped.

Across all 149 records the two checks NEVER co-occur, and corpus-wide they co-occur in 6 of
1034. One root cause — two regex resolvers blinded by the same syntax — two opposite harms:

    _composes_child  blind -> "placeholder stub"    -> FALSE BLOCK   (fixed in #1203a5)
    this resolver    blind -> answers []            -> FALSE GREEN   (fixed here)

★ THE LANE'S "FIX" WAS TO BLIND THE CHECKER. 32 workhub tasks were filed for that one blocker,
all to frontend, "Register the APIs the page actually calls" six times over. What finally
cleared it was not a registration — the delivered registry still lists ONE endpoint for
`for_you_feed` — it was the conversion to lazy imports. With both resolvers fixed, that page
resolves to 6 endpoints again and the blocker is a TRUE positive the lane can satisfy:
`register_ui_page(..., apis_used=[...])` persists, verified against a copy of r142's own hub.

★ UNGUARDED, like the default-import branch and unlike the named-import one: `import('X')`
names ONE module and binds ONE component, so the barrel-dilution failure #1202y2 guards against
(r89: three unrelated pages handed the same four endpoints) cannot arise.

MEASURED: 3 pages across 1 run use this syntax; 2 carry no static or named relative import at
all. Both are r142's.
"""
import os
import shutil
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.frontend_audit as FA  # noqa: E402


def _eps(app, component):
    """The resolver returns a LIST; compare as a set so order is not asserted."""
    return set(FA.page_api_endpoints_1202wd(app, component) or [])

_REPO = os.path.dirname(_AGENT)


_R142 = os.path.join(_REPO, "generated", "tiktok-web-r142", "app")


def _real_tree(tmp_path):
    """A COPY of r142's delivered frontend+backend.

    Synthetic fixtures do not work here and that is the resolver behaving correctly: it maps
    service functions out of a real `services/api*.js`, and #1202y8 refuses a raw `fetch()`
    literal unless the BACKEND actually serves that route — "admitting those would INVENT
    endpoints". A hand-rolled tree has neither, so it resolves to [] for the right reason. The
    shape under test is the page's import syntax, so the honest fixture is the real tree with
    that one page rewritten (#1202w8: fixture shape is where this project's test blind spots
    live).
    """
    if not os.path.isdir(_R142):
        import pytest
        pytest.skip("r142 tree not on this machine")
    dst = tmp_path / "app"
    shutil.copytree(_R142, dst,
                    ignore=shutil.ignore_patterns("__pycache__", "node_modules", "*.pyc"))
    return str(dst)


def _page(app, name):
    return os.path.join(app, "frontend", "src", "pages", name + ".jsx")


def test_the_lazy_page_resolves_the_endpoints_the_blocker_named(tmp_path):
    """★ The defect, against the artifacts that aborted the run. The blocker said "unlisted 5"
    naming `GET /api/videos/{}/comments` and `POST /api/auth/logout`; before this fix the
    resolver answered [] for this page, which is what silenced the check at record 126."""
    app = _real_tree(tmp_path)
    got = _eps(app, "ForYouFeedPage")
    assert "GET /api/feed" in got, got
    assert "GET /api/videos/{}/comments" in got, got
    assert "POST /api/auth/logout" in got, got
    assert len(got) >= 5, got


def test_the_page_really_does_use_a_lazy_import(tmp_path):
    """★ Non-vacuity of the test above: if this page ever stops using `lazy(() => import(...))`,
    it no longer exercises the new branch and the assertion proves nothing."""
    app = _real_tree(tmp_path)
    with open(_page(app, "ForYouFeedPage"), encoding="utf-8") as fh:
        text = fh.read()
    import re
    assert re.search(r"lazy\s*\(\s*\(\s*\)\s*=>\s*import\s*\(", text), text[:200]
    assert not re.search(
        r"import\s+[A-Z]\w*\s+from\s+['\"]\.[^'\"]*components/", text), (
        "the page also has a static component import, so the static branch could be what "
        "resolves it: " + text[:300])


def test_the_same_page_rewritten_to_a_static_import_resolves_the_same(tmp_path):
    """★ The control that makes the fix meaningful rather than coincidental: one syntax swapped,
    same answer. Before the fix these two differed — [] versus six endpoints."""
    app = _real_tree(tmp_path)
    path = _page(app, "ForYouFeedPage")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    import re
    static = re.sub(r"const\s+(\w+)\s*=\s*lazy\(\s*\(\s*\)\s*=>\s*import\(\s*"
                    r"(['\"][^'\"]+['\"])\s*\)\s*\);",
                    r"import \1 from \2;", text)
    assert static != text, "the rewrite matched nothing"
    lazy_eps = _eps(app, "ForYouFeedPage")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(static)
    static_eps = _eps(app, "ForYouFeedPage")
    assert static_eps == lazy_eps, "lazy=%s static=%s" % (sorted(lazy_eps), sorted(static_eps))
    assert static_eps, "both forms resolve nothing — the fixture stopped exercising anything"


def test_a_page_with_its_own_call_still_does_not_descend(tmp_path):
    """The `if own: return` guard this resolver documents (r89: three unrelated pages handed the
    same four endpoints). SignupPage calls `fetch('/auth/register')` itself and must not be
    credited with a child's endpoints."""
    app = _real_tree(tmp_path)
    got = _eps(app, "SignupPage")
    assert "GET /api/videos/{}/comments" not in got, got


def test_a_lazy_import_of_a_missing_module_is_not_a_crash(tmp_path):
    app = _real_tree(tmp_path)
    path = _page(app, "ForYouFeedPage")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("import { lazy } from 'react';\n"
                 "const C = lazy(() => import('../components/DefinitelyGone'));\n"
                 "export default function ForYouFeedPage(){ return <C/>; }\n")
    assert _eps(app, "ForYouFeedPage") == set()


def test_a_bare_module_specifier_is_not_walked(tmp_path):
    """★ FOUND BY MUTANT. Widening the pattern to any `import('...')` left every test green,
    because walking `react` finds no local file. But the sibling default-import branch requires
    a RELATIVE path, and parity is the stated principle of this widening — "not stricter, not
    looser than its siblings". A bare specifier whose LAST SEGMENT happens to match a local
    component would otherwise credit the page with that component's endpoints."""
    app = _real_tree(tmp_path)
    with open(_page(app, "ForYouFeedPage"), "w", encoding="utf-8") as fh:
        fh.write("import { lazy } from 'react';\n"
                 "const C = lazy(() => import('some-pkg/VideoFeed'));\n"
                 "export default function ForYouFeedPage(){ return <C/>; }\n")
    got = _eps(app, "ForYouFeedPage")
    assert got == set(), (
        "a bare module specifier was walked to the local component of the same name: %s"
        % sorted(got))


def test_the_lazy_branch_is_ungated_like_the_default_import_branch():
    """Pinned as a decision: the named-import branch is deliberately guarded against barrel
    dilution; this one must NOT inherit that guard, because a dynamic import names ONE module
    and binds ONE component.

    Located by the regex literal's VALUE, not by `ast.unparse` text — the first version matched
    on the unparsed source and lost to backslash escaping, reporting "the walk is gone" when it
    was right there.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(FA))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        pats = [c.value for c in ast.walk(node.iter)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        # the dynamic form: an `import` immediately followed by an escaped open paren,
        # and NO `from` clause (which is what distinguishes it from the static branch)
        if any("import" in p and r"\s*\(" in p and "from" not in p for p in pats):
            hits.append(node)
    assert hits, "the dynamic-import walk is gone"
    body = ast.unparse(hits[0])
    assert "_walk(" in body, body
    assert "if " not in body.split("_walk(")[0], (
        "the dynamic-import walk grew a guard its sibling default-import branch lacks: " + body)


def test_the_static_and_named_branches_are_both_still_there():
    """Non-vacuity for the test above and a regression guard: #1202y2's named-import branch and
    the original default-import branch must both survive this widening."""
    import ast
    import inspect
    pats = [c.value for c in ast.walk(ast.parse(inspect.getsource(FA)))
            if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    assert any("import" in p and "from" in p and "[A-Z]" in p for p in pats), "default-import gone"
    assert any("import" in p and "from" in p and "{" in p for p in pats), "named-import gone"
