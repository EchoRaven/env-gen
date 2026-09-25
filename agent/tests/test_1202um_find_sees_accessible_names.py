r"""#1202um: the recovery path the failure hint recommends could not see the controls that need it.

`browser_click`'s failure message tells the agent, verbatim, "Try using browser_find() first
to check if element exists". `browser_find` searched VISIBLE TEXT only
(`get_by_text(query, exact=False)`), so for an icon button -- whose entire identity is its
`aria-label` -- the recommended recovery returns nothing, and the agent concludes the control
is absent.

MEASURED on a live generated app (r132 home), per query, text search vs accessible name:

    'Like'          get_by_text 0    aria-label 1     (the control is "Like video")
    'Comment'       get_by_text 0    aria-label 1     ("Open comments")
    'Toggle sound'  get_by_text 0    aria-label 1
    'Explore'       get_by_text 1    aria-label 0     (a text nav link)

The two are COMPLEMENTARY, not redundant: text search finds the navigation, accessible names
find the action controls, and the tool offered only the first. 765 `browser_find` calls across
66 runs went through it. Verified live after the change: Like 0 -> 1, Comment 0 -> 1, Toggle
sound 0 -> 1, Explore 1 -> 1 (unchanged), a no-match query still 0.

This is the third link in one loop, with #1202uk (the candidate list dropped text-only
controls) and #1202ul (role+name matched the accessible name exactly). Each one on its own
left the agent unable to learn that the control it wanted was on the page.

WIDENING ONLY ADDS: the text results stay in the union and stay first, so a query that
matched before matches identically. Regex mode is deliberately untouched -- its pattern is
written against page text, and quietly applying it to attributes would change what an
existing regex means.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.browser.inspection import _widen_to_accessible_names_1202um  # noqa: E402


class _Loc:
    """Records the union rather than performing it."""

    def __init__(self, tag):
        self.tag = tag
        self.ored = None

    def or_(self, other):
        out = _Loc(self.tag)
        out.ored = other
        return out


class _Scope:
    def __init__(self):
        self.located = []

    def locator(self, sel):
        self.located.append(sel)
        return _Loc("attrs")


def test_the_search_is_widened_to_accessible_names():
    """★ The defect: an icon button was invisible to the tool told to find it."""
    scope, base = _Scope(), _Loc("text")
    out = _widen_to_accessible_names_1202um(scope, "Like", base)
    assert out.ored is not None, "text-only search was left unwidened"
    sel = scope.located[0]
    for attr in ("aria-label", "title", "placeholder"):
        assert f'[{attr}*="Like" i]' in sel, sel


def test_the_text_result_is_still_the_base():
    """★ The property this could most easily have cost: widening ADDS, it never replaces."""
    scope, base = _Scope(), _Loc("text")
    out = _widen_to_accessible_names_1202um(scope, "Explore", base)
    assert out.tag == "text", "the text search stopped being the base of the union"


def test_the_match_is_case_insensitive():
    """Agents ask for 'Like'; apps label 'like video'. The `i` flag is the whole point."""
    scope = _Scope()
    _widen_to_accessible_names_1202um(scope, "Like", _Loc("text"))
    assert scope.located[0].count('" i]') == scope.located[0].count("*=")


def test_a_quote_in_the_query_is_not_injected_into_the_selector():
    """★ This runs on a RECOVERY path. A malformed selector there would replace a useful
    miss with an exception, so a query that cannot be embedded safely is left alone."""
    scope = _Scope()
    out = _widen_to_accessible_names_1202um(scope, 'bad"quote', _Loc("text"))
    assert scope.located == [], scope.located
    assert out.ored is None, "widened with an unsafe query"


def test_an_empty_query_is_left_alone():
    scope = _Scope()
    out = _widen_to_accessible_names_1202um(scope, "", _Loc("text"))
    assert scope.located == [] and out.ored is None


def test_a_failure_costs_the_widening_not_the_search():
    """It must never raise: the caller is already recovering from something else."""

    class _Hostile(_Scope):
        def locator(self, sel):
            raise RuntimeError("detached frame")

    base = _Loc("text")
    assert _widen_to_accessible_names_1202um(_Hostile(), "Like", base) is base


def test_it_is_domain_agnostic():
    """★ The user's iron rule: the query is embedded verbatim, never interpreted."""
    scope = _Scope()
    _widen_to_accessible_names_1202um(scope, "tok9", _Loc("text"))
    assert '[aria-label*="tok9" i]' in scope.located[0]


def test_regex_mode_is_not_widened():
    """★ Asserted at the CALL SITE, not by trusting the docstring: a regex is written against
    page text, and applying it to attributes would change what existing patterns mean."""
    import inspect

    from tools.browser.inspection import BrowserFindTool

    src = inspect.getsource(BrowserFindTool.execute)
    head, _, tail = src.partition('if mode == "regex":')
    assert tail, "the regex branch moved; this assertion no longer reads what it names"
    regex_branch, _, text_branch = tail.partition("else:")
    assert "_widen_to_accessible_names_1202um" not in regex_branch, regex_branch
    assert "_widen_to_accessible_names_1202um" in text_branch, text_branch
