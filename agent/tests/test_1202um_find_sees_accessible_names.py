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


def test_a_hostile_query_cannot_malform_the_selector():
    r"""★ This runs on a RECOVERY path, and its own contract says it must never raise.

    My first version REFUSED to widen whenever the query held a `"`. That was not enough: two
    other shapes still produced a malformed selector, and Playwright validates lazily, so the
    error surfaced at `.count()` in the CALLER -- outside this function's try. Probed against
    a live page BEFORE the fix:

        query 'a\\'   -> Error: Unexpected token "" while parsing css selector [aria-label*="a\"
        query 'a\nb'  -> Error: Unsupported token "BADSTRING"

    A recovery path that raises is worse than one that finds nothing. Escaping (rather than
    refusing) also makes a quoted query WORK instead of being dropped, so this is strictly
    stronger than the assertion it replaces. Re-probed live after the fix: all eight hostile
    shapes return a count instead of raising.
    """
    scope = _Scope()
    out = _widen_to_accessible_names_1202um(scope, 'bad"quote', _Loc("text"))
    assert out.ored is not None, "a quoted query is now escaped, not dropped"
    # The property, not a magic count: the quote inside the VALUE is escaped, so every
    # attribute clause still closes on its own delimiter.
    assert '[aria-label*="bad\\"quote" i]' in scope.located[0], scope.located[0]

    scope = _Scope()
    _widen_to_accessible_names_1202um(scope, "a\\", _Loc("text"))
    assert '\\\\' in scope.located[0], scope.located[0]

    scope = _Scope()
    _widen_to_accessible_names_1202um(scope, "a\nb\tc", _Loc("text"))
    assert "\n" not in scope.located[0] and "\t" not in scope.located[0], scope.located[0]
    assert '"a b c"' in scope.located[0], scope.located[0]


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


def test_the_result_carries_what_a_selector_can_be_built_from():
    r"""★ THE HALF-FIX I ALMOST SHIPPED, caught by asking whether the change is usable
    end-to-end rather than whether it matches.

    Widening the SEARCH to accessible names made `browser_find("Like")` return 1 match on a
    live generated app -- and the per-match metadata was `{tag, id, className, text, href,
    role}`. An icon button's `text` is EMPTY, and its identity lives entirely in `aria-label`
    and `data-testid`. So the result would have said "found 1" and named nothing the model
    could click: a match it cannot act on is the same dead end as no match, one step later.
    That is #1202's "fixing one reader is worse than none" shape, in my own change.

    Verified live after adding the fields:

        browser_find('Like')    -> {tag: button, text: '672K',
                                    ariaLabel: 'Like video', testid: 'like-video'}
        browser_find('Comment') -> {ariaLabel: 'Open comments', testid: 'open-comments'}
        browser_find('Explore') -> {tag: span, text: 'Explore'}     (unchanged)

    Asserted against the evaluated JS source, since the projection runs in the page.
    """
    import inspect

    from tools.browser.inspection import BrowserFindTool

    src = inspect.getsource(BrowserFindTool.execute)
    _, _, body = src.partition("el.tagName")
    assert body, "the metadata projection moved; this assertion no longer reads what it names"
    returned, _, _ = body.partition('"""')
    for field in ("aria-label", "data-testid", "placeholder", "title"):
        assert field in returned, f"{field} is matched on but never returned: {returned[:400]}"
