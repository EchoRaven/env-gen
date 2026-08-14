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


def test_a_failed_probe_still_adds_nothing():
    assert hint("") == ""


def test_the_three_renderings_are_distinct():
    assert len({hint(EMPTY), hint("{tag='a'}"), hint("")}) == 3


# --- both call sites use it -----------------------------------------------------------------

def test_fill_uses_the_shared_renderer():
    import inspect
    from env_generator.llm_generator.tools.browser import interaction as ix
    src = inspect.getsource(ix)
    i = src.index("Fill failed:")
    assert "_candidates_hint_688(_cands)" in src[max(0, i - 400):i]


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
