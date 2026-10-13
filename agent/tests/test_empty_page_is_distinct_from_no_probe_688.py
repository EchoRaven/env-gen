r"""#688: "" meant three different things, so the biggest live browser failure carried no hint.

`browser_fill` is the largest LIVE failure class in the corpus and it is getting worse:

    browser_fill   1238 total, 830 in the live era (r100+), up from 408 before
    browser_click   410 total, 214 live

and the live samples read, in full:

    Fill failed: Page.fill: Timeout 5000ms exceeded.

#362 already exists to prevent exactly that — it appends "Interactable elements on this page:
..." so one failure answers the question instead of seeding N more selector guesses. It produced
nothing here, because `describe_interactive_candidates` returns "" for THREE unrelated
conditions:

    page is None            could not look
    the query raised        could not look
    the query found none    the page genuinely offers nothing   <- the significant one

and the caller rendered all three as silence. The third is the opposite diagnosis: the selector
is not wrong, the PAGE never rendered — which lines up with the 27 blank/never-hydrated routes
already measured in the corpus. Telling an agent nothing there sends it to guess more selectors
against a page that has none.

`_EMPTY_PAGE_688` is returned ONLY when the probe RAN and found nothing. A probe that could not
run still returns "" — unchanged — because claiming "the page is empty" when we failed to look
would be worse than saying nothing.
"""
import asyncio

import pytest

from env_generator.llm_generator.tools.browser.interaction import (
    _EMPTY_PAGE_688 as EMPTY,
    _candidates_hint_688 as hint,
    describe_interactive_candidates as describe,
)


class _Page:
    def __init__(self, els=None, raises=False):
        self._els, self._raises = els, raises

    async def query_selector_all(self, selector):
        if self._raises:
            raise RuntimeError("context destroyed")
        return self._els or []


# --- the three conditions are now distinguishable ------------------------------------------

def test_a_page_with_nothing_returns_the_sentinel():
    assert asyncio.run(describe(_Page(els=[]))) == EMPTY


def test_a_page_that_cannot_be_probed_still_returns_empty_string():
    """Claiming 'the page is empty' when we failed to look would be worse than silence."""
    assert asyncio.run(describe(_Page(raises=True))) == ""


def test_no_page_at_all_returns_empty_string():
    assert asyncio.run(describe(None)) == ""


def test_the_sentinel_is_not_a_plausible_element_description():
    """It must never collide with a real candidate list."""
    assert EMPTY.startswith("\x00")


# --- the caller renders them differently ---------------------------------------------------

def test_an_empty_page_says_no_selector_can_match():
    out = hint(EMPTY)
    assert "NO interactable elements" in out
    assert "no selector can match" in out


def test_an_empty_page_tells_it_to_stop_guessing():
    """The behaviour #362 was written to stop, in the case #362 could not see."""
    out = hint(EMPTY)
    assert "Do not try another selector" in out
    assert "check that the route rendered" in out


def test_an_empty_page_names_the_likely_cause():
    assert "blank or never hydrated" in hint(EMPTY)


def test_a_real_candidate_list_is_unchanged():
    """#362's wording must survive verbatim."""
    assert hint("{tag='input'}") == " Interactable elements on this page: {tag='input'}"


def test_a_failed_probe_says_it_could_not_look():
    """#1203il REPLACED this assertion, and the reason matters.

    It used to read `assert hint("") == ""` — a bare snapshot of the implementation with no
    stated reason. The reason THIS file gives for leaving the probe's `""` untouched is
    specific: "claiming 'the page is empty' when we failed to look would be worse than saying
    nothing." That forbids one particular false claim; it does not require silence.

    And silence had a measured cost. Over r182-r185, 186 browser_fill/browser_click failures:
    152 carried the candidate list, 8 said the page is empty, and 26 said NOTHING at all
    (r182 5/33, r183 7/46, r184 6/28, r185 8/79). Those 26 read to the agent exactly like a
    framework with no #362 — `Fill failed: Page.fill: Timeout 5000ms exceeded.` and nothing
    else — so it goes on guessing selectors, the loop #362 exists to end.

    So the rendering now names the real condition (the page could not be inspected, this
    failure is NOT evidence about the selector) while still never claiming the page is empty —
    which `test_a_failed_probe_never_claims_the_page_is_empty` below pins.
    """
    out = hint("")
    assert out.strip(), "the could-not-look case is silent again"
    assert "could not be inspected" in out
    assert "NO evidence" in out


def test_a_failed_probe_never_claims_the_page_is_empty():
    """This file's own rule, kept: the one thing the could-not-look rendering must not do."""
    out = hint("")
    assert "NO interactable elements" not in out
    assert "blank" not in out
    assert out != hint(EMPTY)


def test_the_three_renderings_are_distinct():
    assert len({hint(EMPTY), hint("{tag='a'}"), hint("")}) == 3


# --- both call sites use it -----------------------------------------------------------------

def _non_docstring_strings(fn):
    """Every string constant in `fn` EXCEPT its own docstring.

    #1203il's renderer quotes the literal `Fill failed: Page.fill: Timeout 5000ms exceeded.`
    inside its docstring to explain what the agent used to see. A search for the function that
    BUILDS that message then matched the renderer itself — the fifth time in one session that
    an assertion read my own prose instead of the code. Skip the docstring and the match is
    about behaviour again.
    """
    import ast
    body = list(getattr(fn, "body", []) or [])
    doc = None
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        doc = body[0].value
    out = []
    for node in ast.walk(fn):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node is not doc):
            out.append(node.value)
    return out


def test_fill_uses_the_shared_renderer():
    """Function-scoped, not a 400-byte window before the literal: #1203il grew the renderer's
    docstring and the window stopped reaching the call it was looking for, though the call had
    not moved (#943 — use landmark/structural anchors, never byte windows)."""
    import ast
    import inspect
    from env_generator.llm_generator.tools.browser import interaction as ix
    tree = ast.parse(inspect.getsource(ix))
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any("Fill failed:" in c for c in _non_docstring_strings(fn)):
            continue
        called = {c.func.id for c in ast.walk(fn)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "_candidates_hint_688" in called, (
            "the fill failure builds its hint without the shared renderer")
        return
    raise AssertionError("no function builds the 'Fill failed:' message any more")


def test_click_uses_the_shared_renderer():
    import inspect
    from env_generator.llm_generator.tools.browser import interaction as ix
    src = inspect.getsource(ix)
    assert src.count("_candidates_hint_688(_cands)") == 2


def test_neither_site_still_formats_the_list_inline():
    """Two copies would drift — #665's lesson."""
    import inspect
    from env_generator.llm_generator.tools.browser import interaction as ix
    src = inspect.getsource(ix)
    assert src.count('f" Interactable elements on this page: {cands}"') == 1


# --- the describer keeps its contract ---------------------------------------------------------

def test_it_still_never_raises():
    class _Bad:
        async def query_selector_all(self, s):
            raise KeyboardInterrupt  # noqa: TRY301

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(describe(_Bad()))   # BaseException still propagates, as before


def test_the_docstring_still_states_the_never_raise_contract():
    assert "must never raise" in describe.__doc__


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools.browser import interaction as ix
    flat = " ".join(inspect.getsource(ix.describe_interactive_candidates)
                    .replace("#", " ").split())
    assert "830 of them in the LIVE era" in flat
    assert "it is getting worse" in flat


def test_why_a_failed_probe_stays_silent_is_recorded():
    import inspect
    from env_generator.llm_generator.tools.browser import interaction as ix
    flat = " ".join(inspect.getsource(ix.describe_interactive_candidates).split())
    assert "worse than saying nothing" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
