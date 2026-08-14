r"""#689: the page moved under the read, and only one of the three readers retried.

Last two entries in the browser lane's failure profile, and they are one condition wearing two
engine messages:

    Page.evaluate: Execution context was destroyed, most likely because of a navigation   74
    Page.content:  Unable to retrieve content because the page is navigating               58

132 in the corpus, 50 of them in the LIVE era (r100+). The caller did nothing wrong and has
nothing to change — the page settles a moment later.

`browser_click` already retries transients three times by default. `browser_eval` retried only
#364's async-framing rejection, and the content read inside `browser_navigate` retried nothing,
so both surfaced a race as a plain failure. Same shape as #665 and #687: one member of a pair was
treated and its twin was not.

The predicate follows #364's own rule — let the ENGINE's error decide — so a genuine runtime
error is never retried, and the settle helper never raises, because a timeout while waiting must
leave the caller free to report the ORIGINAL error rather than a new one about waiting.
"""
import asyncio

import pytest

from env_generator.llm_generator.tools.browser.inspection import (
    is_async_framing_error,
    is_navigation_race_error,
    settle_after_navigation_689,
)


# --- the predicate ------------------------------------------------------------------------------

@pytest.mark.parametrize("msg", [
    "Execution context was destroyed, most likely because of a navigation",
    "Page.evaluate: Execution context was destroyed, most likely because of a navigation.",
    "Unable to retrieve content because the page is navigating and changing the content.",
])
def test_it_recognises_both_engine_wordings(msg):
    assert is_navigation_race_error(Exception(msg))


@pytest.mark.parametrize("msg", [
    "ReferenceError: foo is not defined",
    "Illegal return statement",
    "TypeError: Cannot read properties of null",
    "",
])
def test_a_genuine_error_is_not_a_race(msg):
    assert not is_navigation_race_error(Exception(msg))


def test_it_does_not_overlap_with_the_framing_predicate():
    """#364 retries framing; #689 retries a race. A message must not be both."""
    for m in ("Illegal return statement", "await is only valid in async functions"):
        assert is_async_framing_error(Exception(m))
        assert not is_navigation_race_error(Exception(m))


def test_it_reads_playwright_style_error_objects():
    class _PwError(Exception):
        message = "Execution context was destroyed, most likely because of a navigation"

    assert is_navigation_race_error(_PwError())


def test_it_never_raises_on_junk():
    for junk in (None, 42, object(), b"x"):
        is_navigation_race_error(junk)


# --- the settle helper --------------------------------------------------------------------------

def test_it_waits_for_the_document_then_the_network():
    seen = []

    class _P:
        async def wait_for_load_state(self, state, timeout=None):
            seen.append(state)

    asyncio.run(settle_after_navigation_689(_P()))
    assert seen == ["domcontentloaded", "networkidle"]


def test_a_timeout_stops_the_wait_without_raising():
    """A settle that times out must not replace the original error with its own."""
    class _P:
        async def wait_for_load_state(self, state, timeout=None):
            raise RuntimeError("timeout")

    asyncio.run(settle_after_navigation_689(_P()))


def test_no_page_is_safe():
    asyncio.run(settle_after_navigation_689(None))


# --- eval retries the race, once ------------------------------------------------------------

def test_eval_retries_a_race_and_reports_a_second_failure_honestly():
    import inspect
    from env_generator.llm_generator.tools.browser import inspection as ix
    src = inspect.getsource(ix)
    i = src.index("#689: the page moved under the read")
    body = src[i:src.index("if not is_async_framing_error", i)]
    assert "settle_after_navigation_689" in body
    assert "Retried once after the navigation settled" in body


def test_eval_still_reports_the_original_error_first():
    import inspect
    from env_generator.llm_generator.tools.browser import inspection as ix
    src = inspect.getsource(ix)
    i = src.index("#689: the page moved under the read")
    body = src[i:src.index("if not is_async_framing_error", i)]
    assert 'f"Eval failed: {str(e)}' in body


def test_the_framing_retry_is_untouched():
    """#364 must still run for its own case."""
    import inspect
    from env_generator.llm_generator.tools.browser import inspection as ix
    src = inspect.getsource(ix)
    assert "wrap_in_async_iife(script)" in src
    assert "if not is_async_framing_error(e):" in src


# --- the content read retries too --------------------------------------------------------------

def test_the_content_read_retries_a_race():
    import inspect
    from env_generator.llm_generator.tools.browser import core
    src = inspect.getsource(core)
    i = src.index("#689: the page can still be moving")
    body = src[i:src.index("console_errors = [", i)]
    assert "settle_after_navigation_689" in body


def test_a_non_race_content_error_is_re_raised():
    """Only the race is absorbed; anything else must reach #687's handler unchanged."""
    import inspect
    from env_generator.llm_generator.tools.browser import core
    src = inspect.getsource(core)
    i = src.index("#689: the page can still be moving")
    body = src[i:src.index("console_errors = [", i)]
    assert "if not is_navigation_race_error(_ce):" in body
    assert "raise" in body


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools.browser import inspection as ix
    flat = " ".join(inspect.getsource(ix.is_navigation_race_error).replace("#", " ").split())
    assert "132 of them, 50 in the LIVE era" in flat


def test_the_untreated_twin_pattern_is_recorded():
    import inspect
    from env_generator.llm_generator.tools.browser import inspection as ix
    flat = " ".join(inspect.getsource(ix.is_navigation_race_error).replace("#", " ").split())
    assert "665 and 687" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
