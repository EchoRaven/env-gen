"""#1203il — #362's third case was rendered as silence.

`#688` established the sentinel for "the probe RAN and the page offers nothing", noting that
`""` "still means 'could not look'" and that "callers must render these two differently".
`_candidates_hint_688` did render them differently — by saying nothing at all for the probe
that could not run. To the agent that is indistinguishable from a framework with no #362: it
sees

    Fill failed: Page.fill: Timeout 5000ms exceeded.

and goes on guessing selectors, which is the loop #362 exists to end (r91: 52 identical
browser_fill failures on `input[name='username']` in one verifier, plus 17 browser_click,
each costing a 5s timeout AND a full-context round).

Measured over r182-r185: 186 browser_fill/browser_click failures — 152 carried the candidate
list, 8 said the page is empty, and 26 said NOTHING. Per run: r182 5/33, r183 7/46,
r184 6/28, r185 8/79.

The probe is right to keep returning `""` ("saying 'the page is empty' when we failed to look
would be worse than saying nothing"), so the fix is in the rendering.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)

from env_generator.llm_generator.tools.browser.interaction import (  # noqa: E402
    _EMPTY_PAGE_688,
    _candidates_hint_688 as hint,
)


def test_the_probe_that_could_not_look_is_no_longer_silent():
    """★ THE DEFECT. This returned "" — the agent could not tell the probe had failed."""
    out = hint("")
    assert out.strip(), "the could-not-look case is still silent"
    assert "could not be inspected" in out
    assert "NO evidence" in out, (
        "the agent must be told this failure says nothing about its selector")


def test_it_does_not_claim_the_page_is_empty():
    """The probe's own rule: "saying 'the page is empty' when we failed to look would be
    worse than saying nothing". The new text must not drift into that claim."""
    out = hint("")
    assert "NO interactable elements" not in out
    assert "blank" not in out


def test_the_three_cases_stay_distinct():
    empty = hint(_EMPTY_PAGE_688)
    cannot = hint("")
    listed = hint("input[name=q], button[type=submit]")
    assert empty != cannot != listed
    assert "NO interactable elements at all" in empty
    assert "could not be inspected" in cannot
    assert "Interactable elements on this page:" in listed
    # the empty-page case must NOT be told "no evidence about your selector" — there the
    # evidence is conclusive: nothing can match.
    assert "NO evidence" not in empty


def test_the_listed_case_is_unchanged():
    """#362's working path carries 86% of the failures; it must read exactly as before."""
    assert hint("a, b") == " Interactable elements on this page: a, b"


def test_the_could_not_look_text_says_what_to_do_next():
    """A different cause needs a different next step: a closed/navigating page is not a
    wrong selector, so re-open and retry the SAME locator once rather than change it."""
    out = hint("")
    assert "retry the same locator" in out.lower()
    assert "navigat" in out.lower()


def test_both_interaction_tools_render_through_this_one_builder():
    """#1032: one owner for the wording. browser_fill and browser_click must both go through
    `_candidates_hint_688`, so this fix reaches both rather than one."""
    import ast
    import pathlib
    src = pathlib.Path(
        _AGENT, "env_generator/llm_generator/tools/browser/interaction.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    callers = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for c in ast.walk(node):
            if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == "_candidates_hint_688"):
                # the enclosing class, via the qualified source line
                callers.add(node.name)
    assert len(callers) >= 1
    # both failure messages must exist and neither may build its own wording
    assert "Fill failed:" in src and "Click failed" in src
    assert src.count("Interactable elements on this page:") == 1, (
        "the candidate wording is duplicated; #1032's point is that a second copy fails "
        "silently on the day one is edited")
